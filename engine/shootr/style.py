"""Style learning (design 08): learn global develop params from the user's
edit history; predict as a k-NN blend over scene similarity, conditioned on
a discovered look family. Deliberately narrow:

- Global scalar params only — local adjustments and crop are out of scope
  (design 08 §1, permanent).
- Delta targets (§2.1): for the modern crs sliders Adobe's default IS 0,
  so delta = stored value. Temperature/Tint need an as-shot baseline the
  analyzer does not yet emit (`analysis.frame.as_shot_wb` — recorded gap),
  so WB is EXCLUDED from prediction this pass rather than modeled on
  absolute Kelvin, which would learn the light source, not the user (§2.2).
- k-NN before any trained model (§4): inspectable ("edited like these
  photos"), works at hundreds of samples, no training step.
- Confidence is a first-class output; below the gate the honest answer is
  "no prediction" (§6). Predictions are clamped to the family's observed
  range — the worst case must be a bland edit, not a ruined one.
- The bar (§7): beat "family median for everything" or ship the median as
  a preset and drop the model. `tools/eval_style.py` runs that comparison.
"""

from __future__ import annotations

import json
import math
import sqlite3
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np


@contextmanager
def _nan_ok():
    """Params nobody ever set produce all-NaN columns; the NaN-aware
    reductions handle that correctly — silence their warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield

# Modelable per-photo tonal params: modern crs sliders whose Adobe default
# is 0 (delta = value). Ordered; prediction and eval use this order.
TONAL_PARAMS: list[str] = [
    "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012",
    "Whites2012", "Blacks2012", "Texture", "Clarity2012", "Dehaze",
    "Vibrance", "Saturation",
    "ColorGradeMidtoneHue", "ColorGradeMidtoneSat",
]

KNN_K = 8
SOFTMAX_TAU = 0.05          # cosine-similarity temperature
MIN_NEIGHBOR_SIM = 0.5      # below: the photo looks like nothing we know
CONFIDENCE_GATE = 0.35

# Highlight-clip sanity check (§6): a frame that already clips this fraction of
# highlights cannot take a positive exposure push — the blown area only grows,
# and unlike a dark frame there is nothing to recover. We cannot render Adobe's
# pipeline to simulate the result, so the rule is deliberately blunt: refuse to
# ADD exposure, never invent a reduction the neighbours did not support.
CLIPPED_HI_LIMIT = 0.02


@dataclass
class StyleSample:
    photo_id: int
    deltas: np.ndarray          # aligned to TONAL_PARAMS, NaN = param absent
    embedding: np.ndarray       # L2-normalized scene embedding
    process_version: str | None
    family: int = -1


@dataclass
class Prediction:
    params: dict[str, float]
    confidence: float
    neighbor_ids: list[int]
    abstained: bool = False
    reason: str | None = None
    # Guardrails that fired, so the UI can say what was changed and why
    # (design 08 §6; scores/predictions carry evidence — README rule 5).
    damped: dict[str, str] = field(default_factory=dict)


def load_history(conn: sqlite3.Connection,
                 library_id: int | None = None) -> list[StyleSample]:
    """Edited photos (lr_history.develop) joined to their scene embeddings."""
    scope = "AND p.library_id = ?" if library_id else ""
    args = (library_id,) if library_id else ()
    samples = []
    for row in conn.execute(
            f"SELECT h.photo_id, h.develop, e.vec, e.dim FROM lr_history h "
            f"JOIN photo p ON p.id = h.photo_id "
            f"JOIN embedding e ON e.photo_id = h.photo_id AND e.kind='scene' "
            f"WHERE h.develop IS NOT NULL {scope}", args):
        dev = json.loads(row["develop"])
        deltas = np.array([float(dev[k]) if isinstance(dev.get(k), (int, float))
                           and not isinstance(dev.get(k), bool) else np.nan
                           for k in TONAL_PARAMS])
        if np.isnan(deltas).all():
            continue
        vec = np.frombuffer(row["vec"], dtype=np.float32).astype(np.float64)
        n = np.linalg.norm(vec)
        if n == 0:
            continue
        samples.append(StyleSample(
            photo_id=row["photo_id"], deltas=deltas, embedding=vec / n,
            process_version=(str(dev["ProcessVersion"])
                             if dev.get("ProcessVersion") else None)))
    return samples


# --- Look families (design 08 §3): discovered from edits, not assumed -------


def cluster_families(samples: list[StyleSample], distance_cut: float = 0.7,
                     min_family: int = 5) -> int:
    """Average-linkage agglomerative clustering on correlation distance of
    standardized deltas. Small n (hundreds), so O(n²) is fine and we avoid
    a scipy dependency. Tiny clusters fold into family 0 rather than
    becoming one-photo 'looks'. Returns the family count.
    """
    X = np.stack([s.deltas for s in samples])
    with _nan_ok():
        mu = np.nanmean(X, axis=0)
        sd = np.nanstd(X, axis=0)
    sd[np.isnan(sd) | (sd == 0)] = 1.0
    mu = np.where(np.isnan(mu), 0.0, mu)
    Z = (X - mu) / sd
    Z = np.where(np.isnan(Z), 0.0, Z)

    n = len(samples)
    if n <= min_family:
        for s in samples:
            s.family = 0
        return 1

    # correlation distance between standardized rows
    Zc = Z - Z.mean(axis=1, keepdims=True)
    norms = np.linalg.norm(Zc, axis=1)
    norms[norms == 0] = 1.0
    corr = (Zc @ Zc.T) / np.outer(norms, norms)
    dist = 1.0 - corr

    clusters: list[list[int]] = [[i] for i in range(n)]
    d = dist.copy()
    np.fill_diagonal(d, np.inf)
    sizes = np.ones(n)
    active = list(range(n))
    while len(active) > 1:
        sub = d[np.ix_(active, active)]
        i_, j_ = np.unravel_index(np.argmin(sub), sub.shape)
        if sub[i_, j_] > distance_cut:
            break
        a, b = active[i_], active[j_]
        # average linkage update into a; retire b
        for c in active:
            if c in (a, b):
                continue
            d[a, c] = d[c, a] = (d[a, c] * sizes[a] + d[b, c] * sizes[b]) \
                / (sizes[a] + sizes[b])
        sizes[a] += sizes[b]
        clusters[a].extend(clusters[b])
        clusters[b] = []
        active.remove(b)
        d[a, a] = np.inf

    families = [c for c in clusters if len(c) >= min_family]
    families.sort(key=len, reverse=True)
    leftovers = [i for c in clusters if 0 < len(c) < min_family for i in c]
    if not families:
        families = [list(range(n))]
        leftovers = []
    families[0].extend(leftovers)
    for fam_id, members in enumerate(families):
        for i in members:
            samples[i].family = fam_id
    return len(families)


def family_traits(samples: list[StyleSample], family: int,
                  top: int = 3) -> str:
    """Human-readable distinguishing traits vs. the global mean (§3)."""
    X = np.stack([s.deltas for s in samples])
    fam = np.stack([s.deltas for s in samples if s.family == family])
    with _nan_ok():
        mu = np.nanmean(X, axis=0)
        sd = np.nanstd(X, axis=0)
        fmu = np.nanmean(fam, axis=0)
    sd[np.isnan(sd) | (sd == 0)] = 1.0
    diff = (fmu - mu) / sd
    order = np.argsort(-np.abs(np.where(np.isnan(diff), 0, diff)))
    bits = []
    for i in order[:top]:
        if np.isnan(diff[i]) or abs(diff[i]) < 0.2:
            continue
        sign = "+" if diff[i] > 0 else "−"
        bits.append(f"{sign}{TONAL_PARAMS[i]}")
    return " ".join(bits) or "(near the global mean)"


def family_median(samples: list[StyleSample], family: int) -> dict[str, float]:
    fam = np.stack([s.deltas for s in samples if s.family == family])
    with _nan_ok():
        med = np.nanmedian(fam, axis=0)
    return {k: float(v) for k, v in zip(TONAL_PARAMS, med)
            if not math.isnan(v)}


def suggest_family(embeddings: list[np.ndarray],
                   history: list[StyleSample]) -> int:
    """Auto-suggestion (§3): the family whose members are most similar to
    the shoot's photos on average. The user can always override."""
    fams = sorted({s.family for s in history})
    E = np.stack([e / (np.linalg.norm(e) or 1.0) for e in embeddings])
    best, best_sim = fams[0], -np.inf
    for f in fams:
        F = np.stack([s.embedding for s in history if s.family == f])
        sim = float((E @ F.T).mean())
        if sim > best_sim:
            best, best_sim = f, sim
    return best


# --- k-NN prediction (design 08 §4) ------------------------------------------


def predict(embedding: np.ndarray, history: list[StyleSample],
            family: int, k: int = KNN_K, tau: float = SOFTMAX_TAU,
            gate: float = CONFIDENCE_GATE,
            clipped_hi: float | None = None) -> Prediction:
    """Softmax-weighted blend of the k most similar family members' deltas,
    clamped to the family's observed range. Abstains (writes nothing) when
    the neighbors are dissimilar or disagree (§6).

    `clipped_hi` (the frame's measured blown-highlight fraction) enables the
    §6 sanity check: an already-clipping frame never gets a positive exposure
    push, and the damping is reported rather than applied silently.
    """
    fam = [s for s in history if s.family == family]
    if len(fam) < 3:
        return Prediction({}, 0.0, [], abstained=True,
                          reason="family_too_small")
    e = embedding / (np.linalg.norm(embedding) or 1.0)
    sims = np.array([float(e @ s.embedding) for s in fam])
    order = np.argsort(-sims)[:k]
    top_sims = sims[order]
    if top_sims[0] < MIN_NEIGHBOR_SIM:
        return Prediction({}, 0.0, [], abstained=True,
                          reason="no_similar_history")

    w = np.exp((top_sims - top_sims[0]) / tau)
    w /= w.sum()
    D = np.stack([fam[i].deltas for i in order])
    with _nan_ok():
        lo = np.nanmin(np.stack([s.deltas for s in fam]), axis=0)
        hi = np.nanmax(np.stack([s.deltas for s in fam]), axis=0)

    params: dict[str, float] = {}
    disagreements = []
    for j, name in enumerate(TONAL_PARAMS):
        col = D[:, j]
        mask = ~np.isnan(col)
        if not mask.any():
            continue
        wj = w[mask] / w[mask].sum()
        val = float((wj * col[mask]).sum())
        params[name] = float(np.clip(val, lo[j], hi[j]))  # §6 clamping
        scale = max(float(hi[j] - lo[j]), 1e-9)
        disagreements.append(float(np.sqrt(
            (wj * (col[mask] - val) ** 2).sum()) / scale))

    # Confidence: similar neighbors that agree (§4). Both in [0, 1].
    agreement = 1.0 - min(1.0, 2.0 * float(np.mean(disagreements or [1.0])))
    confidence = float(np.mean(top_sims)) * agreement
    if confidence < gate:
        return Prediction({}, confidence, [fam[i].photo_id for i in order],
                          abstained=True, reason="low_confidence")

    damped: dict[str, str] = {}
    if (clipped_hi is not None and clipped_hi > CLIPPED_HI_LIMIT
            and params.get("Exposure2012", 0.0) > 0):
        damped["Exposure2012"] = (
            f"+{params['Exposure2012']:.2f} EV withheld: "
            f"{clipped_hi:.1%} of highlights already clipped")
        params["Exposure2012"] = 0.0
    return Prediction(params, confidence,
                      [fam[i].photo_id for i in order], damped=damped)
