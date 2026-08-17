"""Background job runner for the API process.

One worker thread drains analyze jobs; the API stays responsive because
SQLite is in WAL mode (readers never block on the writer) and the runner
holds its own connection. Single writer discipline is preserved: the runner
IS part of the engine process (design README rule 6).

M1 shape: one thread, jobs run FIFO. The N-subprocess pool lands after the
benchmark sizes it (design 09 §3) — the queue/checkpoint contract here
doesn't change when it does.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import db, pipeline
from .analyze_runner import run_analyze_job


@dataclass(frozen=True)
class JobRequest:
    job_id: int
    library_root: Path


class JobRunner:
    """FIFO worker. `submit` returns immediately; progress is read from the
    jobs tables (the checkpoint state IS the progress state)."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._queue: queue.Queue[JobRequest | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="shootr-job-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=10)

    def submit(self, job_id: int, library_root: Path) -> None:
        self._queue.put(JobRequest(job_id, library_root))

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _loop(self) -> None:
        conn = db.connect(self._db_path)
        try:
            while True:
                req = self._queue.get()
                if req is None:
                    return
                try:
                    progress = run_analyze_job(conn, req.job_id,
                                               req.library_root)
                    # Chain the cheap derived steps once measurements exist.
                    # Firing them any earlier is a race: score joins analysis
                    # and would silently produce nothing (observed on the
                    # first real-photo run).
                    if progress.state in ("done", "failed"):
                        shoot = conn.execute(
                            "SELECT shoot_id FROM job WHERE id = ?",
                            (req.job_id,)).fetchone()
                        if shoot and shoot["shoot_id"]:
                            sid = shoot["shoot_id"]
                            pipeline.group_shoot(conn, sid)
                            pipeline.score_shoot(conn, sid)
                            pipeline.create_selection(conn, sid)
                except Exception:
                    # The job's items are already requeued/failed by the
                    # analyze runner; record for /api/health visibility.
                    self._last_error = traceback.format_exc(limit=3)
        finally:
            conn.close()
