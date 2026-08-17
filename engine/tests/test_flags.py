"""Composition flag detector tests (design 04 §2.4)."""

from shootr.flags import detect_flags


def face(idx=0, bbox=(0.4, 0.4, 0.2, 0.25), yaw=0.0):
    return {"idx": idx, "bbox": list(bbox), "yaw": yaw}


class TestFaceClipped:
    def test_face_at_edge_flagged(self):
        f = [face(bbox=(0.0, 0.4, 0.2, 0.25))]  # x touches left edge
        assert "face_clipped" in detect_flags(f, 0, None, None)

    def test_centered_face_not_flagged(self):
        assert "face_clipped" not in detect_flags([face()], 0, None, None)


class TestNearEdgeAndThirds:
    def test_subject_near_edge_soft_flag(self):
        f = [face(bbox=(0.9, 0.4, 0.08, 0.1))]  # centroid 0.94 → 0.06 hmm
        flags = detect_flags([face(bbox=(0.93, 0.4, 0.05, 0.1))], 0, None, None)
        near = [x for x in flags if x.startswith("subject_near_edge:")]
        assert near and float(near[0].split(":")[1]) < 0.05

    def test_thirds_distance_always_reported_soft(self):
        # Subject dead center: max distance from any thirds intersection.
        flags = detect_flags([face()], 0, None, None)
        thirds = [x for x in flags if x.startswith("thirds_distance:")]
        assert thirds
        centered = float(thirds[0].split(":")[1])
        # Subject at a thirds point: distance ~0.
        at_thirds = detect_flags(
            [face(bbox=(1 / 3 - 0.1, 2 / 3 - 0.125, 0.2, 0.25))],
            0, None, None)
        d = float([x for x in at_thirds
                   if x.startswith("thirds_distance:")][0].split(":")[1])
        assert d < centered

    def test_saliency_substitutes_when_no_faces(self):
        flags = detect_flags([], None, [0.94, 0.4, 0.05, 0.1], None)
        assert any(x.startswith("subject_near_edge:") for x in flags)


class TestHeadroomAndLeadRoom:
    def test_no_headroom(self):
        # Vision origin is bottom-left: top of head = y + h.
        f = [face(bbox=(0.4, 0.75, 0.2, 0.25))]  # reaches y=1.0
        assert "no_headroom" in detect_flags(f, 0, None, None)

    def test_headroom_ok(self):
        f = [face(bbox=(0.4, 0.4, 0.2, 0.25))]
        assert "no_headroom" not in detect_flags(f, 0, None, None)

    def test_lead_room_inverted(self):
        # Subject on the right (cx≈0.85), facing right (yaw>0) → looking out.
        f = [face(bbox=(0.75, 0.4, 0.2, 0.25), yaw=0.5)]
        assert "lead_room_inverted" in detect_flags(f, 0, None, None)

    def test_lead_room_correct_not_flagged(self):
        # Subject on the right, facing left into the frame.
        f = [face(bbox=(0.75, 0.4, 0.2, 0.25), yaw=-0.5)]
        assert "lead_room_inverted" not in detect_flags(f, 0, None, None)

    def test_frontal_face_no_lead_room_flag(self):
        f = [face(bbox=(0.75, 0.4, 0.2, 0.25), yaw=0.05)]
        assert "lead_room_inverted" not in detect_flags(f, 0, None, None)


class TestHorizon:
    def test_tilt_flagged_with_degrees(self):
        flags = detect_flags([], None, None, -3.2)
        assert "horizon_tilt:-3.2" in flags

    def test_level_horizon_not_flagged(self):
        assert not any(x.startswith("horizon_tilt")
                       for x in detect_flags([], None, None, 0.4))

    def test_no_horizon_no_flag(self):
        assert not any(x.startswith("horizon_tilt")
                       for x in detect_flags([], None, None, None))
