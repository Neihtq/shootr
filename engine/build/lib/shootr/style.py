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

# ---------------------------------------------------------------------------
# Which parameters are modelled — DERIVED from the user's own history, not a
# curated list (user requirement, 2026-09-08: "ALL settings"). A curated list
# is guaranteed to miss the parameter that matters most to someone: this
# catalog uses 52 varying global parameters, and the original 13 ignored the
# user's entire HSL signature (yellows/greens shifted and desaturated, orange
# luminance lifted, across ~400 of 560 photos).
#
# So: everything numeric and global in the history is modelled, minus these
# categories, each excluded for a stated reason rather than by taste.

# Compositional intent, never predicted (design 08 §1).
_DENY_PREFIX_GEOMETRY = ("Crop", "Upright", "Perspective", "Straighten")
# Spatial and per-photo; permanently out of scope (§1).
_DENY_PREFIX_LOCAL = ("Local", "Correction", "Mask", "PaintBased",
                      "RetouchArea", "CircularGradient", "GradientBased")
# Absolute white balance describes the LIGHT, not the user's taste. Modelling
# it needs an as-shot baseline the analyzer does not emit yet (§2.2) — a
# recorded gap, not an oversight.
_DENY_WHITE_BALANCE = frozenset({
    "Temperature", "Tint", "CustomTemperature", "CustomTint",
    "IncrementalTemperature", "IncrementalTint",
})
# Bookkeeping and identity: stamped or copied, never blended.
_DENY_BOOKKEEPING = frozenset({
    "Version", "ProcessVersion", "CompatibleVersion", "HDRMaxValue",
    "HasSettings", "RawFileName", "SupportsAmount", "SupportsColor",
    "SupportsMonochrome", "SupportsHighDynamicRange",
    "SupportsNormalDynamicRange", "SupportsSceneReferred", "SupportsOutputReferred",
})
# A seed is not a style: averaging two random seeds means nothing.
_DENY_SUFFIXES = ("Seed", "ID", "Digest", "Name", "Count", "Hash")


def modelable(name: str) -> bool:
    """Is this develop parameter one we may learn and write?

    Everything numeric that is global and not explicitly excluded. Non-numeric
    values (camera profile, ConvertToGrayscale, lens profile names) are handled
    by the caller — a blend of strings is meaningless, so they are never
    predicted.
    """
    if name.startswith(_DENY_PREFIX_GEOMETRY) or \
            name.startswith(_DENY_PREFIX_LOCAL):
        return False
    if name in _DENY_WHITE_BALANCE or name in _DENY_BOOKKEEPING:
        return False
    return not name.endswith(_DENY_SUFFIXES)


def params_of(samples: list["StyleSample"]) -> list[str]:
    """The parameter set this history actually contains, in stable order."""
    seen: set[str] = set()
    for s in samples:
        seen.update(s.deltas)
    return sorted(seen)


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
    # param name → delta. A DICT, not a fixed-length vector: the parameter set
    # is whatever this user's history contains, so it cannot be known at import
    # time. Absent key = the history has no value for it, which is different
    # from a value of zero.
    deltas: dict[str, float]
    embedding: np.ndarray       # L2-normalized scene embedding
    process_version: str | None
    raw_version: str | None = None   # crs:Version (Camera Raw), 07 §4
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
    # Parameters the user opted out of: predicted, deliberately not written.
    # Reported rather than dropped silently, so the UI can show "we had a
    # value for this, you told us not to write it".
    excluded: dict[str, float] = field(default_factory=dict)


def load_history(conn: sqlite3.Connection,
                 library_id: int | None = None) -> list[StyleSample]:
    """Edited photos (lr_history.develop) joined to their scene embeddings.

    Every modelable numeric parameter the catalog recorded is kept — the set
    is the user's, not ours (see `modelable`).
    """
    scope = "AND p.library_id = ?" if library_id else ""
    args = (library_id,) if library_id else ()
    samples = []
    for row in conn.execute(
            f"SELECT h.photo_id, h.develop, e.vec, e.dim FROM lr_history h "
            f"JOIN photo p ON p.id = h.photo_id "
            f"JOIN embedding e ON e.photo_id = h.photo_id AND e.kind='scene' "
            f"WHERE h.develop IS NOT NULL {scope}", args):
        dev = json.loads(row["develop"])
        deltas = {k: float(v) for k, v in dev.items()
                  if isinstance(v, (int, float))
                  and not isinstance(v, bool) and modelable(k)}
        if not deltas:
            continue
        vec = np.frombuffer(row["vec"], dtype=np.float32).astype(np.float64)
        n = np.linalg.norm(vec)
        if n == 0:
            continue
        samples.append(StyleSample(
            photo_id=row["photo_id"], deltas=deltas, embedding=vec / n,
            process_version=(str(dev["ProcessVersion"])
                             if dev.get("ProcessVersion") else None),
            raw_version=(str(dev["Version"]) if dev.get("Version")
                         else None)))
    return samples


def dominant_process_version(samples: list[StyleSample]) -> str | None:
    """The process version most of the history was edited under."""
    pvs = [s.process_version for s in samples if s.process_version]
    return max(set(pvs), key=pvs.count) if pvs else None


@dataclass
class PVSelection:
    samples: list[StyleSample]
    process_version: str | None
    excluded_other_pv: int      # known to be a DIFFERENT process version
    unverified_pv: int          # no ProcessVersion recorded at all


def select_process_version(samples: list[StyleSample],
                           pv: str | None = None) -> PVSelection:
    """Keep only history compatible with one process version (design 08 §6).

    This matters the moment a second catalog is imported: the same
    `Exposure2012` renders differently across process versions, so blending
    PV 11 edits with PV 15 edits produces numbers that describe neither.
    Samples with a *known, different* PV are excluded. Samples with **no**
    recorded PV are kept — absence is not evidence of incompatibility — but
    counted, so a caller can say how much of the history it could not verify
    rather than implying certainty.
    """
    pv = pv or dominant_process_version(samples)
    if pv is None:
        return PVSelection(samples, None, 0, len(samples))
    keep, other, unknown = [], 0, 0
    for s in samples:
        if s.process_version is None:
            keep.append(s)
            unknown += 1
        elif s.process_version == pv:
            keep.append(s)
        else:
            other += 1
    return PVSelection(keep, pv, other, unknown)


# --- Look families (design 08 §3): discovered from edits, not assumed -------


def _matrix(samples: list[StyleSample], params: list[str] | None = None
            ) -> tuple[np.ndarray, list[str]]:
    """(n × p) matrix over the history's own parameter set; NaN where a photo
    has no value for a parameter."""
    params = params or params_of(samples)
    X = np.full((len(samples), len(params)), np.nan)
    for i, s in enumerate(samples):
        for j, name in enumerate(params):
            v = s.deltas.get(name)
            if v is not None:
                X[i, j] = v
    return X, params


def cluster_families(samples: list[StyleSample], distance_cut: float = 0.7,
                     min_family: int = 5) -> int:
    """Average-linkage agglomerative clustering on correlation distance of
    standardized deltas. Small n (hundreds), so O(n²) is fine and we avoid
    a scipy dependency. Tiny clusters fold into family 0 rather than
    becoming one-photo 'looks'. Returns the family count.
    """
    X, params = _matrix(samples)
    # Correlation distance needs at least three parameters to express a
    # difference: with two, every centred row is collinear and every pair sits
    # at distance 0 or 2, so "families" would be an artifact. One family is the
    # honest answer for a history that thin.
    if len(params) < 3:
        for s_ in samples:
            s_.family = 0
        return 1
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
    X, params = _matrix(samples)
    fam, _ = _matrix([s for s in samples if s.family == family], params)
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
        bits.append(f"{sign}{params[i]}")
    return " ".join(bits) or "(near the global mean)"


def family_median(samples: list[StyleSample], family: int) -> dict[str, float]:
    fam, params = _matrix([s for s in samples if s.family == family])
    with _nan_ok():
        med = np.nanmedian(fam, axis=0)
    return {k: float(v) for k, v in zip(params, med)
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
            clipped_hi: float | None = None,
            excluded_params: frozenset[str] | set[str] = frozenset()
            ) -> Prediction:
    """Softmax-weighted blend of the k most similar family members' deltas,
    clamped to the family's observed range. Abstains (writes nothing) when
    the neighbors are dissimilar or disagree (§6).

    `clipped_hi` (the frame's measured blown-highlight fraction) enables the
    §6 sanity check: an already-clipping frame never gets a positive exposure
    push, and the damping is reported rather than applied silently.

    `excluded_params` is the user's per-parameter opt-out (§6). Excluded
    params are removed from `params` — so they are never written — and moved
    to `excluded` with their predicted value, because "we had a number and
    you told us not to use it" is different from "we had nothing".
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
    F, names = _matrix(fam)                       # the family's own params
    D = F[order, :]
    with _nan_ok():
        lo = np.nanmin(F, axis=0)
        hi = np.nanmax(F, axis=0)

    params: dict[str, float] = {}
    disagreements = []
    for j, name in enumerate(names):
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
    excluded = {k: params.pop(k) for k in list(params) if k in excluded_params}
    return Prediction(params, confidence,
                      [fam[i].photo_id for i in order], damped=damped,
                      excluded=excluded)
