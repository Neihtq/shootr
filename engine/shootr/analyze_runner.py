"""Analyze-job runner: drains a job's pending items through the Swift helper
and persists measurements (design 09 §3).

M1 shape: synchronous batches with per-photo incremental consumption. The
helper flushes JSONL per photo, so a batch killed at photo 40 of 64 still
banks 40 results. The asyncio N-worker pool is a drop-in upgrade later —
the checkpointing contract (this module + jobs.py) doesn't change.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from . import helper, jobs

BATCH_SIZE = 48  # 32–64 (design 03 §4): amortize startup, bound blast radius

# analyzer(files, scale) -> yields per-photo dicts. Injectable for tests.
Analyzer = Callable[[list[Path], float], Iterator[dict]]


def run_analyze_job(
    conn: sqlite3.Connection,
    job_id: int,
    library_root: Path,
    scale: float = 0.5,
    analyzer: Analyzer | None = None,
    volume_check: Callable[[], bool] | None = None,
    finalize: Callable[[], None] | None = None,
) -> jobs.Progress:
    """Drain the job. Safe to call repeatedly: resume = re-call.

    `finalize` runs after the last measurement but *before* the job is
    marked done — it's where grouping/scoring/selection happen. Ordering
    matters to clients: they treat a pending/running job as "don't open
    this shoot yet", and between analysis ending and the selection
    existing there is nothing to review. Marking done first would open
    that window.
    """
    analyzer = analyzer or helper.analyze_batch
    volume_check = volume_check or library_root.is_dir

    while True:
        # Volume check before each batch (design 09 §4): offline pauses the
        # job — the unanalyzed photos are unreachable, not bad.
        if not volume_check():
            jobs.pause_job(conn, job_id, "volume_offline")
            return jobs.progress(conn, job_id)

        batch_ids = jobs.pending_items(conn, job_id, limit=BATCH_SIZE)
        if not batch_ids:
            break

        photos = {
            row["id"]: row["rel_path"]
            for row in conn.execute(
                f"SELECT id, rel_path FROM photo WHERE id IN "
                f"({','.join('?' * len(batch_ids))})",
                batch_ids,
            )
        }
        by_path = {photos[pid]: pid for pid in batch_ids if pid in photos}
        jobs.claim_items(conn, job_id, batch_ids)

        done_buffer: list[int] = []
        seen: set[int] = set()
        try:
            files = [library_root / photos[pid] for pid in batch_ids
                     if pid in photos]
            for result in analyzer(files, scale):
                rel = str(Path(result["path"]).relative_to(library_root)) \
                    if result.get("path", "").startswith(str(library_root)) \
                    else result.get("path", "")
                pid = by_path.get(rel)
                if pid is None:
                    continue
                seen.add(pid)
                if "error" in result:
                    jobs.fail_item(conn, job_id, pid, result["error"])
                    continue
                _persist(conn, pid, result)
                done_buffer.append(pid)
                if len(done_buffer) >= jobs.COMMIT_BATCH:
                    jobs.complete_items(conn, job_id, done_buffer)
                    done_buffer = []
        except Exception:
            # Helper crash/hang: bank what we have, requeue the rest.
            if done_buffer:
                jobs.complete_items(conn, job_id, done_buffer)
            jobs.requeue_batch(conn, job_id,
                               [p for p in batch_ids if p not in seen])
            raise

        if done_buffer:
            jobs.complete_items(conn, job_id, done_buffer)
        # Items the helper never reported (crashed mid-batch without output):
        unreported = [p for p in batch_ids if p not in seen and p in photos]
        if unreported:
            jobs.requeue_batch(conn, job_id, unreported)
        # Photos missing from the DB row fetch shouldn't stay claimed.
        orphans = [p for p in batch_ids if p not in photos]
        for p in orphans:
            jobs.fail_item(conn, job_id, p, "photo_row_missing")

    if finalize:
        finalize()
    jobs.finish_job(conn, job_id)
    return jobs.progress(conn, job_id)


def _persist(conn: sqlite3.Connection, photo_id: int, result: dict) -> None:
    """Write one photo's measurements: analysis + faces + embedding.
    Immutable per engine_version (design 01 invariant 3) — REPLACE is only
    reached when re-analyzing with a new version, wiping dependent rows."""
    frame = result.get("frame", {})
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO analysis "
            "(photo_id, engine_version, decode_mode, frame, saliency, "
            "analyzed_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (photo_id, result.get("engine_version", "?"),
             result.get("decode_mode", "?"), json.dumps(frame),
             json.dumps(result.get("saliency"))),
        )
        conn.execute("DELETE FROM face WHERE photo_id = ?", (photo_id,))
        for f in result.get("faces", []):
            eyes = f.get("eyes", {})
            left, right = eyes.get("l", {}), eyes.get("r", {})
            conn.execute(
                "INSERT INTO face (photo_id, idx, bbox, roll, yaw, pitch, "
                "capture_quality, eye_sharp_l, eye_sharp_r, eye_open_l, "
                "eye_open_r, eye_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (photo_id, f["idx"], json.dumps(f["bbox"]), f.get("roll"),
                 f.get("yaw"), f.get("pitch"), f.get("capture_quality"),
                 left.get("sharp_norm"), right.get("sharp_norm"),
                 left.get("open"), right.get("open"),
                 f.get("eye_source", "unknown")),
            )
        if result.get("embedding"):
            import base64
            conn.execute(
                "INSERT OR REPLACE INTO embedding (photo_id, kind, vec, dim) "
                "VALUES (?, 'scene', ?, ?)",
                (photo_id, base64.b64decode(result["embedding"]),
                 result.get("embedding_dim", 0)),
            )
