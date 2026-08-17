"""Quality scoring (docs/design/04-quality-scoring.md).

Pure functions from measurements to an evidence record — no I/O, instantly
recomputable (the Analysis/Score split, design 01). Emits a decomposed record,
never a bare number (design 04 §1).

The invariant that owns this module (design 04 §5): inapplicable or abstained
metrics are ``None``, never 0, and their weight is redistributed across the
applicable metrics. A landscape has no eyes; zeroing eye_focus would rank
every landscape as terrible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Input shapes — mirror the analysis JSONL (design 03 §4) / DB rows (design 01)


@dataclass(frozen=True)
class Eye:
    sharp_norm: float | None  # eye HF energy / sharpest frame tile
    open: float | None  # 0..1; None = detector abstained/unavailable


@dataclass(frozen=True)
class FaceMeasurement:
    idx: int
    bbox: tuple[float, float, float, float]  # normalized [x, y, w, h]
    yaw: float | None = None
    capture_quality: float | None = None
    left: Eye = field(default_factory=lambda: Eye(None, None))
    right: Eye = field(default_factory=lambda: Eye(None, None))


@dataclass(frozen=True)
class FrameMeasurement:
    sharpness_max: float | None = None
    sharpness_mean: float | None = None
    sharpness_tiles: list[list[float]] | None = None  # 16x16 Tenengrad grid
    clipped_hi: float | None = None
    clipped_lo: float | None = None
    horizon_angle: float | None = None
    exposure_bias: float | None = None


@dataclass(frozen=True)
class Measurements:
    """Everything scoring may consume for one photo. All profile-independent."""

    frame: FrameMeasurement = field(default_factory=FrameMeasurement)
    faces: list[FaceMeasurement] = field(default_factory=list)
    saliency_bbox: tuple[float, float, float, float] | None = None
    composition_flags: list[str] = field(default_factory=list)
    in_bracket: bool = False  # suppresses exposure metric (design 04 §6)


# ---------------------------------------------------------------------------
# Profiles (design 04 §4.1). `moment` is a placeholder, NOT implemented — it is
# excluded here so street weight redistributes to the technical metrics; street
# ranking is deliberately weak and defers to the user (design 04 §4.2).

PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "portrait": {
        "eye_focus": 0.35, "eyes_open": 0.25, "sharpness": 0.15,
        "composition": 0.15, "face_quality": 0.10, "exposure": 0.05,
    },
    "event": {
        "eye_focus": 0.35, "eyes_open": 0.25, "sharpness": 0.15,
        "composition": 0.08, "face_quality": 0.10, "exposure": 0.07,
    },
    "landscape": {
        "sharpness": 0.45, "composition": 0.35, "exposure": 0.20,
    },
    "street": {
        "eye_focus": 0.10, "eyes_open": 0.05, "sharpness": 0.15,
        "composition": 0.05, "face_quality": 0.05, "exposure": 0.10,
    },
}

# Flag → penalty. Facts with user-visible individual penalties, never a learned
# score (design 04 §2.4). Soft flags carry a numeric suffix ("flag:0.04").
FLAG_PENALTIES: dict[str, float] = {
    "face_clipped": 0.5,
    "limb_cut_at_joint": 0.3,
    "no_headroom": 0.2,
    "lead_room_inverted": 0.15,
    "subject_near_edge": 0.1,
    "horizon_tilt": 0.2,
}


def weights_hash(profile: str) -> str:
    payload = json.dumps(
        {"profile": profile, "weights": PROFILE_WEIGHTS[profile],
         "penalties": FLAG_PENALTIES},
        sort_keys=True,
    )
    return "ev1-" + hashlib.sha256(payload.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Piecewise curves (design 04 §2.1/2.2 — calibration targets, refit in M2)


def _piecewise(x: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation through (input, score) breakpoints."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# Cliff behavior is intentional: focus is near-binary; a mis-focused portrait
# is unrecoverable, not "slightly worse" (design 04 §2.1).
EYE_FOCUS_CURVE = [(0.0, 0.0), (0.25, 0.2), (0.45, 0.6), (0.70, 1.0)]
# Steep through the partial-blink band — the most common real failure.
EYES_OPEN_CURVE = [(0.0, 0.0), (0.35, 0.1), (0.60, 0.4), (0.85, 1.0)]

# Whole frame soft → motion blur / shake, not a focus miss: eye normalization
# against a soft frame is meaningless (design 04 §2.1 guard).
MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS = 0.15
# Detector abstains beyond this |yaw| (radians): profile views have no
# reliable eye signal — abstain, don't guess (design 04 §2.2).
MAX_YAW_FOR_EYE_METRICS = 0.6


@dataclass(frozen=True)
class Component:
    value: float | None  # None = not applicable / abstained — NEVER 0
    evidence: dict


@dataclass(frozen=True)
class ScoreRecord:
    total: float
    components: dict[str, dict]  # name → {value, weight, contrib, evidence}
    flags: list[str]
    primary_subject: dict | None
    weights_hash: str

    def to_json(self) -> str:
        return json.dumps(
            {"total": self.total, "components": self.components,
             "flags": self.flags, "primary_subject": self.primary_subject,
             "weights_hash": self.weights_hash}
        )


# ---------------------------------------------------------------------------
# Primary subject (design 04 §3): wrong subject → confusingly wrong scores in
# group shots, so the choice is recorded with a `why` and must be inspectable.


def select_primary_subject(m: Measurements) -> tuple[FaceMeasurement | None, str]:
    if not m.faces:
        if m.saliency_bbox:
            return None, "saliency_peak_no_faces"
        return None, "frame_center_fallback"

    def area(f: FaceMeasurement) -> float:
        return f.bbox[2] * f.bbox[3]

    if m.saliency_bbox:
        sx = m.saliency_bbox[0] + m.saliency_bbox[2] / 2
        sy = m.saliency_bbox[1] + m.saliency_bbox[3] / 2
        near = [
            f for f in m.faces
            if abs(f.bbox[0] + f.bbox[2] / 2 - sx) < 0.25
            and abs(f.bbox[1] + f.bbox[3] / 2 - sy) < 0.25
        ]
        if near:
            return max(near, key=area), "largest_face_near_saliency_peak"
    return max(m.faces, key=area), "largest_face"


# ---------------------------------------------------------------------------
# Metrics — each returns Component(value=None) when it cannot honestly measure.


def _eye_focus(m: Measurements, face: FaceMeasurement | None) -> Component:
    if face is None:
        return Component(None, {"reason": "no_face"})
    if face.yaw is not None and abs(face.yaw) > MAX_YAW_FOR_EYE_METRICS:
        return Component(None, {"reason": "abstained_extreme_yaw", "yaw": face.yaw})
    sharps = {
        "left": face.left.sharp_norm,
        "right": face.right.sharp_norm,
    }
    measured = {k: v for k, v in sharps.items() if v is not None}
    if not measured:
        return Component(None, {"reason": "eyes_not_measured"})
    fmax = m.frame.sharpness_max
    if fmax is not None and fmax < MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS:
        # Route to motion blur (sharpness metric), don't report a focus miss.
        return Component(None, {"reason": "frame_soft_motion_blur",
                                "frame_sharpness_max": fmax})
    # max, not mean: the near eye in focus is correct technique at f/1.4;
    # averaging would penalize a properly focused photo (design 04 §2.1).
    best_eye = max(measured, key=measured.__getitem__)
    value = _piecewise(measured[best_eye], EYE_FOCUS_CURVE)
    return Component(value, {"eye": best_eye, "sharp_norm": measured[best_eye],
                             "per_eye": sharps})


def _eyes_open(face: FaceMeasurement | None) -> Component:
    if face is None:
        return Component(None, {"reason": "no_face"})
    if face.yaw is not None and abs(face.yaw) > MAX_YAW_FOR_EYE_METRICS:
        return Component(None, {"reason": "abstained_extreme_yaw", "yaw": face.yaw})
    opens = {"left": face.left.open, "right": face.right.open}
    measured = {k: v for k, v in opens.items() if v is not None}
    if not measured:
        return Component(None, {"reason": "detector_unavailable"})
    # min, not max: one closed eye ruins the frame (design 04 §2.2).
    worst = min(measured.values())
    return Component(_piecewise(worst, EYES_OPEN_CURVE),
                     {"open_l": opens["left"], "open_r": opens["right"]})


def _sharpness(frame: FrameMeasurement) -> Component:
    if frame.sharpness_mean is None or frame.sharpness_max is None:
        return Component(None, {"reason": "not_measured"})
    # Uniformly low → shake/motion blur; high variance → a sharp plane
    # exists, which is a normal shallow-DoF photo (design 04 §2.3).
    if frame.sharpness_max < MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS:
        return Component(0.0, {"diagnosis": "motion_blur_or_shake",
                               "sharpness_max": frame.sharpness_max})
    value = min(1.0, frame.sharpness_max)
    return Component(value, {"sharpness_max": frame.sharpness_max,
                             "sharpness_mean": frame.sharpness_mean})


def _composition(flags: list[str]) -> Component:
    penalty = 0.0
    applied: dict[str, float] = {}
    for flag in flags:
        base = flag.split(":", 1)[0]
        p = FLAG_PENALTIES.get(base)
        if p is not None:
            penalty += p
            applied[flag] = p
    return Component(max(0.0, 1.0 - penalty), {"penalties": applied})


def _face_quality(face: FaceMeasurement | None) -> Component:
    if face is None or face.capture_quality is None:
        return Component(None, {"reason": "no_face_or_not_measured"})
    return Component(face.capture_quality,
                     {"capture_quality": face.capture_quality})


def _exposure(m: Measurements) -> Component:
    if m.in_bracket:
        # The -2EV frame of an HDR set is SUPPOSED to be dark (design 04 §6).
        return Component(None, {"reason": "suppressed_in_bracket"})
    hi, lo = m.frame.clipped_hi, m.frame.clipped_lo
    if hi is None or lo is None:
        return Component(None, {"reason": "not_measured"})
    value = max(0.0, 1.0 - 10.0 * hi - 5.0 * lo)
    return Component(value, {"clipped_hi": hi, "clipped_lo": lo})


# ---------------------------------------------------------------------------
# Combination


def score(m: Measurements, profile: str) -> ScoreRecord:
    if profile not in PROFILE_WEIGHTS:
        raise ValueError(f"unknown profile: {profile!r}")
    weights = PROFILE_WEIGHTS[profile]

    face, why = select_primary_subject(m)

    computed: dict[str, Component] = {}
    if "eye_focus" in weights:
        computed["eye_focus"] = _eye_focus(m, face)
    if "eyes_open" in weights:
        computed["eyes_open"] = _eyes_open(face)
    if "sharpness" in weights:
        computed["sharpness"] = _sharpness(m.frame)
    if "composition" in weights:
        computed["composition"] = _composition(m.composition_flags)
    if "face_quality" in weights:
        computed["face_quality"] = _face_quality(face)
    if "exposure" in weights:
        computed["exposure"] = _exposure(m)

    # Null-redistribution (design 04 §5): weight of inapplicable metrics is
    # spread proportionally across the applicable ones.
    applicable = {k: c for k, c in computed.items() if c.value is not None}
    live_weight = sum(weights[k] for k in applicable)

    components: dict[str, dict] = {}
    total = 0.0
    for name, comp in computed.items():
        if comp.value is None:
            components[name] = {"value": None, "weight": weights[name],
                                "contrib": None, "evidence": comp.evidence}
            continue
        eff = weights[name] / live_weight if live_weight else 0.0
        contrib = comp.value * eff
        total += contrib
        components[name] = {"value": round(comp.value, 4),
                            "weight": round(eff, 4),
                            "contrib": round(contrib, 4),
                            "evidence": comp.evidence}

    # Group-shot signal (design 04 §2.2): non-primary faces blinking is
    # usually the reason to prefer another frame — flagged, not averaged in.
    flags = list(m.composition_flags)
    others_blinking = _count_other_blinking(m.faces, face)
    if others_blinking:
        flags.append(f"other_subject_blinking:{others_blinking}")

    primary = None
    if face is not None or m.faces or m.saliency_bbox:
        primary = {"face_idx": face.idx if face else None, "why": why}

    return ScoreRecord(
        total=round(total, 4),
        components=components,
        flags=flags,
        primary_subject=primary,
        weights_hash=weights_hash(profile),
    )


BLINK_THRESHOLD = 0.5  # below = that subject is blinking in this frame


def _count_other_blinking(faces: list[FaceMeasurement],
                          primary: FaceMeasurement | None) -> int:
    n = 0
    for f in faces:
        if primary is not None and f.idx == primary.idx:
            continue
        opens = [v for v in (f.left.open, f.right.open) if v is not None]
        if opens and min(opens) < BLINK_THRESHOLD:
            n += 1
    return n
