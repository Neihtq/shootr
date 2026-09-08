"""Style-model tests (design 08 §7b).

The user's requirement drives these: learning is explicit, scope is theirs to
choose across catalogs, method is theirs to choose, and comparison is decided
by measurement on their own edits. What must NOT vary with method choice:
§6's clamping and the §7a rule that a prediction says where it came from.
"""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from shootr import style_models
from shootr.api import create_app
from shootr.db import connect

DIM = 12


def vec(axis, seed, jitter=0.05):
    rng = np.random.default_rng(seed)
    v = np.zeros(DIM)
    v[axis] = 1.0
    v += rng.standard_normal(DIM) * jitter
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def env(tmp_path):
    """Two libraries with deliberately DIFFERENT looks, so a scope choice is
    observable: library 1 warms and lifts, library 2 does the opposite."""
    db_path = tmp_path / "shootr.db"
    (tmp_path / "backups").mkdir()
    app = create_app(db_path, tmp_path / "backups",
                     cache_dir=tmp_path / "thumbs")
    client = TestClient(app)
    c = connect(db_path)
    for lib in (1, 2):
        root = tmp_path / f"lib{lib}"
        root.mkdir()
        c.execute("INSERT INTO library (id, root_path, created_at) "
                  "VALUES (?, ?, 'now')", (lib, str(root)))
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's1', 'event', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (2, 2, 's2', 'event', 'now')")
    pid = 1
    for lib, shoot, expo, contrast in ((1, 1, 0.6, 20.0), (2, 2, -0.6, -20.0)):
        for i in range(16):
            (tmp_path / f"lib{lib}" / f"IMG_{pid}.CR3").write_bytes(b"x")
            c.execute(
                "INSERT INTO photo (id, library_id, shoot_id, content_id, "
                "rel_path, filename, file_size, mtime) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0)",
                (pid, lib, shoot, f"c{pid}", f"IMG_{pid}.CR3",
                 f"IMG_{pid}.CR3"))
            c.execute("INSERT INTO embedding (photo_id, kind, vec, dim) "
                      "VALUES (?, 'scene', ?, ?)",
                      (pid, vec(lib - 1, pid).tobytes(), DIM))
            c.execute("INSERT INTO analysis (photo_id, engine_version, "
                      "decode_mode, frame, analyzed_at) VALUES "
                      "(?, 'v', 'scaled', '{\"clipped_hi\": 0.001}', 'now')",
                      (pid,))
            if i < 14:   # last two of each stay unedited → prediction targets
                c.execute(
                    "INSERT INTO lr_history (photo_id, develop) VALUES (?, ?)",
                    (pid, json.dumps({"Exposure2012": expo,
                                      "Contrast2012": contrast,
                                      "ProcessVersion": "15.4"})))
            pid += 1
    c.commit()
    c.close()
    return client, db_path


def test_methods_are_peers_none_privileged(env):
    client, _ = env
    methods = {m["method"]: m for m in client.get("/api/style/methods").json()}
    assert set(methods) == {"knn", "ridge"}
    assert methods["knn"]["fits"] is False
    assert methods["ridge"]["fits"] is True
    # The client must be able to say a fitted model cannot name neighbours.
    assert methods["knn"]["explains_by_neighbours"] is True
    assert methods["ridge"]["explains_by_neighbours"] is False


def test_learning_is_explicit_and_scoped_to_chosen_libraries(env):
    client, _ = env
    # Nothing exists until the user asks for it.
    assert client.get("/api/style/models").json() == []

    warm = client.post("/api/style/models", json={
        "name": "Warm weddings", "method": "knn", "library_ids": [1]}).json()
    assert warm["trained"] and warm["history_n"] == 14
    assert warm["is_active"] is True          # first model becomes active
    assert warm["metrics"]["families"] >= 1

    cool = client.post("/api/style/models", json={
        "name": "Cool travel", "method": "knn", "library_ids": [2]}).json()
    assert cool["history_n"] == 14 and cool["is_active"] is False

    both = client.post("/api/style/models", json={
        "name": "Everything", "method": "knn", "library_ids": []}).json()
    assert both["history_n"] == 28, "empty scope means every library"

    # Scope is observable in the output. A library-1 photo predicts positive
    # exposure under the library-1 model...
    warm_pred = client.post("/api/shoots/1/style/predict",
                            json={"photo_ids": [15],
                                  "model_id": warm["id"]}).json()
    assert warm_pred["predictions"][0]["params"]["Exposure2012"] > 0
    assert warm_pred["model"]["name"] == "Warm weddings"

    # ...and a library-2 photo predicts negative under the library-2 model.
    cool_pred = client.post("/api/shoots/2/style/predict",
                            json={"photo_ids": [31],
                                  "model_id": cool["id"]}).json()
    assert cool_pred["predictions"][0]["params"]["Exposure2012"] < 0

    # Cross-scope, the honest answer is abstention, not a guess: the cool
    # model has never seen a photo that looks like this one (§6).
    crossed = client.post("/api/shoots/1/style/predict",
                          json={"photo_ids": [15],
                                "model_id": cool["id"]}).json()
    entry = crossed["predictions"][0]
    assert entry["abstained"] and entry["reason"] == "no_similar_history"
    assert entry["params"] == {}


def test_relearn_picks_up_newly_imported_history(env):
    client, db_path = env
    m = client.post("/api/style/models", json={
        "name": "M", "method": "knn", "library_ids": [1]}).json()
    assert m["history_n"] == 14

    c = connect(db_path)
    with c:   # the two unedited lib-1 photos now have edits
        for pid in (15, 16):
            c.execute("INSERT INTO lr_history (photo_id, develop) VALUES (?, ?)",
                      (pid, json.dumps({"Exposure2012": 0.6,
                                        "ProcessVersion": "15.4"})))
    c.close()

    # Not until asked: predictions still run, but history_n is the old one.
    assert client.get("/api/style/models").json()[0]["history_n"] == 14
    again = client.post(f"/api/style/models/{m['id']}/train").json()
    assert again["history_n"] == 16
    assert again["trained_at"] >= m["trained_at"]


def test_ridge_model_fits_clamps_and_says_it_was_fitted(env):
    client, _ = env
    r = client.post("/api/style/models", json={
        "name": "Ridge all", "method": "ridge", "library_ids": [1]}).json()
    assert r["trained"] and r["explains_by_neighbours"] is False
    assert r["metrics"]["held_out"] is True, \
        "fitted methods must be scored held-out, not in-sample"

    p = client.post("/api/shoots/1/style/predict",
                    json={"photo_ids": [15], "model_id": r["id"]}).json()
    pred = p["predictions"][0]
    # §7a: no neighbours to name, so it must state its provenance instead.
    assert pred["neighbor_photo_ids"] == []
    assert pred["fitted_from_history_n"] == 14
    # §6 clamp survives the method change: history only ever used +0.6.
    assert pred["params"]["Exposure2012"] == pytest.approx(0.6, abs=0.05)


def test_ridge_still_withholds_exposure_on_clipping_frames(env):
    """§6's guardrails apply to EVERY method, not just retrieval."""
    client, db_path = env
    c = connect(db_path)
    with c:
        c.execute("UPDATE analysis SET frame = '{\"clipped_hi\": 0.3}' "
                  "WHERE photo_id = 15")
    c.close()
    r = client.post("/api/style/models", json={
        "name": "R", "method": "ridge", "library_ids": [1]}).json()
    p = client.post("/api/shoots/1/style/predict",
                    json={"photo_ids": [15], "model_id": r["id"]}).json()
    assert p["predictions"][0]["params"]["Exposure2012"] == 0.0


def test_models_are_comparable_on_the_same_metric(env):
    client, _ = env
    knn = client.post("/api/style/models", json={
        "name": "knn", "method": "knn", "library_ids": []}).json()
    ridge = client.post("/api/style/models", json={
        "name": "ridge", "method": "ridge", "library_ids": []}).json()
    for m in (knn, ridge):
        per = m["metrics"]["per_param"]
        assert "Exposure2012" in per
        assert per["Exposure2012"]["baseline_mae"] is not None, \
            "every model reports the same median baseline to be judged against"


def test_choosing_and_deleting_models(env):
    client, _ = env
    a = client.post("/api/style/models", json={
        "name": "A", "method": "knn", "library_ids": [1]}).json()
    b = client.post("/api/style/models", json={
        "name": "B", "method": "knn", "library_ids": [2]}).json()
    assert client.post(f"/api/style/models/{b['id']}/activate"
                       ).json()["is_active"] is True
    names = {m["name"]: m["is_active"] for m in
             client.get("/api/style/models").json()}
    assert names == {"A": False, "B": True}
    client.delete(f"/api/style/models/{a['id']}")
    assert [m["name"] for m in client.get("/api/style/models").json()] == ["B"]


def test_unknown_method_and_missing_model_are_errors(env):
    client, _ = env
    r = client.post("/api/style/models", json={
        "name": "X", "method": "neural_net", "library_ids": []})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unknown_method"
    assert client.post("/api/shoots/1/style/predict",
                       json={"model_id": 999}).status_code == 404


def test_untrained_model_refuses_to_predict(env):
    client, db_path = env
    c = connect(db_path)
    mid = style_models.create(c, "empty", "knn", [1])
    c.close()
    r = client.post("/api/shoots/1/style/predict",
                    json={"photo_ids": [15], "model_id": mid})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "model_not_trained"


def test_untrained_model_cannot_be_made_active(env):
    """The engine must not offer a state where the active model cannot
    predict — refusing here is cheaper than every client guarding against it
    (design 10 §1: the engine owns the rules)."""
    client, db_path = env
    good = client.post("/api/style/models", json={
        "name": "good", "method": "knn", "library_ids": [1]}).json()
    c = connect(db_path)
    empty = style_models.create(c, "never learned", "knn", [1])
    c.close()

    r = client.post(f"/api/style/models/{empty}/activate")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "model_not_trained"
    # The previously active model is still active — a refused call changes
    # nothing.
    active = [m for m in client.get("/api/style/models").json()
              if m["is_active"]]
    assert [m["id"] for m in active] == [good["id"]]
