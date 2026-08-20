"""Pure-unit tests — no models, no RAWs, no network."""

import hashlib

import numpy as np
import pytest

from shootr_analyzer.coords import (
    bbox_norm_to_vision,
    bbox_px_to_vision,
    clamp_bbox,
    point_px_to_vision,
)
from shootr_analyzer.probe import _subsec, normalize_exif_date
from shootr_analyzer.sharpness import clipping, tenengrad, tile_map


class TestCoords:
    """The silent-wrongness guard: flags.py's headroom check reads bbox[1] in
    bottom-left coords; a wrong flip mis-scores every photo undetectably."""

    def test_top_of_frame_lands_near_one(self):
        # 200px-tall face at the very top of a 1000px image.
        b = bbox_px_to_vision(100, 0, 200, 200, 1000, 1000)
        assert b == [0.1, 0.8, 0.2, 0.2]
        assert b[1] + b[3] == pytest.approx(1.0)  # touches the top edge

    def test_bottom_of_frame_lands_at_zero(self):
        b = bbox_px_to_vision(100, 800, 200, 200, 1000, 1000)
        assert b[1] == pytest.approx(0.0)

    def test_normalized_flip_roundtrip(self):
        b = bbox_norm_to_vision(0.1, 0.2, 0.3, 0.4)
        # Flipping twice = identity.
        b2 = bbox_norm_to_vision(b[0], b[1], b[2], b[3])
        assert b2 == pytest.approx([0.1, 0.2, 0.3, 0.4])

    def test_point_flip(self):
        assert point_px_to_vision(500, 0, 1000, 1000) == (0.5, 1.0)
        assert point_px_to_vision(500, 1000, 1000, 1000) == (0.5, 0.0)

    def test_clamp_contains_offscreen_boxes(self):
        b = clamp_bbox([-0.1, 0.9, 0.5, 0.5])
        assert b[0] >= 0 and b[1] + b[3] <= 1.0 + 1e-9


class TestSharpness:
    """Swift-parity vectors — the same synthetic patterns as SelfTest.swift.
    If these orderings diverge between analyzers, the A/B measures the port,
    not the photographs."""

    def test_flat_field_zero(self):
        assert tenengrad(np.full((64, 64), 128, dtype=np.uint8)) == 0

    def test_edge_beats_ramp(self):
        w = h = 64
        xx = np.tile(np.arange(w), (h, 1))
        edge = np.where(xx < w // 2, 0, 255).astype(np.uint8)
        ramp = (xx * 255 // (w - 1)).astype(np.uint8)
        assert tenengrad(edge) > tenengrad(ramp) * 2

    def test_fine_beats_coarse(self):
        w = h = 64
        xx, yy = np.meshgrid(np.arange(w), np.arange(h))
        fine = (((xx // 2) + (yy // 2)) % 2 * 255).astype(np.uint8)
        coarse = (((xx // 16) + (yy // 16)) % 2 * 255).astype(np.uint8)
        assert tenengrad(fine) > tenengrad(coarse)

    def test_degenerate_size_zero(self):
        assert tenengrad(np.array([[1, 2]], dtype=np.uint8)) == 0

    def test_normalization_matches_swift(self):
        """Not just ordering — the VALUE, hand-computed under the shared
        Swift normalization `sum / n / (4·255²)`. A hard vertical edge in a
        64-wide buffer: exactly the two columns adjacent to the edge have
        |gx| = 4·255 (gy = 0), so
        sum/n = 2·(4·255)²/62 and dividing by 4·255² leaves 8/62."""
        w = h = 64
        xx = np.tile(np.arange(w), (h, 1))
        edge = np.where(xx < w // 2, 0, 255).astype(np.uint8)
        assert tenengrad(edge) == pytest.approx(8 / 62, rel=1e-9)

    def test_tile_map_localizes(self):
        W = H = 256
        px = np.full((H, W), 128, dtype=np.uint8)
        qx, qy = np.meshgrid(np.arange(W // 4), np.arange(H // 4))
        px[:H // 4, :W // 4] = (((qx // 2) + (qy // 2)) % 2 * 255).astype(
            np.uint8)
        m = tile_map(px)
        assert m.max > 0 and m.mean < m.max / 4
        for ty in range(16):
            for tx in range(16):
                if m.tiles[ty][tx] > m.max / 2:
                    assert tx < 4 and ty < 4

    def test_flat_map_is_motion_blur_signature(self):
        m = tile_map(np.full((256, 256), 100, dtype=np.uint8))
        assert m.max == 0 and m.mean == 0

    def test_clipping_thresholds(self):
        px = np.array([[0, 1, 2], [253, 254, 255]], dtype=np.uint8)
        hi, lo = clipping(px)
        assert hi == pytest.approx(2 / 6)  # 254, 255
        assert lo == pytest.approx(2 / 6)  # 0, 1


class TestProbe:
    def test_exif_date_normalized(self):
        assert normalize_exif_date("2026:06:14 15:22:08") == \
            "2026-06-14T15:22:08"

    def test_malformed_date_passes_through(self):
        assert normalize_exif_date("garbage") == "garbage"

    def test_subsec_pads_right(self):
        """'5' is 500 ms, not 5 ms — matches the Swift prefix/padding."""
        assert _subsec("5") == 500
        assert _subsec("62") == 620
        assert _subsec("6203") == 620
        assert _subsec("abc") is None


class TestRegistry:
    def test_registry_hash_changes_with_pins(self, monkeypatch):
        """The hash is the re-analysis invalidation key: any pin change must
        change engine_version."""
        from shootr_analyzer import models

        h1 = models.registry_hash()
        spec = models.REGISTRY[0]
        changed = type(spec)(
            spec.component, spec.name, spec.tier, spec.url,
            "0" * 64, spec.filename, spec.archive_member, spec.member_sha256)
        monkeypatch.setattr(models, "REGISTRY",
                            [changed] + models.REGISTRY[1:])
        assert models.registry_hash() != h1

    def test_resolve_prefers_accuracy_tier(self):
        from shootr_analyzer.models import REGISTRY, resolve

        for component in {m.component for m in REGISTRY}:
            spec = resolve(component)
            if spec is None:
                continue
            tiers = {m.tier for m in REGISTRY
                     if m.component == component and m.active}
            if "accuracy" in tiers:
                assert spec.tier == "accuracy"

    def test_ensure_rejects_bad_checksum(self, tmp_path, monkeypatch):
        from shootr_analyzer import models

        monkeypatch.setenv("SHOOTR_MODEL_DIR", str(tmp_path))
        bad = tmp_path / "weights.onnx"
        bad.write_bytes(b"not the model")
        spec = models.ModelSpec(
            "x", "x", "floor", url="https://example.com/w.onnx",
            sha256=hashlib.sha256(b"the real model").hexdigest(),
            filename="weights.onnx")
        with pytest.raises(RuntimeError, match="checksum"):
            models.ensure(spec)

    def test_ensure_downloads_and_verifies(self, tmp_path, monkeypatch):
        from shootr_analyzer import models

        payload = b"model bytes"
        monkeypatch.setenv("SHOOTR_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(
            models.urllib.request, "urlretrieve",
            lambda url, dst: Path(dst).write_bytes(payload))
        from pathlib import Path
        spec = models.ModelSpec(
            "x", "x", "floor", url="https://example.com/w.onnx",
            sha256=hashlib.sha256(payload).hexdigest(),
            filename="weights.onnx")
        got = models.ensure(spec)
        assert got.read_bytes() == payload
