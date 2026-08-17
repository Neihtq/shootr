"""Invariant tests for culling (design 06). Each test names the doc rule."""

from shootr.culling import CullCandidate, CullGroup, cull, cull_group, keep_n


def cand(pid, total, embedding=None, eyes_open=None, eye_focus=None,
         blinking=0, persons=()):
    return CullCandidate(
        photo_id=pid, total=total, embedding=embedding,
        eyes_open=eyes_open, eye_focus=eye_focus,
        other_subjects_blinking=blinking, person_ids=frozenset(persons),
    )


class TestBracketGuard:
    """design 04 §6 / 06 §6 — the explicit 'destroys HDR sets' test."""

    def test_bracket_group_all_picked(self):
        g = CullGroup(1, [cand(1, 0.9), cand(2, 0.2), cand(3, 0.5)],
                      is_bracket=True)
        entries, no_good = cull_group(g, "landscape")
        assert all(e.state == "pick" for e in entries)
        assert len(entries) == 3
        assert not no_good

    def test_dark_bracket_frame_never_rejected(self):
        """The -2EV frame scores terribly; it must still be kept."""
        g = CullGroup(1, [cand(1, 0.8), cand(2, 0.05), cand(3, 0.7)],
                      is_bracket=True)
        entries, _ = cull_group(g, "landscape")
        assert {e.photo_id: e.state for e in entries}[2] == "pick"


class TestKeepN:
    def test_sublinear_scaling(self):
        assert keep_n(9, "event") == 2  # ceil(9*0.2)
        assert keep_n(30, "event") == 3  # capped
        assert keep_n(1, "event") == 1  # floor
        assert keep_n(9, "street") == 6  # weak ranking → keep more

    def test_street_keeps_more_than_event(self):
        """Aggressiveness scales with confidence (design 06 §2.1)."""
        assert keep_n(10, "street") > keep_n(10, "event")


class TestDiversity:
    def test_near_duplicates_not_all_picked(self):
        """Top 3 of a burst must not be 3 identical frames (design 06 §2.2)."""
        dup_a = cand(1, 0.90, embedding=(1.0, 0.0))
        dup_b = cand(2, 0.89, embedding=(1.0, 0.01))  # ~same instant
        distinct = cand(3, 0.80, embedding=(0.0, 1.0))
        filler = [cand(i, 0.3, embedding=(1.0, 0.0)) for i in range(4, 10)]
        g = CullGroup(1, [dup_a, dup_b, distinct] + filler)
        entries, _ = cull_group(g, "portrait")  # keep_n = ceil(9*.35) = 4
        states = {e.photo_id: e.state for e in entries}
        assert states[1] == "pick"
        assert states[3] == "pick"  # diversity promoted the distinct frame

    def test_fewest_blinking_preferred_in_group_shots(self):
        worse_score_fewer_blinks = cand(1, 0.70, blinking=0)
        better_score_more_blinks = cand(2, 0.75, blinking=3)
        g = CullGroup(1, [worse_score_fewer_blinks, better_score_more_blinks])
        entries, _ = cull_group(g, "event")  # keep_n = 1
        top = next(e for e in entries if e.rank == 1)
        assert top.photo_id == 1


class TestQualityFloor:
    def test_bad_group_gets_alt_not_pick(self):
        """Decline to recommend, never hide (design 06 §2.3)."""
        g = CullGroup(7, [cand(1, 0.2), cand(2, 0.1)])
        entries, no_good = cull_group(g, "event")
        assert no_good
        assert all(e.state == "alt" for e in entries)
        assert not any(e.state == "reject" for e in entries)

    def test_no_good_frame_groups_reported(self):
        groups = [CullGroup(1, [cand(1, 0.9), cand(2, 0.8)]),
                  CullGroup(2, [cand(3, 0.1)])]
        proposal = cull(groups, "event")
        assert proposal.no_good_frame_groups == [2]


class TestOverrides:
    """design 01 invariant 5 — user overrides are sacred."""

    def test_override_survives_regeneration(self):
        g = CullGroup(1, [cand(i, 0.9 - i * 0.1) for i in range(1, 6)])
        proposal = cull([g], "event", overrides={5: "pick"})
        e = proposal.by_photo()[5]
        assert e.state == "pick"
        assert "override" in e.reason

    def test_override_can_demote_engine_pick(self):
        g = CullGroup(1, [cand(1, 0.9), cand(2, 0.5)])
        proposal = cull([g], "event", overrides={1: "reject"})
        assert proposal.by_photo()[1].state == "reject"


class TestCoverageGuard:
    """design 06 §6 — 'no photo of the bride's grandmother'."""

    def test_person_with_all_rejects_gets_promotion(self):
        # Grandmother (person 42) only appears in the weak tail of a big
        # event group; all her frames would be rejected.
        strong = [cand(i, 0.9, embedding=(1.0, 0.0)) for i in range(1, 9)]
        grandma = [cand(20, 0.30, persons=(42,)),
                   cand(21, 0.25, persons=(42,))]
        g = CullGroup(1, strong + grandma)  # 10 members, event keep_n=2
        proposal = cull([g], "event")
        states = {e.photo_id: e.state
                  for e in proposal.entries if e.photo_id in (20, 21)}
        assert "pick" in states.values()
        promoted = proposal.by_photo()[20]
        assert promoted.state == "pick"  # 0.30 > 0.25 → best frame promoted
        assert "coverage guard" in promoted.reason

    def test_guard_respects_user_rejects(self):
        """Overrides outrank the guard — user said no, guard stays silent."""
        strong = [cand(i, 0.9) for i in range(1, 9)]
        grandma = [cand(20, 0.30, persons=(42,))]
        g = CullGroup(1, strong + grandma)
        proposal = cull([g], "event", overrides={20: "reject"})
        assert proposal.by_photo()[20].state == "reject"

    def test_guard_idle_when_person_has_a_pick(self):
        g = CullGroup(1, [cand(1, 0.9, persons=(42,)), cand(2, 0.5, persons=(42,))])
        proposal = cull([g], "event")
        reasons = [e.reason for e in proposal.entries]
        assert not any("coverage guard" in r for r in reasons)


class TestReasons:
    """design 06 §3 — every entry carries a justification."""

    def test_all_entries_have_reasons(self):
        g = CullGroup(1, [cand(i, 0.9 - i * 0.1) for i in range(1, 8)])
        entries, _ = cull_group(g, "event")
        assert all(e.reason for e in entries)

    def test_reject_reason_names_the_defect(self):
        g = CullGroup(1, [cand(1, 0.9), cand(2, 0.85), cand(3, 0.84),
                          cand(4, 0.2, eyes_open=0.15)])
        entries, _ = cull_group(g, "event")
        blink_reject = next(e for e in entries if e.photo_id == 4)
        assert blink_reject.state == "reject"
        assert "eyes closed" in blink_reject.reason
