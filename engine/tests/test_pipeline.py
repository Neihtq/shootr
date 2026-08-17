"""End-to-end pipeline tests: analysis rows → score → group → select,
all against real SQLite. The integration seams the pure-module tests skip."""

import json
import struct

import pytest

from shootr.db import connect
from shootr.pipeline import (
    create_selection,
    group_shoot,
    override_entry,
    score_shoot,
)


def emb_blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)


EMB_A = (1.0, 0.0, 0.0)
EMB_B = (0.0, 1.0, 0.0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/x', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    yield c
    c.close()


def add_photo(conn, pid, t, subsec=0, bias=0.0, emb=EMB_A,
              eye_sharp=0.8, eye_open=0.95, sharp_max=0.8, faces=1):
    conn.execute(
        "INSERT INTO photo (id, library_id, shoot_id, content_id, rel_path, "
        "filename, file_size, mtime, captured_at, subsec, exposure_bias) "
        "VALUES (?, 1, 1, ?, ?, ?, 1, 0, ?, ?, ?)",
        (pid, f"c{pid}", f"IMG_{pid}.CR3", f"IMG_{pid}.CR3", t, subsec, bias),
    )
    frame = {"sharpness_max": sharp_max, "sharpness_mean": 0.3,
             "clipped_hi": 0.001, "clipped_lo": 0.001}
    conn.execute(
        "INSERT INTO analysis (photo_id, engine_version, decode_mode, frame, "
        "analyzed_at) VALUES (?, 'v1', 'scaled', ?, 'now')",
        (pid, json.dumps(frame)),
    )
    for i in range(faces):
        conn.execute(
            "INSERT INTO face (photo_id, idx, bbox, yaw, capture_quality, "
            "eye_sharp_l, eye_sharp_r, eye_open_l, eye_open_r, eye_source) "
            "VALUES (?, ?, ?, 0.0, 0.7, ?, ?, ?, ?, 'test')",
            (pid, i, json.dumps([0.4, 0.4, 0.2, 0.25]),
             eye_sharp, eye_sharp - 0.1, eye_open, eye_open),
        )
    conn.execute(
        "INSERT INTO embedding (photo_id, kind, vec, dim) "
        "VALUES (?, 'scene', ?, ?)",
        (pid, emb_blob(emb), len(emb)),
    )


def burst(conn, ids, t0="2026-06-14T15:00:00", **kw):
    for i, pid in enumerate(ids):
        add_photo(conn, pid, t0, subsec=i * 100, **kw)


class TestScoreShoot:
    def test_scores_written_with_detected_flags(self, conn):
        add_photo(conn, 1, "2026-06-14T15:00:00")
        n = score_shoot(conn, 1)
        assert n == 1
        row = conn.execute("SELECT * FROM score").fetchone()
        assert row["profile"] == "event"
        assert row["total"] > 0.5
        comps = json.loads(row["components"])
        assert comps["eye_focus"]["value"] == 1.0
        # Flag detectors ran: thirds_distance is always emitted for a subject.
        assert any(f.startswith("thirds_distance")
                   for f in json.loads(row["flags"]))

    def test_rescore_after_profile_change_no_reanalysis(self, conn):
        """The Analysis/Score split payoff (design 01): profile change =
        rescore only, analysis untouched."""
        add_photo(conn, 1, "2026-06-14T15:00:00")
        score_shoot(conn, 1)
        conn.execute("UPDATE shoot SET profile = 'portrait' WHERE id = 1")
        score_shoot(conn, 1)
        profiles = {r["profile"] for r in
                    conn.execute("SELECT profile FROM score")}
        assert profiles == {"event", "portrait"}  # both coexist (§01 schema)
        assert conn.execute(
            "SELECT COUNT(*) FROM analysis").fetchone()[0] == 1

    def test_bracket_photo_scored_with_exposure_suppressed(self, conn):
        # A -2EV frame with heavy clipping, inside a bracket group.
        add_photo(conn, 1, "2026-06-14T15:00:00", bias=-2.0)
        conn.execute(
            'INSERT INTO "group" (id, shoot_id, level, is_bracket) '
            "VALUES (10, 1, 'shot', 1)")
        conn.execute(
            "INSERT INTO group_member (group_id, photo_id) VALUES (10, 1)")
        score_shoot(conn, 1)
        comps = json.loads(
            conn.execute("SELECT components FROM score").fetchone()[0])
        assert comps["exposure"]["value"] is None
        assert comps["exposure"]["evidence"]["reason"] == \
            "suppressed_in_bracket"


class TestGroupShoot:
    def test_bursts_become_shot_groups(self, conn):
        burst(conn, [1, 2, 3])
        burst(conn, [4, 5], t0="2026-06-14T16:00:00", emb=EMB_B)
        n = group_shoot(conn, 1)
        assert n == 2
        rows = conn.execute(
            'SELECT g.id, COUNT(*) AS n FROM "group" g '
            "JOIN group_member gm ON gm.group_id = g.id "
            "WHERE g.level = 'shot' GROUP BY g.id ORDER BY g.id").fetchall()
        assert [r["n"] for r in rows] == [3, 2]

    def test_bracket_persisted_sealed(self, conn):
        for i, bias in enumerate([-2.0, 0.0, 2.0]):
            add_photo(conn, i + 1, "2026-06-14T15:00:00", subsec=i * 400,
                      bias=bias)
        group_shoot(conn, 1)
        row = conn.execute(
            'SELECT is_bracket FROM "group" WHERE level = ?', ("shot",)
        ).fetchone()
        assert row["is_bracket"] == 1

    def test_regroup_replaces_groups(self, conn):
        burst(conn, [1, 2, 3])
        group_shoot(conn, 1)
        group_shoot(conn, 1)
        n = conn.execute(
            'SELECT COUNT(*) FROM "group" WHERE level = ?', ("shot",)
        ).fetchone()[0]
        assert n == 1  # no duplicates from re-running


class TestSelection:
    def _pipeline(self, conn):
        group_shoot(conn, 1)
        score_shoot(conn, 1)
        return create_selection(conn, 1)

    def test_end_to_end_pick_alt_reject(self, conn):
        burst(conn, [1, 2, 3, 4, 5, 6])  # one 6-frame burst, event profile
        # Frame 6: eyes closed → should be rejected with a named reason.
        conn.execute("UPDATE face SET eye_open_l = 0.1, eye_open_r = 0.1 "
                     "WHERE photo_id = 6")
        sel = self._pipeline(conn)
        entries = {r["photo_id"]: r for r in conn.execute(
            "SELECT * FROM selection_entry WHERE selection_id = ?", (sel,))}
        assert len(entries) == 6
        states = {e["state"] for e in entries.values()}
        assert states == {"pick", "alt", "reject"}
        assert entries[6]["state"] == "reject"
        assert "eyes closed" in entries[6]["reason"]
        assert all(e["reason"] for e in entries.values())

    def test_bracket_all_picked_end_to_end(self, conn):
        """The full-stack HDR guard: detection → grouping → culling → DB."""
        for i, bias in enumerate([-2.0, 0.0, 2.0]):
            add_photo(conn, i + 1, "2026-06-14T15:00:00", subsec=i * 400,
                      bias=bias)
        sel = self._pipeline(conn)
        states = [r["state"] for r in conn.execute(
            "SELECT state FROM selection_entry WHERE selection_id = ?",
            (sel,))]
        assert states == ["pick", "pick", "pick"]

    def test_override_survives_regeneration(self, conn):
        burst(conn, [1, 2, 3, 4, 5])
        sel1 = self._pipeline(conn)
        reject = conn.execute(
            "SELECT photo_id FROM selection_entry WHERE selection_id = ? "
            "AND state = 'reject' LIMIT 1", (sel1,)).fetchone()["photo_id"]
        override_entry(conn, sel1, reject, "pick")
        sel2 = create_selection(conn, 1)  # regenerate
        assert sel2 != sel1  # versioned, not mutated (design 06 §5)
        row = conn.execute(
            "SELECT state, user_override FROM selection_entry "
            "WHERE selection_id = ? AND photo_id = ?",
            (sel2, reject)).fetchone()
        assert row["state"] == "pick" and row["user_override"] == 1

    def test_frozen_selection_rejects_override(self, conn):
        burst(conn, [1, 2, 3])
        sel = self._pipeline(conn)
        conn.execute("UPDATE selection SET exported_at = 'now' WHERE id = ?",
                     (sel,))
        with pytest.raises(ValueError, match="frozen"):
            override_entry(conn, sel, 1, "reject")

    def test_invalid_override_state_rejected(self, conn):
        burst(conn, [1, 2, 3])
        sel = self._pipeline(conn)
        with pytest.raises(ValueError):
            override_entry(conn, sel, 1, "delete")
