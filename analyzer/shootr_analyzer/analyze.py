"""Full analysis of one photo — the Python port of Analyze.swift.

Emits the contract AS IMPLEMENTED by the Swift helper (Output.swift), not the
aspirational doc-03 shape: flat top-level `embedding`+`embedding_dim`,
clipped_hi/lo directly under `frame`, eyes keyed "l"/"r". Fields the Swift
helper leaves null (faceprint) this analyzer fills — the schema has the
columns waiting.

Model-backed steps degrade to absence, never to zeros: a missing detector
model means no `faces` entries and no saliency, and the scorer's null-
handling does the right thing (null ≠ 0, design 04 §5).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .decode import Decoded, decode_measurement, green_plane
from .io import prune_nulls
from .sharpness import clipping, tile_map


def analyze(path: Path, scale: float = 0.5,
            sharpness_source: str = "luminance") -> dict[str, Any]:
    timing: dict[str, int] = {}
    t0 = time.monotonic()

    decoded = decode_measurement(path, scale)
    timing["decode"] = _ms(t0)

    # --- Frame sharpness + exposure ----------------------------------------
    t = time.monotonic()
    surface = decoded.luminance
    if sharpness_source == "cfa":
        # The design-03 §3.4 question, finally measurable: gradient energy on
        # the raw green plane, demosaic-invented detail excluded.
        cfa = green_plane(path)
        if cfa is not None:
            surface = cfa
    tiles = tile_map(surface)
    hi, lo = clipping(decoded.luminance)  # clipping is a viewing-space stat
    frame: dict[str, Any] = {
        "sharpness_tiles": tiles.tiles,
        "sharpness_max": tiles.max,
        "sharpness_mean": tiles.mean,
        "clipped_hi": hi,
        "clipped_lo": lo,
        "horizon_angle": None,
        "exposure_bias": None,  # probe's job; Swift emits null here too
    }
    timing["sharpness"] = _ms(t)

    # --- Horizon (classical, non-neural by design — doc 13 §1.5) ------------
    t = time.monotonic()
    from .horizon import horizon_angle

    frame["horizon_angle"] = horizon_angle(decoded.luminance)
    timing["horizon"] = _ms(t)

    # --- Model-backed passes -------------------------------------------------
    t = time.monotonic()
    from .faces import detect_faces

    faces = detect_faces(path, decoded, frame_max=tiles.max)
    timing["faces"] = _ms(t)

    t = time.monotonic()
    from .embedding import scene_embedding

    embedding, embedding_dim = scene_embedding(decoded)
    timing["embedding"] = _ms(t)

    t = time.monotonic()
    from .saliency import attention_bbox

    saliency_box = attention_bbox(decoded)
    timing["saliency"] = _ms(t)

    # "vision" for rough Swift comparability in the A/B timing report.
    timing["vision"] = timing["faces"] + timing["embedding"] + timing["saliency"]

    from .cli import engine_version

    out: dict[str, Any] = {
        "path": str(path),
        "decode_mode": decoded.mode
        + ("+cfa" if sharpness_source == "cfa" and surface is not decoded.luminance
           else ""),
        "engine_version": engine_version(),
        "frame": frame,
        "saliency": {"attention_bbox": saliency_box} if saliency_box else None,
        "faces": faces,
        "embedding": embedding,
        "embedding_dim": embedding_dim,
        "timing_ms": timing,
    }
    return prune_nulls(out)


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


__all__ = ["analyze", "Decoded"]
