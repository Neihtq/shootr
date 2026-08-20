"""CR3 metadata extraction — minimal ISO-BMFF walk.

CR3 is an ISO base-media container (not TIFF), so exifread can't read it
directly. Canon stores standard little-endian TIFF structures in CMT boxes
inside a vendor uuid box under moov:

    moov → uuid(85c0b687-820f-11e0-8111-f4ce462b6a48) → CMT1 (IFD0)
                                                      → CMT2 (ExifIFD)
                                                      → CMT3 (MakerNotes)
                                                      → CMT4 (GPS)

CMT1/CMT2 begin with a complete TIFF header ("II*\\0"), so each parses as a
standalone TIFF via exifread. This walker finds them without reading the
(multi-GB-scale) mdat: boxes are skipped by size, never loaded.
"""

from __future__ import annotations

import struct
from pathlib import Path

_CANON_UUID = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")
_MAX_CMT = 1 << 22  # 4 MB — metadata boxes are tens of KB; cap defends
                    # against a corrupt size field slurping the file


def extract_cmt(path: Path) -> dict[str, bytes]:
    """{"CMT1": tiff_bytes, "CMT2": ...} — empty dict if not a CR3."""
    out: dict[str, bytes] = {}
    with open(path, "rb") as fh:
        end = fh.seek(0, 2)
        fh.seek(0)
        _walk(fh, 0, end, out, depth=0)
    return out


def _walk(fh, start: int, end: int, out: dict[str, bytes], depth: int) -> None:
    if depth > 4:  # moov → uuid → CMTn is depth 2; anything deeper is noise
        return
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        payload = pos + 8
        if size == 1:  # 64-bit largesize
            size = struct.unpack(">Q", fh.read(8))[0]
            payload = pos + 16
        elif size == 0:  # box extends to EOF
            size = end - pos
        if size < 8 or pos + size > end:
            return  # corrupt size — stop, don't guess

        if kind == b"moov":
            _walk(fh, payload, pos + size, out, depth + 1)
        elif kind == b"uuid" and size >= 24:
            fh.seek(payload)
            if fh.read(16) == _CANON_UUID:
                _walk(fh, payload + 16, pos + size, out, depth + 1)
        elif kind in (b"CMT1", b"CMT2", b"CMT3", b"CMT4"):
            length = min(size - (payload - pos), _MAX_CMT)
            fh.seek(payload)
            out[kind.decode()] = fh.read(length)
        pos += size
