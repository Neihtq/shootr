"""Catalog reader tests (design 07 §2): schema validation before querying,
degrade-don't-guess, filename+time matching with reported ambiguity, and
the copy protocol. A synthetic mini-catalog stands in for the real thing;
the real-catalog run is a benchmark, not a unit test.
"""

import sqlite3
import zlib
from pathlib import Path

import pytest

from shootr.db import connect
from shootr.lr_catalog import (CatalogBusy, CatalogInvalid, copy_catalog,
                               extract, import_history, open_copy, probe)


def make_catalog(path: Path, *, drop_table: str | None = None,
                 drop_column: str | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE Adobe_variablesTable (name TEXT, value TEXT);
        INSERT INTO Adobe_variablesTable VALUES ('Adobe_DBVersion','1504001');
        CREATE TABLE AgLibraryRootFolder (id_local INTEGER, absolutePath TEXT);
        CREATE TABLE AgLibraryFolder
            (id_local INTEGER, rootFolder INTEGER, pathFromRoot TEXT);
        CREATE TABLE AgLibraryFile (id_local INTEGER, folder INTEGER,
            idx_filename TEXT, extension TEXT);
        CREATE TABLE Adobe_images (id_local INTEGER, rootFile INTEGER,
            pick REAL, rating REAL, colorLabels TEXT, captureTime TEXT);
        CREATE TABLE Adobe_AdditionalMetadata (image INTEGER, xmp BLOB);
        INSERT INTO AgLibraryRootFolder VALUES (1, '/Volumes/shoot/');
        INSERT INTO AgLibraryFolder VALUES (10, 1, '');
        INSERT INTO AgLibraryFile VALUES
            (100, 10, 'A.CR3', 'CR3'),
            (101, 10, 'B.CR3', 'CR3'),
            (102, 10, 'GHOST.CR3', 'CR3'),
            (103, 10, 'DUP.CR3', 'CR3');
        INSERT INTO Adobe_images VALUES
            (200, 100, 1.0, 5.0, '',     '2026-08-22T10:00:00.123'),
            (201, 101, 0.0, NULL, 'Red', '2026-08-22T11:00:00'),
            (202, 102, 1.0, 5.0, '',     '2026-08-22T12:00:00'),
            (203, 103, 1.0, 4.0, '',     '2026-08-22T13:00:00');
    """)
    xmp = b"<x:xmpmeta crs:Exposure2012=\"+0.30\"/>"
    blob = len(xmp).to_bytes(4, "big") + zlib.compress(xmp)
    c.execute("INSERT INTO Adobe_AdditionalMetadata VALUES (200, ?)", (blob,))
    # B has the Lua-text source (the common case on a real LrC 15 catalog);
    # A only has the crs XMP fallback.
    c.execute("CREATE TABLE Adobe_imageDevelopSettings "
              "(image INTEGER, text TEXT)")
    lua = ('s = { AILook = {  },\n'
           'Blacks2012 = -5,\n'
           'CameraProfile = "Adobe Standard",\n'
           'ToneCurvePV2012 = { 0, 0, 255, 255 },\n'
           'MaskGroupBasedCorrections = {\n'
           'CorrectionAmount = 1,\n'
           '},\n'
           'Exposure2012 = 0.5,\n'
           'ConvertToGrayscale = false,\n'
           '}')
    c.execute("INSERT INTO Adobe_imageDevelopSettings VALUES (201, ?)",
              (lua,))
    if drop_column:
        table, col = drop_column.split(".")
        c.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    if drop_table:
        c.execute(f"DROP TABLE {drop_table}")
    c.commit()
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture
def app_conn(tmp_path):
    c = connect(tmp_path / "app.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/lib', 'now')")
    photos = [
        (1, "A.CR3", "2026-08-22T10:00:00", 111),
        (2, "B.CR3", "2026-08-22T11:00:00", 222),
        # DUP.CR3 exists twice with different capture times: only the
        # 13:00 one is the catalog's row.
        (3, "DUP.CR3", "2026-08-22T13:00:00", 333),
        (4, "DUP.CR3", "2026-08-22T14:00:00", 444),
    ]
    for pid, name, ts, size in photos:
        c.execute(
            "INSERT INTO photo (id, library_id, content_id, rel_path, "
            "filename, file_size, mtime, captured_at) "
            "VALUES (?, 1, ?, ?, ?, ?, 0, ?)",
            (pid, f"c{pid}", name, name, size, ts))
    yield c
    c.close()


def test_probe_validates_and_reads_version(tmp_path):
    c = make_catalog(tmp_path / "cat.lrcat")
    info = probe(c)
    assert info.valid and info.db_version == "1504001"
    # Optional table absent → noted, still valid.
    c2 = make_catalog(tmp_path / "cat2.lrcat",
                      drop_table="Adobe_AdditionalMetadata")
    info2 = probe(c2)
    assert info2.valid
    assert "Adobe_AdditionalMetadata" in info2.optional_missing


def test_missing_required_column_degrades_not_guesses(tmp_path):
    c = make_catalog(tmp_path / "cat.lrcat", drop_column="Adobe_images.pick")
    info = probe(c)
    assert not info.valid and info.missing == {"Adobe_images": {"pick"}}
    with pytest.raises(CatalogInvalid):
        list(extract(c))


def test_extract_parses_develop_lua_with_crs_fallback(tmp_path):
    c = make_catalog(tmp_path / "cat.lrcat")
    recs = {r.filename: r for r in extract(c)}
    # B: Lua text — depth-1 scalars only; nested tables (masks, curves)
    # are local adjustments, out of style scope.
    assert recs["B.CR3"].develop == {
        "Blacks2012": -5, "CameraProfile": "Adobe Standard",
        "Exposure2012": 0.5, "ConvertToGrayscale": False}
    # A: no Lua row → crs attributes from the XMP blob.
    assert recs["A.CR3"].develop == {"Exposure2012": 0.3}
    assert recs["GHOST.CR3"].develop is None
    assert recs["B.CR3"].color_label == "Red"
    assert recs["A.CR3"].pick == 1.0 and recs["A.CR3"].rating == 5.0


def test_import_matches_and_reports_honestly(tmp_path, app_conn):
    c = make_catalog(tmp_path / "cat.lrcat")
    report = import_history(app_conn, extract(c), library_id=1)
    # A, B match by filename; DUP disambiguates by capture time;
    # GHOST has no photo row.
    assert report.catalog_rows == 4
    assert report.matched == 3
    assert report.unmatched == 1 and report.unmatched_samples == ["GHOST.CR3"]
    assert report.ambiguous == 0
    assert report.with_develop == 2
    assert report.coverage == pytest.approx(0.75)
    row = app_conn.execute(
        "SELECT * FROM lr_history WHERE photo_id = 3").fetchone()
    assert row["rating"] == 4.0
    # The 14:00 duplicate was NOT matched.
    assert app_conn.execute(
        "SELECT COUNT(*) FROM lr_history WHERE photo_id = 4"
    ).fetchone()[0] == 0


def test_ambiguity_is_counted_never_guessed(tmp_path, app_conn):
    # Second DUP.CR3 at the SAME capture time and no size in the catalog:
    # cannot be told apart — skip and count.
    app_conn.execute("UPDATE photo SET captured_at = '2026-08-22T13:00:00' "
                     "WHERE id = 4")
    c = make_catalog(tmp_path / "cat.lrcat")
    report = import_history(app_conn, extract(c), library_id=1)
    assert report.ambiguous == 1 and report.matched == 2


def test_copy_refuses_while_lrc_runs(tmp_path, monkeypatch):
    src = tmp_path / "Lightroom Catalog.lrcat"
    src.write_bytes(b"db")
    monkeypatch.setattr("shootr.lr_catalog.lrc_running", lambda: True)
    with pytest.raises(CatalogBusy):
        copy_catalog(src, tmp_path / "out")
    # force overrides; -wal/-shm siblings come along.
    src.with_name(src.name + "-wal").write_bytes(b"wal")
    dest = copy_catalog(src, tmp_path / "out", force=True)
    assert dest.read_bytes() == b"db"
    assert dest.with_name(dest.name + "-wal").exists()


def test_open_copy_immutable_when_quiesced(tmp_path):
    path = tmp_path / "cat.lrcat"
    make_catalog(path).close()
    conn = open_copy(path)
    assert probe(conn).valid
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO Adobe_variablesTable VALUES ('x','y')")


def test_open_copy_recovers_wal_then_locks(tmp_path):
    path = tmp_path / "cat.lrcat"
    c = make_catalog(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("INSERT INTO Adobe_variablesTable VALUES ('walrow','1')")
    c.commit()
    # Leave the -wal behind (no clean close checkpoint).
    assert path.with_name(path.name + "-wal").exists()
    conn = open_copy(path)
    assert conn.execute("SELECT value FROM Adobe_variablesTable "
                        "WHERE name='walrow'").fetchone()["value"] == "1"
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO Adobe_variablesTable VALUES ('x','y')")
