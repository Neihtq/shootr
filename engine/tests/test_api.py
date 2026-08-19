"""API contract tests (design 10) via FastAPI TestClient — the full loop a
client would drive, plus the contract rules that protect the seam."""

import json
import struct

import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app
from shootr.db import connect


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "shootr.db"
    backups = tmp_path / "backups"
    backups.mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()

    app = create_app(db_path, backups)
    client = TestClient(app)

    # Seed: library + shoot + analyzed burst of 5 (one with eyes closed),
    # going through the DB directly — analysis is the Swift helper's job and
    # is tested elsewhere.
    c = connect(db_path)
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, ?, 'now')", (str(lib),))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 'Test Wedding', 'event', 'now')")
    for i in range(1, 6):
        (lib / f"IMG_{i}.CR3").write_bytes(b"raw" * 100)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime, captured_at, subsec) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0, '2026-06-14T15:00:00', ?)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3", i * 100))
        frame = {"sharpness_max": 0.8, "sharpness_mean": 0.3,
                 "sharpness_tiles": [[0.1] * 16] * 16,
                 "clipped_hi": 0.001, "clipped_lo": 0.001}
        c.execute(
            "INSERT INTO analysis (photo_id, engine_version, decode_mode, "
            "frame, analyzed_at) VALUES (?, 'v1', 'scaled', ?, 'now')",
            (i, json.dumps(frame)))
        eye_open = 0.1 if i == 5 else 0.95
        c.execute(
            "INSERT INTO face (photo_id, idx, bbox, yaw, capture_quality, "
            "eye_sharp_l, eye_sharp_r, eye_open_l, eye_open_r, eye_source) "
            "VALUES (?, 0, ?, 0.0, 0.7, 0.8, 0.7, ?, ?, 'test')",
            (i, json.dumps([0.4, 0.4, 0.2, 0.25]), eye_open, eye_open))
        c.execute(
            "INSERT INTO embedding (photo_id, kind, vec, dim) "
            "VALUES (?, 'scene', ?, 3)",
            (i, struct.pack("3f", 1.0, 0.0, 0.0)))
    c.commit()
    c.close()
    return client, lib


def run_pipeline(client):
    assert client.post("/api/shoots/1/group").status_code == 200
    assert client.post("/api/shoots/1/score").status_code == 200
    r = client.post("/api/shoots/1/select", json={})
    assert r.status_code == 200
    return r.json()["selection_id"]


class TestContract:
    def test_health(self, env):
        client, _ = env
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["schema_version"] == 1

    def test_error_envelope_shape(self, env):
        """Stable code/message/detail/retryable (design 10 §5)."""
        client, _ = env
        r = client.get("/api/photos/999")
        assert r.status_code == 404
        err = r.json()["error"]
        assert set(err) == {"code", "message", "detail", "retryable"}

    def test_photo_detail_carries_evidence(self, env):
        """design 10 §3 — the payload the review UI decomposes."""
        client, _ = env
        run_pipeline(client)
        p = client.get("/api/photos/1").json()
        assert p["score"]["components"]["eye_focus"]["evidence"]
        assert p["score"]["weights_hash"].startswith("ev1-")
        assert p["faces"][0]["eyes"]["left"]["sharp_norm"] == 0.8
        assert p["group"]["size"] == 5
        assert p["selection"]["reason"]  # never a bare verdict

    def test_null_component_stays_null_in_json(self, env):
        """null ≠ 0 must survive serialization (design 10 §3)."""
        client, _ = env
        client.patch("/api/shoots/1", json={"profile": "landscape"})
        p = client.get("/api/photos/1").json()
        # face metrics don't exist for landscape profile weights
        assert "eye_focus" not in p["score"]["components"] or \
            p["score"]["components"]["eye_focus"]["value"] is None

    def test_profile_change_rescores_without_reanalysis(self, env):
        client, _ = env
        run_pipeline(client)
        r = client.patch("/api/shoots/1", json={"profile": "portrait"})
        assert r.json()["rescored"] == 5

    def test_photo_detail_serves_current_profile_score(self, env):
        """Regression (user-reported 'sharpness 0 on EVERY picture'): score
        rows for multiple profiles coexist; the detail endpoint must serve
        the shoot's CURRENT profile, not an arbitrary/stale row."""
        client, _ = env
        run_pipeline(client)  # scores as 'event'
        client.patch("/api/shoots/1", json={"profile": "landscape"})
        p = client.get("/api/photos/1").json()
        assert p["score"]["profile"] == "landscape"
        # And the listing endpoint joins on the current profile too.
        items = client.get("/api/shoots/1/photos").json()["items"]
        assert all(i["total"] is not None for i in items)


class TestPipelineFlow:
    def test_full_cull_loop(self, env):
        """The M1 loop: group → score → select → review states."""
        client, _ = env
        sel_id = run_pipeline(client)
        sel = client.get(f"/api/selections/{sel_id}").json()
        assert len(sel["entries"]) == 5
        by_photo = {e["photo_id"]: e for e in sel["entries"]}
        # Eyes-closed frame rejected with a named defect.
        assert by_photo[5]["state"] == "reject"
        assert "eyes closed" in by_photo[5]["reason"]

    def test_groups_and_members_come_back_in_capture_order(self, env):
        """Photo ids come from ingest and do NOT ascend with capture time, so
        an unordered query hands the client a filmstrip that scrubs out of
        sequence — and `subsec` has to break ties between burst frames
        sharing a whole second (design 05 §3)."""
        client, lib = env
        c = connect(client.app.state.db_path)
        # Two frames in one second, inserted with ids descending against time.
        c.execute("UPDATE photo SET captured_at = '2026-06-14T15:00:00', "
                  "subsec = 900 WHERE id = 1")
        c.execute("UPDATE photo SET captured_at = '2026-06-14T15:00:00', "
                  "subsec = 100 WHERE id = 2")
        c.commit(); c.close()
        run_pipeline(client)

        groups = client.get("/api/shoots/1/groups").json()
        members = [pid for g in groups for pid in g["photo_ids"]]
        c = connect(client.app.state.db_path)
        order = {r["id"]: (r["captured_at"], r["subsec"]) for r in
                 c.execute("SELECT id, captured_at, subsec FROM photo")}
        c.close()
        keys = [order[pid] for pid in members]
        assert keys == sorted(keys), "filmstrip must scrub chronologically"
        # Photo 2 (subsec 100) precedes photo 1 (subsec 900) despite the id.
        assert members.index(2) < members.index(1)

    def test_override_and_regenerate(self, env):
        client, _ = env
        sel_id = run_pipeline(client)
        r = client.patch(f"/api/selections/{sel_id}/entries/5",
                         json={"state": "pick"})
        assert r.json()["user_override"] is True
        sel2 = client.post("/api/shoots/1/select", json={}).json()[
            "selection_id"]
        e = {x["photo_id"]: x for x in
             client.get(f"/api/selections/{sel2}").json()["entries"]}
        assert e[5]["state"] == "pick" and e[5]["user_override"] == 1

    def test_analyze_with_nothing_pending_chains_inline(self, env):
        """All photos already analyzed → the derived steps (group/score/
        select) run inline so 'Analyze & cull' is one action either way."""
        client, _ = env
        r = client.post("/api/shoots/1/analyze")
        assert r.status_code == 200
        assert r.json()["total"] == 0  # all 5 already analyzed
        assert r.json()["chained"] is True
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        assert job["state"] == "done"
        # The chain actually produced a selection.
        shoots = client.get("/api/shoots").json()
        assert shoots[0]["latest_selection_id"] is not None

    def test_busy_job_id_gates_opening_a_shoot(self, env):
        """Clients must not let the user open a shoot mid-cull: there are no
        groups or scores until the chained steps run. Server-derived so a
        relaunch or the other frontend agrees."""
        client, lib = env
        assert client.get("/api/shoots").json()[0]["busy_job_id"] is None

        c = connect(client.app.state.db_path)
        c.execute(
            "INSERT INTO job (id, shoot_id, kind, state, total, completed, "
            "created_at, updated_at) VALUES "
            "(99, 1, 'analyze', 'running', 10, 3, datetime('now'), "
            "datetime('now'))")
        c.commit()
        assert client.get("/api/shoots").json()[0]["busy_job_id"] == 99

        # Finished → open again.
        c.execute("UPDATE job SET state = 'done' WHERE id = 99")
        c.commit()
        assert client.get("/api/shoots").json()[0]["busy_job_id"] is None

        # A job paused by an offline volume is pending but NOT progressing.
        # Treating it as busy would lock the shoot while the drive is out.
        c.execute("UPDATE job SET state = 'pending', error = 'volume_offline' "
                  "WHERE id = 99")
        c.commit(); c.close()
        assert client.get("/api/shoots").json()[0]["busy_job_id"] is None

    def test_crashed_job_does_not_lock_the_shoot_forever(self, env):
        """The gate's failure mode. A helper crash/stall leaves the job row
        'running'; nothing resubmits it, so a NULL error would keep the card
        locked with no worker draining it — worse than the hang it replaced.
        `interrupt_job` records why it stopped, which releases the gate."""
        from shootr import jobs

        client, _ = env
        c = connect(client.app.state.db_path)
        c.execute(
            "INSERT INTO job (id, shoot_id, kind, state, total, completed, "
            "created_at, updated_at) VALUES "
            "(77, 1, 'analyze', 'running', 5, 2, datetime('now'), "
            "datetime('now'))")
        c.commit()
        assert client.get("/api/shoots").json()[0]["busy_job_id"] == 77

        jobs.interrupt_job(c, 77, "helper_failed")
        c.close()
        s = client.get("/api/shoots").json()[0]
        assert s["busy_job_id"] is None
        # Unlocked, but not misreported as never-analyzed: the clients show
        # the reason and offer Resume.
        assert s["stopped_reason"] == "helper_failed"

    def test_restart_does_not_lock_the_shoot(self, env):
        """Same hazard via the startup sweep: reset_stale_running returns the
        job to 'pending', but nothing resubmits it on boot."""
        from shootr import jobs

        client, _ = env
        c = connect(client.app.state.db_path)
        c.execute(
            "INSERT INTO job (id, shoot_id, kind, state, total, completed, "
            "created_at, updated_at) VALUES "
            "(78, 1, 'analyze', 'running', 5, 2, datetime('now'), "
            "datetime('now'))")
        c.commit()
        jobs.reset_stale_running(c)
        c.close()
        assert client.get("/api/shoots").json()[0]["busy_job_id"] is None

    def test_interrupted_job_resumes_instead_of_409(self, env):
        """Unlocking the card is only useful if the user can act on it: the
        retry must resume the interrupted job, not collide with it."""
        from shootr import jobs

        client, lib = env
        (lib / "IMG_9.CR3").write_bytes(b"x" * 100)
        c = connect(client.app.state.db_path)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (9, 1, 1, 'c9', 'IMG_9.CR3', 'IMG_9.CR3', 1, 0)")
        c.commit(); c.close()

        first = client.post("/api/shoots/1/analyze").json()["job_id"]
        c = connect(client.app.state.db_path)
        jobs.interrupt_job(c, first, "helper_failed")
        c.close()

        r = client.post("/api/shoots/1/analyze")
        assert r.status_code == 200
        assert r.json()["job_id"] == first  # resumed, not a duplicate
        # Back in flight → gated again, and the checkpoint is intact.
        s = client.get("/api/shoots").json()[0]
        assert s["busy_job_id"] == first

    def test_job_conflict_is_409(self, env):
        client, lib = env
        (lib / "IMG_9.CR3").write_bytes(b"x" * 100)
        c = connect(client.app.state.db_path)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (9, 1, 1, 'c9', 'IMG_9.CR3', 'IMG_9.CR3', 1, 0)")
        c.commit(); c.close()
        assert client.post("/api/shoots/1/analyze").status_code == 200
        r = client.post("/api/shoots/1/analyze")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "job_conflict"


class TestExport:
    def test_preview_then_export(self, env):
        client, lib = env
        sel_id = run_pipeline(client)
        preview = client.post(
            f"/api/selections/{sel_id}/export/preview").json()
        assert preview["new_sidecars"] > 0
        assert preview["conflicts"] == []

        r = client.post(f"/api/selections/{sel_id}/export", json={})
        assert r.json()["written"] == preview["new_sidecars"]
        # Sidecars exist for picks; rejected photo has none.
        assert (lib / "IMG_1.xmp").exists()
        assert not (lib / "IMG_5.xmp").exists()

    def test_conflict_blocks_without_confirm(self, env):
        client, lib = env
        sel_id = run_pipeline(client)
        # Find a picked photo and give it a sidecar with develop settings.
        sel = client.get(f"/api/selections/{sel_id}").json()
        pick = next(e["photo_id"] for e in sel["entries"]
                    if e["state"] == "pick")
        (lib / f"IMG_{pick}.xmp").write_text(
            '<x:xmpmeta xmlns:x="a"><rdf:RDF '
            'xmlns:rdf="r"><rdf:Description xmlns:xmp="x" '
            'xmlns:crs="c" xmp:Rating="1" crs:Exposure2012="+1.0">'
            "</rdf:Description></rdf:RDF></x:xmpmeta>")
        r = client.post(f"/api/selections/{sel_id}/export", json={})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "sidecar_conflict"

    def test_frozen_after_export(self, env):
        client, _ = env
        sel_id = run_pipeline(client)
        client.post(f"/api/selections/{sel_id}/export", json={})
        r = client.patch(f"/api/selections/{sel_id}/entries/1",
                         json={"state": "reject"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "selection_frozen"
