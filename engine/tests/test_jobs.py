"""Orchestration tests (design 09). The failure matrix, line by line."""

import pytest

from shootr.db import connect
from shootr.jobs import (
    JobConflict,
    cancel_job,
    claim_items,
    complete_items,
    create_job,
    fail_item,
    finish_job,
    pause_job,
    pending_items,
    progress,
    requeue_batch,
    reset_stale_running,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/x', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    for i in range(1, 11):
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3"),
        )
    yield c
    c.close()


PHOTOS = list(range(1, 11))


class TestJobLifecycle:
    def test_create_and_drain(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        assert len(pending_items(conn, job)) == 10
        claim_items(conn, job, PHOTOS[:5])
        complete_items(conn, job, PHOTOS[:5])
        assert pending_items(conn, job) == PHOTOS[5:]
        p = progress(conn, job)
        assert p.completed == 5 and p.total == 10

    def test_one_job_per_shoot_and_kind(self, conn):
        """design 09 §7 — two analyze jobs would double-decode and race."""
        create_job(conn, 1, "analyze", PHOTOS)
        with pytest.raises(JobConflict):
            create_job(conn, 1, "analyze", PHOTOS)
        create_job(conn, 1, "group", PHOTOS)  # different kind: fine

    def test_finished_job_releases_conflict(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS)
        complete_items(conn, job, PHOTOS)
        finish_job(conn, job)
        assert progress(conn, job).state == "done"
        create_job(conn, 1, "analyze", PHOTOS)  # no conflict now

    def test_unknown_kind_rejected(self, conn):
        with pytest.raises(ValueError):
            create_job(conn, 1, "transcode", PHOTOS)


class TestResume:
    """design 09 §2 — the normal path IS the recovery path."""

    def test_resume_is_the_pending_query(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS[:6])
        complete_items(conn, job, PHOTOS[:4])
        # "Crash": items 5,6 stuck running. Startup reset:
        reset_stale_running(conn)
        # Resume = same query, no special path.
        assert pending_items(conn, job) == PHOTOS[4:]

    def test_stale_running_reset_on_startup(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS)
        n = reset_stale_running(conn)
        assert n == 10
        assert progress(conn, job).state == "pending"


class TestFailureMatrix:
    def test_corrupt_raw_fails_permanently_after_attempts(self, conn):
        """attempts >= 3 → failed, excluded from retries (design 09 §4)."""
        job = create_job(conn, 1, "analyze", PHOTOS)
        for _ in range(3):
            assert 1 in pending_items(conn, job)
            fail_item(conn, job, 1, "decode_failed")
        assert 1 not in pending_items(conn, job)
        assert progress(conn, job).failed == 1

    def test_failed_item_retried_below_cap(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        fail_item(conn, job, 1, "transient")
        assert 1 in pending_items(conn, job)  # back to pending, attempts=1

    def test_helper_crash_requeues_unfinished_only(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS[:6])
        complete_items(conn, job, PHOTOS[:3])  # banked before the crash
        requeue_batch(conn, job, PHOTOS[:6])  # crash: requeue the batch
        # Done items stay done; only the running ones went back.
        assert pending_items(conn, job) == PHOTOS[3:]
        assert progress(conn, job).completed == 3

    def test_volume_offline_pauses_never_fails(self, conn):
        """THE conflation guard (design 09 §4): 6,000 unreachable photos are
        not 6,000 bad photos. Pause leaves attempts untouched."""
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS[:4])
        pause_job(conn, job, "volume_offline")
        assert progress(conn, job).state == "pending"
        assert progress(conn, job).failed == 0
        # Everything unfinished is pending again — nothing consumed attempts.
        assert pending_items(conn, job) == PHOTOS
        rows = conn.execute(
            "SELECT attempts FROM job_item WHERE job_id = ?", (job,))
        assert all(r["attempts"] == 0 for r in rows)

    def test_finish_marks_failed_if_any_item_failed(self, conn):
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS)
        complete_items(conn, job, PHOTOS[1:])
        for _ in range(3):
            fail_item(conn, job, 1, "corrupt")
        finish_job(conn, job)
        p = progress(conn, job)
        assert p.state == "failed" and p.failed == 1 and p.completed == 9


class TestCancellation:
    def test_cancel_keeps_completed_work(self, conn):
        """design 09 §6 — analysis rows valid regardless of job fate."""
        job = create_job(conn, 1, "analyze", PHOTOS)
        claim_items(conn, job, PHOTOS[:5])
        complete_items(conn, job, PHOTOS[:5])
        cancel_job(conn, job)
        assert progress(conn, job).state == "cancelled"
        assert progress(conn, job).completed == 5
        # Re-running later picks up where it stopped:
        assert pending_items(conn, job) == PHOTOS[5:]
