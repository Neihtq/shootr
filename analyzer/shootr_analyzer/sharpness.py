"""Tenengrad sharpness — numeric port of helper/Sources/ShootrKit/Sharpness.swift.

The two analyzers must agree on this math or the A/B comparison measures the
port, not the decode. Same Sobel kernels, same interior-only iteration, same
normalization sum/n/(4·255)² — validated by running the Swift selftest's
synthetic patterns through both (tests/test_sharpness.py, selftest.py).

Vectorized with numpy but kept semantically identical: mean squared gradient
magnitude over the (w-2)×(h-2) interior.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TILE_GRID = 16


def tenengrad(pixels: np.ndarray) -> float:
    """Mean squared Sobel gradient magnitude, normalized to a 0..1-ish range.
    `pixels` is a 2-D uint8 array. Absolute numbers are meaningless; only
    ratios are diagnostic (design 03 §3.1)."""
    h, w = pixels.shape
    if w <= 2 or h <= 2:
        return 0.0
    p = pixels.astype(np.float64)
    # 3×3 Sobel via shifted views over the interior — matches the Swift
    # loop's indexing exactly (no border padding, no cv2 border modes).
    a = p[:-2, :-2]; b = p[:-2, 1:-1]; c = p[:-2, 2:]
    d = p[1:-1, :-2];                  f = p[1:-1, 2:]
    g = p[2:, :-2];  hh = p[2:, 1:-1]; i = p[2:, 2:]
    gx = (c + 2 * f + i) - (a + 2 * d + g)
    gy = (g + 2 * hh + i) - (a + 2 * b + c)
    total = float(np.sum(gx * gx + gy * gy))
    n = float((w - 2) * (h - 2))
    return total / n / (4.0 * 255 * 255)


@dataclass
class TileMap:
    tiles: list[list[float]]  # 16×16, row-major
    max: float
    mean: float


def tile_map(pixels: np.ndarray, grid: int = TILE_GRID) -> TileMap:
    """16×16 tile grid (design 03 §3.3): normalization denominator, landscape
    focus-plane detection, motion-blur detection. Tiles are cropped views of
    size (h//grid, w//grid), same truncation as the Swift version — trailing
    rows/columns beyond grid*tile are ignored by both."""
    h, w = pixels.shape
    tw, th = w // grid, h // grid
    if tw <= 2 or th <= 2:
        zero = [[0.0] * grid for _ in range(grid)]
        return TileMap(tiles=zero, max=0.0, mean=0.0)
    tiles = [[0.0] * grid for _ in range(grid)]
    max_v = 0.0
    total = 0.0
    for ty in range(grid):
        for tx in range(grid):
            v = tenengrad(pixels[ty * th:(ty + 1) * th, tx * tw:(tx + 1) * tw])
            tiles[ty][tx] = v
            max_v = max(max_v, v)
            total += v
    return TileMap(tiles=tiles, max=max_v, mean=total / (grid * grid))


def clipping(pixels: np.ndarray) -> tuple[float, float]:
    """Fraction of pixels at the rails — same thresholds as Analyze.swift
    (>=254 high, <=1 low)."""
    n = float(pixels.size)
    hi = float(np.count_nonzero(pixels >= 254)) / n
    lo = float(np.count_nonzero(pixels <= 1)) / n
    return hi, lo
