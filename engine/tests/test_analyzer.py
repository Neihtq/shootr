"""Integration tests driving the Python analyzer (shootr-analyze-py) through
the SAME contract seams as the Swift helper — the design-13 requirement made
executable: either binary behind SHOOTR_HELPER must satisfy these.

Skipped when the analyzer isn't installed. Model-free by construction: a
plain JPEG exercises decode/sharpness/probe/error paths; model-backed fields
(faces, embedding) are allowed to be absent here because the fixture has no
faces and CI has no weights — their correctness is the A/B harness's job on
real photos.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ANALYZER = shutil.which(
    "shootr-analyze-py",
    path=str(Path(sys.executable).parent),
) or shutil.which("shootr-analyze-py")

pytestmark = pytest.mark.skipif(
    ANALYZER is None, reason="Python analyzer not installed"
)


@pytest.fixture(scope="module")
def test_jpeg(tmp_path_factory) -> Path:
    """512×512 grey field, sharp checkerboard center — same pattern as
    test_helper.py's fixture, no sips dependency (must build on Linux)."""
    import numpy as np
    from PIL import Image

    tmp = tmp_path_factory.mktemp("images")
    img = np.full((512, 512), 128, dtype=np.uint8)
    yy, xx = np.meshgrid(np.arange(512), np.arange(512), indexing="ij")
    center = (xx >= 192) & (xx < 320) & (yy >= 192) & (yy < 320)
    checker = (((xx // 2) + (yy // 2)) % 2 * 255).astype(np.uint8)
    img[center] = checker[center]
    jpg = tmp / "test.jpg"
    Image.fromarray(img).convert("RGB").save(jpg, "JPEG", quality=95)
    return jpg


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([ANALYZER, *args], capture_output=True, text=True)


def batch(command: str, files: list[Path], *extra: str) -> list[dict]:
    """Drive the analyzer the way the engine does — via shootr.helper with
    SHOOTR_HELPER pointed at it, exercising the real watchdog/framing path."""
    import shootr.helper as helper

    return list(helper._run_jsonl(command, files, list(extra) or None))


@pytest.fixture(autouse=True)
def _point_engine_at_analyzer(monkeypatch):
    monkeypatch.setenv("SHOOTR_HELPER", ANALYZER)


def test_selftest_passes():
    """Pure-math parity checks — same synthetic patterns as the Swift
    selftest, so the two analyzers verify the same orderings."""
    out = run_cli("selftest")
    assert out.returncode == 0, out.stdout
    assert json.loads(out.stdout.strip()) == {"status": "ok"}


def test_version_reports_engine_and_registry():
    out = run_cli("version")
    v = json.loads(out.stdout.strip())
    assert v["engine_version"].startswith("py-")
    assert "+" in v["engine_version"]  # registry hash = invalidation key
    assert v["providers"]  # EP list always present, CPU at minimum


def test_probe_returns_dimensions(test_jpeg):
    results = batch("probe", [test_jpeg])
    assert len(results) == 1
    assert results[0]["width"] == 512 and results[0]["height"] == 512


def test_analyze_localizes_sharp_region(test_jpeg):
    """Same assertion as the Swift suite: the sharp center must land in the
    center tiles. If both pass, the two analyzers agree on what 'where did
    focus land' means."""
    results = batch("analyze", [test_jpeg], "--scale", "1.0")
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
    assert o["engine_version"].startswith("py-")
    assert o["decode_mode"] == "jpeg"
    assert set(o["timing_ms"]) >= {"decode", "vision", "sharpness"}


def test_missing_file_is_per_photo_error_not_crash(test_jpeg, tmp_path):
    """One corrupt/missing file must not fail the batch (design 03 §4)."""
    ghost = tmp_path / "nope.cr3"
    results = batch("analyze", [ghost, test_jpeg], "--scale", "1.0")
    assert len(results) == 2
    assert "error" in results[0]
    assert "error" not in results[1]  # batch continued past the failure


def test_render_writes_jpeg(test_jpeg, tmp_path):
    out_path = tmp_path / "render.jpg"
    out = run_cli("render", "--file", str(test_jpeg),
                  "--size", "256", "--out", str(out_path))
    assert out.returncode == 0, out.stdout
    assert out_path.exists()
    assert out_path.read_bytes()[:2] == b"\xff\xd8"  # JPEG SOI


def test_prober_plugs_into_ingest(test_jpeg):
    """swift_prober is analyzer-agnostic (it shells out to SHOOTR_HELPER) —
    the Python analyzer must satisfy the same ingest Prober contract."""
    from shootr.helper import swift_prober

    out = swift_prober(test_jpeg)
    assert out is not None and out["width"] == 512


def test_persist_accepts_analyzer_output(test_jpeg, tmp_path):
    """The full engine seam: analyze via SHOOTR_HELPER → _persist → the
    columns scoring reads. Faceprint column round-trips when present."""
    from shootr.analyze_runner import _persist
    from shootr.db import connect

    results = batch("analyze", [test_jpeg], "--scale", "1.0")
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO library (id, root_path, created_at) "
                 "VALUES (1, '/', 'now')")
    conn.execute(
        "INSERT INTO photo (id, library_id, content_id, rel_path, filename, "
        "file_size, mtime) VALUES (1, 1, 'c1', 'test.jpg', 'test.jpg', 1, 0)")
    _persist(conn, 1, results[0])
    row = conn.execute("SELECT * FROM analysis WHERE photo_id = 1").fetchone()
    assert row["engine_version"].startswith("py-")
    frame = json.loads(row["frame"])
    assert frame["sharpness_max"] > 0
    conn.close()
