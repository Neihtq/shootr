"""Tests for the M1 finish items: profile hints, landscape focus-plane,
rolling rate/ETA, hardlink Selects folder."""

import time

import pytest

from shootr.scoring import (
    Eye,
    FaceMeasurement,
    FrameMeasurement,
    Measurements,
    score,
)
from shootr.xmp import export_hardlinks


def face(idx=0, open_=0.95):
    return FaceMeasurement(
        idx=idx, bbox=(0.1 + idx * 0.1, 0.4, 0.08, 0.1), yaw=0.0,
        capture_quality=0.7,
        left=Eye(0.8, open_), right=Eye(0.7, open_))


def sharp_frame(**kw):
    defaults = dict(sharpness_max=0.08, sharpness_mean=0.01,
                    clipped_hi=0.001, clipped_lo=0.001)
    return FrameMeasurement(**{**defaults, **kw})


def tiles(pattern: str, n=16, max_v=0.08):
    """'full' = sharp everywhere; 'band' = sharp middle rows only;
    'center' = sharp center, soft corners."""
    t = [[0.001] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            if pattern == "full":
                t[y][x] = max_v * 0.8
            elif pattern == "band" and n // 3 <= y < 2 * n // 3:
                t[y][x] = max_v * 0.8
            elif pattern == "center" and 3 <= y < n - 3 and 3 <= x < n - 3:
                t[y][x] = max_v * 0.8
    t[0][0] = max(t[0][0], 0.0)
    t[n // 2][n // 2] = max_v  # ensure stated max exists
    return t


class TestProfileHints:
    """design 04 §4.4 — renormalization within a profile, not a new one."""

    def test_no_faces_in_event_named_and_renormalized(self):
        m = Measurements(frame=sharp_frame())  # rings/venue detail shot
        rec = score(m, "event")
        # Face metrics stay as null (design 04 §5 — UI shows "—" and why);
        # the hint names the situation; weights renormalize over the rest.
        assert rec.components["eye_focus"]["value"] is None
        assert "profile_hint:no_faces_detail_shot" in rec.flags
        live = [c for c in rec.components.values() if c["value"] is not None]
        assert sum(c["weight"] for c in live) == pytest.approx(1.0, abs=1e-3)

    def test_group_shot_hint_flagged(self):
        m = Measurements(frame=sharp_frame(),
                         faces=[face(idx=i) for i in range(8)])
        rec = score(m, "event")
        assert "profile_hint:group_shot" in rec.flags

    def test_normal_face_count_no_hint(self):
        m = Measurements(frame=sharp_frame(), faces=[face()])
        rec = score(m, "event")
        assert not any(f.startswith("profile_hint") for f in rec.flags)

    def test_landscape_unaffected_by_hints(self):
        m = Measurements(frame=sharp_frame())
        rec = score(m, "landscape")
        assert not any(f.startswith("profile_hint") for f in rec.flags)


class TestLandscapeFocusPlane:
    """design 04 §4.3 — coverage of the sharp plane, not peak sharpness."""

    def test_full_coverage_beats_narrow_band(self):
        full = Measurements(frame=sharp_frame(
            sharpness_tiles=tiles("full")))
        band = Measurements(frame=sharp_frame(
            sharpness_tiles=tiles("band")))
        s_full = score(full, "landscape").components["sharpness"]
        s_band = score(band, "landscape").components["sharpness"]
        assert s_full["value"] > s_band["value"]
        assert "focus_plane_coverage" in s_full["evidence"]

    def test_soft_corners_cap_score(self):
        center = Measurements(frame=sharp_frame(
            sharpness_tiles=tiles("center")))
        s = score(center, "landscape").components["sharpness"]
        assert s["evidence"]["corner_ratio"] < 0.05
        assert s["value"] <= 0.7

    def test_no_tile_map_falls_back(self):
        m = Measurements(frame=sharp_frame(sharpness_tiles=None))
        s = score(m, "landscape").components["sharpness"]
        assert s["value"] is not None  # measurable frame never nulled

    def test_event_profile_uses_plain_sharpness(self):
        m = Measurements(frame=sharp_frame(sharpness_tiles=tiles("band")),
                         faces=[face()])
        s = score(m, "event").components["sharpness"]
        assert "focus_plane_coverage" not in s["evidence"]


class TestRollingRate:
    def test_rate_and_eta_reported_while_running(self, tmp_path):
        from shootr.db import connect
        from shootr.jobs import claim_items, complete_items, create_job, \
            progress

        c = connect(tmp_path / "db.sqlite")
        c.execute("INSERT INTO library (id, root_path, created_at) "
                  "VALUES (1, '/x', 'now')")
        c.execute("INSERT INTO shoot (id, library_id, name, profile, "
                  "created_at) VALUES (1, 1, 's', 'event', 'now')")
        for i in range(1, 101):
            c.execute(
                "INSERT INTO photo (id, library_id, shoot_id, content_id, "
                "rel_path, filename, file_size, mtime) "
                "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
                (i, f"c{i}", f"I{i}.CR3", f"I{i}.CR3"))
        job = create_job(c, 1, "analyze", list(range(1, 101)))
        claim_items(c, job, list(range(1, 101)))

        complete_items(c, job, list(range(1, 21)))
        p1 = progress(c, job)  # first sample: no rate yet
        assert p1.rate_per_sec is None
        time.sleep(0.15)
        complete_items(c, job, list(range(21, 41)))
        p2 = progress(c, job)
        assert p2.rate_per_sec is not None and p2.rate_per_sec > 0
        assert p2.eta_sec is not None and p2.eta_sec >= 0
        c.close()


class TestHardlinkSelects:
    def test_links_picks_only(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        pick = lib / "IMG_1.CR3"
        rej = lib / "IMG_2.CR3"
        pick.write_bytes(b"p" * 100)
        rej.write_bytes(b"r" * 100)
        dest = tmp_path / "selects"
        n = export_hardlinks([(pick, "pick"), (rej, "reject")], dest)
        assert n == 1
        assert (dest / "IMG_1.CR3").exists()
        assert not (dest / "IMG_2.CR3").exists()
        # Hardlink, not copy: same inode.
        assert (dest / "IMG_1.CR3").stat().st_ino == pick.stat().st_ino

    def test_idempotent(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        pick = lib / "IMG_1.CR3"
        pick.write_bytes(b"p")
        dest = tmp_path / "selects"
        export_hardlinks([(pick, "pick")], dest)
        n = export_hardlinks([(pick, "pick")], dest)  # re-export
        assert n == 0  # already linked; no duplicates invented
        assert len(list(dest.iterdir())) == 1

    def test_missing_file_skipped(self, tmp_path):
        ghost = tmp_path / "lib" / "gone.CR3"
        n = export_hardlinks([(ghost, "pick")], tmp_path / "selects")
        assert n == 0
