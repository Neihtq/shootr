"""RAF metadata extraction — Fuji's container is not TIFF at the top level.

Measured on real files (X-T50, X-E5 samples, 2026-08-30): `exifread` returns
nothing for a `.RAF`, so the Python analyzer's probe failed on every Fuji
file while Sony ARW worked. Same class of problem as CR3, different fix.

RAF layout (fixed-offset header, big-endian, confirmed against samples):

    0x00  16B  "FUJIFILMCCD-RAW "
    0x10   4B  format version ("0201")
    0x14   8B  camera serial
    0x1C  32B  camera model, null-padded ("X-T50")
    0x54   4B  embedded-JPEG offset
    0x58   4B  embedded-JPEG length
    0x5C…      CFA header / CFA offsets and lengths

The embedded JPEG carries a complete Exif APP1 segment, so slicing it out
and handing it to exifread yields the same tags a JPEG would. Only the
declared slice is read — never the multi-tens-of-MB CFA payload.

One trap the samples exposed: that Exif describes the **preview** (4416×2944
on an X-T50), not the frame (7728×5152). Real dimensions live in the CFA
header's tag directory, so `raw_dimensions` reads those — otherwise the
Python analyzer would disagree with the Swift helper on every Fuji file.
"""

from __future__ import annotations

import struct
from pathlib import Path

_MAGIC = b"FUJIFILMCCD-RAW "
_JPEG_PTR = 0x54
_CFA_HDR_PTR = 0x5C
_MAX_JPEG = 1 << 25  # 32 MB — previews are a few MB; caps a corrupt field
_MAX_CFA_HDR = 1 << 20
# CFA-header tag carrying (height, width) of the output frame. 0x0113/0x0119
# repeat it and 0x0100 is the sensor incl. masked margins — verified equal /
# larger respectively on X-T50 and X-E5 samples.
_TAG_OUTPUT_SIZE = 0x0111


def camera_model(path: Path) -> str | None:
    """Model string from the RAF header itself (fallback when Exif lacks it)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(0x3C)
    except OSError:
        return None
    if not head.startswith(_MAGIC):
        return None
    return head[0x1C:0x3C].split(b"\0", 1)[0].decode("ascii", "replace") \
        or None


def raw_dimensions(path: Path) -> tuple[int, int] | None:
    """(width, height) of the actual frame, from the CFA header's tag
    directory. None if the container or the tag is unreadable — callers then
    keep whatever the preview Exif said rather than inventing a size."""
    try:
        with path.open("rb") as fh:
            head = fh.read(_CFA_HDR_PTR + 8)
            if len(head) < _CFA_HDR_PTR + 8 or not head.startswith(_MAGIC):
                return None
            offset, length = struct.unpack_from(">II", head, _CFA_HDR_PTR)
            if not (0 < length <= _MAX_CFA_HDR):
                return None
            fh.seek(offset)
            hdr = fh.read(min(length, _MAX_CFA_HDR))
    except OSError:
        return None
    if len(hdr) < 4:
        return None
    count = struct.unpack_from(">I", hdr, 0)[0]
    pos = 4
    for _ in range(min(count, 256)):
        if pos + 4 > len(hdr):
            return None
        tag, size = struct.unpack_from(">HH", hdr, pos)
        if tag == _TAG_OUTPUT_SIZE and size == 4 and pos + 8 <= len(hdr):
            height, width = struct.unpack_from(">HH", hdr, pos + 4)
            return (width, height) if width and height else None
        pos += 4 + size
    return None


def extract_jpeg(path: Path) -> bytes | None:
    """The embedded Exif-bearing JPEG, or None if this isn't a readable RAF."""
    try:
        with path.open("rb") as fh:
            head = fh.read(_JPEG_PTR + 8)
            if len(head) < _JPEG_PTR + 8 or not head.startswith(_MAGIC):
                return None
            offset, length = struct.unpack_from(">II", head, _JPEG_PTR)
            if not (0 < length <= _MAX_JPEG) or offset < _JPEG_PTR:
                return None
            fh.seek(offset)
            blob = fh.read(length)
    except OSError:
        return None
    # A valid slice starts with SOI; anything else means the offsets lied.
    return blob if blob[:2] == b"\xff\xd8" else None
