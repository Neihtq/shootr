"""Static web UI serving (bundled-app mode)."""

import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html><body>shootr ui</body></html>")
    (d / "assets" / "app.js").write_text("console.log('ui')")
    return d


def make_client(tmp_path, dist=None):
    (tmp_path / "backups").mkdir(exist_ok=True)
    app = create_app(tmp_path / "db.sqlite", tmp_path / "backups",
                     web_dist=dist)
    return TestClient(app)


def test_ui_served_when_dist_present(tmp_path, dist):
    client = make_client(tmp_path, dist)
    r = client.get("/ui/")
    assert r.status_code == 200 and "shootr ui" in r.text
    assert client.get("/ui/assets/app.js").status_code == 200


def test_root_redirects_to_ui(tmp_path, dist):
    client = make_client(tmp_path, dist)
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/ui/"


def test_api_keeps_priority_over_mount(tmp_path, dist):
    client = make_client(tmp_path, dist)
    r = client.get("/api/health")
    assert r.status_code == 200 and "engine_version" in r.json()


def test_no_dist_no_ui_routes(tmp_path):
    client = make_client(tmp_path, dist=None)
    assert client.get("/ui/").status_code == 404
    assert client.get("/api/health").status_code == 200
