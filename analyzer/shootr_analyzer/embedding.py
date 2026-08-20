"""Scene embedding — DINOv2 with registers (ONNX), replacing
VNGenerateImageFeaturePrintRequest.

CLS-token output, L2-normalized, base64 float32 — the engine stores it as
embedding kind='scene' and unpacks with struct('<{dim}f'), so little-endian
float32 is part of the contract. Grouping thresholds are embedding-specific
(design 13 §4): distances from this embedding must be re-measured against real
shoots before any threshold tuned on Vision feature prints is trusted.
"""

from __future__ import annotations

import base64

import numpy as np

from .decode import Decoded

_INPUT = 224            # ViT-14 patch grid: 224 → 16×16 patches
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)  # ImageNet
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_session = None
_loaded = False


def scene_embedding(decoded: Decoded) -> tuple[str | None, int | None]:
    """(base64 float32, dim) or (None, None) when no model is available —
    grouping then treats the photo as maximally distant (never silently
    merged, grouping._dist's None handling)."""
    global _session, _loaded
    if not _loaded:
        from .models import load_session

        _session = load_session("scene_embedding")
        _loaded = True
    if _session is None:
        return None, None

    import cv2

    rgb = decoded.model_rgb()
    # Center-crop to square then resize: framing similarity should compare
    # the same field of view; anisotropic squash distorts composition.
    h, w = rgb.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    img = cv2.resize(rgb[y0:y0 + side, x0:x0 + side], (_INPUT, _INPUT),
                     interpolation=cv2.INTER_AREA)
    x = (img.astype(np.float32) / 255.0 - _MEAN) / _STD
    x = x.transpose(2, 0, 1)[None]  # NCHW

    name = _session.get_inputs()[0].name
    outputs = _session.run(None, {name: x})
    # onnx-community export: last_hidden_state [1, tokens, dim]; token 0 = CLS.
    out = outputs[0]
    vec = out[0, 0] if out.ndim == 3 else out[0]
    vec = vec.astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    # Little-endian float32 — matches struct.unpack in pipeline.group_shoot.
    return base64.b64encode(vec.astype("<f4").tobytes()).decode(), len(vec)
