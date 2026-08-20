"""EXIF probe — no pixel decode (design 02 §2 stage 4).

Emits the same shape as the Swift ProbeOut (helper/Sources/ShootrKit/
Probe.swift), including its hard-won vendor quirks:
- subsec zero-padded/truncated to 3 digits (burst ordering depends on it),
- the CR3 ISO fallback chain: ISOSpeedRatings → ISOSpeed →
  RecommendedExposureIndex (Canon leaves the first empty on CR3 — verified
  against real files in the earlier session).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import exifread


def probe(path: Path) -> dict[str, Any] | None:
    try:
        tags = _read_tags(path)
    except Exception:  # noqa: BLE001 — probe failure is a per-file event
        return None
    if not tags:
        # EXIF-less files (edited/exported JPEGs) still probe: ImageIO
        # reports pixel dimensions regardless of EXIF, so parity requires
        # the same here — dimensions from the image header, rest absent.
        dims = _header_dimensions(path)
        if dims is None:
            return None
        return {"path": str(path), "width": dims[0], "height": dims[1]}

    out: dict[str, Any] = {"path": str(path)}

    if dt := _s(tags, "EXIF DateTimeOriginal"):
        out["captured_at"] = normalize_exif_date(dt)
    if ss := _s(tags, "EXIF SubSecTimeOriginal"):
        out["subsec"] = _subsec(ss)
    out["camera_model"] = _s(tags, "Image Model")
    out["lens_model"] = _s(tags, "EXIF LensModel")
    out["iso"] = (
        _i(tags, "EXIF ISOSpeedRatings")
        or _i(tags, "EXIF ISOSpeed")
        or _i(tags, "EXIF RecommendedExposureIndex")
    )
    out["shutter"] = _f(tags, "EXIF ExposureTime")
    out["aperture"] = _f(tags, "EXIF FNumber")
    out["focal_length"] = _f(tags, "EXIF FocalLength")
    out["exposure_bias"] = _f(tags, "EXIF ExposureBiasValue")
    out["orientation"] = _i(tags, "Image Orientation")
    out["width"] = _i(tags, "EXIF ExifImageWidth") or _i(tags, "Image ImageWidth")
    out["height"] = (_i(tags, "EXIF ExifImageLength")
                     or _i(tags, "Image ImageLength"))
    if not out.get("width") or not out.get("height"):
        if dims := _header_dimensions(path):
            out["width"], out["height"] = dims
    return {k: v for k, v in out.items() if v is not None}


def _header_dimensions(path: Path) -> tuple[int, int] | None:
    """Pixel dimensions from the image header (Pillow reads them lazily
    without decoding). RAW containers aren't Pillow-readable — for those,
    EXIF is the only source and its absence stays an absence."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None


def _read_tags(path: Path) -> dict:
    """TIFF-container RAWs (CR2/ARW/RAF/NEF/DNG/JPEG) parse directly; CR3 is
    ISO-BMFF, so its embedded CMT1/CMT2 TIFF blocks are parsed separately and
    merged (CMT1 = IFD0 'Image *' tags, CMT2 = ExifIFD → keys arrive as
    'Image *' too, so remap the ones probe() expects under 'EXIF *')."""
    import io

    if path.suffix.lower() == ".cr3":
        from .cr3 import extract_cmt

        cmt = extract_cmt(path)
        tags: dict = {}
        if b1 := cmt.get("CMT1"):
            tags.update(exifread.process_file(io.BytesIO(b1), details=False))
        if b2 := cmt.get("CMT2"):
            exif = exifread.process_file(io.BytesIO(b2), details=False)
            for k, v in exif.items():
                # ExifIFD parsed standalone shows up as IFD0 keys.
                tags[k.replace("Image ", "EXIF ", 1)] = v
        return tags
    with open(path, "rb") as fh:
        return exifread.process_file(fh, details=False)


def normalize_exif_date(raw: str) -> str:
    """EXIF "2026:06:14 15:22:08" → ISO-8601 "2026-06-14T15:22:08".
    Same tolerance as the Swift version: malformed input passes through."""
    parts = raw.split(" ", 1)
    if len(parts) != 2:
        return raw
    return parts[0].replace(":", "-") + "T" + parts[1]


def _subsec(raw: str) -> int | None:
    """First 3 digits, right-padded with zeros — '5' means 500 ms, not 5 ms
    (matches Probe.swift's prefix(3).padding(...))."""
    digits = raw.strip()[:3]
    if not digits.isdigit():
        return None
    return int(digits.ljust(3, "0"))


# --- tag coercion — exifread values arrive as IfdTag wrappers ---------------


def _s(tags: dict, key: str) -> str | None:
    tag = tags.get(key)
    return str(tag).strip() if tag is not None else None


def _i(tags: dict, key: str) -> int | None:
    tag = tags.get(key)
    if tag is None or not getattr(tag, "values", None):
        return None
    v = tag.values[0]
    # Orientation arrives as a printable string ("Horizontal (normal)") with
    # numeric .values; ISO arrays arrive as [int]. Ratios reduce.
    try:
        if isinstance(v, Fraction):
            return int(v)
        return int(v)
    except (TypeError, ValueError):
        return None


def _f(tags: dict, key: str) -> float | None:
    tag = tags.get(key)
    if tag is None or not getattr(tag, "values", None):
        return None
    v = tag.values[0]
    try:
        if isinstance(v, Fraction):
            return float(v)
        num = getattr(v, "num", None)
        den = getattr(v, "den", None)
        if num is not None and den:
            return num / den
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
