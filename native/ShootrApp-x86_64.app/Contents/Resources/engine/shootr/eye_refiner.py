"""Blendshape eye refinement — design 03 §5's swappable blink component.

The Swift analyze path emits EAR eye values, which the merged labelled set
showed have no usable open/closed separation (scoring abstains on them —
`ABSTAIN_EYE_SOURCES`). This module re-runs the canonical face stack
(SCRFD + MediaPipe blendshapes) over a shoot's face-bearing photos and
updates matched faces in place, so `eyes_open` scores from the calibrated
blendshapes curve instead of abstaining.

Runs inside the analyze job's finalize (before grouping/scoring) and is
idempotent: only faces not already on blendshapes are revisited, per-photo
commits, safe to re-run after a crash — the same checkpoint contract as
the rest of the pipeline (design 09).

Degrades honestly: if the canonical analyzer stack isn't importable
(mediapipe/onnxruntime not installed), refinement is skipped and EAR faces
simply keep abstaining — eyes_open goes null, never wrong.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MATCH_IOU = 0.3  # same bar the blink-label tool uses to pair the analyzers
DECODE_SCALE = 0.5

# (path) -> list of contract face dicts with normalized bbox + eyes l/r.
Analyzer = Callable[[Path], list[dict]]


def available() -> bool:
    try:
        import mediapipe  # noqa: F401
        import shootr_analyzer  # noqa: F401
    except ImportError:
        return False
    return True


def _default_analyzer(path: Path) -> list[dict]:
    from shootr_analyzer.decode import decode_measurement
    from shootr_analyzer.faces import detect_faces

    decoded = decode_measurement(path, DECODE_SCALE)
    # frame_max=0 skips the full-res eye-sharpness re-decode: the stored
    # eye_sharp values stay authoritative, only eye-openness is refined.
    faces = detect_faces(path, decoded, frame_max=0.0)
    return [f for f in faces if f["eye_source"] == "mediapipe_blendshapes"]


def iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    x0, y0 = max(ax0, bx0), max(ay0, by0)
    x1, y1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    return inter / (aw * ah + bw * bh - inter)


def match_faces(db_faces: list[dict], mp_faces: list[dict]
                ) -> list[tuple[dict, dict]]:
    """Greedy best-IoU pairing; each side used at most once."""
    pairs = sorted(
        ((iou(d["bbox"], m["bbox"]), i, j)
         for i, d in enumerate(db_faces) for j, m in enumerate(mp_faces)),
        reverse=True)
    used_d: set[int] = set()
    used_m: set[int] = set()
    out = []
    for score, i, j in pairs:
        if score < MATCH_IOU or i in used_d or j in used_m:
            continue
        used_d.add(i)
        used_m.add(j)
        out.append((db_faces[i], mp_faces[j]))
    return out


@dataclass
class RefineStats:
    photos: int = 0
    faces_updated: int = 0
    failed: int = 0
    skipped_unavailable: bool = False


def refine_photo(conn, photo_id: int, path: Path,
                 analyzer: Analyzer) -> int:
    db_faces = [dict(r) for r in conn.execute(
        "SELECT id, bbox FROM face WHERE photo_id = ?", (photo_id,))]
    for f in db_faces:
        f["bbox"] = json.loads(f["bbox"])
    mp_faces = analyzer(path)
    updates = []
    for dbf, mpf in match_faces(db_faces, mp_faces):
        eyes = mpf["eyes"]
        updates.append((eyes["l"]["open"], eyes["r"]["open"],
                        mpf["roll"], mpf["yaw"], mpf["pitch"],
                        "mediapipe_blendshapes", dbf["id"]))
    if updates:
        with conn:
            conn.executemany(
                "UPDATE face SET eye_open_l=?, eye_open_r=?, "
                "roll=?, yaw=?, pitch=?, eye_source=? WHERE id=?",
                updates)
    return len(updates)


def refine_shoot(conn, shoot_id: int, root: Path,
                 analyzer: Analyzer | None = None) -> RefineStats:
    """Refine every photo that still has a non-blendshape face.

    Idempotent per photo; failures skip (the face keeps its EAR values and
    scoring abstains — degraded, never wrong).
    """
    stats = RefineStats()
    if analyzer is None:
        if not available():
            log.warning("eye refiner unavailable (mediapipe/analyzer "
                        "not importable); EAR faces will abstain")
            stats.skipped_unavailable = True
            return stats
        analyzer = _default_analyzer

    photos = conn.execute(
        "SELECT DISTINCT p.id, p.rel_path FROM photo p "
        "JOIN face f ON f.photo_id = p.id "
        "WHERE p.shoot_id = ? AND p.missing = 0 "
        "AND f.eye_source != 'mediapipe_blendshapes' "
        "ORDER BY p.id", (shoot_id,)).fetchall()
    for row in photos:
        try:
            stats.faces_updated += refine_photo(
                conn, row["id"], root / row["rel_path"], analyzer)
        except Exception as e:  # noqa: BLE001 — per-photo tolerance (09 §4)
            stats.failed += 1
            log.warning("eye refine failed for %s: %s", row["rel_path"], e)
        stats.photos += 1
    return stats
