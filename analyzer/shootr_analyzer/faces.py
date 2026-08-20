"""Faces — SCRFD detection, MediaPipe blendshapes, two-tier eye sharpness,
ArcFace faceprint.

Replaces the Vision face stack (design 13 §2.1). Per-face flow mirrors
Analyze.swift's analyzeFace:
  1. SCRFD finds faces on the measurement decode (display-corrected RGB).
  2. MediaPipe FaceLandmarker runs on each face crop: eyeBlink blendshapes →
     eye-open (the purpose-built signal design 03 §5 wanted; eye_source
     "mediapipe_blendshapes"), facial transformation matrix → yaw/roll/pitch,
     eye landmark clusters → eye ROIs.
  3. Two-tier eye sharpness: the eye ROI is re-decoded at FULL scale and its
     Tenengrad energy ratioed against the sharpest frame tile — identical
     normalization to the Swift eyeSharpness (design 03 §3.1), so 'focus
     missed the eye' means the same thing in both analyzers.
  4. ArcFace embedding of the aligned face crop → faceprint (base64 f32).

All coordinates leave this module in Vision convention (coords.py).
Model-less operation degrades honestly: no detector → no faces; no
landmarker → faces with bbox/faceprint but null eyes (abstain ≠ 0).
"""

from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any

import numpy as np

from .coords import bbox_px_to_vision, clamp_bbox
from .decode import Decoded, decode_measurement
from .sharpness import tenengrad

DETECT_INPUT = 640
DETECT_THRESHOLD = 0.5
NMS_IOU = 0.4
MAX_FACES = 16                  # matches practical Vision behavior on groups
EYE_PAD = 0.5                   # pad eye ROI by 50% each side (Swift parity)
EYE_SHARP_CAP = 1.5             # >1 = eye sharper than any tile (Swift parity)

# MediaPipe FaceLandmarker mesh indices for the eye contours (the 6-point
# EAR-style ring per eye — enough for a tight ROI box).
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]

_detector = None
_landmarker = None
_face_id = None
_loaded = False


def detect_faces(path: Path, decoded: Decoded,
                 frame_max: float) -> list[dict[str, Any]]:
    _ensure_models()
    if _detector is None:
        return []

    rgb = decoded.model_rgb()
    boxes = _scrfd_detect(rgb)
    faces: list[dict[str, Any]] = []
    full_lum: np.ndarray | None = None  # lazy full-res decode, shared per photo

    for idx, (x, y, w, h, _score) in enumerate(boxes[:MAX_FACES]):
        crop = _crop(rgb, x, y, w, h, pad=0.25)
        mp_result = _landmark(crop) if _landmarker is not None else None

        eyes: dict[str, dict[str, float | None]] = {
            "l": {"sharp_norm": None, "open": None},
            "r": {"sharp_norm": None, "open": None},
        }
        roll = yaw = pitch = None

        if mp_result is not None:
            openness, angles, eye_rois = mp_result
            eyes["l"]["open"], eyes["r"]["open"] = openness
            yaw, roll, pitch = angles
            if frame_max > 0 and eye_rois:
                if full_lum is None:
                    full_lum = _full_luminance(path, decoded)
                if full_lum is not None:
                    fh, fw = full_lum.shape
                    ch, cw = crop.image.shape[:2]
                    for side, roi in eye_rois.items():
                        # ROI is in crop pixels → full-res pixels.
                        rx = (crop.x0 + roi[0] / cw * crop.w_px) / decoded.width
                        ry = (crop.y0 + roi[1] / ch * crop.h_px) / decoded.height
                        rw = roi[2] / cw * crop.w_px / decoded.width
                        rh = roi[3] / ch * crop.h_px / decoded.height
                        eyes[side]["sharp_norm"] = _eye_sharpness(
                            full_lum, rx, ry, rw, rh, frame_max)

        faces.append({
            "idx": idx,
            "bbox": clamp_bbox(bbox_px_to_vision(
                x, y, w, h, decoded.width, decoded.height)),
            "roll": roll,
            "yaw": yaw,
            "pitch": pitch,
            # Proxy until CR-FIQA is pinned (design 13 §2.1 deferred set):
            # detector confidence tracks pose/occlusion/blur well enough to
            # rank faces within one photo. Provenance in eye_source.
            "capture_quality": round(float(_score), 4),
            "eyes": eyes,
            "eye_source": "mediapipe_blendshapes" if mp_result is not None
                          else "none",
            "faceprint": _faceprint(crop.image),
        })
    return faces


# --- SCRFD ------------------------------------------------------------------


def _scrfd_detect(rgb: np.ndarray) -> list[tuple[float, float, float, float, float]]:
    """SCRFD det_10g: 640×640 letterboxed input; outputs score/bbox distances
    at strides 8/16/32, 2 anchors per cell. Returns (x, y, w, h, score) in
    top-left image pixels, NMS applied, sorted by score."""
    import cv2

    h, w = rgb.shape[:2]
    scale = DETECT_INPUT / max(h, w)
    nh, nw = round(h * scale), round(w * scale)
    resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((DETECT_INPUT, DETECT_INPUT, 3), dtype=np.uint8)
    canvas[:nh, :nw] = resized
    blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]

    name = _detector.get_inputs()[0].name
    outputs = _detector.run(None, {name: blob})

    # det_10g output order: scores(8,16,32), bboxes(8,16,32), kps(8,16,32).
    strides = (8, 16, 32)
    dets: list[tuple[float, float, float, float, float]] = []
    for i, stride in enumerate(strides):
        scores = outputs[i].reshape(-1)
        bbox_d = outputs[i + 3].reshape(-1, 4) * stride
        grid = DETECT_INPUT // stride
        # 2 anchors per cell, row-major grid.
        anchors = np.stack(np.meshgrid(np.arange(grid), np.arange(grid)),
                           axis=-1).reshape(-1, 2)
        anchors = np.repeat(anchors, 2, axis=0).astype(np.float32) * stride
        keep = scores >= DETECT_THRESHOLD
        for (ax, ay), (l, t, r, b), s in zip(
                anchors[keep], bbox_d[keep], scores[keep]):
            x0, y0 = (ax - l) / scale, (ay - t) / scale
            x1, y1 = (ax + r) / scale, (ay + b) / scale
            dets.append((x0, y0, x1 - x0, y1 - y0, float(s)))

    return _nms(dets)


def _nms(dets: list[tuple[float, float, float, float, float]]):
    dets = sorted(dets, key=lambda d: -d[4])
    kept: list[tuple[float, float, float, float, float]] = []
    for d in dets:
        if all(_iou(d, k) < NMS_IOU for k in kept):
            kept.append(d)
    return kept


def _iou(a, b) -> float:
    ax0, ay0, aw, ah, _ = a
    bx0, by0, bw, bh, _ = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


# --- MediaPipe landmarker -----------------------------------------------------


class _Crop:
    def __init__(self, image: np.ndarray, x0: float, y0: float,
                 w_px: float, h_px: float):
        self.image = image
        self.x0 = x0
        self.y0 = y0
        self.w_px = w_px
        self.h_px = h_px


def _crop(rgb: np.ndarray, x: float, y: float, w: float, h: float,
          pad: float) -> _Crop:
    ih, iw = rgb.shape[:2]
    x0 = max(0, int(x - w * pad))
    y0 = max(0, int(y - h * pad))
    x1 = min(iw, int(x + w * (1 + pad)))
    y1 = min(ih, int(y + h * (1 + pad)))
    return _Crop(rgb[y0:y1, x0:x1], x0, y0, x1 - x0, y1 - y0)


def _landmark(crop: _Crop):
    """(openness (l, r), angles (yaw, roll, pitch) rad, eye ROIs in crop px).
    Returns None when MediaPipe finds no face in the crop — the detector saw
    one, the landmarker didn't; abstain rather than fabricate."""
    import mediapipe as mp

    if crop.image.size == 0:
        return None
    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(crop.image))
    result = _landmarker.detect(image)
    if not result.face_landmarks:
        return None

    # Blendshapes: eyeBlinkLeft/Right in [0,1], 1 = fully closed.
    open_l = open_r = None
    if result.face_blendshapes:
        shapes = {c.category_name: c.score
                  for c in result.face_blendshapes[0]}
        if "eyeBlinkLeft" in shapes:
            open_l = round(1.0 - shapes["eyeBlinkLeft"], 4)
        if "eyeBlinkRight" in shapes:
            open_r = round(1.0 - shapes["eyeBlinkRight"], 4)

    yaw = roll = pitch = None
    if result.facial_transformation_matrixes:
        m = np.asarray(result.facial_transformation_matrixes[0])
        # ZYX Euler from the rotation block; radians, Vision-comparable signs.
        yaw = math.atan2(-m[2, 0], math.hypot(m[0, 0], m[1, 0]))
        roll = math.atan2(m[1, 0], m[0, 0])
        pitch = math.atan2(m[2, 1], m[2, 2])

    lms = result.face_landmarks[0]
    ch, cw = crop.image.shape[:2]

    def roi(indices: list[int]) -> tuple[float, float, float, float]:
        xs = [lms[i].x * cw for i in indices]
        ys = [lms[i].y * ch for i in indices]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        w, h = x1 - x0, y1 - y0
        # Pad by 50% each side for gradient context (Swift eyeSharpness parity).
        return (x0 - w * EYE_PAD, y0 - h * EYE_PAD,
                w * (1 + 2 * EYE_PAD), h * (1 + 2 * EYE_PAD))

    # MediaPipe's "left eye" indices are the subject's left = image right;
    # the Swift helper keys by the LANDMARK region name, so keep the same
    # subject-relative naming for l/r.
    rois = {"l": roi(_LEFT_EYE), "r": roi(_RIGHT_EYE)}
    return (open_l, open_r), (yaw, roll, pitch), rois


# --- Two-tier eye sharpness ---------------------------------------------------


def _full_luminance(path: Path, decoded: Decoded) -> np.ndarray | None:
    """Tier 2: full-scale measurement decode, shared across faces of one
    photo (the Swift version re-decodes per eye; sharing is strictly cheaper
    and numerically identical)."""
    if decoded.mode == "rawpy-full":
        return decoded.luminance
    try:
        return decode_measurement(path, scale=1.0).luminance
    except Exception:  # noqa: BLE001 — sharpness then abstains
        return None


def _eye_sharpness(full_lum: np.ndarray, x: float, y: float,
                   w: float, h: float, frame_max: float) -> float | None:
    """Normalized-coordinate ROI → Tenengrad ratio vs sharpest frame tile.
    min size and cap match the Swift implementation."""
    fh, fw = full_lum.shape
    x0, y0 = max(0, int(x * fw)), max(0, int(y * fh))
    x1, y1 = min(fw, int((x + w) * fw)), min(fh, int((y + h) * fh))
    if x1 - x0 <= 8 or y1 - y0 <= 8:
        return None
    energy = tenengrad(full_lum[y0:y1, x0:x1])
    return round(min(EYE_SHARP_CAP, energy / frame_max), 4)


# --- Faceprint ----------------------------------------------------------------


def _faceprint(face_rgb: np.ndarray) -> str | None:
    """ArcFace embedding of the (unaligned) face crop, L2-normalized base64
    f32. Unaligned is a known accuracy tax vs 5-point alignment — recorded
    in doc 13 as a follow-up; clustering thresholds are conservative
    (PERSON_MERGE_DIST prefers split over merge) which tolerates it."""
    if _face_id is None or face_rgb.size == 0:
        return None
    import cv2

    img = cv2.resize(face_rgb, (112, 112), interpolation=cv2.INTER_AREA)
    blob = ((img.astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
    name = _face_id.get_inputs()[0].name
    vec = _face_id.run(None, {name: blob})[0][0].astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return base64.b64encode(vec.astype("<f4").tobytes()).decode()


# --- Model loading ------------------------------------------------------------


def _ensure_models() -> None:
    global _detector, _landmarker, _face_id, _loaded
    if _loaded:
        return
    _loaded = True
    from .models import ensure, load_session, resolve

    _detector = load_session("face_detect")
    _face_id = load_session("face_id")

    spec = resolve("blink")
    if spec is not None:
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            options = mp_vision.FaceLandmarkerOptions(
                # CPU delegate explicitly: the Metal path aborts the process
                # (DrishtiMetalHelper "Service is unavailable", observed on
                # macOS 26 / mediapipe 1.0.1) — and a SIGABRT in a batch is
                # exactly what the crash-boundary design exists to avoid
                # triggering ourselves. Blendshapes are tiny; CPU is fine.
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(ensure(spec)),
                    delegate=mp_python.BaseOptions.Delegate.CPU),
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                num_faces=1,  # one landmarker pass per SCRFD crop
            )
            _landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        except Exception:  # noqa: BLE001 — no landmarker → eyes abstain
            _landmarker = None
