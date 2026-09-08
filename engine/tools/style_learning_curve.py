"""When would a trained model beat retrieval? (design 08 §4 "Phase 2")

Two empirical questions the doc leaves open, both answerable from the user's
own history rather than from priors:

  1. **Is k-NN saturating?** Error as a function of history size. If it is
     still falling at the current size, more edits help retrieval too, and
     the crossover with a parametric model is further away than it looks.
  2. **How does a trained model actually do here?** Ridge regression from the
     scene embedding to the delta — the honest first rung of "trained", and
     the one that needs the least data. If ridge loses badly at this size, a
     larger model will not rescue it; if it is close, the crossover is near.

Method: shot-group-aware splits (burst siblings must not straddle train and
test — they leak), history subsampled by GROUP so a small "history" is a
plausible smaller catalog rather than a thinned one. Ridge is fit per
parameter on centred targets with the intercept free, λ chosen on a held-out
slice of the training groups, never on test.

Usage: python engine/tools/style_learning_curve.py [--db PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db, style  # noqa: E402

SIZES = (0.15, 0.3, 0.5, 0.75, 1.0)
LAMBDAS = (1.0, 10.0, 100.0, 1000.0)
REPORT_PARAMS = ("Exposure2012", "Highlights2012", "Shadows2012")


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float):
    """Closed-form ridge with a free intercept (the mean edit)."""
    mu_x, mu_y = X.mean(axis=0), y.mean()
    Xc = X - mu_x
    d = Xc.shape[1]
    w = np.linalg.solve(Xc.T @ Xc + lam * np.eye(d), Xc.T @ (y - mu_y))
    return w, mu_x, mu_y


def ridge_predict(model, X: np.ndarray) -> np.ndarray:
    w, mu_x, mu_y = model
    return (X - mu_x) @ w + mu_y


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    ap.add_argument("--folds", type=int, default=4)
    args = ap.parse_args()

    conn = db.connect(args.db)
    samples = style.select_process_version(style.load_history(conn)).samples
    gid = {}
    for r in conn.execute(
            'SELECT gm.photo_id AS pid, gm.group_id AS gid FROM group_member '
            'gm JOIN "group" g ON g.id = gm.group_id AND g.level = \'shot\''):
        gid[r["pid"]] = r["gid"]
    samples = [s for s in samples if s.photo_id in gid]
    groups = sorted({gid[s.photo_id] for s in samples})
    rng = np.random.default_rng(0)
    rng.shuffle(groups)
    print(f"{len(samples)} history photos across {len(groups)} shot groups\n")

    params = style.params_of(samples)
    idx = {n: params.index(n) for n in REPORT_PARAMS if n in params}
    header = "  ".join(f"{n[:11]:>11}" for n in REPORT_PARAMS)
    print(f"{'history':>8} {'method':>8}  {header}")

    folds = np.array_split(np.array(groups), args.folds)
    for frac in SIZES:
        acc = {m: {n: [] for n in REPORT_PARAMS}
               for m in ("k-NN", "median", "ridge")}
        for f in range(args.folds):
            test_groups = set(folds[f].tolist())
            train_pool = [g for g in groups if g not in test_groups]
            keep = set(train_pool[:max(4, int(len(train_pool) * frac))])
            train = [s for s in samples if gid[s.photo_id] in keep]
            test = [s for s in samples if gid[s.photo_id] in test_groups]
            if len(train) < 12:
                continue

            # k-NN and the median baseline both need families, fit on TRAIN
            # only — clustering on everything would leak the test look.
            nfam = style.cluster_families(train)
            medians = {fam: style.family_median(train, fam)
                       for fam in range(nfam)}
            # A test photo has no family of its own: assign it the family
            # whose members it most resembles, exactly as the API does.
            Xtr = np.stack([s.embedding for s in train])
            ytr_all, _tr_names = style._matrix(train, params)

            ridge_models = {}
            for name, j in idx.items():
                mask = ~np.isnan(ytr_all[:, j])
                if mask.sum() < 12:
                    continue
                X, y = Xtr[mask], ytr_all[mask, j]
                cut = max(8, int(len(X) * 0.75))
                best = None
                for lam in LAMBDAS:
                    m = ridge_fit(X[:cut], y[:cut], lam)
                    err = np.mean(np.abs(ridge_predict(m, X[cut:]) - y[cut:])) \
                        if cut < len(X) else np.inf
                    if best is None or err < best[0]:
                        best = (err, lam)
                ridge_models[name] = ridge_fit(X, y, best[1])

            for s in test:
                fam = style.suggest_family([s.embedding], train)
                pr = style.predict(s.embedding, train, fam)
                med = medians.get(fam, {})
                for name, j in idx.items():
                    truth = s.deltas[j]
                    if np.isnan(truth):
                        continue
                    if not pr.abstained and name in pr.params:
                        acc["k-NN"][name].append(abs(pr.params[name] - truth))
                    if name in med:
                        acc["median"][name].append(abs(med[name] - truth))
                    if name in ridge_models:
                        p = ridge_predict(ridge_models[name],
                                          s.embedding[None, :])[0]
                        acc["ridge"][name].append(abs(p - truth))

        n_photos = int(len(samples) * frac)
        for method in ("k-NN", "median", "ridge"):
            cells = []
            for name in REPORT_PARAMS:
                v = acc[method][name]
                cells.append(f"{np.mean(v):>11.3f}" if v else f"{'—':>11}")
            label = f"~{n_photos}" if method == "k-NN" else ""
            print(f"{label:>8} {method:>8}  " + "  ".join(cells))
        print()


if __name__ == "__main__":
    main()
