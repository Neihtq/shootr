"""Schema and migration tests (design 01)."""

import sqlite3

import pytest

from shootr.db import connect, schema_version


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    yield c
    c.close()


def test_migrations_apply_and_are_idempotent(tmp_path):
    db = tmp_path / "shootr.db"
    c1 = connect(db)
    assert schema_version(c1) == 1
    c1.close()
    c2 = connect(db)  # reopening must not re-apply
    assert schema_version(c2) == 1
    c2.close()


def test_wal_mode_enabled(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_profile_check_constraint(conn):
    conn.execute("INSERT INTO library (root_path, created_at) VALUES ('/x', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO shoot (library_id, name, profile, created_at) "
            "VALUES (1, 'bad', 'wedding', 'now')"
        )


def test_selection_entry_state_constraint(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO selection_entry (selection_id, photo_id, state) "
            "VALUES (1, 1, 'delete')"  # 'delete' must never be a state
        )


def test_content_id_unique_per_library(conn):
    conn.execute("INSERT INTO library (root_path, created_at) VALUES ('/x', 'now')")
    ins = ("INSERT INTO photo (library_id, content_id, rel_path, filename, "
           "file_size, mtime) VALUES (1, 'abc', ?, 'a.cr3', 1, 0)")
    conn.execute(ins, ("a/a.cr3",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("b/a.cr3",))


def test_score_composite_key_allows_multiple_profiles(conn):
    conn.execute("INSERT INTO library (root_path, created_at) VALUES ('/x', 'now')")
    conn.execute(
        "INSERT INTO photo (library_id, content_id, rel_path, filename, "
        "file_size, mtime) VALUES (1, 'abc', 'a.cr3', 'a.cr3', 1, 0)"
    )
    for profile in ("event", "portrait"):
        conn.execute(
            "INSERT INTO score (photo_id, profile, total, components, flags, "
            "weights_hash) VALUES (1, ?, 0.5, '{}', '[]', 'h')", (profile,)
        )
    n = conn.execute("SELECT COUNT(*) FROM score").fetchone()[0]
    assert n == 2
