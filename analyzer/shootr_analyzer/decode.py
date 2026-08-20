"""RAW decode via rawpy/libraw — the two paths of design 03 §2.

THE critical correctness rule carries over verbatim: the measurement decode
must not measure the decoder. libraw has no hidden sharpening, but it does
have auto-brightening, camera white balance, and gamma — all off (or linear)
for measurement. Unlike CIRAWFilter this is deterministic across OS updates,
which is half the reason design 13 picked it.

Measurement bonus over Core Image: direct CFA access (`raw_image_visible` +
`raw_colors_visible`) — the green-plane sharpness question from design 03
§3.4 is finally measurable without vendor-specific byte parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

RAW_SUFFIXES = {".cr2", ".cr3", ".arw", ".raf", ".dng", ".nef", ".orf", ".rw2"}


class DecodeUnreadable(RuntimeError):
    pass


@dataclass
class Decoded:
    luminance: np.ndarray  # 2-D uint8 — the measurement surface
    rgb: np.ndarray        # H×W×3 uint8, same geometry as luminance
    mode: str              # "rawpy-scaled" | "rawpy-full" | "jpeg"
    width: int             # of the decoded (possibly scaled) image
    height: int

    def model_rgb(self) -> np.ndarray:
        """Input for semantic models (embedding/faces/saliency). The
        measurement decode is linear and un-white-balanced — correct for
        gradients, dim and green for a network trained on sRGB photos. Cheap
        per-pixel correction, NO second demosaic: gray-world WB + sRGB-ish
        gamma. Deterministic, platform-independent, and consistent across
        the library — which is what embedding distances actually require."""
        if self.mode == "jpeg":
            return self.rgb  # already display-space
        lin = self.rgb.astype(np.float32) / 255.0
        means = lin.reshape(-1, 3).mean(axis=0)
        gray = float(means.mean()) or 1.0
        gains = gray / np.maximum(means, 1e-4)
        lin = np.clip(lin * gains, 0.0, 1.0)
        return (np.power(lin, 1 / 2.2) * 255.0).astype(np.uint8)


def _is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_SUFFIXES


def decode_measurement(path: Path, scale: float) -> Decoded:
    """Enhancement-free luminance for gradient math. `half_size` decodes each
    2×2 CFA cell to one pixel — cheap and alias-free, the rawpy analogue of
    CIRAWFilter's scaleFactor 0.5. Scales other than 0.5/1.0 resample after
    a half or full decode; the measurement surface never upsamples."""
    if not _is_raw(path):
        return _decode_jpeg(path, scale)
    import rawpy  # deferred: heavy import, and probe/version never need it

    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                half_size=scale <= 0.5,
                use_camera_wb=False,
                use_auto_wb=False,
                no_auto_bright=True,
                gamma=(1, 1),          # linear — measurement, not viewing
                output_bps=8,
                # EXIF orientation IS applied (libraw default): CIRAWFilter
                # orients too, and detectors aren't rotation-invariant — a
                # portrait-orientation CR3 with sideways faces detects
                # nothing (observed: SCRFD max score 0.06 on an orientation=8
                # file). "Geometry must not shift" (design 03 §2) is about
                # lens correction, which stays off.
            )
    except Exception as exc:  # rawpy raises LibRawError subclasses + OSError
        raise DecodeUnreadable(f"cannot decode: {path}") from exc

    rgb = _rescale_rgb(rgb, scale, half_decoded=scale <= 0.5)
    lum = _to_luminance(rgb)
    h, w = lum.shape
    return Decoded(luminance=lum, rgb=rgb,
                   mode="rawpy-full" if scale >= 1.0 else "rawpy-scaled",
                   width=w, height=h)


def decode_display(path: Path, size: int) -> np.ndarray:
    """Display decode — camera WB, auto-bright, sRGB gamma; the best rendering
    libraw offers. Returns RGB uint8 with the long edge <= size. On macOS the
    engine still prefers CIRAWFilter for display (design 13 §2.2); this path
    is what Windows/Linux thumbnails are made of."""
    if not _is_raw(path):
        rgb = _read_jpeg_rgb(path)
    else:
        import rawpy

        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        except Exception as exc:
            raise DecodeUnreadable(f"cannot decode: {path}") from exc
    h, w = rgb.shape[:2]
    s = min(1.0, size / max(w, h))
    if s < 1.0:
        import cv2

        rgb = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))),
                         interpolation=cv2.INTER_AREA)
    return rgb


def green_plane(path: Path) -> np.ndarray | None:
    """The raw CFA green plane, no demosaic — the cleanest focus signal
    (design 03 §3.4). Returns a 2-D uint8 array of green-site values (half
    lattice collapsed for Bayer; X-Trans handled by the same mask since
    raw_colors marks green sites regardless of pattern). None for non-RAW."""
    if not _is_raw(path):
        return None
    import rawpy

    try:
        with rawpy.imread(str(path)) as raw:
            cfa = raw.raw_image_visible
            colors = raw.raw_colors_visible
            # libraw color indices: 0=R, 1=G, 2=B, 3=G2. Both greens.
            mask = (colors == 1) | (colors == 3)
            if not mask.any():
                return None
            # Collapse to a dense array: every Bayer row has greens at
            # alternating x, so reshaping by row-counts is uneven for
            # X-Trans. Simplest dense form that preserves local gradients:
            # zero the non-green sites and take 2×2 max-pool — adjacent
            # green sites survive, spacing stays uniform.
            g = np.where(mask, cfa, 0).astype(np.float32)
            h, w = g.shape
            h2, w2 = h - h % 2, w - w % 2
            pooled = g[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2).max(axis=(1, 3))
            white = float(raw.white_level) or 65535.0
            return np.clip(pooled / white * 255.0, 0, 255).astype(np.uint8)
    except Exception:  # noqa: BLE001 — CFA path is optional, never fatal
        return None


# ---------------------------------------------------------------------------


def _to_luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec.601 luma — mirrors CIContext's grayscale render closely enough for
    ratio-based metrics (absolute values are non-diagnostic by design)."""
    lum = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2])
    return np.clip(lum, 0, 255).astype(np.uint8)


def _rescale_rgb(rgb: np.ndarray, scale: float,
                 half_decoded: bool) -> np.ndarray:
    effective = scale * (2.0 if half_decoded else 1.0)  # half decode did 0.5
    if effective >= 1.0 - 1e-6:
        return rgb  # never upsample a measurement surface
    import cv2

    h, w = rgb.shape[:2]
    return cv2.resize(rgb, (max(1, round(w * effective)),
                            max(1, round(h * effective))),
                      interpolation=cv2.INTER_AREA)


def _decode_jpeg(path: Path, scale: float) -> Decoded:
    rgb = _read_jpeg_rgb(path)
    if scale < 1.0:
        rgb = _rescale_rgb(rgb, scale, half_decoded=False)
    lum = _to_luminance(rgb)
    h, w = lum.shape
    return Decoded(luminance=lum, rgb=rgb, mode="jpeg", width=w, height=h)


def _read_jpeg_rgb(path: Path) -> np.ndarray:
    from PIL import Image

    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB"))
    except Exception as exc:
        raise DecodeUnreadable(f"cannot decode: {path}") from exc
