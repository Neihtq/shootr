"""Library removal: cascades app data, never touches disk."""

import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app
from shootr.db import connect


@pytest.fixture
def env(tmp_path):
    (tmp_path / "backups").mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "IMG_1.CR3").write_bytes(b"raw" * 100)
    app = create_app(tmp_path / "db.sqlite", tmp_path / "backups")
    client = TestClient(app)
    c = connect(tmp_path / "db.sqlite")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, ?, 'now')", (str(lib),))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    c.execute("INSERT INTO photo (id, library_id, shoot_id, content_id, "
              "rel_path, filename, file_size, mtime) "
              "VALUES (1, 1, 1, 'c1', 'IMG_1.CR3', 'IMG_1.CR3', 1, 0)")
    c.execute("INSERT INTO analysis (photo_id, engine_version, decode_mode, "
              "frame, analyzed_at) VALUES (1, 'v1', 'scaled', '{}', 'now')")
    c.commit()
    c.close()
    return client, tmp_path / "db.sqlite", lib


def test_delete_cascades_app_rows(env):
    client, db_path, _ = env
    assert client.delete("/api/libraries/1").status_code == 200
    c = connect(db_path)
    for table in ("library", "shoot", "photo", "analysis"):
        n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 0, table
    c.close()


def test_delete_never_touches_files(env):
    """The invariant that matters: user files survive library removal."""
    client, _, lib = env
    client.delete("/api/libraries/1")
    assert (lib / "IMG_1.CR3").exists()


def test_delete_unknown_library_404(env):
    client, _, _ = env
    assert client.delete("/api/libraries/99").status_code == 404


def test_readd_after_delete_rescans_cleanly(env):
    client, db_path, lib = env
    client.delete("/api/libraries/1")
    r = client.post("/api/libraries", json={"root_path": str(lib)})
    assert r.status_code == 200
    assert r.json()["scan"]["added"] == 1


def test_duplicate_add_reuses_library(env):
    """The 3-clicks bug: re-adding the same path must not duplicate."""
    client, db_path, lib = env
    first = client.post("/api/libraries", json={"root_path": str(lib)})
    second = client.post("/api/libraries", json={"root_path": str(lib)})
    assert first.json()["id"] == second.json()["id"]
    c = connect(db_path)
    n = c.execute("SELECT COUNT(*) FROM library").fetchone()[0]
    p = c.execute("SELECT COUNT(*) FROM photo").fetchone()[0]
    c.close()
    assert n == 1 and p == 1