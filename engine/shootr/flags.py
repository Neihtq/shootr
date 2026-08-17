"""Composition flag detectors (design 04 §2.4).

Detectors that state facts — never a learned score. Each consumes analysis
data (face bboxes, saliency, horizon) and emits flag strings, soft ones with
a numeric suffix ("subject_near_edge:0.04"). The scorer maps them to
individually visible penalties; the user weights them.

Coordinates are Vision-normalized [x, y, w, h], origin bottom-left, 0..1.
"""

from __future__ import annotations

EDGE_EPS = 0.005  # bbox touching frame edge within this = clipped
NEAR_EDGE_PCT = 0.05  # subject centroid closer than this to an edge
HEADROOM_MIN = 0.01  # top margin below this = no_headroom
HORIZON_TILT_DEG = 1.0  # flag beyond this; landscape treats it as a defect
YAW_LEAD_ROOM = 0.25  # |yaw| radians beyond which lead room matters


def detect_flags(
    faces: list[dict],
    primary_idx: int | None,
    saliency_bbox: list[float] | None,
    horizon_angle: float | None,
) -> list[str]:
    flags: list[str] = []
    primary = None
    if primary_idx is not None:
        primary = next((f for f in faces if f.get("idx") == primary_idx), None)

    for f in faces:
        if _clipped(f["bbox"]):
            flags.append("face_clipped")
            break  # one flag per defect kind; evidence names the face in UI

    subject_bbox = (primary or {}).get("bbox") or saliency_bbox
    if subject_bbox:
        d = _edge_distance(subject_bbox)
        if d < NEAR_EDGE_PCT:
            flags.append(f"subject_near_edge:{d:.2f}")
        flags.append(f"thirds_distance:{_thirds_distance(subject_bbox):.2f}")

    if primary:
        x, y, w, h = primary["bbox"]
        if y + h > 1.0 - HEADROOM_MIN:
            flags.append("no_headroom")
        yaw = primary.get("yaw")
        if yaw is not None and abs(yaw) > YAW_LEAD_ROOM:
            # Facing toward the NEAR edge = looking out of frame.
            cx = x + w / 2
            facing_right = yaw > 0
            if (facing_right and cx > 0.5) or (not facing_right and cx < 0.5):
                flags.append("lead_room_inverted")

    if horizon_angle is not None and abs(horizon_angle) > HORIZON_TILT_DEG:
        flags.append(f"horizon_tilt:{horizon_angle:.1f}")

    return flags


def _clipped(bbox: list[float]) -> bool:
    x, y, w, h = bbox
    return (x < EDGE_EPS or y < EDGE_EPS
            or x + w > 1.0 - EDGE_EPS or y + h > 1.0 - EDGE_EPS)


def _edge_distance(bbox: list[float]) -> float:
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    return min(cx, cy, 1.0 - cx, 1.0 - cy)


def _thirds_distance(bbox: list[float]) -> float:
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    return min(
        ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
        for tx in (1 / 3, 2 / 3)
        for ty in (1 / 3, 2 / 3)
    )
