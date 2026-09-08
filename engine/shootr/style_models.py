"""Style models the user creates and controls (design 08 §7b).

A model is a named row: a method, the libraries its history comes from, its
knobs, and the metrics §7's harness measured *for it*. Four operations —
learn, relearn, compare, choose — all explicit. Nothing is learned on import
and no method is auto-selected: the measurement that found ridge better on
exposure came from a single wedding, and treating that as a conclusion is the
overreach this module exists to avoid.

Methods are peers behind one interface. `knn` needs no fitting; `ridge` fits
per parameter and stores its coefficients. Whatever the method, §6's
guardrails wrap the output and the prediction still has to say where it came
from (§7a) — accuracy does not buy the right to be unexplained.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import style

METHODS = ("knn", "ridge")

DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "knn": {"k": style.KNN_K, "tau": style.SOFTMAX_TAU},
    # `lambda: null` = choose it by cross-validation at fit time. A fixed
    # default is a trap here: embeddings are L2-normalized, so X'X has trace n
    # and a λ of 100 shrinks predictions most of the way to the global mean —
    # which measured WORSE than the per-family median, making the method look
    # bad when only its knob was wrong.
    "ridge": {"lambda": None},
}

RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
CV_FOLDS = 5


class UnknownMethod(ValueError):
    pass


class ModelNotTrained(RuntimeError):
    pass


@dataclass
class StyleModel:
    id: int
    name: str
    method: str
    library_ids: list[int]          # empty = every library
    params: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    fit: dict[str, Any] = field(default_factory=dict)
    history_n: int = 0
    process_version: str | None = None
    trained_at: str | None = None
    is_active: bool = False

    @property
    def trained(self) -> bool:
        return self.trained_at is not None


# --- storage -----------------------------------------------------------------


def _row_to_model(r: sqlite3.Row) -> StyleModel:
    return StyleModel(
        id=r["id"], name=r["name"], method=r["method"],
        library_ids=json.loads(r["library_ids"]),
        params=json.loads(r["params"]),
        metrics=json.loads(r["metrics"]) if r["metrics"] else {},
        fit=json.loads(r["fit"]) if r["fit"] else {},
        history_n=r["history_n"] or 0,
        process_version=r["process_version"],
        trained_at=r["trained_at"], is_active=bool(r["is_active"]))


def create(conn: sqlite3.Connection, name: str, method: str,
           library_ids: list[int] | None = None,
           params: dict[str, Any] | None = None) -> int:
    if method not in METHODS:
        raise UnknownMethod(f"unknown method {method!r}; have {METHODS}")
    merged = dict(DEFAULT_PARAMS[method])
    merged.update(params or {})
    with conn:
        return conn.execute(
            "INSERT INTO style_model (name, method, library_ids, params, "
            "created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (name, method, json.dumps(sorted(library_ids or [])),
             json.dumps(merged))).lastrowid


def get(conn: sqlite3.Connection, model_id: int) -> StyleModel | None:
    r = conn.execute("SELECT * FROM style_model WHERE id = ?",
                     (model_id,)).fetchone()
    return _row_to_model(r) if r else None


def list_models(conn: sqlite3.Connection) -> list[StyleModel]:
    return [_row_to_model(r) for r in conn.execute(
        "SELECT * FROM style_model ORDER BY id")]


def active(conn: sqlite3.Connection) -> StyleModel | None:
    r = conn.execute("SELECT * FROM style_model WHERE is_active = 1 "
                     "ORDER BY id LIMIT 1").fetchone()
    return _row_to_model(r) if r else None


def set_active(conn: sqlite3.Connection, model_id: int) -> None:
    with conn:
        conn.execute("UPDATE style_model SET is_active = 0")
        conn.execute("UPDATE style_model SET is_active = 1 WHERE id = ?",
                     (model_id,))


def delete(conn: sqlite3.Connection, model_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM style_model WHERE id = ?", (model_id,))


# --- history scope -----------------------------------------------------------


def history_for(conn: sqlite3.Connection, model: StyleModel
                ) -> style.PVSelection:
    """The model's history: its libraries, narrowed to one process version.

    Scope may span catalogs — that is the point — but blending process
    versions would describe none of them (§6), so the PV filter runs after
    the union, and the model records which version it learned.
    """
    if not model.library_ids:
        samples = style.load_history(conn)
    else:
        samples = []
        for lib in model.library_ids:
            samples.extend(style.load_history(conn, library_id=lib))
    return style.select_process_version(samples)


# --- fitting -----------------------------------------------------------------


def _ridge_fit(X: np.ndarray, y: np.ndarray, lam: float) -> dict:
    mu_x, mu_y = X.mean(axis=0), float(y.mean())
    Xc = X - mu_x
    w = np.linalg.solve(Xc.T @ Xc + lam * np.eye(Xc.shape[1]),
                        Xc.T @ (y - mu_y))
    return {"w": w.tolist(), "mu_x": mu_x.tolist(), "mu_y": mu_y}


def _ridge_predict(coef: dict, embedding: np.ndarray) -> float:
    return float((embedding - np.asarray(coef["mu_x"])) @ np.asarray(coef["w"])
                 + coef["mu_y"])


def _folds(n: int, k: int = CV_FOLDS,
           groups: list[int] | None = None) -> list[np.ndarray]:
    """Deterministic folds, split by GROUP when group ids are supplied.

    This is not a detail: burst siblings are near-duplicates, so letting them
    straddle a split hands retrieval a copy of the answer and makes it look
    better than it is. Measured on the reference catalog, sibling leakage
    moved k-NN's exposure error from 0.34 to 0.25 EV — enough to flip which
    method a user would choose.
    """
    rng = np.random.default_rng(0)
    if groups is None:
        idx = np.arange(n)
        rng.shuffle(idx)
        return np.array_split(idx, min(k, max(2, n // 4)))
    uniq = sorted(set(groups))
    rng.shuffle(uniq)
    chunks = np.array_split(np.array(uniq, dtype=object),
                            min(k, max(2, len(uniq))))
    by_group: dict[Any, list[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(g, []).append(i)
    return [np.array([i for g in chunk for i in by_group[g]], dtype=int)
            for chunk in chunks]


def _fit_ridge_params(X: np.ndarray, Y: np.ndarray, lam: float | None,
                      groups: list[int] | None = None) -> tuple[dict, float]:
    """Per-parameter coefficients, choosing λ by CV when not pinned."""
    if lam is None:
        best: tuple[float, float] | None = None
        folds = _folds(len(X), groups=groups)
        for cand in RIDGE_LAMBDAS:
            errs = []
            for f in folds:
                tr = np.setdiff1d(np.arange(len(X)), f)
                for j in range(Y.shape[1]):
                    m_tr = tr[~np.isnan(Y[tr, j])]
                    m_te = f[~np.isnan(Y[f, j])]
                    if len(m_tr) < 12 or len(m_te) == 0:
                        continue
                    model = _ridge_fit(X[m_tr], Y[m_tr, j], cand)
                    pred = (X[m_te] - np.asarray(model["mu_x"])) @ \
                        np.asarray(model["w"]) + model["mu_y"]
                    # Scale-free so parameters on wildly different units
                    # (EV vs slider points) contribute comparably.
                    scale = np.nanstd(Y[:, j]) or 1.0
                    errs.append(np.mean(np.abs(pred - Y[m_te, j])) / scale)
            if errs and (best is None or np.mean(errs) < best[0]):
                best = (float(np.mean(errs)), cand)
        lam = best[1] if best else 1.0
    coefs = {}
    for j, name in enumerate(style.TONAL_PARAMS):
        mask = ~np.isnan(Y[:, j])
        if mask.sum() < 12:   # too little signal → abstain on this param
            continue
        coefs[name] = _ridge_fit(X[mask], Y[mask, j], lam)
    return coefs, lam


def train(conn: sqlite3.Connection, model_id: int) -> StyleModel:
    """Learn (or relearn) a model against current history.

    `knn` has no fitting step by design — 'training' it records scope,
    families and metrics. `ridge` fits per parameter and stores coefficients.
    Either way the model comes out with metrics from the SAME harness and the
    same held-out protocol, which is what makes the user's comparison mean
    something.
    """
    model = get(conn, model_id)
    if model is None:
        raise ModelNotTrained(f"no model {model_id}")
    sel = history_for(conn, model)
    samples = sel.samples
    if len(samples) < 10:
        raise ModelNotTrained(
            f"only {len(samples)} edited photos in scope; need 10")
    style.cluster_families(samples)
    # Shot groups, so evaluation can hold out whole bursts rather than
    # individual frames (see _folds).
    gmap = {r["pid"]: r["gid"] for r in conn.execute(
        'SELECT gm.photo_id AS pid, gm.group_id AS gid FROM group_member gm '
        'JOIN "group" g ON g.id = gm.group_id AND g.level = \'shot\'')}
    groups = [gmap.get(s.photo_id, -s.photo_id) for s in samples]

    fit: dict[str, Any] = {}
    if model.method == "ridge":
        X = np.stack([s.embedding for s in samples])
        Y = np.stack([s.deltas for s in samples])
        coefs, lam = _fit_ridge_params(X, Y, model.params.get("lambda"),
                                       groups=groups)
        fit["coefficients"] = coefs
        fit["lambda"] = lam
        # Clamps come from history, not from the fit: §6's guarantee that the
        # worst case is a bland edit must survive the method change.
        fit["ranges"] = {
            name: [float(np.nanmin(Y[:, j])), float(np.nanmax(Y[:, j]))]
            for j, name in enumerate(style.TONAL_PARAMS)
            if not np.isnan(Y[:, j]).all()}

    metrics = evaluate(samples, model.method, fit, model.params,
                       groups=groups)
    with conn:
        conn.execute(
            "UPDATE style_model SET metrics = ?, fit = ?, history_n = ?, "
            "process_version = ?, trained_at = datetime('now') WHERE id = ?",
            (json.dumps(metrics), json.dumps(fit), len(samples),
             sel.process_version, model_id))
    return get(conn, model_id)


# --- evaluation (design 08 §7, one harness for every method) ------------------


def evaluate(samples: list[style.StyleSample], method: str,
             fit: dict, params: dict,
             groups: list[int] | None = None) -> dict:
    """Per-parameter MAE against the family-median baseline.

    **Held out for every method**, which is what makes the comparison the
    user is asked to make honest: retrieval leaves the photo out of its own
    neighbour pool, and a fitted method is *refit per fold* so it never sees
    the photo it is scored on. Scoring a fitted model in-sample against a
    leave-one-out retrieval number would be a rigged fight.

    Splits are by **shot group** when group ids are supplied, so a photo is
    never scored against its own burst siblings — near-duplicates would hand
    retrieval the answer and flip which method a user would pick.
    """
    nfam = max((s.family for s in samples), default=0) + 1
    medians = {f: style.family_median(samples, f) for f in range(nfam)}
    err: dict[str, list[float]] = {}
    base: dict[str, list[float]] = {}
    abstained = 0

    fold_fit: dict[int, dict] = {}
    if method != "knn":
        X = np.stack([s.embedding for s in samples])
        Y = np.stack([s.deltas for s in samples])
        lam = (fit or {}).get("lambda") or params.get("lambda") or 1.0
        for f in _folds(len(samples), groups=groups):
            tr = np.setdiff1d(np.arange(len(samples)), f)
            coefs, _ = _fit_ridge_params(X[tr], Y[tr], lam)
            held = {"coefficients": coefs, "ranges": (fit or {}).get("ranges")}
            for i in f.tolist():
                fold_fit[i] = held

    for i, s in enumerate(samples):
        if groups is not None:
            g = groups[i]
            rest = [t for j, t in enumerate(samples) if groups[j] != g]
        else:
            rest = samples[:i] + samples[i + 1:]
        pred = predict_with(method, fold_fit.get(i, fit), params,
                            s.embedding, rest, s.family)
        if pred is None:
            abstained += 1
            continue
        med = medians.get(s.family, {})
        for j, name in enumerate(style.TONAL_PARAMS):
            truth = s.deltas[j]
            if np.isnan(truth):
                continue
            if name in pred:
                err.setdefault(name, []).append(abs(pred[name] - truth))
            if name in med:
                base.setdefault(name, []).append(abs(med[name] - truth))
    per_param = {
        name: {"mae": round(float(np.mean(v)), 4),
               "baseline_mae": (round(float(np.mean(base[name])), 4)
                                if base.get(name) else None),
               "n": len(v)}
        for name, v in sorted(err.items())}
    wins = sum(1 for d in per_param.values()
               if d["baseline_mae"] is not None and d["mae"] < d["baseline_mae"])
    return {
        "history_n": len(samples),
        "families": nfam,
        "coverage": round(1 - abstained / len(samples), 4) if samples else 0.0,
        "beats_median_on": wins,
        "params_scored": len(per_param),
        "per_param": per_param,
        "held_out": True,
        "held_out_by": "shot_group" if groups is not None else "photo",
        "lambda": (fit or {}).get("lambda"),
    }


def predict_with(method: str, fit: dict, params: dict,
                 embedding: np.ndarray, history: list[style.StyleSample],
                 family: int, clipped_hi: float | None = None,
                 excluded_params: frozenset[str] = frozenset()
                 ) -> dict[str, float] | None:
    """One prediction from any method, or None when the method abstains."""
    if method == "knn":
        pr = style.predict(embedding, history, family,
                           k=int(params.get("k", style.KNN_K)),
                           tau=float(params.get("tau", style.SOFTMAX_TAU)),
                           clipped_hi=clipped_hi,
                           excluded_params=excluded_params)
        return None if pr.abstained else pr.params
    if method == "ridge":
        coefs = (fit or {}).get("coefficients") or {}
        if not coefs:
            return None
        ranges = (fit or {}).get("ranges") or {}
        out: dict[str, float] = {}
        for name, coef in coefs.items():
            if name in excluded_params:
                continue
            v = _ridge_predict(coef, embedding)
            lo, hi = ranges.get(name, (v, v))
            out[name] = float(np.clip(v, lo, hi))  # §6 clamp, every method
        if (clipped_hi is not None and clipped_hi > style.CLIPPED_HI_LIMIT
                and out.get("Exposure2012", 0.0) > 0):
            out["Exposure2012"] = 0.0
        return out
    raise UnknownMethod(method)
