"""Tests for the M1 straggler fixes: collision escalation, group-shot blink
flag, group move endpoint."""

import json
import struct

import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app
from shootr.db import connect
from shootr.ingest import scan
from shootr.scoring import Eye, FaceMeasurement, FrameMeasurement, \
    Measurements, score


class TestCollisionEscalation:
    """design 01 §2: same head/tail hash + different full hash must not be
    silently merged into one Photo."""

    def test_middle_difference_same_size_kept_distinct(self, tmp_path, caplog):
        db = connect(tmp_path / "db.sqlite")
        lib = tmp_path / "lib"
        lib.mkdir()
        db.execute("INSERT INTO library (id, root_path, created_at) "
                   "VALUES (1, ?, 'now')", (str(lib),))

        # Same size, same first/last 64KB, different middle → head/tail
        # collision by construction.
        head = b"h" * (64 * 1024)
        tail = b"t" * (64 * 1024)
        (lib / "a.cr3").write_bytes(head + b"MIDDLE_ONE" + tail)
        (lib / "b.cr3").write_bytes(head + b"MIDDLE_TWO" + tail)

        with caplog.at_level("ERROR", logger="shootr.ingest"):
            result = scan(db, 1, lib)

        assert result.added == 2  # both photos exist
        assert result.duplicates == 0  # NOT merged
        assert any("collision" in r.message for r in caplog.records)
        cids = [r["content_id"] for r in
                db.execute("SELECT content_id FROM photo")]
        assert len(set(cids)) == 2  # distinct stored ids
        db.close()

    def test_true_duplicates_still_merge(self, tmp_path):
        db = connect(tmp_path / "db.sqlite")
        lib = tmp_path / "lib"
        lib.mkdir()
        db.execute("INSERT INTO library (id, root_path, created_at) "
                   "VALUES (1, ?, 'now')", (str(lib),))
        (lib / "a.cr3").write_bytes(b"same" * 100)
        (lib / "b.cr3").write_bytes(b"same" * 100)
        result = scan(db, 1, lib)
        assert result.added == 1 and result.duplicates == 1
        db.close()


class TestOtherSubjectBlinking:
    """design 04 §2.2: non-primary blinks are flagged, never averaged in."""

    def _measure(self, other_open):
        big = FaceMeasurement(
            idx=0, bbox=(0.3, 0.3, 0.3, 0.35),
            left=Eye(0.8, 0.95), right=Eye(0.7, 0.95))
        other = FaceMeasurement(
            idx=1, bbox=(0.7, 0.4, 0.1, 0.12),
            left=Eye(0.5, other_open), right=Eye(0.5, other_open))
        return Measurements(
            frame=FrameMeasurement(sharpness_max=0.8, sharpness_mean=0.3,
                                   clipped_hi=0.001, clipped_lo=0.001),
            faces=[big, other])

    def test_blinking_other_flagged(self):
        rec = score(self._measure(other_open=0.1), "event")
        assert "other_subject_blinking:1" in rec.flags

    def test_open_other_not_flagged(self):
        rec = score(self._measure(other_open=0.95), "event")
        assert not any(f.startswith("other_subject_blinking")
                       for f in rec.flags)

    def test_primary_score_unaffected_by_other_blink(self):
        """The flag is a flag — the primary's eyes_open score must not move."""
        blinky = score(self._measure(other_open=0.1), "event")
        clear = score(self._measure(other_open=0.95), "event")
        assert blinky.components["eyes_open"]["value"] == \
            clear.components["eyes_open"]["value"]


class TestGroupMove:
    @pytest.fixture
    def env(self, tmp_path):
        (tmp_path / "backups").mkdir()
        app = create_app(tmp_path / "db.sqlite", tmp_path / "backups")
        client = TestClient(app)
        c = connect(tmp_path / "db.sqlite")
        c.execute("INSERT INTO library (id, root_path, created_at) "
                  "VALUES (1, '/x', 'now')")
        c.execute("INSERT INTO shoot (id, library_id, name, profile, "
                  "created_at) VALUES (1, 1, 's', 'event', 'now')")
        for i in range(1, 5):
            c.execute(
                "INSERT INTO photo (id, library_id, shoot_id, content_id, "
                "rel_path, filename, file_size, mtime) "
                "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
                (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3"))
        c.execute('INSERT INTO "group" (id, shoot_id, level, is_bracket) '
                  "VALUES (10, 1, 'shot', 0)")
        c.execute('INSERT INTO "group" (id, shoot_id, level, is_bracket) '
                  "VALUES (11, 1, 'shot', 0)")
        c.execute('INSERT INTO "group" (id, shoot_id, level, is_bracket) '
                  "VALUES (12, 1, 'shot', 1)")
        c.executemany("INSERT INTO group_member (group_id, photo_id) "
                      "VALUES (?, ?)", [(10, 1), (10, 2), (11, 3), (12, 4)])
        c.commit()
        c.close()
        return client

    def test_move(self, env):
        r = env.post("/api/groups/10/move",
                     json={"photo_id": 2, "to_group_id": 11})
        assert r.status_code == 200
        groups = {g["id"]: sorted(g["photo_ids"])
                  for g in env.get("/api/shoots/1/groups").json()}
        assert groups[10] == [1] and groups[11] == [2, 3]

    def test_emptied_group_deleted(self, env):
        env.post("/api/groups/10/move", json={"photo_id": 1, "to_group_id": 11})
        r = env.post("/api/groups/10/move", json={"photo_id": 2, "to_group_id": 11})
        assert r.json()["source_deleted"] is True
        ids = {g["id"] for g in env.get("/api/shoots/1/groups").json()}
        assert 10 not in ids

    def test_bracket_move_rejected(self, env):
        r = env.post("/api/groups/12/move",
                     json={"photo_id": 4, "to_group_id": 11})
        assert r.status_code == 409
        r = env.post("/api/groups/11/move",
                     json={"photo_id": 3, "to_group_id": 12})
        assert r.status_code == 409

    def test_photo_not_in_group_rejected(self, env):
        r = env.post("/api/groups/10/move",
                     json={"photo_id": 3, "to_group_id": 11})
        assert r.status_code == 400
