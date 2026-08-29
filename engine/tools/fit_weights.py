"""Fit profile weights against the user's own cull (design 04 §7, M2).

Ground truth: `lr_history` rows (catalog membership = keeper). The recall
gap is within-group ordering — the engine picks a different frame of the
same moment — so the objective is pairwise: inside each non-bracket group,
a keeper should outscore every non-keeper.

Faithful to scoring semantics: total = Σ w·v / Σ w over *applicable*
components (null-redistribution, design 04 §5), reproduced here from the
stored evidence records' per-component values. Weights are softmax-
parametrized (positive, sum-1 — total is scale-invariant in w) and
regularized toward the hand-tuned priors so one noisy shoot can't produce
wild weights (04 §7). Groups split even/odd into train/holdout; report
holdout pairwise accuracy and top-of-group hit rate per λ.

Prints recommended weights; applying them is a PROFILE_WEIGHTS edit
(weights_hash changes → rescore invalidates stale scores by design).

Usage: python engine/tools/fit_weights.py --shoot 3 [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import db  # noqa: E402
from shootr.scoring import PROFILE_WEIGHTS  # noqa: E402

SIGMOID_SCALE = 20.0  # score gaps live at ~0.1; 1/20 = the soft margin


def load(conn, shoot_id: int, profile: str):
    metrics = sorted(PROFILE_WEIGHTS[profile])
    rows = conn.execute("""
        SELECT s.photo_id, s.components, gm.group_id,
               (h.photo_id IS NOT NULL) AS keeper
        FROM score s
        JOIN group_member gm ON gm.photo_id = s.photo_id
        JOIN "group" g ON g.id = gm.group_id AND g.is_bracket = 0
            AND g.level = 'shot'  -- culling ranks within shot groups only
        JOIN photo p ON p.id = s.photo_id
        LEFT JOIN lr_history h ON h.photo_id = s.photo_id
        WHERE p.shoot_id = ? AND s.profile = ?""",
        (shoot_id, profile)).fetchall()
    V = np.zeros((len(rows), len(metrics)))
    M = np.zeros_like(V)
    gids = np.empty(len(rows), dtype=int)
    keep = np.empty(len(rows), dtype=bool)
    for i, r in enumerate(rows):
        comp = json.loads(r["components"])
        for j, name in enumerate(metrics):
            v = comp.get(name, {}).get("value")
            if v is not None:
                V[i, j] = v
                M[i, j] = 1.0
        gids[i] = r["group_id"]
        keep[i] = bool(r["keeper"])
    return metrics, V, M, gids, keep


def totals(w: np.ndarray, V: np.ndarray, M: np.ndarray) -> np.ndarray:
    live = M @ w
    live[live == 0] = 1.0  # all-null photo: total 0, same as scoring
    return (V * M) @ w / live


def build_pairs(gids, keep):
    """(keeper_idx, nonkeeper_idx) within each group."""
    pairs = []
    for g in np.unique(gids):
        idx = np.where(gids == g)[0]
        ks = idx[keep[idx]]
        ns = idx[~keep[idx]]
        pairs.extend((k, n) for k in ks for n in ns)
    return np.array(pairs) if pairs else np.empty((0, 2), dtype=int)


def loss(w, V, M, pairs, prior, lam):
    t = totals(w, V, M)
    d = SIGMOID_SCALE * (t[pairs[:, 0]] - t[pairs[:, 1]])
    pair_loss = np.mean(np.logaddexp(0.0, -d))
    return pair_loss + lam * float(np.sum((w - prior) ** 2))


def fit(V, M, pairs, prior, lam, iters=1500, lr=0.05, seed=0):
    rng = np.random.default_rng(seed)
    theta = np.log(prior + 1e-6) + 0.01 * rng.standard_normal(len(prior))
    m = np.zeros_like(theta)
    v = np.zeros_like(theta)
    for t_step in range(1, iters + 1):
        w = np.exp(theta) / np.exp(theta).sum()
        base = loss(w, V, M, pairs, prior, lam)
        g = np.zeros_like(theta)
        eps = 1e-4
        for j in range(len(theta)):
            th = theta.copy()
            th[j] += eps
            wj = np.exp(th) / np.exp(th).sum()
            g[j] = (loss(wj, V, M, pairs, prior, lam) - base) / eps
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        theta -= lr * m / (np.sqrt(v) + 1e-8)
    w = np.exp(theta) / np.exp(theta).sum()
    return w


def pairwise_acc(w, V, M, pairs):
    if not len(pairs):
        return float("nan")
    t = totals(w, V, M)
    return float(np.mean(t[pairs[:, 0]] > t[pairs[:, 1]]))


def top1_hit(w, V, M, gids, keep):
    """Groups with a keeper where the top-scored frame IS a keeper."""
    t = totals(w, V, M)
    hits = tot = 0
    for g in np.unique(gids):
        idx = np.where(gids == g)[0]
        if not keep[idx].any() or keep[idx].all():
            continue
        tot += 1
        hits += bool(keep[idx[np.argmax(t[idx])]])
    return hits / tot if tot else float("nan"), tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoot", type=int, required=True)
    ap.add_argument("--profile", default="event")
    ap.add_argument("--db", type=Path, default=Path.home() / "Library"
                    / "Application Support" / "Shootr" / "shootr.db")
    args = ap.parse_args()

    conn = db.connect(args.db)
    metrics, V, M, gids, keep = load(conn, args.shoot, args.profile)
    prior = np.array([PROFILE_WEIGHTS[args.profile][m] for m in metrics])
    print(f"{len(V)} photos, {keep.sum()} keepers, "
          f"{len(np.unique(gids))} non-bracket groups")

    train_mask = (gids % 2 == 0)
    p_train = build_pairs(gids[train_mask], keep[train_mask])
    p_hold = build_pairs(gids[~train_mask], keep[~train_mask])
    # build_pairs indexes into the masked arrays; remap to full indexing
    full_t = np.where(train_mask)[0]
    full_h = np.where(~train_mask)[0]
    p_train = full_t[p_train] if len(p_train) else p_train
    p_hold = full_h[p_hold] if len(p_hold) else p_hold
    print(f"pairs: train {len(p_train)}, holdout {len(p_hold)}")

    acc0 = pairwise_acc(prior, V, M, p_hold)
    t10, ngroups = top1_hit(prior, V, M, gids[~train_mask], keep[~train_mask])
    print(f"\npriors {dict(zip(metrics, prior.round(2)))}")
    print(f"  holdout pairwise {acc0:.1%}, top1 {t10:.1%} ({ngroups} groups)")

    best = None
    for lam in (0.0, 0.3, 1.0, 3.0):
        w = fit(V, M, p_train, prior, lam)
        acc = pairwise_acc(w, V, M, p_hold)
        t1, _ = top1_hit(w, V, M, gids[~train_mask], keep[~train_mask])
        print(f"λ={lam:<4} {dict(zip(metrics, w.round(3)))}")
        print(f"  holdout pairwise {acc:.1%}, top1 {t1:.1%}")
        if best is None or acc > best[1]:
            best = (w, acc, lam)

    w, acc, lam = best
    print(f"\nrecommended (λ={lam}): "
          f"{json.dumps(dict(zip(metrics, np.round(w, 2))), default=float)}")


if __name__ == "__main__":
    main()
