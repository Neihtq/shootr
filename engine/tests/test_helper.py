"""Integration tests driving the built Swift helper binary.

Skipped when the helper isn't built (CI without a Swift toolchain). These
also stand in for Swift unit tests: neither swift-testing nor XCTest ships
with CLI-tools-only, so the helper exposes `selftest` and pytest drives it.
"""

import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from shootr.helper import (
    analyze_batch,
    helper_available,
    helper_path,
    probe_batch,
    swift_prober,
)

pytestmark = pytest.mark.skipif(
    not helper_available(), reason="Swift helper not built"
)


@pytest.fixture(scope="module")
def test_jpeg(tmp_path_factory) -> Path:
    """512×512 grey field with a sharp checkerboard center."""
    tmp = tmp_path_factory.mktemp("images")
    w = h = 512
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            if 192 <= x < 320 and 192 <= y < 320:
                v = 0 if ((x // 2) + (y // 2)) % 2 == 0 else 255
            else:
                v = 128
            row += bytes([v, v, v])
        rows.append(bytes(row))

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data))

    png = tmp / "test.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )
    jpg = tmp / "test.jpg"
    subprocess.run(
        ["sips", "-s", "format", "jpeg", str(png), "--out", str(jpg)],
        check=True, capture_output=True,
    )
    return jpg


def test_selftest_passes():
    """The helper's pure-math unit checks (Tenengrad, tile map, EAR)."""
    out = subprocess.run(
        [str(helper_path()), "selftest"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout
    assert json.loads(out.stdout.strip()) == {"status": "ok"}


def test_version_reports_engine_and_vision():
    out = subprocess.run(
        [str(helper_path()), "version"], capture_output=True, text=True
    )
    v = json.loads(out.stdout.strip())
    assert v["engine_version"]
    assert v["face_landmarks_revision"] == "3"


def test_probe_returns_dimensions(test_jpeg):
    results = list(probe_batch([test_jpeg]))
    assert len(results) == 1
    assert results[0]["width"] == 512 and results[0]["height"] == 512


def test_analyze_localizes_sharp_region(test_jpeg):
    """The measurement that everything downstream depends on: the sharp
    center region must appear in the center tiles of the map."""
    results = list(analyze_batch([test_jpeg], scale=1.0))
    assert len(results) == 1
    o = results[0]
    assert "error" not in o
    frame = o["frame"]
    tiles = frame["sharpness_tiles"]
    assert len(tiles) == 16 and len(tiles[0]) == 16
    _, ty, tx = max(
        (v, ty, tx)
        for ty, row in enumerate(tiles)
        for tx, v in enumerate(row)
    )
    assert 5 <= ty <= 10 and 5 <= tx <= 10, "sharp region not localized"
    assert frame["sharpness_mean"] < frame["sharpness_max"] / 3
    assert o["embedding_dim"] and o["embedding_dim"] > 0
    assert set(o["timing_ms"]) >= {"decode", "vision", "sharpness"}


def test_missing_file_is_per_photo_error_not_crash(test_jpeg, tmp_path):
    """One corrupt/missing file must not fail the batch (design 03 §4)."""
    ghost = tmp_path / "nope.cr3"
    results = list(analyze_batch([ghost, test_jpeg], scale=1.0))
    assert len(results) == 2
    assert "error" in results[0]
    assert "error" not in results[1]  # batch continued past the failure


def test_swift_prober_plugs_into_ingest(test_jpeg, tmp_path):
    """The real prober satisfies ingest's Prober contract end-to-end."""
    from shootr.db import connect
    from shootr.ingest import scan

    (tmp_path / "db").mkdir()
    conn = connect(tmp_path / "db" / "shootr.db")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "IMG_1.jpg").write_bytes(test_jpeg.read_bytes())
    conn.execute(
        "INSERT INTO library (id, root_path, created_at) VALUES (1, ?, 'now')",
        (str(lib),),
    )
    result = scan(conn, 1, lib, prober=swift_prober)
    assert result.added == 1 and not result.errors
    row = conn.execute("SELECT width, height FROM photo").fetchone()
    assert (row["width"], row["height"]) == (512, 512)
    conn.close()
