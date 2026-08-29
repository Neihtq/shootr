"""Analyze-job runner: drains a job's pending items through the Swift helper
and persists measurements (design 09 §3).

Per-photo incremental consumption: the helper flushes JSONL per photo, so
a batch killed at photo 40 of 64 still banks 40 results.

Concurrency (design 09 §5): `workers` N > 1 runs N helper subprocesses,
each on its own slice of the claimed batch, feeding one queue. Only the
coordinator thread touches SQLite — workers produce, it consumes — so the
checkpointing contract is byte-identical to the single-worker path. One
worker crashing (or stalling: the helper layer's watchdog raises
HelperStalled) requeues only ITS unreported slice; the round continues.
A round that completes nothing while a worker failed raises, preserving
the "crash marks the job errored, resume retries" semantics — otherwise a
persistent crasher would spin forever.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import sqlite3
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from . import helper, jobs

# 32–64 (design 03 §4): amortize startup, bound blast radius. Overridable:
# the Python analyzer pays model loading per process, which amortizes
# better at 128+ (design 13).
BATCH_SIZE = int(os.environ.get("SHOOTR_BATCH_SIZE", 48))

# analyzer(files, scale) -> yields per-photo dicts. Injectable for tests.
Analyzer = Callable[[list[Path], float], Iterator[dict]]


def _pooled(analyzer: Analyzer, slices: list[list[Path]], scale: float
            ) -> Iterator[tuple[str, object, int]]:
    """Merge N analyzer generators into one stream of events:
    ("result", dict, slot) · ("error", exception, slot) · ("done", _, slot).
    """
    q: queue.Queue = queue.Queue(maxsize=64)  # backpressure on producers

    def work(slot: int, files: list[Path]) -> None:
        try:
            for result in analyzer(files, scale):
                q.put(("result", result, slot))
        except Exception as e:  # noqa: BLE001 — reported, decided upstream
            q.put(("error", e, slot))
        else:
            q.put(("done", None, slot))

    threads = [threading.Thread(target=work, args=(i, files), daemon=True)
               for i, files in enumerate(slices)]
    for t in threads:
        t.start()
    live = len(threads)
    while live:
        kind, payload, slot = q.get()
        if kind in ("done", "error"):
            live -= 1
        yield kind, payload, slot
    for t in threads:
        t.join()


def run_analyze_job(
    conn: sqlite3.Connection,
    job_id: int,
    library_root: Path,
    scale: float = 0.5,
    analyzer: Analyzer | None = None,
    volume_check: Callable[[], bool] | None = None,
    finalize: Callable[[], None] | None = None,
    workers: int | None = None,
) -> jobs.Progress:
    """Drain the job. Safe to call repeatedly: resume = re-call.

    `finalize` runs after the last measurement but *before* the job is
    marked done — it's where grouping/scoring/selection happen. Ordering
    matters to clients: they treat a pending/running job as "don't open
    this shoot yet", and between analysis ending and the selection
    existing there is nothing to review. Marking done first would open
    that window.

    `workers` > 1 fans each claimed round out over N helper subprocesses
    (default from SHOOTR_WORKERS). Error semantics are unchanged from the
    single-worker path: a worker crash/stall banks everything already
    reported (by ANY worker), requeues the unreported, and raises after
    the surviving workers drain — resume continues from the checkpoint.
    """
    analyzer = analyzer or helper.analyze_batch
    volume_check = volume_check or library_root.is_dir
    # Default 4, sized on real CR3s (M5 Pro, 2026-08-30): 1.47 s/photo
    # single → 0.47 at 4 (3.1×, 10k ≈ 1.3 h); 8 still gains (0.28) but at
    # 65% efficiency and the machine should stay usable during a run.
    workers = max(1, workers if workers is not None
                  else int(os.environ.get("SHOOTR_WORKERS", "4")))

    while True:
        # Volume check before each batch (design 09 §4): offline pauses the
        # job — the unanalyzed photos are unreachable, not bad.
        if not volume_check():
            jobs.pause_job(conn, job_id, "volume_offline")
            return jobs.progress(conn, job_id)

        batch_ids = jobs.pending_items(conn, job_id,
                                       limit=BATCH_SIZE * workers)
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
        first_error: BaseException | None = None
        try:
            files = [library_root / photos[pid] for pid in batch_ids
                     if pid in photos]
            slices = [files[i::workers] for i in range(workers)]
            slices = [s for s in slices if s]
            for kind, payload, _slot in _pooled(analyzer, slices, scale):
                if kind == "error":
                    # Keep consuming: the other workers' results are real
                    # work — bank them before surfacing the failure.
                    first_error = first_error or payload  # type: ignore
                    continue
                if kind == "done":
                    continue
                result: dict = payload  # type: ignore[assignment]
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
            # Consumer-side crash (persist bug, interrupt): bank what we
            # have, requeue the rest.
            if done_buffer:
                jobs.complete_items(conn, job_id, done_buffer)
            jobs.requeue_batch(conn, job_id,
                               [p for p in batch_ids if p not in seen])
            raise

        if done_buffer:
            jobs.complete_items(conn, job_id, done_buffer)
        if first_error is not None:
            # Helper crash/stall in ≥1 worker: everything reported above is
            # banked; the unreported items go back to pending.
            jobs.requeue_batch(conn, job_id,
                               [p for p in batch_ids if p not in seen])
            raise first_error
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
            # Faceprint: base64 f32 identity embedding. The Swift helper
            # emits null (Vision path deferred); the Python analyzer fills
            # it — person clustering's input (design 05 §5).
            fp = f.get("faceprint")
            conn.execute(
                "INSERT INTO face (photo_id, idx, bbox, roll, yaw, pitch, "
                "capture_quality, eye_sharp_l, eye_sharp_r, eye_open_l, "
                "eye_open_r, eye_source, faceprint) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (photo_id, f["idx"], json.dumps(f["bbox"]), f.get("roll"),
                 f.get("yaw"), f.get("pitch"), f.get("capture_quality"),
                 left.get("sharp_norm"), right.get("sharp_norm"),
                 left.get("open"), right.get("open"),
                 f.get("eye_source", "unknown"),
                 base64.b64decode(fp) if fp else None),
            )
        if result.get("embedding"):
            conn.execute(
                "INSERT OR REPLACE INTO embedding (photo_id, kind, vec, dim) "
                "VALUES (?, 'scene', ?, ?)",
                (photo_id, base64.b64decode(result["embedding"]),
                 result.get("embedding_dim", 0)),
            )
