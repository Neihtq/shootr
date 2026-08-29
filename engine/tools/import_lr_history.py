"""CLI for `shootr.lr_catalog` — copy a Lightroom catalog, validate it,
and import pick/rating/label/develop into `lr_history` (design 07 §2).

Usage:
  python engine/tools/import_lr_history.py \
      --catalog "~/Pictures/Lightroom/Lightroom Catalog.lrcat" \
      [--library ID] [--db PATH] [--force]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db, lr_catalog as lr  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--library", type=int, default=None,
                    help="restrict matching to one library's photos")
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    ap.add_argument("--force", action="store_true",
                    help="copy even if Lightroom Classic is running")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="shootr-lrcat-") as tmp:
        copy = lr.copy_catalog(args.catalog.expanduser(), Path(tmp),
                               force=args.force)
        conn = lr.open_copy(copy)
        info = lr.probe(conn)
        print(f"catalog DB version {info.db_version}; "
              f"schema {'valid' if info.valid else f'INVALID {info.missing}'}")
        if info.optional_missing:
            print(f"  optional tables missing (fields degrade): "
                  f"{sorted(info.optional_missing)}")
        app = db.connect(args.db)
        report = lr.import_history(app, lr.extract(conn, info),
                                   library_id=args.library)
        report.db_version = info.db_version
        print(f"matched {report.matched}/{report.catalog_rows} "
              f"({report.coverage:.1%}) — unmatched {report.unmatched} "
              f"{report.unmatched_samples or ''}, "
              f"ambiguous {report.ambiguous}, "
              f"develop on {report.with_develop}")


if __name__ == "__main__":
    main()
