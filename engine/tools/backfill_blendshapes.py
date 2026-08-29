"""Backfill blendshape eye-openness onto existing Vision face rows.

The live Swift path ships EAR eye values (`eye_source='ear_landmarks'`) —
the source hand-labelling measured as unreliable (2026-08-20: FA 16.7%;
2026-08-29 wedding keepers: 76% false-reject at the culling cut). This is
the "MediaPipe blendshape refiner (Python side, swappable)" from design
03 §5, as a backfill over already-analyzed shoots: re-decode each photo
with faces, run the canonical analyzer's face stage (SCRFD + MediaPipe
blendshapes), match to the stored Vision faces by bbox IoU (both sides
use the 03 §4 contract's normalized Vision-convention boxes), and update
eye_open_l/r + roll/yaw/pitch + eye_source on matches. Scoring then picks
the calibrated blendshapes curve by provenance (EYES_OPEN_CURVES).

Unmatched DB faces keep their EAR values — provenance stays honest.
Resumable via a checkpoint file (last completed photo id, ascending scan).

Usage:
  python engine/tools/backfill_blendshapes.py --shoot 3 [--db PATH]
      [--scale 0.5] [--checkpoint PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db  # noqa: E402

MATCH_IOU = 0.3  # same bar the blink-label tool uses to pair the analyzers


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoot", type=int, required=True)
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--checkpoint", type=Path,
                    default=Path("/tmp/backfill_blendshapes.ckpt"))
    args = ap.parse_args()

    from shootr_analyzer.decode import DecodeUnreadable, decode_measurement
    from shootr_analyzer.faces import detect_faces

    conn = db.connect(args.db)
    root = Path(conn.execute(
        "SELECT l.root_path FROM shoot s JOIN library l "
        "ON l.id = s.library_id WHERE s.id = ?",
        (args.shoot,)).fetchone()["root_path"])

    after = 0
    if args.checkpoint.exists():
        after = int(args.checkpoint.read_text().strip() or 0)
        print(f"resuming after photo id {after}", flush=True)

    photos = conn.execute(
        "SELECT DISTINCT p.id, p.rel_path FROM photo p "
        "JOIN face f ON f.photo_id = p.id "
        "WHERE p.shoot_id = ? AND p.missing = 0 AND p.id > ? "
        "ORDER BY p.id", (args.shoot, after)).fetchall()
    print(f"{len(photos)} photos with faces to backfill", flush=True)

    t0 = time.time()
    n_faces = n_matched = n_failed = 0
    for k, row in enumerate(photos, 1):
        db_faces = [dict(r) for r in conn.execute(
            "SELECT id, bbox FROM face WHERE photo_id = ?", (row["id"],))]
        for f in db_faces:
            f["bbox"] = json.loads(f["bbox"])
        n_faces += len(db_faces)
        try:
            decoded = decode_measurement(root / row["rel_path"], args.scale)
            # frame_max=0 skips the full-res eye-sharpness re-decode; the
            # stored Swift eye_sharp values stay authoritative.
            mp_faces = detect_faces(root / row["rel_path"], decoded,
                                    frame_max=0.0)
        except (DecodeUnreadable, Exception) as e:  # noqa: BLE001
            n_failed += 1
            print(f"  FAIL {row['rel_path']}: {e}", flush=True)
            continue
        mp_faces = [m for m in mp_faces
                    if m["eye_source"] == "mediapipe_blendshapes"]
        updates = []
        for dbf, mpf in match_faces(db_faces, mp_faces):
            eyes = mpf["eyes"]
            updates.append((
                eyes["l"]["open"], eyes["r"]["open"],
                mpf["roll"], mpf["yaw"], mpf["pitch"],
                "mediapipe_blendshapes", dbf["id"]))
        if updates:
            with conn:
                conn.executemany(
                    "UPDATE face SET eye_open_l=?, eye_open_r=?, "
                    "roll=?, yaw=?, pitch=?, eye_source=? WHERE id=?",
                    updates)
            n_matched += len(updates)
        args.checkpoint.write_text(str(row["id"]))
        if k % 50 == 0:
            rate = k / (time.time() - t0)
            print(f"  {k}/{len(photos)}  {rate:.2f} photos/s  "
                  f"eta {(len(photos)-k)/rate/60:.0f} min", flush=True)

    print(f"done in {(time.time()-t0)/60:.1f} min: "
          f"{n_matched}/{n_faces} faces updated to blendshapes, "
          f"{n_failed} photos failed", flush=True)


if __name__ == "__main__":
    main()
