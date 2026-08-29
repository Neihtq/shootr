"""Style-learning evaluation (design 08 §7): leave-one-out over the user's
own edits, k-NN vs the mandated baseline — "apply the family's median edit
to everything". If k-NN can't beat the median, ship the median as a preset
and drop the model.

Reports per-parameter MAE in user units (EV for exposure), direction
agreement, and coverage (fraction clearing the confidence gate).

Usage: python engine/tools/eval_style.py [--library ID] [--db PATH]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db, style  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", type=int, default=None)
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    args = ap.parse_args()

    conn = db.connect(args.db)
    samples = style.load_history(conn, library_id=args.library)
    print(f"{len(samples)} edited photos with embeddings")
    n_fam = style.cluster_families(samples)
    for f in range(n_fam):
        n = sum(1 for s in samples if s.family == f)
        print(f"  family {f}: {n} photos — {style.family_traits(samples, f)}")

    err_knn: dict[str, list[float]] = defaultdict(list)
    err_med: dict[str, list[float]] = defaultdict(list)
    dir_knn: dict[str, list[bool]] = defaultdict(list)
    dir_med: dict[str, list[bool]] = defaultdict(list)
    abstained = 0

    medians = {f: style.family_median(samples, f) for f in range(n_fam)}
    for i, s in enumerate(samples):
        rest = samples[:i] + samples[i + 1:]
        pred = style.predict(s.embedding, rest, s.family)
        med = medians[s.family]
        if pred.abstained:
            abstained += 1
            continue
        for j, name in enumerate(style.TONAL_PARAMS):
            truth = s.deltas[j]
            if np.isnan(truth):
                continue
            if name in pred.params:
                err_knn[name].append(abs(pred.params[name] - truth))
                if abs(truth) > 1e-9:
                    dir_knn[name].append(
                        np.sign(pred.params[name]) == np.sign(truth))
            if name in med:
                err_med[name].append(abs(med[name] - truth))
                if abs(truth) > 1e-9:
                    dir_med[name].append(np.sign(med[name]) == np.sign(truth))

    coverage = 1 - abstained / len(samples)
    print(f"\ncoverage: {coverage:.1%} ({abstained} abstained)")
    print(f"{'param':>22} {'kNN MAE':>9} {'med MAE':>9} "
          f"{'kNN dir':>8} {'med dir':>8}   n")
    wins = 0
    comparable = 0
    for name in style.TONAL_PARAMS:
        if not err_knn.get(name):
            continue
        mk = float(np.mean(err_knn[name]))
        mm = float(np.mean(err_med[name])) if err_med.get(name) else float("nan")
        dk = float(np.mean(dir_knn[name])) if dir_knn.get(name) else float("nan")
        dm = float(np.mean(dir_med[name])) if dir_med.get(name) else float("nan")
        comparable += 1
        wins += mk < mm
        print(f"{name:>22} {mk:>9.3f} {mm:>9.3f} {dk:>8.1%} {dm:>8.1%}   "
              f"{len(err_knn[name])}")
    print(f"\nk-NN beats family median on {wins}/{comparable} params")
    print("(Exposure2012 MAE is in EV — the interpretable unit)")


if __name__ == "__main__":
    main()
