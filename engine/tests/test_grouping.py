"""Grouping tests (design 05). Synthetic embeddings; tests name doc rules."""

from datetime import datetime, timedelta

from shootr.grouping import (
    PhotoFeatures,
    Pin,
    apply_pins,
    detect_brackets,
    group_persons,
    group_poses,
    group_scenes,
    group_shots,
)

T0 = datetime(2026, 6, 14, 15, 0, 0)

# Distinct unit vectors: A/B are orthogonal (max cosine distance);
# A and A2 are nearly identical.
EMB_A = (1.0, 0.0, 0.0)
EMB_A2 = (0.999, 0.04, 0.0)
EMB_B = (0.0, 1.0, 0.0)
# Distance 0.15 from A: past the face-count corroboration threshold (0.10)
# but still inside the same shot (SHOT_EMBEDDING_DIST 0.20).
EMB_A_SHIFTED = (0.85, 0.53, 0.0)


def photo(pid, seconds=0.0, subsec=0, bias=0.0, emb=EMB_A, faces=0,
          faceprint=None, pose=None, pose_conf=0.0, faceprints=()):
    return PhotoFeatures(
        photo_id=pid,
        captured_at=T0 + timedelta(seconds=seconds),
        subsec=subsec,
        exposure_bias=bias,
        embedding=emb,
        face_count=faces,
        primary_faceprint=faceprint,
        pose=pose,
        pose_confidence=pose_conf,
        faceprints=faceprints,
    )


class TestBracketDetection:
    """design 04 §6 — the 'destroys HDR sets' guard, detection side."""

    def test_symmetric_bracket_detected(self):
        run = [photo(1, 0, bias=-2.0), photo(2, 0.5, bias=0.0),
               photo(3, 1.0, bias=2.0)]
        assert len(detect_brackets(run)) == 1

    def test_burst_at_constant_bias_is_not_a_bracket(self):
        """A burst shares one exposure — must never be sealed as a bracket."""
        run = [photo(i, i * 0.2, bias=0.0) for i in range(1, 6)]
        assert detect_brackets(run) == []

    def test_slow_sequence_not_a_bracket(self):
        run = [photo(1, 0, bias=-2.0), photo(2, 10, bias=0.0),
               photo(3, 20, bias=2.0)]
        assert detect_brackets(run) == []

    def test_scene_change_breaks_bracket(self):
        run = [photo(1, 0, bias=-2.0), photo(2, 0.5, bias=0.0, emb=EMB_B),
               photo(3, 1.0, bias=2.0)]
        assert detect_brackets(run) == []

    def test_one_sided_bias_walk_not_a_bracket(self):
        """0 / +1 / +2 is exposure riding, not a bracket around metered."""
        run = [photo(1, 0, bias=0.0), photo(2, 0.5, bias=1.0),
               photo(3, 1.0, bias=2.0)]
        assert detect_brackets(run) == []

    def test_five_frame_bracket(self):
        biases = [-2.0, -1.0, 0.0, 1.0, 2.0]
        run = [photo(i + 1, i * 0.4, bias=b) for i, b in enumerate(biases)]
        brackets = detect_brackets(run)
        assert len(brackets) == 1 and len(brackets[0]) == 5


class TestSceneGrouping:
    def test_long_gap_is_decisive(self):
        photos = [photo(1, 0), photo(2, 60), photo(3, 10 * 60)]
        scenes = group_scenes(photos)
        assert [g.member_ids for g in scenes] == [[1, 2], [3]]

    def test_short_gap_needs_visual_confirmation(self):
        """90s–8min gap splits only when the embedding also moved (§2)."""
        same_look = [photo(1, 0), photo(2, 120, emb=EMB_A2)]
        assert len(group_scenes(same_look)) == 1
        new_look = [photo(1, 0), photo(2, 120, emb=EMB_B)]
        assert len(group_scenes(new_look)) == 2

    def test_lull_in_ceremony_not_a_new_scene(self):
        """Time alone over-splits (§2) — 3 min pause, same room."""
        photos = [photo(1, 0), photo(2, 180, emb=EMB_A2)]
        assert len(group_scenes(photos)) == 1


class TestShotGrouping:
    """The cull unit (§3) — both error directions are costly."""

    def test_burst_stays_together(self):
        burst = [photo(i, i * 0.2, faces=1) for i in range(1, 10)]
        shots = group_shots(burst)
        assert len(shots) == 1 and len(shots[0].member_ids) == 9

    def test_time_gap_splits(self):
        photos = [photo(1, 0), photo(2, 0.5), photo(3, 30)]
        shots = group_shots(photos)
        assert [g.member_ids for g in shots] == [[1, 2], [3]]

    def test_framing_change_splits(self):
        photos = [photo(1, 0), photo(2, 0.5, emb=EMB_B)]
        assert len(group_shots(photos)) == 2

    def test_face_count_change_splits_when_framing_corroborates(self):
        """People entering/leaving moves the framing too (§3)."""
        photos = [photo(1, 0, faces=2),
                  photo(2, 0.5, faces=3, emb=EMB_A_SHIFTED)]
        assert len(group_shots(photos)) == 2

    def test_face_count_flicker_alone_does_not_split(self):
        """Regression (user-reported: 'group 1 and 2 each have one picture but
        they look similar'). Vision's face detector flickers between frames of
        the same shot — on a real 1232-frame event shoot, 26% of
        near-identical consecutive pairs disagreed on face count. Trusting it
        uncorroborated turned 130 real groups into 527, which saves the user
        nothing."""
        photos = [photo(1, 0, faces=2), photo(2, 0.5, faces=3)]
        assert len(group_shots(photos)) == 1

    def test_same_setup_a_few_seconds_apart_stays_one_group(self):
        """Regression, same report: an event photographer reshooting the same
        setup every ~3.5 s was getting one group per frame at the old 3 s
        gap. Near-identical frames sit p95 = 4.3 s apart on real files."""
        photos = [photo(1, 0), photo(2, 3.6, emb=EMB_A2)]
        assert len(group_shots(photos, profile="event")) == 1

    def test_cumulative_drift_bounds_a_group(self):
        """Sequential chaining compares each frame only to its predecessor,
        so a pan can walk a group arbitrarily far from where it started (a
        real 39-frame group spanned 0.354 first-to-last). Every frame is also
        checked against the group's first."""
        # Each step is ~0.01 — far inside SHOT_EMBEDDING_DIST, so the
        # per-step check never fires — but they accumulate past 0.25.
        drift = [(1.0, 0.0, 0.0), (0.99, 0.14, 0.0), (0.96, 0.28, 0.0),
                 (0.92, 0.39, 0.0), (0.87, 0.49, 0.0), (0.81, 0.59, 0.0),
                 (0.74, 0.67, 0.0), (0.66, 0.75, 0.0)]
        photos = [photo(i + 1, i * 0.3, emb=e) for i, e in enumerate(drift)]
        shots = group_shots(photos)
        assert len(shots) > 1, "unbounded drift is over-merge (§3)"

    def test_subject_change_splits(self):
        photos = [photo(1, 0, faces=1, faceprint=EMB_A),
                  photo(2, 0.5, faces=1, faceprint=EMB_B)]
        assert len(group_shots(photos)) == 2

    def test_pose_boundary_portrait_only(self):
        """Pose repositioning splits in portrait profile, not event (§3)."""
        photos = [photo(1, 0, pose=EMB_A, pose_conf=0.9),
                  photo(2, 0.5, pose=EMB_B, pose_conf=0.9)]
        assert len(group_shots(photos, profile="portrait")) == 2
        assert len(group_shots(photos, profile="event")) == 1

    def test_subsec_orders_burst_frames(self):
        """Whole-second timestamps + subsec must give deterministic order."""
        photos = [photo(2, 1, subsec=500), photo(1, 1, subsec=100),
                  photo(3, 1, subsec=900)]
        shots = group_shots(photos)
        assert shots[0].member_ids == [1, 2, 3]

    def test_bracket_sealed_inside_shot_stream(self):
        """Bracket in the middle of a burst becomes its own sealed group,
        never merged (§3 bracket exclusion)."""
        stream = [
            photo(1, 0.0), photo(2, 0.4),                      # burst
            photo(3, 3.0, bias=-2.0), photo(4, 3.5, bias=0.0),  # bracket
            photo(5, 4.0, bias=2.0),
            photo(6, 7.0), photo(7, 7.4),                      # burst
        ]
        shots = group_shots(stream)
        bracket = [g for g in shots if g.is_bracket]
        assert len(bracket) == 1
        assert bracket[0].member_ids == [3, 4, 5]
        normal = [g.member_ids for g in shots if not g.is_bracket]
        assert normal == [[1, 2], [6, 7]]


class TestPoseGrouping:
    def test_cross_session_matching(self):
        """Same pose separated in time clusters together (§4) — the opposite
        of shot grouping."""
        photos = [photo(1, 0, pose=EMB_A, pose_conf=0.9),
                  photo(2, 3600, pose=EMB_A2, pose_conf=0.9),
                  photo(3, 7200, pose=EMB_B, pose_conf=0.9)]
        poses = group_poses(photos)
        assert sorted(sorted(g.member_ids) for g in poses) == [[1, 2], [3]]

    def test_low_confidence_unassigned_not_junk_clustered(self):
        photos = [photo(1, 0, pose=EMB_A, pose_conf=0.9),
                  photo(2, 10, pose=EMB_A, pose_conf=0.2)]  # seated/occluded
        poses = group_poses(photos)
        clustered = {pid for g in poses for pid in g.member_ids}
        assert 2 not in clustered


class TestPersonIdentity:
    def test_same_faceprint_clusters(self):
        photos = [photo(1, 0, faceprints=(EMB_A,)),
                  photo(2, 10, faceprints=(EMB_A2,)),
                  photo(3, 20, faceprints=(EMB_B,))]
        persons = group_persons(photos)
        assert sorted(sorted(g.member_ids) for g in persons) == [[1, 2], [3]]

    def test_multi_person_photo_in_multiple_clusters(self):
        """person is an orthogonal axis: one photo, three people (§1)."""
        photos = [photo(1, 0, faceprints=(EMB_A, EMB_B)),
                  photo(2, 10, faceprints=(EMB_A2,))]
        persons = group_persons(photos)
        containing_1 = [g for g in persons if 1 in g.member_ids]
        assert len(containing_1) == 2

    def test_borderline_faces_split_not_merged(self):
        """Conservative threshold: distance just past the limit → two
        clusters. A merge silently corrupts 'best of each person' (§5)."""
        # cos distance between this and EMB_A = 1 - 0.6 = 0.4 > 0.35 threshold
        near = (0.6, 0.8, 0.0)
        photos = [photo(1, 0, faceprints=(EMB_A,)),
                  photo(2, 10, faceprints=(near,))]
        assert len(group_persons(photos)) == 2


class TestPins:
    """§7 — manual corrections survive regrouping."""

    def test_split_pin(self):
        from shootr.grouping import Group
        shots = [Group("shot", [1, 2, 3, 4])]
        out = apply_pins(shots, [Pin(photo_id=3, kind="split_before")])
        assert [g.member_ids for g in out] == [[1, 2], [3, 4]]

    def test_merge_pin(self):
        from shootr.grouping import Group
        shots = [Group("shot", [1, 2]), Group("shot", [3])]
        out = apply_pins(shots, [Pin(photo_id=3, kind="merge_with_prev")])
        assert [g.member_ids for g in out] == [[1, 2, 3]]

    def test_pins_never_break_brackets(self):
        from shootr.grouping import Group
        shots = [Group("shot", [1, 2, 3], is_bracket=True), Group("shot", [4])]
        out = apply_pins(shots, [
            Pin(photo_id=2, kind="split_before"),
            Pin(photo_id=4, kind="merge_with_prev"),
        ])
        assert [g.member_ids for g in out] == [[1, 2, 3], [4]]
        assert out[0].is_bracket

    def test_reapplied_after_regroup(self):
        """The workflow: regroup from scratch, re-apply the same pins —
        the manual split is still there."""
        burst = [photo(i, i * 0.2) for i in range(1, 6)]
        pins = [Pin(photo_id=4, kind="split_before")]
        for _ in range(2):  # regroup twice; pin persists both times
            shots = apply_pins(group_shots(burst), pins)
            assert [g.member_ids for g in shots] == [[1, 2, 3], [4, 5]]
