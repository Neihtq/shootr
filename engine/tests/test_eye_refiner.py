"""Eye-refiner tests: bbox matching, provenance-honest updates, idempotency,
and per-photo failure tolerance (design 03 §5 swappable blink component;
09 §4 per-file error tolerance).

A fake analyzer stands in for SCRFD+MediaPipe so tests need neither models
nor photos.
"""

import json

import pytest

from shootr.db import connect
from shootr.eye_refiner import RefineStats, iou, match_faces, refine_shoot


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/lib', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    for i in (1, 2):
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
            (i, f"c{i}", f"IMG_{i}.CR3", f"IMG_{i}.CR3"))
    # Photo 1: two EAR faces. Photo 2: one already-blendshapes face.
    c.execute("INSERT INTO face (photo_id, idx, bbox, eye_open_l, "
              "eye_open_r, eye_source) VALUES "
              "(1, 0, ?, 0.1, 0.1, 'ear_landmarks'),"
              "(1, 1, ?, 0.2, 0.2, 'ear_landmarks'),"
              "(2, 0, ?, 0.9, 0.9, 'mediapipe_blendshapes')",
              (json.dumps([0.1, 0.1, 0.2, 0.2]),
               json.dumps([0.6, 0.6, 0.2, 0.2]),
               json.dumps([0.4, 0.4, 0.2, 0.2])))
    yield c
    c.close()


def mp_face(bbox, open_l=0.8, open_r=0.9, yaw=0.1):
    return {"bbox": bbox, "roll": 0.0, "yaw": yaw, "pitch": 0.05,
            "eyes": {"l": {"open": open_l}, "r": {"open": open_r}},
            "eye_source": "mediapipe_blendshapes"}


def test_iou_and_greedy_matching():
    a = {"bbox": [0.1, 0.1, 0.2, 0.2]}
    b = {"bbox": [0.6, 0.6, 0.2, 0.2]}
    near_a = {"bbox": [0.12, 0.11, 0.2, 0.2]}
    far = {"bbox": [0.0, 0.8, 0.05, 0.05]}
    assert iou(a["bbox"], a["bbox"]) == pytest.approx(1.0)
    assert iou(a["bbox"], b["bbox"]) == 0.0
    pairs = match_faces([a, b], [near_a, far])
    # near_a pairs with a; far clears no IoU bar with b.
    assert pairs == [(a, near_a)]


def test_refine_updates_matched_faces_only(conn):
    def analyzer(path):
        if "IMG_1" in str(path):
            # Matches face idx 0; nothing near idx 1.
            return [mp_face([0.11, 0.1, 0.2, 0.2])]
        return []

    stats = refine_shoot(conn, 1, __import__("pathlib").Path("/lib"),
                         analyzer=analyzer)
    assert stats.faces_updated == 1 and stats.failed == 0
    f0, f1 = conn.execute(
        "SELECT * FROM face WHERE photo_id = 1 ORDER BY idx").fetchall()
    assert f0["eye_source"] == "mediapipe_blendshapes"
    assert f0["eye_open_l"] == 0.8 and f0["yaw"] == 0.1
    # Unmatched face keeps EAR provenance — scoring abstains, never guesses.
    assert f1["eye_source"] == "ear_landmarks"
    assert f1["eye_open_l"] == 0.2


def test_refine_is_idempotent_and_skips_done_photos(conn):
    calls = []

    def analyzer(path):
        calls.append(str(path))
        return [mp_face([0.1, 0.1, 0.2, 0.2]),
                mp_face([0.6, 0.6, 0.2, 0.2])]

    refine_shoot(conn, 1, __import__("pathlib").Path("/lib"),
                 analyzer=analyzer)
    # Photo 2 is already fully blendshapes: never decoded.
    assert calls == ["/lib/IMG_1.CR3"]
    calls.clear()
    stats = refine_shoot(conn, 1, __import__("pathlib").Path("/lib"),
                         analyzer=analyzer)
    # Second run: photo 1 fully refined now, nothing to do.
    assert calls == [] and stats.photos == 0


def test_analyzer_failure_skips_photo_not_run(conn):
    def broken(path):
        raise RuntimeError("decode exploded")

    stats = refine_shoot(conn, 1, __import__("pathlib").Path("/lib"),
                         analyzer=broken)
    assert stats.failed == 1 and stats.faces_updated == 0
    # Faces untouched: EAR provenance survives a refiner crash.
    assert conn.execute(
        "SELECT COUNT(*) FROM face WHERE eye_source='ear_landmarks'"
    ).fetchone()[0] == 2


def test_unavailable_stack_degrades_honestly(conn, monkeypatch):
    monkeypatch.setattr("shootr.eye_refiner.available", lambda: False)
    stats = refine_shoot(conn, 1, __import__("pathlib").Path("/lib"))
    assert stats == RefineStats(skipped_unavailable=True)
