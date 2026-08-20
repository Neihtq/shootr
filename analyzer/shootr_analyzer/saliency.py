"""Subject saliency — BiRefNet segmentation → attention_bbox.

Replaces VNGenerateAttentionBasedSaliencyImageRequest, and per design 13 §2.1
upgrades on it: a real subject mask instead of a coarse attention heat blob.
The engine consumes only a bbox (scoring's primary-subject selection and the
thirds/headroom flags), so the mask reduces to its bounding box here.

Output: Vision-convention normalized [x, y, w, h], bottom-left origin
(coords.py). None when no model or no confident subject — absent, never a
full-frame guess.
"""

from __future__ import annotations

import numpy as np

from .coords import bbox_norm_to_vision, clamp_bbox
from .decode import Decoded

_INPUT = 1024        # BiRefNet-general native resolution
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_MASK_THRESHOLD = 0.5
_MIN_AREA = 0.005     # subject under 0.5% of frame = nothing salient

_session = None
_loaded = False


def attention_bbox(decoded: Decoded) -> list[float] | None:
    global _session, _loaded
    if not _loaded:
        from .models import load_session

        _session = load_session("saliency")
        _loaded = True
    if _session is None:
        return None

    import cv2

    rgb = decoded.model_rgb()
    h, w = rgb.shape[:2]
    img = cv2.resize(rgb, (_INPUT, _INPUT), interpolation=cv2.INTER_AREA)
    x = (img.astype(np.float32) / 255.0 - _MEAN) / _STD
    x = x.transpose(2, 0, 1)[None]

    name = _session.get_inputs()[0].name
    logits = _session.run(None, {name: x})[0]  # [1, 1, H, W]
    mask = 1.0 / (1.0 + np.exp(-logits[0, 0]))
    ys, xs = np.nonzero(mask > _MASK_THRESHOLD)
    if len(xs) == 0:
        return None
    mh, mw = mask.shape
    if len(xs) / (mh * mw) < _MIN_AREA:
        return None

    # Top-left normalized bbox in mask space == image space (both resized
    # from the full frame), then flipped to Vision convention.
    x0, x1 = xs.min() / mw, (xs.max() + 1) / mw
    y0, y1 = ys.min() / mh, (ys.max() + 1) / mh
    return clamp_bbox(bbox_norm_to_vision(x0, y0, x1 - x0, y1 - y0))
