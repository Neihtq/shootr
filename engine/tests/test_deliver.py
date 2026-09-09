"""Delivery tests (design 07 §3.2b).

The safety properties are what these pin down: rejects untouched, a move that
never risks the original, nothing overwritten, and a library that does not lie
about where a photo went.
"""

import os

import pytest

from shootr.db import connect
from shootr.deliver import DeliveryImpossible, execute, plan


@pytest.fixture
def env(tmp_path):
    lib = tmp_path / "shoot"
    lib.mkdir()
    out = tmp_path / "selects"
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, ?, 'now')", (str(lib),))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    entries = []
    states = ["pick", "pick", "alt", "reject"]
    for i, state in enumerate(states, start=1):
        raw = lib / f"IMG_{i}.CR3"
        raw.write_bytes(b"raw-data-%d" % i * 100)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, ?, 0)",
            (i, f"c{i}", raw.name, raw.name, raw.stat().st_size))
        entries.append((i, raw, state))
    c.commit()
    return c, lib, out, entries


def test_picks_only_by_default_rejects_never_touched(env):
    c, lib, out, entries = env
    p = plan(entries, out, "copy")
    assert [i.source.name for i in p.items] == ["IMG_1.CR3", "IMG_2.CR3"]
    execute(c, p, lib)
    assert sorted(f.name for f in out.iterdir()) == ["IMG_1.CR3", "IMG_2.CR3"]
    # Every original still in place, including the reject.
    assert sorted(f.name for f in lib.iterdir()) == [
        "IMG_1.CR3", "IMG_2.CR3", "IMG_3.CR3", "IMG_4.CR3"]


def test_alt_is_opt_in(env):
    c, lib, out, entries = env
    p = plan(entries, out, "copy", states=("pick", "alt"))
    assert len(p.items) == 3
    # A reject is not reachable even by asking for it explicitly here: the
    # caller chooses states, and the API never offers 'reject'.
    assert all(i.source.name != "IMG_4.CR3" for i in p.items)


def test_hardlink_shares_inodes_and_costs_nothing(env):
    c, lib, out, entries = env
    execute(c, plan(entries, out, "hardlink"), lib)
    a = (lib / "IMG_1.CR3").stat()
    b = (out / "IMG_1.CR3").stat()
    assert a.st_ino == b.st_ino and b.st_nlink >= 2


def test_hardlink_across_volumes_is_refused_before_writing(env, monkeypatch):
    c, lib, out, entries = env
    real_stat = os.stat_result

    def fake_stat(self, *a, **k):
        s = os.stat(str(self))
        # Pretend the destination is on another device.
        dev = 999 if "selects" in str(self) else s.st_dev
        return real_stat((s.st_mode, s.st_ino, dev, s.st_nlink, s.st_uid,
                          s.st_gid, s.st_size, s.st_atime, s.st_mtime,
                          s.st_ctime))
    out.mkdir()
    monkeypatch.setattr("pathlib.Path.stat", fake_stat)
    with pytest.raises(DeliveryImpossible, match="cannot cross volumes"):
        plan(entries, out, "hardlink")
    assert not list(out.iterdir()), "nothing written when the mode is refused"


def test_move_relocates_and_keeps_the_library_honest(env):
    c, lib, out, entries = env
    # Destination OUTSIDE the library root → the photos leave the library.
    r = execute(c, plan(entries, out, "move"), lib)
    assert r.marked_missing == 2 and r.relinked == 0
    assert not (lib / "IMG_1.CR3").exists()
    assert (out / "IMG_1.CR3").is_file()
    rows = dict(c.execute("SELECT id, missing FROM photo").fetchall())
    assert rows[1] == 1 and rows[2] == 1
    # Untouched photos keep missing = 0.
    assert rows[3] == 0 and rows[4] == 0


def test_move_inside_the_library_updates_the_path_instead(env):
    c, lib, out, entries = env
    inside = lib / "keepers"
    r = execute(c, plan(entries, inside, "move"), lib)
    assert r.relinked == 2 and r.marked_missing == 0
    row = c.execute("SELECT rel_path, missing FROM photo WHERE id = 1"
                    ).fetchone()
    assert row["rel_path"] == "keepers/IMG_1.CR3" and row["missing"] == 0


def test_sidecars_and_jpeg_siblings_travel_along(env):
    c, lib, out, entries = env
    (lib / "IMG_1.xmp").write_text("<x:xmpmeta/>")
    (lib / "IMG_1.jpg").write_bytes(b"jpeg")
    r = execute(c, plan(entries, out, "copy"), lib)
    assert r.companions == 2
    assert (out / "IMG_1.xmp").is_file() and (out / "IMG_1.jpg").is_file()


def test_existing_file_is_never_overwritten(env):
    c, lib, out, entries = env
    out.mkdir()
    (out / "IMG_1.CR3").write_bytes(b"SOMETHING ELSE")
    p = plan(entries, out, "copy")
    r = execute(c, p, lib)
    assert (out / "IMG_1.CR3").read_bytes() == b"SOMETHING ELSE"
    assert "IMG_1_2.CR3" in r.renamed and (out / "IMG_1_2.CR3").is_file()


def test_copy_refuses_when_the_disk_is_too_small(env):
    c, lib, out, entries = env
    p = plan(entries, out, "copy")
    p.free_bytes = 1          # as if the destination were full
    p.bytes_needed = 10 ** 9
    with pytest.raises(DeliveryImpossible, match="GB free"):
        execute(c, p, lib)
    assert not out.exists() or not list(out.iterdir())


def test_one_unreadable_photo_does_not_abandon_the_rest(env):
    c, lib, out, entries = env
    p = plan(entries, out, "copy")
    p.items[0].source = lib / "GONE.CR3"      # vanished after planning
    r = execute(c, p, lib)
    assert len(r.failed) == 1 and len(r.delivered) == 1
    assert (out / "IMG_2.CR3").is_file()


def test_missing_sources_are_reported_by_the_plan(env):
    c, lib, out, entries = env
    (lib / "IMG_1.CR3").unlink()
    p = plan(entries, out, "copy")
    assert p.missing_source == [str(lib / "IMG_1.CR3")]
    assert len(p.items) == 1
