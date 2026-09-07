"""Pose vector construction (design 05 §4) and limb-cut detection (04 §2.4).

Both analyzers emit *raw* joints — name → [x, y, confidence] in normalized
bottom-left coordinates — and the derived vector is built here, once, so the
two implementations only have to agree on what they measured.

Normalization, per 05 §4:
  1. translate to the hip midpoint,
  2. scale by torso length (shoulder midpoint → hip midpoint) so the vector
     is distance-invariant,
  3. drop low-confidence joints.

**Abstention is the point.** Seated, occluded or tightly-cropped subjects
have no visible hips or shoulders, so normalization is impossible — those
photos get `None` and go unassigned rather than into a junk cluster that
would make pose grouping untrustworthy.
"""

from __future__ import annotations

# Vision's joint names (VNHumanBodyPoseObservation.JointName.rawValue) — the
# Python analyzer maps its own skeleton onto these when it lands.
LEFT_HIP, RIGHT_HIP = "left_upLeg_joint", "right_upLeg_joint"
LEFT_SHOULDER, RIGHT_SHOULDER = "left_shoulder_1_joint", "right_shoulder_1_joint"

# Joints whose position carries pose meaning, in a fixed order so vectors are
# comparable element-wise. Face joints are excluded: they track head detail,
# not body pose, and faces already have their own axis (05 §5).
VECTOR_JOINTS: tuple[str, ...] = (
    "left_shoulder_1_joint", "right_shoulder_1_joint",
    "left_forearm_joint", "right_forearm_joint",
    "left_hand_joint", "right_hand_joint",
    "left_upLeg_joint", "right_upLeg_joint",
    "left_leg_joint", "right_leg_joint",
    "left_foot_joint", "right_foot_joint",
    "neck_1_joint", "head_joint",
)

MIN_JOINT_CONFIDENCE = 0.3
# Below this fraction of VECTOR_JOINTS present, the vector describes too
# little of the body to cluster on.
MIN_JOINT_COVERAGE = 0.5
MIN_TORSO_LENGTH = 0.02  # normalized units; smaller means the body is a speck

# Joints where a frame-edge crop reads as a mistake (04 §2.4). Cutting
# *between* joints is normal framing; cutting *at* one is the classic error,
# so only these are checked.
CUT_SENSITIVE_JOINTS: tuple[str, ...] = (
    "left_forearm_joint", "right_forearm_joint",    # elbow
    "left_hand_joint", "right_hand_joint",          # wrist
    "left_leg_joint", "right_leg_joint",            # knee
    "left_foot_joint", "right_foot_joint",          # ankle
)
EDGE_EPSILON = 0.02  # within 2% of an edge counts as "cut at"


def _mid(a: list[float] | None, b: list[float] | None
         ) -> tuple[float, float] | None:
    if a and b:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return a[:2] if a else (b[:2] if b else None)  # type: ignore[return-value]


def _confident(joints: dict[str, list[float]]) -> dict[str, list[float]]:
    return {k: v for k, v in joints.items()
            if len(v) >= 3 and v[2] >= MIN_JOINT_CONFIDENCE}


def pose_vector(joints: dict[str, list[float]]
                ) -> tuple[tuple[float, ...], float] | None:
    """(vector, mean confidence) or None when the pose can't be normalized.

    Missing joints are filled with 0.0 — the hip origin — which is why
    coverage is checked first: a vector of mostly-origin points would look
    like a distinct "pose" and cluster with every other sparse frame.
    """
    conf = _confident(joints)
    hip = _mid(conf.get(LEFT_HIP), conf.get(RIGHT_HIP))
    shoulder = _mid(conf.get(LEFT_SHOULDER), conf.get(RIGHT_SHOULDER))
    if hip is None or shoulder is None:
        return None  # no torso → no scale → abstain (05 §4)
    torso = ((shoulder[0] - hip[0]) ** 2 + (shoulder[1] - hip[1]) ** 2) ** 0.5
    if torso < MIN_TORSO_LENGTH:
        return None

    present = [j for j in VECTOR_JOINTS if j in conf]
    if len(present) / len(VECTOR_JOINTS) < MIN_JOINT_COVERAGE:
        return None

    vec: list[float] = []
    for name in VECTOR_JOINTS:
        p = conf.get(name)
        if p is None:
            vec.extend((0.0, 0.0))
        else:
            vec.extend(((p[0] - hip[0]) / torso, (p[1] - hip[1]) / torso))
    mean_conf = sum(conf[j][2] for j in present) / len(present)
    return tuple(vec), mean_conf


def best_pose(poses: list[dict]) -> tuple[tuple[float, ...], float] | None:
    """The most confident normalizable body in the frame.

    One vector per photo: pose grouping asks "is this the same pose as that
    photo", which is only meaningful for the subject. Group shots are handled
    by shot grouping instead (05 §4).
    """
    best: tuple[tuple[float, ...], float] | None = None
    for entry in poses or []:
        built = pose_vector(entry.get("joints") or {})
        if built and (best is None or built[1] > best[1]):
            best = built
    return best


def limb_cut_at_joint(poses: list[dict]) -> str | None:
    """`limb_cut_at_joint` when a cut-sensitive joint sits on a frame edge.

    Anatomically specific on purpose (04 §2.4): flagging every limb that
    crosses the edge would fire on nearly every environmental portrait and
    train the user to ignore the whole flag set.
    """
    for entry in poses or []:
        conf = _confident(entry.get("joints") or {})
        for name in CUT_SENSITIVE_JOINTS:
            p = conf.get(name)
            if not p:
                continue
            x, y = p[0], p[1]
            if (x <= EDGE_EPSILON or x >= 1 - EDGE_EPSILON
                    or y <= EDGE_EPSILON or y >= 1 - EDGE_EPSILON):
                return name
    return None
