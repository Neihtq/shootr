"""Analyze-runner tests: the checkpointing contract under simulated failures.

A fake analyzer stands in for the Swift helper so failure injection is
deterministic; test_helper.py covers the real binary.
"""

import pytest

from shootr.analyze_runner import run_analyze_job
from shootr.db import connect
from shootr.jobs import create_job, pending_items, progress


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/lib', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    for i in range(1, 7):
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3"),
        )
    yield c
    c.close()


ROOT = pytest.importorskip("pathlib").Path("/lib")


def ok_result(path):
    return {
        "path": str(path), "decode_mode": "scaled",
        "engine_version": "0.1.0+vision3",
        "frame": {"sharpness_max": 0.8, "sharpness_mean": 0.3},
        "faces": [{"idx": 0, "bbox": [0.1, 0.1, 0.2, 0.2],
                   "eyes": {"l": {"sharp_norm": 0.8, "open": 0.9},
                            "r": {"sharp_norm": 0.7, "open": 0.95}},
                   "eye_source": "ear_landmarks"}],
    }


def happy_analyzer(files, scale):
    for f in files:
        yield ok_result(f)


def test_full_run_persists_measurements(conn):
    job = create_job(conn, 1, "analyze", [1, 2, 3, 4, 5, 6])
    p = run_analyze_job(conn, job, ROOT, analyzer=happy_analyzer,
                        volume_check=lambda: True)
    assert p.state == "done" and p.completed == 6 and p.failed == 0
    assert conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0] == 6
    face = conn.execute("SELECT * FROM face WHERE photo_id = 1").fetchone()
    assert face["eye_sharp_l"] == 0.8
    assert face["eye_source"] == "ear_landmarks"


def test_per_photo_error_does_not_stop_run(conn):
    def flaky(files, scale):
        for f in files:
            if "IMG_3" in str(f):
                yield {"path": str(f), "error": "decode_failed"}
            else:
                yield ok_result(f)

    job = create_job(conn, 1, "analyze", [1, 2, 3, 4, 5, 6])
    # Item 3 fails each pass; after MAX_ATTEMPTS it's permanently failed and
    # the loop drains to completion — no infinite retry.
    p = run_analyze_job(conn, job, ROOT, analyzer=flaky,
                        volume_check=lambda: True)
    assert p.completed == 5 and p.failed == 1
    assert p.state == "failed"  # coverage honesty: not silently "done"


def test_crash_mid_batch_banks_partial_results(conn):
    """The per-photo flush payoff (design 09 §3): results before the crash
    are committed; unfinished items are requeued, and a re-call finishes."""
    calls = {"n": 0}

    def crashy(files, scale):
        calls["n"] += 1
        if calls["n"] == 1:
            for f in files[:3]:
                yield ok_result(f)
            raise RuntimeError("helper died")
        yield from (ok_result(f) for f in files)

    job = create_job(conn, 1, "analyze", [1, 2, 3, 4, 5, 6])
    with pytest.raises(RuntimeError):
        run_analyze_job(conn, job, ROOT, analyzer=crashy,
                        volume_check=lambda: True)
    # 3 banked, 3 requeued.
    assert progress(conn, job).completed == 3
    assert len(pending_items(conn, job)) == 3
    # Resume = re-call. No special path.
    p = run_analyze_job(conn, job, ROOT, analyzer=crashy,
                        volume_check=lambda: True)
    assert p.state == "done" and p.completed == 6


def test_finalize_runs_before_the_job_is_marked_done(conn):
    """Ordering the clients depend on: they gate "can I open this shoot?"
    on the job still being pending/running. If the job flipped to done
    before grouping/scoring/selection ran, the card would unlock onto a
    shoot with measurements but nothing to review."""
    states = []

    def finalize():
        states.append(
            conn.execute("SELECT state FROM job WHERE id = ?",
                         (job,)).fetchone()["state"])

    job = create_job(conn, 1, "analyze", [1, 2, 3])
    p = run_analyze_job(conn, job, ROOT, analyzer=happy_analyzer,
                        volume_check=lambda: True, finalize=finalize)
    assert states == ["running"]  # not yet done when finalize ran
    assert p.state == "done"


def test_finalize_skipped_when_volume_goes_offline(conn):
    """A paused job hasn't finished: deriving a selection from a partial
    analysis would present it as a complete cull."""
    called = []
    job = create_job(conn, 1, "analyze", [1, 2, 3])
    p = run_analyze_job(conn, job, ROOT, analyzer=happy_analyzer,
                        volume_check=lambda: False,
                        finalize=lambda: called.append(1))
    assert p.state == "pending" and called == []


def test_volume_offline_pauses_before_batch(conn):
    job = create_job(conn, 1, "analyze", [1, 2, 3, 4, 5, 6])
    p = run_analyze_job(conn, job, ROOT, analyzer=happy_analyzer,
                        volume_check=lambda: False)
    assert p.state == "pending" and p.completed == 0
    assert len(pending_items(conn, job)) == 6  # nothing failed, nothing lost

    # Drive reconnects → same call drains normally.
    p = run_analyze_job(conn, job, ROOT, analyzer=happy_analyzer,
                        volume_check=lambda: True)
    assert p.state == "done" and p.completed == 6
