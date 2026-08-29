"""CLI for `shootr.eye_refiner` — backfill blendshape eye values onto an
already-analyzed shoot. Fresh analyze jobs run the refiner automatically
(runner finalize); this exists for shoots analyzed before that wiring, or
to re-run after a partial failure. Idempotent: only non-blendshape faces
are revisited.

Usage: python engine/tools/backfill_blendshapes.py --shoot 3 [--db PATH]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db, eye_refiner  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoot", type=int, required=True)
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = db.connect(args.db)
    root = Path(conn.execute(
        "SELECT l.root_path FROM shoot s JOIN library l "
        "ON l.id = s.library_id WHERE s.id = ?",
        (args.shoot,)).fetchone()["root_path"])

    t0 = time.time()
    stats = eye_refiner.refine_shoot(conn, args.shoot, root)
    print(f"done in {(time.time()-t0)/60:.1f} min: {stats.photos} photos, "
          f"{stats.faces_updated} faces updated, {stats.failed} failed"
          + (" (refiner unavailable)" if stats.skipped_unavailable else ""))


if __name__ == "__main__":
    main()
