"""What the user's overrides actually tell us (design 06 §7, 04 §7).

Overrides are the precise ground truth: few, but made directly on our own
proposals rather than inferred from a catalog confounded by client needs and
deletions. This module turns them into the two things they can honestly
support.

**1. Measurement.** Every promotion is a labelled pair — "this frame beat the
one you picked, in this group". Fed through the same pairwise check as the
`lr_history` fit, it answers "is the engine's ordering getting better or worse
for this user" on data that is unambiguously about *our* output.

**2. One adaptable number: `keep_n`.** Deliberately not a weight fit. Weight
fitting was measured against 559 real keepers and came out at chance —
within-group ordering among technically-equal frames is under-determined at
frame level (04 §7) — and a few dozen overrides cannot beat what thousands of
keepers could not. Breadth, however, is a single scalar with an unambiguous
signal: if the user keeps promoting extra frames per group, they want a wider
net; if they keep rejecting our picks outright, a narrower one.

Nothing here changes behaviour on its own. The suggestion is reported so the
user (or a caller) decides — silently re-tuning someone's cull from a handful
of clicks is exactly the kind of unexplained change this project avoids.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import culling


@dataclass
class OverridePair:
    """The user preferred `winner` over `loser`, inside one group."""

    group_id: int
    winner: int
    loser: int


@dataclass
class OverrideReport:
    overrides: int = 0
    promotions: int = 0        # → pick, against our judgement
    demotions: int = 0         # our pick → alt/reject
    pairs: list[OverridePair] = field(default_factory=list)
    # Ordering agreement on those pairs: did our score already rank the
    # user's preferred frame higher? nan when there is nothing to judge.
    ordering_agreement: float | None = None
    engine_keep_rate: float | None = None
    user_keep_rate: float | None = None
    suggested_keep_rate: float | None = None
    profile: str | None = None
    note: str = ""


def _keep_rate(entries: list[sqlite3.Row], key: str) -> float | None:
    groups: dict[int, list[sqlite3.Row]] = {}
    for e in entries:
        if e["group_id"] is not None:
            groups.setdefault(e["group_id"], []).append(e)
    if not groups:
        return None
    kept = total = 0
    for members in groups.values():
        total += len(members)
        kept += sum(1 for m in members if m[key] == "pick")
    return kept / total if total else None


def report(conn: sqlite3.Connection, selection_id: int) -> OverrideReport:
    rows = conn.execute(
        "SELECT se.photo_id, se.group_id, se.state, se.user_override, "
        "se.reason, s.total AS score, sh.profile "
        "FROM selection_entry se "
        "JOIN selection sel ON sel.id = se.selection_id "
        "JOIN shoot sh ON sh.id = sel.shoot_id "
        "LEFT JOIN score s ON s.photo_id = se.photo_id "
        "  AND s.profile = sh.profile "
        "WHERE se.selection_id = ?", (selection_id,)).fetchall()
    out = OverrideReport()
    if not rows:
        out.note = "no such selection, or it has no entries"
        return out
    out.profile = rows[0]["profile"]

    by_group: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        if r["group_id"] is not None:
            by_group.setdefault(r["group_id"], []).append(r)

    overridden = [r for r in rows if r["user_override"]]
    out.overrides = len(overridden)
    out.promotions = sum(1 for r in overridden if r["state"] == "pick")
    out.demotions = out.overrides - out.promotions

    # Pairs: a promoted frame beat every non-promoted frame the engine
    # preferred in the same group. Groups the user never touched say nothing
    # about ordering — silence is not agreement.
    agree = judged = 0
    for gid, members in by_group.items():
        promoted = [m for m in members if m["user_override"]
                    and m["state"] == "pick"]
        if not promoted:
            continue
        engine_picked = [m for m in members if not m["user_override"]
                         and m["state"] == "pick"]
        for w in promoted:
            for loser in engine_picked:
                out.pairs.append(OverridePair(gid, w["photo_id"],
                                              loser["photo_id"]))
                if w["score"] is None or loser["score"] is None:
                    continue
                judged += 1
                agree += w["score"] > loser["score"]
    if judged:
        out.ordering_agreement = agree / judged

    out.engine_keep_rate = _keep_rate(
        [r for r in rows if not r["user_override"]], "state")
    out.user_keep_rate = _keep_rate(rows, "state")

    # keep_n breadth: only suggest when there is enough signal to mean
    # something. A handful of clicks is a mood, not a pattern.
    if out.overrides >= 20 and out.user_keep_rate and out.profile:
        current, cap = culling.KEEP_RATES[out.profile]
        out.suggested_keep_rate = round(
            min(cap / 1.0, max(0.05, out.user_keep_rate)), 3)
        direction = "wider" if out.suggested_keep_rate > current else "narrower"
        out.note = (
            f"{out.overrides} overrides say you want a {direction} net: "
            f"your realized keep rate is {out.user_keep_rate:.0%} vs the "
            f"profile's {current:.0%}. Suggestion only — nothing was changed.")
    else:
        out.note = (f"{out.overrides} overrides — too few to suggest a keep "
                    f"rate (needs 20). Ordering agreement is still reported.")
    return out
