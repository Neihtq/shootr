"""Horizon angle — classical line detection, deliberately non-neural
(design 13 §1.5: a model here adds opacity, not accuracy).

Dominant near-horizontal line via Canny + probabilistic Hough, angle as the
length-weighted median of candidates within ±25° of horizontal. Abstains
(None) when nothing near-horizontal dominates — a portrait or dance-floor
shot has no horizon, and null ≠ 0: reporting 0° would claim "perfectly level"
(design 04 §5).

Convention matches VNDetectHorizonRequest as the engine consumes it: degrees,
counter-clockwise positive; flags.py only uses abs(angle).
"""

from __future__ import annotations

import math

import numpy as np

MAX_TILT_DEG = 25.0     # beyond this it isn't a horizon, it's a composition
MIN_TOTAL_LENGTH = 0.5  # candidate lines must sum to ≥ half the image width


def horizon_angle(luminance: np.ndarray) -> float | None:
    import cv2

    h, w = luminance.shape
    if w < 64 or h < 64:
        return None
    # Downscale for speed — angle estimation doesn't need resolution.
    scale = 512 / max(w, h)
    if scale < 1.0:
        img = cv2.resize(luminance, (round(w * scale), round(h * scale)),
                         interpolation=cv2.INTER_AREA)
    else:
        img = luminance
    ih, iw = img.shape

    edges = cv2.Canny(img, 50, 150)
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180, threshold=60,
                            minLineLength=iw // 5, maxLineGap=iw // 20)
    if lines is None:
        return None

    candidates: list[tuple[float, float]] = []  # (angle_deg, length)
    for (x1, y1, x2, y2) in np.asarray(lines).reshape(-1, 4):
        dx, dy = float(x2 - x1), float(y2 - y1)
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        # Image y grows downward; horizon convention is CCW-positive.
        angle = math.degrees(math.atan2(-dy, dx))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        if abs(angle) <= MAX_TILT_DEG:
            candidates.append((angle, length))

    if not candidates:
        return None
    total = sum(length for _, length in candidates)
    if total < iw * MIN_TOTAL_LENGTH:
        return None  # no dominant horizontal structure — abstain

    # Length-weighted median: robust to a few slanted outliers.
    candidates.sort(key=lambda c: c[0])
    acc = 0.0
    for angle, length in candidates:
        acc += length
        if acc >= total / 2:
            return round(angle, 2)
    return round(candidates[-1][0], 2)
