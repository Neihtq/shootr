"""Pose vector + limb-cut tests (design 05 §4, 04 §2.4).

The abstention cases are the point: 05 §4 says a seated, occluded or tightly
cropped subject must go UNASSIGNED, because a garbage vector would cluster
with every other sparse frame and make pose grouping untrustworthy.
"""

import pytest

from shootr.pose import (VECTOR_JOINTS, best_pose, limb_cut_at_joint,
                         pose_vector)


def standing(x=0.5, y=0.5, scale=1.0, conf=0.9):
    """A full skeleton, scaled and translated — same pose, different framing.

    `y=0.5` keeps the feet at 0.10, clear of the frame edge: at y=0.4 the feet
    land exactly on 0.0 and the limb-cut detector correctly flags them, which
    is a fixture bug, not a detector bug.
    """
    layout = {
        "left_shoulder_1_joint": (-0.10, 0.30), "right_shoulder_1_joint": (0.10, 0.30),
        "left_forearm_joint": (-0.16, 0.16), "right_forearm_joint": (0.16, 0.16),
        "left_hand_joint": (-0.18, 0.02), "right_hand_joint": (0.18, 0.02),
        "left_upLeg_joint": (-0.06, 0.00), "right_upLeg_joint": (0.06, 0.00),
        "left_leg_joint": (-0.07, -0.20), "right_leg_joint": (0.07, -0.20),
        "left_foot_joint": (-0.07, -0.40), "right_foot_joint": (0.07, -0.40),
        "neck_1_joint": (0.0, 0.34), "head_joint": (0.0, 0.42),
    }
    return {k: [x + dx * scale, y + dy * scale, conf]
            for k, (dx, dy) in layout.items()}


def test_vector_is_translation_and_scale_invariant():
    """Distance-invariance is the whole reason for torso normalization."""
    near = pose_vector(standing(x=0.3, y=0.5, scale=1.0))
    far = pose_vector(standing(x=0.7, y=0.35, scale=0.45))
    assert near and far
    assert len(near[0]) == len(VECTOR_JOINTS) * 2
    for a, b in zip(near[0], far[0]):
        assert a == pytest.approx(b, abs=1e-6)


def test_no_torso_abstains():
    """Seated/occluded: no hips or no shoulders → None, not a guess."""
    j = standing()
    for missing in ("left_upLeg_joint", "right_upLeg_joint"):
        j.pop(missing)
    assert pose_vector(j) is None
    j2 = standing()
    for missing in ("left_shoulder_1_joint", "right_shoulder_1_joint"):
        j2.pop(missing)
    assert pose_vector(j2) is None


def test_sparse_skeleton_abstains_rather_than_filling_with_origins():
    """Missing joints become the hip origin, so a mostly-missing body would
    look like a distinct pose and cluster with every other sparse frame."""
    j = standing()
    keep = {"left_upLeg_joint", "right_upLeg_joint",
            "left_shoulder_1_joint", "right_shoulder_1_joint"}
    sparse = {k: v for k, v in j.items() if k in keep}
    assert pose_vector(sparse) is None


def test_low_confidence_joints_are_dropped():
    j = standing(conf=0.1)
    assert pose_vector(j) is None  # nothing survives the confidence filter


def test_tiny_subject_abstains():
    """A body a few pixels tall has no reliable torso scale."""
    assert pose_vector(standing(scale=0.02)) is None


def test_best_pose_picks_the_most_confident_body():
    a = {"joints": standing(x=0.3, conf=0.5)}
    b = {"joints": standing(x=0.7, conf=0.95)}
    got = best_pose([a, b])
    assert got and got[1] == pytest.approx(0.95)
    assert best_pose([]) is None
    assert best_pose([{"joints": {}}]) is None


class TestLimbCut:
    def test_flags_a_joint_on_the_edge(self):
        j = standing()
        j["left_leg_joint"] = [0.005, 0.5, 0.9]  # knee against the left edge
        assert limb_cut_at_joint([{"joints": j}]) == "left_leg_joint"

    def test_limb_crossing_between_joints_is_not_flagged(self):
        """Cutting mid-thigh is normal framing; only cuts AT joints read as
        errors (04 §2.4) — otherwise the flag fires on every environmental
        portrait and the whole flag set gets ignored."""
        j = standing()
        # Hip and knee both well inside; the thigh between them exits frame.
        j["left_upLeg_joint"] = [0.10, 0.5, 0.9]
        j["left_leg_joint"] = [0.10, 0.2, 0.9]
        assert limb_cut_at_joint([{"joints": j}]) is None

    def test_low_confidence_joint_does_not_flag(self):
        j = standing()
        j["right_hand_joint"] = [0.99, 0.5, 0.05]
        assert limb_cut_at_joint([{"joints": j}]) is None

    def test_no_poses_is_no_flag(self):
        assert limb_cut_at_joint([]) is None

    def test_extrapolated_out_of_frame_joint_does_not_flag(self):
        """MediaPipe guesses where occluded limbs would be, past the frame
        bounds (19% of its joints, measured). A joint OUTSIDE the frame means
        the limb left frame before it — the between-joints case that is normal
        framing, not a cut at the joint (04 §2.4)."""
        j = standing()
        j["left_leg_joint"] = [0.79, -0.165, 0.9]   # confidently guessed knee
        j["left_foot_joint"] = [0.78, -0.362, 0.9]
        assert limb_cut_at_joint([{"joints": j}]) is None

    def test_joint_just_inside_the_edge_still_flags(self):
        """The in-frame requirement must not swallow the real case."""
        j = standing()
        j["right_hand_joint"] = [0.995, 0.5, 0.9]
        assert limb_cut_at_joint([{"joints": j}]) == "right_hand_joint"
