"""Orchestration: jobs & resumability (docs/design/09-orchestration.md).

The design's core move: **idempotent by construction**. Resuming is
"select all job_item where state != done" — the normal path IS the recovery
path. Bespoke recovery code only runs during failures, exactly when it can't
be tested well (design 09 §2).

Per-photo checkpointing is structural, not an optimization: at 10k photos an
analyze run is 20–30 minutes, and in that window drives unplug, lids close,
and helpers crash (design 09 §1).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_ATTEMPTS = 3  # design 09 §4: attempts >= 3 → failed permanently
COMMIT_BATCH = 50  # ~50-item transactions: per-item fsync is the bottleneck

JOB_KINDS = ("scan", "analyze", "group", "select", "export")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobConflict(Exception):
    """One job per (shoot, kind) at a time (design 09 §7): two concurrent
    analyze jobs would double-decode and race on analysis rows."""


@dataclass(frozen=True)
class Progress:
    job_id: int
    kind: str
    state: str
    total: int
    completed: int
    failed: int
    rate_per_sec: float | None = None  # rolling, from recent updates
    eta_sec: int | None = None


# ---------------------------------------------------------------------------
# Job lifecycle


def create_job(conn: sqlite3.Connection, shoot_id: int, kind: str,
               photo_ids: list[int]) -> int:
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    live = conn.execute(
        "SELECT id FROM job WHERE shoot_id = ? AND kind = ? "
        "AND state IN ('pending','running')",
        (shoot_id, kind),
    ).fetchone()
    if live:
        raise JobConflict(
            f"job {live['id']} ({kind}) already active for shoot {shoot_id}")

    now = _now()
    with conn:
        cur = conn.execute(
            "INSERT INTO job (shoot_id, kind, state, total, completed, "
            "created_at, updated_at) VALUES (?, ?, 'pending', ?, 0, ?, ?)",
            (shoot_id, kind, len(photo_ids), now, now),
        )
        job_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO job_item (job_id, photo_id, state) "
            "VALUES (?, ?, 'pending')",
            [(job_id, pid) for pid in photo_ids],
        )
    # Job ids repeat across separate databases (tests, reinstalls); a stale
    # rate window from a previous job would corrupt the first ETA.
    _rate_samples.pop(job_id, None)
    return job_id


def pending_items(conn: sqlite3.Connection, job_id: int,
                  limit: int | None = None) -> list[int]:
    """THE resume query (design 09 §2): everything not done is pending work.
    No separate resume path exists."""
    sql = ("SELECT photo_id FROM job_item WHERE job_id = ? "
           "AND state = 'pending' AND attempts < ?")
    args: list = [job_id, MAX_ATTEMPTS]
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return [r["photo_id"] for r in conn.execute(sql, args)]


def claim_items(conn: sqlite3.Connection, job_id: int,
                photo_ids: list[int]) -> None:
    with conn:
        conn.executemany(
            "UPDATE job_item SET state = 'running' "
            "WHERE job_id = ? AND photo_id = ?",
            [(job_id, pid) for pid in photo_ids],
        )
        conn.execute(
            "UPDATE job SET state = 'running', updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )


def complete_items(conn: sqlite3.Connection, job_id: int,
                   photo_ids: list[int]) -> None:
    with conn:
        conn.executemany(
            "UPDATE job_item SET state = 'done' "
            "WHERE job_id = ? AND photo_id = ?",
            [(job_id, pid) for pid in photo_ids],
        )
        conn.execute(
            "UPDATE job SET completed = completed + ?, updated_at = ? "
            "WHERE id = ?",
            (len(photo_ids), _now(), job_id),
        )


def fail_item(conn: sqlite3.Connection, job_id: int, photo_id: int,
              error: str) -> None:
    """Corrupt RAW / per-photo error: attempts++, permanent fail at the cap.
    Below the cap the item returns to pending for the next pass."""
    with conn:
        conn.execute(
            "UPDATE job_item SET attempts = attempts + 1, error = ?, "
            "state = CASE WHEN attempts + 1 >= ? THEN 'failed' "
            "ELSE 'pending' END "
            "WHERE job_id = ? AND photo_id = ?",
            (error, MAX_ATTEMPTS, job_id, photo_id),
        )


def requeue_batch(conn: sqlite3.Connection, job_id: int,
                  photo_ids: list[int]) -> None:
    """Helper crash/hang: unfinished items of the batch go back to pending
    with attempts++ (design 09 §4). Items already committed stay done."""
    with conn:
        conn.executemany(
            "UPDATE job_item SET attempts = attempts + 1, "
            "state = CASE WHEN attempts + 1 >= ? THEN 'failed' "
            "ELSE 'pending' END "
            "WHERE job_id = ? AND photo_id = ? AND state = 'running'",
            [(MAX_ATTEMPTS, job_id, pid) for pid in photo_ids],
        )


def pause_job(conn: sqlite3.Connection, job_id: int, reason: str) -> None:
    """Volume offline (design 09 §4): the remaining photos are NOT bad —
    they're temporarily unreachable. Items stay pending (never failed, or
    they'd exhaust attempts and be skipped on reconnect); the job returns to
    pending so resume continues from the same query."""
    with conn:
        conn.execute(
            "UPDATE job_item SET state = 'pending' "
            "WHERE job_id = ? AND state = 'running'",
            (job_id,),
        )
        conn.execute(
            "UPDATE job SET state = 'pending', error = ?, updated_at = ? "
            "WHERE id = ?",
            (reason, _now(), job_id),
        )


def cancel_job(conn: sqlite3.Connection, job_id: int) -> None:
    """Completed work is kept — analysis rows are valid regardless of whether
    the job that produced them finished (design 09 §6)."""
    with conn:
        conn.execute(
            "UPDATE job SET state = 'cancelled', updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )


def finish_job(conn: sqlite3.Connection, job_id: int) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM job_item "
        "WHERE job_id = ? AND state = 'failed'",
        (job_id,),
    ).fetchone()
    state = "failed" if row["n"] else "done"
    with conn:
        conn.execute(
            "UPDATE job SET state = ?, updated_at = ? WHERE id = ?",
            (state, _now(), job_id),
        )


def reset_stale_running(conn: sqlite3.Connection) -> int:
    """Startup recovery (design 09 §4): items claimed by a worker that no
    longer exists are indistinguishable from in-progress without this."""
    with conn:
        cur = conn.execute(
            "UPDATE job_item SET state = 'pending' WHERE state = 'running'")
        n = cur.rowcount
        conn.execute(
            "UPDATE job SET state = 'pending', updated_at = ? "
            "WHERE state = 'running'",
            (_now(),),
        )
    return n


# Rolling rate window (design 09 §5): a cumulative average lags badly after
# a pause and produces visibly wrong ETAs. In-memory per-process is fine —
# the rate is presentation, never state.
_RATE_WINDOW_S = 60.0
_rate_samples: dict[int, list[tuple[float, int]]] = {}


def _rolling_rate(job_id: int, completed: int) -> float | None:
    import time

    now = time.monotonic()
    samples = _rate_samples.setdefault(job_id, [])
    samples.append((now, completed))
    del samples[: max(0, len(samples) - 600)]  # bound memory
    window = [(t, c) for t, c in samples if now - t <= _RATE_WINDOW_S]
    if len(window) < 2:
        return None
    dt = window[-1][0] - window[0][0]
    dc = window[-1][1] - window[0][1]
    if dt <= 0 or dc <= 0:
        return None
    return dc / dt


def progress(conn: sqlite3.Connection, job_id: int) -> Progress:
    job = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    failed = conn.execute(
        "SELECT COUNT(*) AS n FROM job_item "
        "WHERE job_id = ? AND state = 'failed'",
        (job_id,),
    ).fetchone()["n"]
    total = job["total"] or 0
    completed = job["completed"]
    rate = eta = None
    if job["state"] == "running":
        rate = _rolling_rate(job_id, completed)
        if rate and total > completed:
            eta = int((total - completed) / rate)
    return Progress(
        job_id=job_id, kind=job["kind"], state=job["state"],
        total=total, completed=completed, failed=failed,
        rate_per_sec=round(rate, 2) if rate else None, eta_sec=eta,
    )
