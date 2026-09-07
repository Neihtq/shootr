"""Override-learning tests (design 06 §7).

The restraint is the design: overrides adjust ONE number (keep_n breadth) and
otherwise only measure, because weight fitting was already shown to be at
chance against 559 real keepers (04 §7). These tests pin that restraint so a
future change has to argue with it rather than drift past it.
"""

import pytest

from shootr.db import connect
from shootr.overrides import report


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "shootr.db")
    c.execute("INSERT INTO library (id, root_path, created_at) "
              "VALUES (1, '/lib', 'now')")
    c.execute("INSERT INTO shoot (id, library_id, name, profile, created_at) "
              "VALUES (1, 1, 's', 'event', 'now')")
    c.execute("INSERT INTO selection (id, shoot_id, created_at, params) "
              "VALUES (1, 1, 'now', '{}')")
    yield c
    c.close()


def add_group(c, gid, frames):
    """frames = [(photo_id, state, user_override, score)]"""
    c.execute('INSERT INTO "group" (id, shoot_id, level) '
              "VALUES (?, 1, 'shot')", (gid,))
    for pid, state, override, score in frames:
        c.execute(
            "INSERT INTO photo (id, library_id, shoot_id, content_id, "
            "rel_path, filename, file_size, mtime) "
            "VALUES (?, 1, 1, ?, ?, ?, 1, 0)",
            (pid, f"c{pid}", f"IMG_{pid}.CR3", f"IMG_{pid}.CR3"))
        c.execute("INSERT INTO group_member (group_id, photo_id) "
                  "VALUES (?, ?)", (gid, pid))
        c.execute("INSERT INTO score (photo_id, profile, total, components, "
                  "flags, weights_hash) VALUES (?, 'event', ?, '{}', '[]', "
                  "'h')", (pid, score))
        c.execute(
            "INSERT INTO selection_entry (selection_id, photo_id, group_id, "
            "state, user_override) VALUES (1, ?, ?, ?, ?)",
            (pid, gid, state, override))
    c.commit()


def test_promotion_becomes_a_labelled_pair_against_our_pick(conn):
    add_group(conn, 1, [(1, "pick", 0, 0.80),    # engine's choice
                        (2, "pick", 1, 0.60),    # user promoted this
                        (3, "reject", 0, 0.40)])
    r = report(conn, 1)
    assert r.overrides == 1 and r.promotions == 1 and r.demotions == 0
    assert len(r.pairs) == 1
    assert (r.pairs[0].winner, r.pairs[0].loser) == (2, 1)
    # Our score had it backwards — that must show as disagreement, not be
    # quietly averaged away.
    assert r.ordering_agreement == 0.0


def test_ordering_agreement_counts_the_cases_we_got_right(conn):
    add_group(conn, 1, [(1, "pick", 0, 0.50), (2, "pick", 1, 0.90)])
    add_group(conn, 2, [(3, "pick", 0, 0.90), (4, "pick", 1, 0.10)])
    r = report(conn, 1)
    assert len(r.pairs) == 2
    assert r.ordering_agreement == 0.5


def test_untouched_groups_are_not_counted_as_agreement(conn):
    """Silence is not agreement: a group the user never corrected says
    nothing about whether our ordering was right."""
    add_group(conn, 1, [(1, "pick", 0, 0.9), (2, "reject", 0, 0.2)])
    add_group(conn, 2, [(3, "pick", 0, 0.8), (4, "reject", 0, 0.3)])
    r = report(conn, 1)
    assert r.pairs == [] and r.ordering_agreement is None
    assert r.overrides == 0


def test_no_keep_rate_suggestion_from_a_handful_of_clicks(conn):
    add_group(conn, 1, [(1, "pick", 0, 0.8), (2, "pick", 1, 0.7)])
    r = report(conn, 1)
    assert r.suggested_keep_rate is None
    assert "too few" in r.note


def test_enough_overrides_suggest_breadth_but_change_nothing(conn):
    # 12 groups of 4, user promotes 2 extra per group → a much wider net.
    pid = 1
    for gid in range(1, 13):
        frames = [(pid, "pick", 0, 0.9), (pid + 1, "pick", 1, 0.8),
                  (pid + 2, "pick", 1, 0.7), (pid + 3, "reject", 0, 0.2)]
        add_group(conn, gid, frames)
        pid += 4
    r = report(conn, 1)
    assert r.overrides == 24 and r.promotions == 24
    assert r.user_keep_rate == pytest.approx(0.75)
    assert r.engine_keep_rate == pytest.approx(0.5)  # excludes overridden
    assert r.suggested_keep_rate == pytest.approx(0.75)
    assert "wider net" in r.note and "nothing was changed" in r.note
    # The profile itself is untouched — suggestions are not applications.
    from shootr.culling import KEEP_RATES
    assert KEEP_RATES["event"][0] == 0.20


def test_demotions_are_counted_separately(conn):
    add_group(conn, 1, [(1, "reject", 1, 0.9), (2, "pick", 0, 0.5)])
    r = report(conn, 1)
    assert r.demotions == 1 and r.promotions == 0
    # A demotion alone yields no ordering pair: the user said "not this one",
    # not "that one instead".
    assert r.pairs == []
