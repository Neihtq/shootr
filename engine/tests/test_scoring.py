"""Invariant tests for scoring (design 04). Each test names the doc rule."""

import pytest

from shootr.scoring import (
    Eye,
    FaceMeasurement,
    FrameMeasurement,
    Measurements,
    score,
)


def face(sharp_l=0.8, sharp_r=0.6, open_l=0.95, open_r=0.9, yaw=0.0,
         quality=0.7, idx=0, bbox=(0.3, 0.2, 0.2, 0.25)):
    return FaceMeasurement(
        idx=idx, bbox=bbox, yaw=yaw, capture_quality=quality,
        left=Eye(sharp_l, open_l), right=Eye(sharp_r, open_r),
    )


def sharp_frame():
    return FrameMeasurement(sharpness_max=0.8, sharpness_mean=0.3,
                            clipped_hi=0.001, clipped_lo=0.001)


class TestNullNotZero:
    """design 04 §5 — the invariant most likely to cause wrong rankings."""

    def test_landscape_without_faces_scores_well(self):
        m = Measurements(frame=sharp_frame())
        rec = score(m, "landscape")
        assert rec.total > 0.5  # zeroing eyes would have tanked this

    def test_no_face_eye_metrics_are_null(self):
        m = Measurements(frame=sharp_frame())
        rec = score(m, "portrait")
        assert rec.components["eye_focus"]["value"] is None
        assert rec.components["eyes_open"]["value"] is None
        assert rec.components["eye_focus"]["contrib"] is None

    def test_null_weight_redistributed(self):
        """A faceless frame in portrait profile: applicable weights sum to 1."""
        m = Measurements(frame=sharp_frame())
        rec = score(m, "portrait")
        live = [c for c in rec.components.values() if c["value"] is not None]
        assert sum(c["weight"] for c in live) == pytest.approx(1.0, abs=1e-3)

    def test_extreme_yaw_abstains(self):
        """Profile view → abstain, don't guess (design 04 §2.2)."""
        m = Measurements(frame=sharp_frame(), faces=[face(yaw=1.2)])
        rec = score(m, "portrait")
        assert rec.components["eyes_open"]["value"] is None
        assert "yaw" in rec.components["eyes_open"]["evidence"]

    def test_genuinely_closed_eyes_score_low_not_null(self):
        """'Measured badly' must stay distinct from 'couldn't measure'."""
        m = Measurements(frame=sharp_frame(),
                         faces=[face(open_l=0.1, open_r=0.1)])
        rec = score(m, "portrait")
        val = rec.components["eyes_open"]["value"]
        assert val is not None and val < 0.1


class TestEyeSemantics:
    def test_eye_focus_uses_max(self):
        """Near eye sharp at f/1.4 is correct technique (design 04 §2.1)."""
        m = Measurements(frame=sharp_frame(),
                         faces=[face(sharp_l=0.85, sharp_r=0.2)])
        rec = score(m, "portrait")
        assert rec.components["eye_focus"]["value"] == 1.0
        assert rec.components["eye_focus"]["evidence"]["eye"] == "left"

    def test_eyes_open_uses_min(self):
        """One closed eye ruins the frame (design 04 §2.2)."""
        m = Measurements(frame=sharp_frame(),
                         faces=[face(open_l=0.95, open_r=0.2)])
        rec = score(m, "portrait")
        assert rec.components["eyes_open"]["value"] < 0.1

    def test_focus_cliff(self):
        """Sharp vs missed must be a cliff, not a slope (design 04 §2.1)."""
        sharp = score(Measurements(frame=sharp_frame(),
                                   faces=[face(sharp_l=0.75, sharp_r=0.7)]),
                      "portrait")
        missed = score(Measurements(frame=sharp_frame(),
                                    faces=[face(sharp_l=0.15, sharp_r=0.1)]),
                       "portrait")
        f_sharp = sharp.components["eye_focus"]["value"]
        f_missed = missed.components["eye_focus"]["value"]
        assert f_sharp == 1.0 and f_missed < 0.15

    def test_soft_frame_routes_to_motion_blur_not_focus_miss(self):
        m = Measurements(
            frame=FrameMeasurement(sharpness_max=0.05, sharpness_mean=0.02,
                                   clipped_hi=0.0, clipped_lo=0.0),
            faces=[face(sharp_l=0.1, sharp_r=0.1)],
        )
        rec = score(m, "portrait")
        assert rec.components["eye_focus"]["value"] is None
        assert rec.components["eye_focus"]["evidence"]["reason"] == \
            "frame_soft_motion_blur"
        assert rec.components["sharpness"]["value"] == 0.0


class TestBracketAndEvidence:
    def test_bracket_suppresses_exposure(self):
        """The -2EV frame is supposed to be dark (design 04 §6)."""
        m = Measurements(frame=FrameMeasurement(
            sharpness_max=0.8, sharpness_mean=0.3,
            clipped_hi=0.30, clipped_lo=0.0), in_bracket=True)
        rec = score(m, "landscape")
        assert rec.components["exposure"]["value"] is None

    def test_every_component_carries_evidence(self):
        """design 04 §1 / README rule 5 — no opaque numbers."""
        m = Measurements(frame=sharp_frame(), faces=[face()],
                         composition_flags=["subject_near_edge:0.04"])
        rec = score(m, "event")
        for name, comp in rec.components.items():
            assert "evidence" in comp, name
        assert rec.weights_hash.startswith("ev1-")
        assert rec.primary_subject == {"face_idx": 0, "why": "largest_face"}

    def test_composition_flags_penalize_individually(self):
        clean = score(Measurements(frame=sharp_frame()), "landscape")
        flagged = score(Measurements(frame=sharp_frame(),
                                     composition_flags=["face_clipped"]),
                        "landscape")
        assert flagged.components["composition"]["value"] < \
            clean.components["composition"]["value"]
        assert "face_clipped" in \
            flagged.components["composition"]["evidence"]["penalties"]

    def test_multi_face_primary_is_largest_near_saliency(self):
        small_central = face(idx=0, bbox=(0.45, 0.4, 0.10, 0.12))
        big_peripheral = face(idx=1, bbox=(0.05, 0.05, 0.2, 0.25))
        m = Measurements(frame=sharp_frame(),
                         faces=[small_central, big_peripheral],
                         saliency_bbox=(0.4, 0.35, 0.2, 0.2))
        rec = score(m, "event")
        assert rec.primary_subject["face_idx"] == 0
        assert rec.primary_subject["why"] == "largest_face_near_saliency_peak"

    def test_unknown_profile_rejected(self):
        with pytest.raises(ValueError):
            score(Measurements(), "wedding")
