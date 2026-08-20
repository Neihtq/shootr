"""Pure-math self-checks — the same synthetic patterns as the Swift
SelfTest.swift, so `shootr-analyze selftest` and `shootr-analyze-py selftest`
verify the SAME orderings. If the two analyzers disagree here, the A/B on
real photos measures the port, not the photographs.
"""

from __future__ import annotations

import numpy as np

from .coords import bbox_px_to_vision
from .probe import normalize_exif_date
from .sharpness import tenengrad, tile_map


def run() -> list[str]:
    failures: list[str] = []

    def check(cond: bool, name: str) -> None:
        if not cond:
            failures.append(name)

    # --- Tenengrad (Swift parity) -------------------------------------------
    flat = np.full((64, 64), 128, dtype=np.uint8)
    check(tenengrad(flat) == 0, "flat field has zero gradient energy")

    w = h = 64
    xx, yy = np.meshgrid(np.arange(w), np.arange(h))
    edge = np.where(xx < w // 2, 0, 255).astype(np.uint8)
    ramp = (xx * 255 // (w - 1)).astype(np.uint8)
    fine = (((xx // 2) + (yy // 2)) % 2 * 255).astype(np.uint8)
    coarse = (((xx // 16) + (yy // 16)) % 2 * 255).astype(np.uint8)

    check(tenengrad(edge) > tenengrad(ramp) * 2, "hard edge beats soft ramp")
    check(tenengrad(fine) > tenengrad(coarse), "fine detail beats coarse")
    check(tenengrad(np.array([[1, 2]], dtype=np.uint8)) == 0,
          "degenerate size returns zero")

    # --- Tile map (Swift parity) --------------------------------------------
    W = H = 256
    px = np.full((H, W), 128, dtype=np.uint8)
    qx, qy = np.meshgrid(np.arange(W // 4), np.arange(H // 4))
    px[:H // 4, :W // 4] = (((qx // 2) + (qy // 2)) % 2 * 255).astype(np.uint8)
    m = tile_map(px)
    check(m.max > 0, "sharp quadrant produces nonzero max")
    check(m.mean < m.max / 4, "mean well below max for local sharpness")
    outside = any(
        m.tiles[ty][tx] > m.max / 2 and (tx >= 4 or ty >= 4)
        for ty in range(16) for tx in range(16))
    check(not outside, "sharp tiles localized to quadrant")

    soft = np.full((H, W), 100, dtype=np.uint8)
    sm = tile_map(soft)
    check(sm.max == 0 and sm.mean == 0,
          "uniformly flat map = motion-blur signature")

    # --- Coordinate flip — the silent-wrongness guard -------------------------
    # A face at the TOP of a 1000×1000 image must land near y≈1 in Vision
    # coords (bottom-left origin). Doubly-flipped or unflipped = headroom and
    # thirds scoring silently wrong on every photo.
    b = bbox_px_to_vision(100, 0, 200, 200, 1000, 1000)
    check(abs(b[1] - 0.8) < 1e-9, "top-of-frame face → Vision y = 0.8")
    b2 = bbox_px_to_vision(100, 800, 200, 200, 1000, 1000)
    check(abs(b2[1] - 0.0) < 1e-9, "bottom-of-frame face → Vision y = 0.0")

    # --- Probe date (Swift parity) --------------------------------------------
    check(normalize_exif_date("2026:06:14 15:22:08") == "2026-06-14T15:22:08",
          "EXIF date normalized to ISO-8601")
    check(normalize_exif_date("garbage") == "garbage",
          "malformed date passed through")

    return failures
