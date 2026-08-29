"""Dump full MediaPipe blendshape vectors per face for a shoot — the
measurement behind the expression/peak-moment metric decision (design
04 §7: within-group ordering needs a new measurement, not new weights).

Writes JSONL only (no DB writes): one row per matched face with all 52
blendshape category scores, keyed to the stored face row by bbox IoU so
the evaluation can join keeper ground truth (lr_history) and groups.

Usage: python engine/tools/expression_probe.py --shoot 3 --out FILE.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db  # noqa: E402
from shootr.eye_refiner import match_faces  # noqa: E402


def all_blendshapes(crop) -> dict[str, float] | None:
    import mediapipe as mp
    from shootr_analyzer import faces as F

    if crop.image.size == 0:
        return None
    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(crop.image))
    result = F._landmarker.detect(image)
    if not result.face_landmarks or not result.face_blendshapes:
        return None
    return {c.category_name: round(c.score, 4)
            for c in result.face_blendshapes[0]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoot", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    ap.add_argument("--scale", type=float, default=0.5)
    args = ap.parse_args()

    from shootr_analyzer import faces as F
    from shootr_analyzer.decode import decode_measurement

    F._ensure_models()
    conn = db.connect(args.db)
    root = Path(conn.execute(
        "SELECT l.root_path FROM shoot s JOIN library l "
        "ON l.id = s.library_id WHERE s.id = ?",
        (args.shoot,)).fetchone()["root_path"])

    done: set[int] = set()
    if args.out.exists():  # resume: skip photos already probed
        for line in args.out.read_text().splitlines():
            done.add(json.loads(line)["photo_id"])

    photos = conn.execute(
        "SELECT DISTINCT p.id, p.rel_path FROM photo p "
        "JOIN face f ON f.photo_id = p.id "
        "WHERE p.shoot_id = ? AND p.missing = 0 ORDER BY p.id",
        (args.shoot,)).fetchall()
    photos = [p for p in photos if p["id"] not in done]
    print(f"{len(photos)} photos to probe", flush=True)

    t0 = time.time()
    with args.out.open("a") as out:
        for k, row in enumerate(photos, 1):
            db_faces = [dict(r) for r in conn.execute(
                "SELECT id, bbox FROM face WHERE photo_id = ?",
                (row["id"],))]
            for f in db_faces:
                f["bbox"] = json.loads(f["bbox"])
            recs = []
            try:
                decoded = decode_measurement(root / row["rel_path"],
                                             args.scale)
                rgb = decoded.model_rgb()
                boxes = F._scrfd_detect(rgb)
                mp_faces = []
                for x, y, w, h, score in boxes[:F.MAX_FACES]:
                    crop = F._crop(rgb, x, y, w, h, pad=0.25)
                    shapes = all_blendshapes(crop)
                    if shapes is None:
                        continue
                    from shootr_analyzer.coords import (bbox_px_to_vision,
                                                        clamp_bbox)
                    mp_faces.append({
                        "bbox": clamp_bbox(bbox_px_to_vision(
                            x, y, w, h, decoded.width, decoded.height)),
                        "shapes": shapes})
                for dbf, mpf in match_faces(db_faces, mp_faces):
                    recs.append({"photo_id": row["id"],
                                 "face_id": dbf["id"],
                                 "shapes": mpf["shapes"]})
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL {row['rel_path']}: {e}", flush=True)
            # One line per face; empty photos still get a marker row so
            # resume skips them.
            if not recs:
                recs = [{"photo_id": row["id"], "face_id": None,
                         "shapes": None}]
            for r in recs:
                out.write(json.dumps(r) + "\n")
            out.flush()
            if k % 100 == 0:
                rate = k / (time.time() - t0)
                print(f"  {k}/{len(photos)} {rate:.2f}/s "
                      f"eta {(len(photos)-k)/rate/60:.0f} min", flush=True)
    print(f"done in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
