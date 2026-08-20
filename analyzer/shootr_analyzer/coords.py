"""Coordinate convention conversion — THE one place it happens.

The engine's consumers (flags.py headroom check, scoring's primary-subject
selection, both clients' overlay renderers) all assume the Vision convention:
**normalized [x, y, w, h] with origin at the BOTTOM-left**. Every detector this
analyzer uses (SCRFD, MediaPipe, BiRefNet) reports top-left pixel or top-left
normalized coordinates. Convert here, at the boundary, and nowhere else — a
flip applied twice or zero times is invisible in unit tests of the parts and
catastrophic for headroom/thirds scoring on real photos.
"""

from __future__ import annotations


def bbox_px_to_vision(x: float, y: float, w: float, h: float,
                      img_w: int, img_h: int) -> list[float]:
    """Top-left pixel bbox → Vision-normalized bottom-left [x, y, w, h]."""
    return [
        x / img_w,
        1.0 - (y + h) / img_h,  # bottom edge in top-left coords → y origin
        w / img_w,
        h / img_h,
    ]


def bbox_norm_to_vision(x: float, y: float, w: float, h: float) -> list[float]:
    """Top-left normalized bbox → Vision bottom-left [x, y, w, h]."""
    return [x, 1.0 - (y + h), w, h]


def point_px_to_vision(x: float, y: float,
                       img_w: int, img_h: int) -> tuple[float, float]:
    """Top-left pixel point → Vision-normalized bottom-left (x, y)."""
    return (x / img_w, 1.0 - y / img_h)


def clamp_bbox(b: list[float]) -> list[float]:
    """Clamp a normalized bbox into [0, 1] — detectors happily report boxes
    hanging off the frame edge, and downstream area math assumes containment."""
    x = min(1.0, max(0.0, b[0]))
    y = min(1.0, max(0.0, b[1]))
    w = min(1.0 - x, max(0.0, b[2]))
    h = min(1.0 - y, max(0.0, b[3]))
    return [x, y, w, h]
