"""Style API tests (design 08 over doc 10 conventions): families with
evidence, read-only prediction preview, and gated develop export that never
touches a user-edited sidecar.
"""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from shootr.api import create_app
from shootr.db import connect

DIM = 16


def vec(axis, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(DIM)
    v[axis] = 1.0
    v += rng.standard_normal(DIM) * 0.05
    v /= np.linalg.norm(v)
    return v.astype(np.float32).tobytes()


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "shootr.db"
    (tmp_path / "backups").mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()
    app = create_app(db_path, tmp_path / "backups",
                     cache_dir=tmp_path / "thumbs")
    client = TestClient(app)

    c = connect(db_path)
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, ?, 'now')", (str(lib),))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    # 12 edited history photos (axis 0 look) + 2 new unedited ones.
    for i in range(1, 15):
        (lib / f"IMG_{i}.CR3").write_bytes(b"raw" * 10)
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3"))
        c.execute("INSERT INTO embedding (photo_id, kind, vec, dim) "
                  "VALUES (?, 'scene', ?, ?)", (i, vec(0, i), DIM))
    for i in range(1, 13):
        dev = {"Exposure2012": 0.5, "Contrast2012": 10 + (i % 3),
               "ProcessVersion": "15.4"}
        c.execute("INSERT INTO lr_history (photo_id, develop) VALUES (?, ?)",
                  (i, json.dumps(dev)))
    c.commit()
    c.close()
    return client, db_path, lib


def test_families_carry_evidence(env):
    client, _, _ = env
    fams = client.get("/api/style/families").json()
    assert len(fams) >= 1
    f = fams[0]
    assert f["size"] == 12 and len(f["sample_photo_ids"]) == 4
    assert "Exposure2012" in f["median"]
    assert isinstance(f["traits"], str)


def test_predict_is_readonly_and_inspectable(env):
    client, _, lib = env
    r = client.post("/api/shoots/1/style/predict",
                    json={"photo_ids": [13, 14]})
    assert r.status_code == 200
    body = r.json()
    assert body["process_version"] == "15.4"
    p = body["predictions"][0]
    assert not p["abstained"]
    assert p["params"]["Exposure2012"] == pytest.approx(0.5, abs=0.01)
    assert 10 <= p["params"]["Contrast2012"] <= 12  # clamped to history
    assert p["neighbor_photo_ids"], "blend must name its neighbors"
    assert not list(lib.glob("*.xmp")), "predict must write nothing"


def test_export_writes_gated_sidecars(env):
    client, _, lib = env
    # Photo 14 already has USER develop settings in its sidecar.
    (lib / "IMG_14.xmp").write_text(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="" crs:Exposure2012="+1.00">\n'
        '  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n')
    r = client.post("/api/shoots/1/style/export-develop",
                    json={"family": 0, "photo_ids": [13, 14]})
    body = r.json()
    assert body["written"] == [13]
    assert body["conflicts"][0]["photo_id"] == 14
    text = (lib / "IMG_13.xmp").read_text()
    assert 'crs:Exposure2012=' in text and 'crs:ProcessVersion="15.4"' in text
    # The user's sidecar is untouched.
    assert 'crs:Exposure2012="+1.00"' in (lib / "IMG_14.xmp").read_text()


def test_insufficient_history_is_a_409_not_a_guess(env):
    client, db_path, _ = env
    c = connect(db_path)
    with c:
        c.execute("DELETE FROM lr_history")
    c.close()
    r = client.post("/api/shoots/1/style/predict", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "insufficient_history"


def test_per_parameter_optout_is_honoured_on_write(env):
    """08 §6's opt-out, server-side: an excluded parameter is reported with
    its predicted value but never written. Server-side on purpose — the
    opt-out changes the user's files, so a client-local toggle would let the
    two clients write different edits from the same click."""
    client, _, lib = env
    prefs = client.get("/api/style/preferences").json()
    assert "Exposure2012" in prefs["modelable_params"]
    # Shipped default, from the measurement (08 §6): the family median beats
    # k-NN on this one parameter, so it starts excluded.
    assert prefs["excluded_params"] == ["ColorGradeMidtoneHue"]

    r = client.put("/api/style/preferences",
                   json={"excluded_params": ["Exposure2012"]})
    assert r.json()["excluded_params"] == ["Exposure2012"]

    pred = client.post("/api/shoots/1/style/predict",
                       json={"photo_ids": [13]}).json()
    p = pred["predictions"][0]
    assert "Exposure2012" not in p["params"]          # never written
    assert p["excluded"]["Exposure2012"] == pytest.approx(0.5, abs=0.01)
    assert pred["excluded_params"] == ["Exposure2012"]
    # Other params survive.
    assert "Contrast2012" in p["params"]

    client.post("/api/shoots/1/style/export-develop",
                json={"family": 0, "photo_ids": [13]})
    text = (lib / "IMG_13.xmp").read_text()
    assert "crs:Exposure2012" not in text
    assert "crs:Contrast2012" in text


def test_unknown_param_is_rejected_not_silently_stored(env):
    """Two distinct wrongs, and the error says which: policy never predicts
    it, or the user's history has no such parameter (usually a typo, and
    excluding it would silently do nothing)."""
    client, _, _ = env
    r = client.put("/api/style/preferences",
                   json={"excluded_params": ["NotAParam"]})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unknown_param"
    assert r.json()["error"]["detail"]["absent"] == ["NotAParam"]

    # Policy-forbidden names are refused with the other reason.
    r2 = client.put("/api/style/preferences",
                    json={"excluded_params": ["CropTop"]})
    assert r2.status_code == 400
    assert r2.json()["error"]["detail"]["forbidden"] == ["CropTop"]
    # Rejected wholesale — the prior value stands, nothing partially applied.
    assert client.get("/api/style/preferences").json()[
        "excluded_params"] == ["ColorGradeMidtoneHue"]
