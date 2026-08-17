"""Ingest tests (design 02). Synthetic files; no real RAWs needed."""

import os

import pytest

from shootr.db import connect
from shootr.ingest import (
    content_id,
    discover,
    pair_files,
    propose_shoots,
    scan,
)


@pytest.fixture
def conn(tmp_path):
    (tmp_path / "db").mkdir()
    c = connect(tmp_path / "db" / "shootr.db")
    yield c
    c.close()


@pytest.fixture
def library(conn, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    conn.execute(
        "INSERT INTO library (id, root_path, created_at) VALUES (1, ?, 'now')",
        (str(root),),
    )
    return root


def make_raw(root, rel, content=b"rawdata", mtime=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content * 100)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class TestDiscover:
    def test_skips_hidden_lightroom_and_junk_dirs(self, tmp_path):
        root = tmp_path / "lib"
        make_raw(root, "a/IMG_1.CR3")
        make_raw(root, ".hidden/IMG_2.CR3")
        make_raw(root, "@eaDir/IMG_3.CR3")
        make_raw(root, "cat_previews.lrdata/IMG_4.CR3")
        make_raw(root, "wedding.lrcat-data/IMG_5.CR3")
        make_raw(root, "a/notes.txt")
        found = {f.rel_path for f in discover(root)}
        assert found == {"a/IMG_1.CR3"}

    def test_stat_comes_with_entry(self, tmp_path):
        root = tmp_path / "lib"
        p = make_raw(root, "IMG_1.ARW")
        f = next(iter(discover(root)))
        assert f.size == p.stat().st_size
        assert f.ext == "arw"


class TestContentIdentity:
    def test_same_bytes_same_id_regardless_of_name(self, tmp_path):
        a = make_raw(tmp_path, "a.cr3", b"identical")
        b = make_raw(tmp_path, "b.cr3", b"identical")
        assert content_id(a, a.stat().st_size) == content_id(b, b.stat().st_size)

    def test_different_bytes_different_id(self, tmp_path):
        a = make_raw(tmp_path, "a.cr3", b"aaaa")
        b = make_raw(tmp_path, "b.cr3", b"bbbb")
        assert content_id(a, a.stat().st_size) != content_id(b, b.stat().st_size)

    def test_large_file_reads_head_and_tail_only(self, tmp_path):
        # Two 5 MB files differing only in the middle third would collide —
        # that's the documented trade-off; size+head+tail distinguishes real
        # captures. Here: same head, different tail → different id.
        a = tmp_path / "a.cr3"
        b = tmp_path / "b.cr3"
        head = b"h" * (128 * 1024)
        a.write_bytes(head + b"tail-one" * 8192)
        b.write_bytes(head + b"tail-two" * 8192)
        assert content_id(a, a.stat().st_size) != content_id(b, b.stat().st_size)


class TestPairing:
    def test_raw_jpeg_sidecar_is_one_photo(self, tmp_path):
        root = tmp_path / "lib"
        make_raw(root, "a/IMG_1.CR3")
        make_raw(root, "a/IMG_1.JPG")
        make_raw(root, "a/IMG_1.xmp")
        cands = pair_files(list(discover(root)))
        assert len(cands) == 1
        c = cands[0]
        assert c.primary.ext == "cr3"
        assert c.jpeg_sibling == "a/IMG_1.JPG"
        assert c.sidecar_path == "a/IMG_1.xmp"

    def test_lone_jpeg_is_its_own_photo(self, tmp_path):
        root = tmp_path / "lib"
        make_raw(root, "IMG_9.JPG")
        cands = pair_files(list(discover(root)))
        assert len(cands) == 1 and cands[0].primary.ext == "jpg"

    def test_same_basename_different_dirs_not_merged(self, tmp_path):
        root = tmp_path / "lib"
        make_raw(root, "day1/IMG_1.CR3", b"one")
        make_raw(root, "day2/IMG_1.CR3", b"two")
        assert len(pair_files(list(discover(root)))) == 2


class TestScan:
    def test_first_scan_adds_rows(self, conn, library):
        make_raw(library, "a/IMG_1.CR3", b"one")
        make_raw(library, "a/IMG_2.CR3", b"two")
        r = scan(conn, 1, library)
        assert r.added == 2 and not r.errors
        n = conn.execute("SELECT COUNT(*) FROM photo").fetchone()[0]
        assert n == 2

    def test_rescan_unchanged_is_all_fast_path(self, conn, library):
        make_raw(library, "IMG_1.CR3", mtime=1000)
        scan(conn, 1, library)
        r = scan(conn, 1, library)
        assert r.unchanged == 1 and r.added == 0

    def test_moved_file_keeps_analysis(self, conn, library):
        """The payoff of content identity (design 02 §2 stage 3)."""
        p = make_raw(library, "old/IMG_1.CR3", mtime=1000)
        scan(conn, 1, library)
        conn.execute(
            "INSERT INTO analysis (photo_id, engine_version, decode_mode, "
            "frame, analyzed_at) VALUES (1, 'v1', 'scaled', '{}', 'now')")
        new = library / "new" / "IMG_1.CR3"
        new.parent.mkdir()
        p.rename(new)
        r = scan(conn, 1, library)
        assert r.updated_path == 1 and r.added == 0
        row = conn.execute(
            "SELECT p.rel_path, a.photo_id FROM photo p "
            "JOIN analysis a ON a.photo_id = p.id").fetchone()
        assert row["rel_path"] == "new/IMG_1.CR3"  # analysis survived

    def test_modified_file_invalidates_analysis(self, conn, library):
        p = make_raw(library, "IMG_1.CR3", b"before", mtime=1000)
        scan(conn, 1, library)
        conn.execute(
            "INSERT INTO analysis (photo_id, engine_version, decode_mode, "
            "frame, analyzed_at) VALUES (1, 'v1', 'scaled', '{}', 'now')")
        p.write_bytes(b"after" * 100)
        os.utime(p, (2000, 2000))
        r = scan(conn, 1, library)
        assert r.invalidated == 1
        n = conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
        assert n == 0

    def test_duplicate_content_not_added_twice(self, conn, library):
        make_raw(library, "a/IMG_1.CR3", b"same")
        make_raw(library, "b/copy.CR3", b"same")
        r = scan(conn, 1, library)
        assert r.added == 1 and r.duplicates == 1

    def test_missing_file_marked_never_deleted(self, conn, library):
        """Absence is never destructive (design 02 §5)."""
        p = make_raw(library, "IMG_1.CR3")
        scan(conn, 1, library)
        p.unlink()
        scan(conn, 1, library)
        row = conn.execute("SELECT missing FROM photo").fetchone()
        assert row["missing"] == 1  # row still exists, flagged

    def test_reappeared_file_unmarked(self, conn, library):
        p = make_raw(library, "IMG_1.CR3", mtime=1000)
        scan(conn, 1, library)
        p.unlink()
        scan(conn, 1, library)
        make_raw(library, "IMG_1.CR3", mtime=1000)
        scan(conn, 1, library)
        assert conn.execute("SELECT missing FROM photo").fetchone()["missing"] == 0

    def test_probe_failure_does_not_abort_scan(self, conn, library):
        make_raw(library, "IMG_1.CR3", b"ok")
        make_raw(library, "IMG_2.CR3", b"bad")

        def flaky(path):
            if "IMG_2" in str(path):
                raise RuntimeError("corrupt")
            return {"iso": 800}

        r = scan(conn, 1, library, prober=flaky)
        assert r.added == 2  # both rows created
        assert len(r.errors) == 1 and "IMG_2" in r.errors[0][0]
        isos = {row["iso"] for row in conn.execute("SELECT iso FROM photo")}
        assert isos == {800, None}  # bad file has NULL metadata, flagged row

    def test_probe_metadata_lands_in_columns(self, conn, library):
        make_raw(library, "IMG_1.CR3")
        meta = {"captured_at": "2026-06-14T15:22:08", "subsec": 340,
                "iso": 800, "aperture": 1.8, "exposure_bias": 0.0,
                "camera_model": "Canon EOS R5"}
        scan(conn, 1, library, prober=lambda p: meta)
        row = conn.execute("SELECT * FROM photo").fetchone()
        assert row["camera_model"] == "Canon EOS R5"
        assert row["subsec"] == 340


class TestShootProposals:
    """The folder IS the shoot — one proposal per top-level folder; a root
    with loose photos is a single shoot folder."""

    def _add(self, conn, pid, captured_at, rel="a"):
        conn.execute(
            "INSERT INTO photo (id, library_id, content_id, rel_path, filename,"
            " file_size, mtime, captured_at) VALUES (?, 1, ?, ?, ?, 1, 0, ?)",
            (pid, f"c{pid}", f"{rel}/IMG_{pid}.CR3" if rel != "." else
             f"IMG_{pid}.CR3", f"IMG_{pid}.CR3", captured_at),
        )

    def test_one_proposal_per_top_level_folder(self, conn, library):
        self._add(conn, 1, "2026-06-14T10:00:00", rel="wedding-nguyen")
        self._add(conn, 2, "2026-06-14T10:30:00", rel="wedding-nguyen")
        self._add(conn, 3, "2026-07-01T09:00:00", rel="street-tokyo")
        props = propose_shoots(conn, 1)
        assert len(props) == 2
        by_dir = {p.directories[0]: p.photo_ids for p in props}
        assert by_dir["wedding-nguyen"] == (1, 2)
        assert by_dir["street-tokyo"] == (3,)

    def test_multi_day_folder_stays_one_shoot(self, conn, library):
        """The wedding case: a long gap inside one folder must NOT split —
        the user's folder is the statement of intent."""
        self._add(conn, 1, "2026-06-14T10:00:00", rel="wedding")
        self._add(conn, 2, "2026-06-14T22:00:00", rel="wedding")  # 12 h later
        self._add(conn, 3, "2026-06-15T11:00:00", rel="wedding")  # next day
        props = propose_shoots(conn, 1)
        assert len(props) == 1
        assert props[0].photo_ids == (1, 2, 3)

    def test_root_with_loose_photos_is_one_shoot(self, conn, library):
        """User pointed at a single shoot folder (photos at top level, maybe
        subfolders too) → everything is one proposal."""
        self._add(conn, 1, "2026-06-14T10:00:00", rel=".")
        self._add(conn, 2, "2026-06-25T10:00:00", rel=".")  # 11 days later
        self._add(conn, 3, "2026-06-14T11:00:00", rel="selects")
        props = propose_shoots(conn, 1)
        assert len(props) == 1
        assert set(props[0].photo_ids) == {1, 2, 3}

    def test_nested_subfolders_grouped_by_top_level(self, conn, library):
        self._add(conn, 1, "2026-06-14T10:00:00", rel="wedding/ceremony")
        self._add(conn, 2, "2026-06-14T16:00:00", rel="wedding/reception")
        self._add(conn, 3, "2026-07-01T09:00:00", rel="travel/day1")
        props = propose_shoots(conn, 1)
        assert len(props) == 2

    def test_undated_photos_included(self, conn, library):
        """Folder membership needs no timestamp — a photo with missing EXIF
        must not vanish from proposals."""
        self._add(conn, 1, "2026-06-14T10:00:00", rel="wedding")
        self._add(conn, 2, None, rel="wedding")
        props = propose_shoots(conn, 1)
        assert len(props) == 1
        assert set(props[0].photo_ids) == {1, 2}
        assert props[0].start == "2026-06-14T10:00:00"

    def test_proposals_never_write_shoots(self, conn, library):
        self._add(conn, 1, "2026-06-14T10:00:00")
        propose_shoots(conn, 1)
        n = conn.execute("SELECT COUNT(*) FROM shoot").fetchone()[0]
        assert n == 0  # user confirms; ingest never finalizes (design 02 §4)
