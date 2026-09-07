"""Body pose for the cross-platform analyzer (design 03 §4 `pose`, 13 §2.1).

The Swift helper emits Vision joints; without this the cutover would silently
lose pose grouping (05 §4) and the limb-cut flag (04 §2.4). So MediaPipe's
pose landmarks are **renamed onto Vision's joint names** — the engine's
`shootr.pose` then consumes either analyzer's output unchanged, and the two
implementations only have to agree on measurements, never on derived vectors.

Interim by design: 13 §2.1 names ViTPose-L as the accuracy-first candidate.
MediaPipe Pose is the floor — already a dependency (the blink refiner uses
the same task API), no new model tier, and it emits exactly the joints the
pose vector needs. Swapping in ViTPose later changes this file only.

Coordinates match the contract: normalized, **bottom-left origin** (MediaPipe
is top-left, so y is flipped here — getting this wrong silently mirrors every
pose and every limb-cut verdict).
"""

from __future__ import annotations

from typing import Any

import numpy as np

# MediaPipe pose landmark index → Vision joint name. Only the joints the
# engine consumes (VECTOR_JOINTS + the cut-sensitive set) are mapped; the
# other 20 landmarks (face detail, fingers, heels) carry no pose meaning we
# use. MediaPipe's left/right are the SUBJECT's, matching Vision's naming.
LANDMARK_TO_JOINT: dict[int, str] = {
    0: "head_joint",
    11: "left_shoulder_1_joint", 12: "right_shoulder_1_joint",
    13: "left_forearm_joint", 14: "right_forearm_joint",   # elbow
    15: "left_hand_joint", 16: "right_hand_joint",         # wrist
    23: "left_upLeg_joint", 24: "right_upLeg_joint",       # hip
    25: "left_leg_joint", 26: "right_leg_joint",           # knee
    27: "left_foot_joint", 28: "right_foot_joint",         # ankle
}

MAX_BODIES = 4

_landmarker: Any = None
_loaded = False


def _ensure_model() -> None:
    global _landmarker, _loaded
    if _loaded:
        return
    _loaded = True
    from .models import ensure, resolve

    spec = resolve("pose")
    if spec is None or not spec.active:
        return  # unpinned → no pose, and the engine abstains cleanly
    try:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        options = mp_vision.PoseLandmarkerOptions(
            # CPU delegate for the same reason as the face landmarker: the
            # Metal path aborts the process on macOS 26 / mediapipe 1.0.1,
            # and a SIGABRT mid-batch is what the crash boundary exists to
            # avoid provoking.
            base_options=mp_python.BaseOptions(
                model_asset_path=str(ensure(spec)),
                delegate=mp_python.BaseOptions.Delegate.CPU),
            num_poses=MAX_BODIES,
        )
        _landmarker = mp_vision.PoseLandmarker.create_from_options(options)
    except Exception:  # noqa: BLE001 — no landmarker → no pose, never a crash
        _landmarker = None


def detect_pose(rgb: np.ndarray) -> list[dict[str, Any]]:
    """[{joints: {name: [x, y, confidence]}, confidence: float}] per body.

    Empty when pose is unavailable — the contract treats a missing `pose` and
    an empty one the same way, and the engine abstains rather than inventing
    a vector.
    """
    _ensure_model()
    if _landmarker is None or rgb.size == 0:
        return []
    import mediapipe as mp

    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(rgb))
    try:
        result = _landmarker.detect(image)
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    for landmarks in (result.pose_landmarks or [])[:MAX_BODIES]:
        joints: dict[str, list[float]] = {}
        confs: list[float] = []
        for idx, name in LANDMARK_TO_JOINT.items():
            if idx >= len(landmarks):
                continue
            lm = landmarks[idx]
            # MediaPipe: presence/visibility in [0,1]; y is top-left origin.
            conf = float(getattr(lm, "visibility", 0.0) or 0.0)
            if conf <= 0:
                continue
            joints[name] = [round(float(lm.x), 5),
                            round(1.0 - float(lm.y), 5),  # → bottom-left
                            round(conf, 4)]
            confs.append(conf)
        if joints:
            out.append({"joints": joints,
                        "confidence": round(sum(confs) / len(confs), 4)})
    return out
