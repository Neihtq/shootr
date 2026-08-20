"""Unit tests for the blink-labelling tool's decision math — the part that
turns labels into a threshold recommendation. Mislabeling the asymmetric
failure direction here would produce a confidently wrong calibration."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "label_blinks",
    Path(__file__).resolve().parents[1] / "tools" / "label_blinks.py")
label_blinks = importlib.util.module_from_spec(_spec)
sys.modules["label_blinks"] = label_blinks
_spec.loader.exec_module(label_blinks)

evaluate = label_blinks.evaluate
best_threshold = label_blinks.best_threshold
face_score = label_blinks.face_score
iou = label_blinks.iou


class TestFaceScore:
    def test_min_of_both_eyes(self):
        """The scorer uses min(l, r) — one closed eye means blinking."""
        f = {"eyes": {"l": {"open": 0.9}, "r": {"open": 0.2}}}
        assert face_score(f) == 0.2

    def test_single_eye_used_alone(self):
        f = {"eyes": {"l": {"open": 0.7}, "r": {"open": None}}}
        assert face_score(f) == 0.7

    def test_no_eyes_abstains(self):
        assert face_score({"eyes": {}}) is None
        assert face_score({}) is None


class TestEvaluate:
    def test_false_reject_is_open_flagged_closed(self):
        """The asymmetric failure: an open eye scoring below threshold."""
        e = evaluate(open_scores=[0.3, 0.9], closed_scores=[0.1],
                     threshold=0.4)
        assert e["false_reject_rate"] == 0.5  # the 0.3 open eye
        assert e["false_accept_rate"] == 0.0

    def test_false_accept_is_closed_passing(self):
        e = evaluate(open_scores=[0.9], closed_scores=[0.5, 0.1],
                     threshold=0.4)
        assert e["false_accept_rate"] == 0.5  # the 0.5 closed eye
        assert e["false_reject_rate"] == 0.0

    def test_perfect_separation(self):
        e = evaluate([0.8, 0.9], [0.1, 0.2], 0.5)
        assert e["balanced_accuracy"] == 1.0


class TestBestThreshold:
    def test_finds_the_separating_gap(self):
        best = best_threshold(open_scores=[0.7, 0.8, 0.9],
                              closed_scores=[0.1, 0.2, 0.3])
        assert 0.3 < best["threshold"] <= 0.7
        assert best["balanced_accuracy"] == 1.0

    def test_ties_prefer_lower_threshold(self):
        """Lower threshold = fewer false rejects — the asymmetric cost
        (design 06: a good frame rejected is worse than a blink kept)."""
        best = best_threshold([0.9], [0.1])
        assert best["threshold"] <= 0.5


class TestIou:
    def test_identical_boxes(self):
        assert abs(iou([0.1, 0.1, 0.2, 0.2], [0.1, 0.1, 0.2, 0.2]) - 1.0) < 1e-9

    def test_disjoint_boxes(self):
        assert iou([0.0, 0.0, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]) == 0.0

    def test_half_overlap_matches_at_threshold(self):
        # Two boxes sharing half their area: IoU = 1/3 ≥ MATCH_IOU (0.3).
        v = iou([0.0, 0.0, 0.2, 0.2], [0.1, 0.0, 0.2, 0.2])
        assert abs(v - 1 / 3) < 1e-9
        assert v >= label_blinks.MATCH_IOU
