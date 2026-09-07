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
         quality=0.7, idx=0, bbox=(0.3, 0.2, 0.2, 0.25), eye_source=None):
    return FaceMeasurement(
        idx=idx, bbox=bbox, yaw=yaw, capture_quality=quality,
        left=Eye(sharp_l, open_l), right=Eye(sharp_r, open_r),
        eye_source=eye_source,
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

    def test_eyes_open_handling_is_per_source(self):
        """Refit 2026-08-29 on the merged labelled set (285 faces): the
        blendshapes curve places culling's 0.4 boundary at raw 0.50
        (FR 2.2%), and EAR — no usable separation (open p50 = 0.32,
        closed spanning 0.0–1.0) — abstains rather than guesses
        (design 04 §5: detector abstained ≠ genuinely bad)."""
        def comp(source, raw):
            m = Measurements(frame=sharp_frame(),
                             faces=[face(open_l=raw, open_r=raw,
                                         eye_source=source)])
            return score(m, "portrait").components["eyes_open"]

        assert comp("mediapipe_blendshapes", 0.55)["value"] > 0.4
        assert comp("mediapipe_blendshapes", 0.45)["value"] < 0.4
        # EAR abstains: null value, weight renormalizes away, and the
        # evidence says why — never a zero (design 04 §5).
        ear = comp("ear_landmarks", 0.55)
        assert ear["value"] is None
        assert ear["evidence"]["reason"] == "unreliable_source_abstained"
        assert ear["evidence"]["eye_source"] == "ear_landmarks"
        # Provenance lands in the evidence for scored sources (design 04 §1).
        bl = comp("mediapipe_blendshapes", 0.7)
        assert bl["evidence"]["eye_source"] == "mediapipe_blendshapes"

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

    def test_unusable_frame_routes_away_from_a_false_focus_miss(self):
        """Far below its population (rel 0.025 < 0.03) → one honest verdict:
        the frame has no usable detail, so eye_focus abstains instead of
        reporting a focus miss it cannot see."""
        m = Measurements(
            frame=FrameMeasurement(sharpness_max=0.001, sharpness_mean=0.0005,
                                   clipped_hi=0.0, clipped_lo=0.0,
                                   sharpness_ref=0.04, population_n=500),
            faces=[face(sharp_l=0.1, sharp_r=0.1)],
        )
        rec = score(m, "portrait")
        assert rec.components["eye_focus"]["value"] is None
        assert rec.components["eye_focus"]["evidence"]["reason"] == \
            "frame_no_usable_detail"
        assert rec.components["sharpness"]["value"] == 0.0

    def test_dark_low_detail_scene_is_not_accused_of_blur(self):
        """The first-dance case (design 04 §2.3): smoke, darkness, red light —
        a keeper at rel 0.056. Low gradient energy is the SCENE, not shake, so
        it scores low but is never branded unusable."""
        m = Measurements(
            frame=FrameMeasurement(sharpness_max=0.00224, sharpness_mean=0.001,
                                   clipped_hi=0.0, clipped_lo=0.0,
                                   sharpness_ref=0.04, population_n=4448),
        )
        sharp = score(m, "landscape").components["sharpness"]
        assert sharp["value"] is not None and sharp["value"] > 0.0
        assert "diagnosis" not in sharp["evidence"]
        assert sharp["evidence"]["sharpness_rel"] == pytest.approx(0.056,
                                                                  abs=0.001)

    def test_without_a_population_it_scores_but_never_accuses(self):
        """No reference → absolute curve (calibrated on one camera) for a
        score, but no hard verdict: we cannot tell an unusable frame from an
        uncalibrated camera. The evidence says which basis was used."""
        m = Measurements(
            frame=FrameMeasurement(sharpness_max=0.001, sharpness_mean=0.0005,
                                   clipped_hi=0.0, clipped_lo=0.0),
            faces=[face(sharp_l=0.1, sharp_r=0.1)],
        )
        rec = score(m, "portrait")
        sharp = rec.components["sharpness"]
        assert "diagnosis" not in sharp["evidence"]
        assert sharp["evidence"]["basis"] == "absolute_no_population"
        # eye_focus is judged on its own merits, not routed away.
        assert rec.components["eye_focus"]["value"] is not None

    def test_relative_basis_makes_two_cameras_comparable(self):
        """The bug this fixes: identical frame quality on two bodies whose
        absolute Tenengrad differs 10× must score the same."""
        canon = Measurements(frame=FrameMeasurement(
            sharpness_max=0.040, sharpness_mean=0.02,
            sharpness_ref=0.040, population_n=100))
        other = Measurements(frame=FrameMeasurement(
            sharpness_max=0.400, sharpness_mean=0.2,
            sharpness_ref=0.400, population_n=100))
        a = score(canon, "landscape").components["sharpness"]["value"]
        b = score(other, "landscape").components["sharpness"]["value"]
        assert a == pytest.approx(b)


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
