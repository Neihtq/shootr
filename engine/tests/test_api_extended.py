"""Tests for the API additions: group corrections, job runner wiring, SSE
payloads, thumbnail cache behavior."""

import json
import struct
import time

import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app
from shootr.db import connect
from shootr.runner import JobRunner


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "shootr.db"
    (tmp_path / "backups").mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()

    app = create_app(db_path, tmp_path / "backups",
                     cache_dir=tmp_path / "thumbs")
    client = TestClient(app)

    c = connect(db_path)
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, ?, 'now')", (str(lib),))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    for i in range(1, 7):
        (lib / f"IMG_{i}.CR3").write_bytes(b"raw" * 100)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime, captured_at, subsec) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0, '2026-06-14T15:00:00', ?)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3", i * 100))
    c.commit()
    c.close()
    return client, db_path, lib


def seed_group(db_path, ids, is_bracket=0):
    c = connect(db_path)
    cur = c.execute(
        'INSERT INTO "group" (shoot_id, level, is_bracket) '
        "VALUES (1, 'shot', ?)", (is_bracket,))
    gid = cur.lastrowid
    c.executemany("INSERT INTO group_member (group_id, photo_id) "
                  "VALUES (?, ?)", [(gid, pid) for pid in ids])
    c.commit()
    c.close()
    return gid


class TestGroupCorrections:
    def test_split(self, env):
        client, db_path, _ = env
        gid = seed_group(db_path, [1, 2, 3, 4])
        r = client.post(f"/api/groups/{gid}/split",
                        json={"at_photo_id": 3})
        assert r.status_code == 200
        new_id = r.json()["new_group_id"]
        groups = {g["id"]: g["photo_ids"]
                  for g in client.get("/api/shoots/1/groups").json()}
        assert sorted(groups[gid]) == [1, 2]
        assert sorted(groups[new_id]) == [3, 4]

    def test_split_at_first_photo_is_noop(self, env):
        client, db_path, _ = env
        gid = seed_group(db_path, [1, 2])
        r = client.post(f"/api/groups/{gid}/split", json={"at_photo_id": 1})
        assert r.json()["new_group_id"] is None

    def test_merge(self, env):
        client, db_path, _ = env
        g1 = seed_group(db_path, [1, 2])
        g2 = seed_group(db_path, [3, 4])
        r = client.post("/api/groups/merge", json={"group_ids": [g1, g2]})
        assert r.status_code == 200
        groups = {g["id"]: g["photo_ids"]
                  for g in client.get("/api/shoots/1/groups").json()}
        assert sorted(groups[g1]) == [1, 2, 3, 4]
        assert g2 not in groups

    def test_brackets_immutable(self, env):
        """design 05 §3 / 04 §6 — corrections must never break brackets."""
        client, db_path, _ = env
        bracket = seed_group(db_path, [1, 2, 3], is_bracket=1)
        normal = seed_group(db_path, [4, 5])
        r = client.post(f"/api/groups/{bracket}/split",
                        json={"at_photo_id": 2})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "bracket_immutable"
        r = client.post("/api/groups/merge",
                        json={"group_ids": [bracket, normal]})
        assert r.status_code == 409


class TestThumbnails:
    def test_invalid_size_rejected(self, env):
        client, _, _ = env
        r = client.get("/api/photos/1/thumb?size=999")
        assert r.status_code == 400

    def test_missing_file_is_volume_offline(self, env):
        client, db_path, lib = env
        (lib / "IMG_1.CR3").unlink()
        r = client.get("/api/photos/1/thumb?size=256")
        assert r.status_code == 404
        err = r.json()["error"]
        assert err["code"] == "volume_offline" and err["retryable"]

    def test_cached_thumb_served_without_helper(self, env, tmp_path):
        """Cache hit path: pre-seed the content-addressed cache; no helper
        call should be needed."""
        client, _, _ = env
        cache = tmp_path / "thumbs"
        (cache / "c1_256.jpg").write_bytes(b"\xff\xd8fakejpeg")
        r = client.get("/api/photos/1/thumb?size=256")
        assert r.status_code == 200
        assert r.headers["etag"] == '"c1:256"'
        assert "immutable" in r.headers["cache-control"]


class TestRunnerWiring:
    def test_analyze_submits_to_runner_and_drains(self, env, tmp_path,
                                                  monkeypatch):
        client, db_path, lib = env

        def fake_analyze(files, scale=0.5):
            for f in files:
                yield {"path": str(f), "decode_mode": "scaled",
                       "engine_version": "test",
                       "frame": {"sharpness_max": 0.5,
                                 "sharpness_mean": 0.2}}

        import shootr.analyze_runner as ar
        monkeypatch.setattr(ar.helper, "analyze_batch", fake_analyze)

        runner = JobRunner(db_path)
        client.app.state.runner = runner
        runner.start()
        try:
            r = client.post("/api/shoots/1/analyze")
            job_id = r.json()["job_id"]
            assert r.json()["total"] == 6

            deadline = time.time() + 10
            while time.time() < deadline:
                status = client.get(f"/api/jobs/{job_id}").json()
                if status["state"] in ("done", "failed"):
                    break
                time.sleep(0.05)
            assert status["state"] == "done"
            assert status["completed"] == 6
        finally:
            runner.stop()

        c = connect(db_path)
        n = c.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
        c.close()
        assert n == 6

    def test_runner_chains_group_score_select_after_analyze(
            self, env, tmp_path, monkeypatch):
        """THE race regression test: on the first real-photo run, group and
        score fired while analysis was still running → 0 scores, singleton
        groups, empty selection. The runner must chain the derived steps
        after the job completes."""
        client, db_path, lib = env

        def fake_analyze(files, scale=0.5):
            for f in files:
                yield {"path": str(f), "decode_mode": "scaled",
                       "engine_version": "test",
                       "frame": {"sharpness_max": 0.8,
                                 "sharpness_mean": 0.3,
                                 "clipped_hi": 0.001, "clipped_lo": 0.001}}

        import shootr.analyze_runner as ar
        monkeypatch.setattr(ar.helper, "analyze_batch", fake_analyze)

        runner = JobRunner(db_path)
        client.app.state.runner = runner
        runner.start()
        try:
            job_id = client.post("/api/shoots/1/analyze").json()["job_id"]
            deadline = time.time() + 10
            while time.time() < deadline:
                shoots = client.get("/api/shoots").json()
                if shoots[0]["latest_selection_id"] is not None:
                    break
                time.sleep(0.05)
        finally:
            runner.stop()

        c = connect(db_path)
        scores = c.execute("SELECT COUNT(*) FROM score").fetchone()[0]
        entries = c.execute(
            "SELECT COUNT(*) FROM selection_entry").fetchone()[0]
        c.close()
        assert scores == 6, "scoring must run AFTER analysis lands"
        assert entries == 6, "selection must cover all photos"
        assert shoots[0]["latest_selection_id"] is not None


class TestSSE:
    def test_stream_emits_job_progress(self, env, tmp_path):
        client, db_path, _ = env
        c = connect(db_path)
        from shootr.jobs import create_job
        create_job(c, 1, "analyze", [1, 2, 3])
        c.close()

        # once=true: snapshot then close — the infinite stream can't be
        # cleanly interrupted under TestClient.
        with client.stream("GET", "/api/jobs/stream?once=true") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = [json.loads(line[6:]) for line in r.iter_lines()
                      if line.startswith("data: ")]
        assert len(events) == 1
        assert events[0]["kind"] == "analyze"
        assert events[0]["total"] == 3
