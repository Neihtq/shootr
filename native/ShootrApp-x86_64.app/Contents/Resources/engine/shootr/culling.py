"""Culling & selection (docs/design/06-culling.md).

Produces a proposal — pick / alt / reject — per shot group. Never deletes;
`reject` means "not chosen", nothing more (design 01 invariant 2). Pure
function over scored, grouped photos; cheap and re-runnable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

# design 06 §2.1: keep_n = clamp(ceil(group_size * rate), 1, cap).
# Street keeps the most BECAUSE the engine ranks it worst — aggressiveness
# scales with confidence, not uniformly.
KEEP_RATES: dict[str, tuple[float, int]] = {
    "portrait": (0.35, 5),
    "event": (0.20, 3),
    "landscape": (0.50, 4),
    "street": (0.60, 6),
}

DEFAULT_QUALITY_FLOOR = 0.35  # design 06 §2.3, profile-tunable
DIVERSITY_LAMBDA = 0.25  # design 06 §2.2
ALT_COUNT = 1  # runner-ups surfaced beyond keep_n


@dataclass(frozen=True)
class CullCandidate:
    photo_id: int
    total: float
    # Human-readable fragments pulled from the score record for reasons.
    eye_focus: float | None = None
    eyes_open: float | None = None
    # Similarity inputs for the diversity rule (scene embedding + pose).
    embedding: tuple[float, ...] | None = None
    other_subjects_blinking: int = 0  # group-photo special case (§2.2)
    person_ids: frozenset[int] = frozenset()  # coverage guard (§6)


@dataclass(frozen=True)
class CullGroup:
    group_id: int
    members: list[CullCandidate]
    is_bracket: bool = False


@dataclass(frozen=True)
class Entry:
    photo_id: int
    group_id: int
    state: str  # pick | alt | reject
    rank: int | None
    reason: str


@dataclass
class Proposal:
    entries: list[Entry] = field(default_factory=list)
    no_good_frame_groups: list[int] = field(default_factory=list)

    def by_photo(self) -> dict[int, Entry]:
        return {e.photo_id: e for e in self.entries}


def keep_n(group_size: int, profile: str) -> int:
    rate, cap = KEEP_RATES[profile]
    return max(1, min(cap, ceil(group_size * rate)))


def _similarity(a: CullCandidate, b: CullCandidate) -> float:
    if a.embedding is None or b.embedding is None:
        return 0.0
    dot = sum(x * y for x, y in zip(a.embedding, b.embedding))
    na = sum(x * x for x in a.embedding) ** 0.5
    nb = sum(x * x for x in b.embedding) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _rank_with_diversity(members: list[CullCandidate]) -> list[CullCandidate]:
    """Greedy: top frame first, then penalize by similarity to already-picked
    (design 06 §2.2). Prevents 'top 3 = 3 near-identical frames'."""
    remaining = sorted(members, key=lambda c: c.total, reverse=True)
    ranked: list[CullCandidate] = []
    while remaining:
        if not ranked:
            best = remaining[0]
        else:
            best = max(
                remaining,
                key=lambda c: c.total - DIVERSITY_LAMBDA
                * max(_similarity(c, p) for p in ranked),
            )
        ranked.append(best)
        remaining.remove(best)
    return ranked


def _reason(c: CullCandidate, state: str, ranked: list[CullCandidate],
            rank: int) -> str:
    if state == "pick":
        if rank == 1:
            runner = ranked[1].total if len(ranked) > 1 else None
            vs = f" ({c.total:.2f} vs {runner:.2f} next)" if runner is not None else ""
            return f"best in group{vs}"
        return f"rank {rank} pick after diversity spread"
    if state == "alt":
        return "credible runner-up; second choice is often the human's first"
    # reject — name the dominant defect where we can see one.
    if c.eyes_open is not None and c.eyes_open < 0.4:
        return f"eyes closed ({c.eyes_open:.2f})"
    if c.eye_focus is not None and c.eye_focus < 0.3:
        return f"focus missed ({c.eye_focus:.2f})"
    top = ranked[0]
    sim = _similarity(c, top)
    if sim > 0.9:
        return f"near-duplicate of pick #1 (similarity {sim:.2f})"
    return f"outscored in group ({c.total:.2f} vs {top.total:.2f} best)"


def _prefer_fewest_blinking(ranked: list[CullCandidate]) -> list[CullCandidate]:
    """Group-photo special case (design 06 §2.2): across a 6-frame group shot
    there is often no frame where everyone is perfect — the useful answer is
    the fewest problems, a set-level property."""
    if not any(c.other_subjects_blinking for c in ranked):
        return ranked
    return sorted(ranked, key=lambda c: (c.other_subjects_blinking, -c.total))


def cull_group(group: CullGroup, profile: str,
               floor: float = DEFAULT_QUALITY_FLOOR) -> tuple[list[Entry], bool]:
    """Returns (entries, no_good_frame)."""
    gid = group.group_id

    # 1. Brackets: every frame is a keeper — the dark one is SUPPOSED to be
    #    dark. Culling inside destroys HDR sets (design 04 §6, 06 §2 step 1).
    if group.is_bracket:
        return [
            Entry(c.photo_id, gid, "pick", None,
                  "exposure bracket — all frames kept")
            for c in group.members
        ], False

    # 2. Singletons: pick if above floor, else alt.
    if len(group.members) == 1:
        c = group.members[0]
        if c.total >= floor:
            return [Entry(c.photo_id, gid, "pick", 1, "only frame in group")], False
        return [Entry(c.photo_id, gid, "alt", 1,
                      f"only frame, below quality floor ({c.total:.2f} < {floor})")], True

    # 3–5. Rank, diversity, group-photo blink preference.
    ranked = _rank_with_diversity(group.members)
    ranked = _prefer_fewest_blinking(ranked)

    # 6. Quality floor: best-of-bad wastes review time and misrepresents
    #    confidence — decline to recommend, never hide (design 06 §2.3).
    if ranked[0].total < floor:
        return [
            Entry(c.photo_id, gid, "alt", i + 1,
                  f"no frame above quality floor; best is {ranked[0].total:.2f}")
            for i, c in enumerate(ranked)
        ], True

    # 7. Assign states.
    n = keep_n(len(group.members), profile)
    entries: list[Entry] = []
    for i, c in enumerate(ranked):
        rank = i + 1
        if i < n:
            state = "pick"
        elif i < n + ALT_COUNT:
            state = "alt"
        else:
            state = "reject"
        entries.append(Entry(c.photo_id, gid, state, rank,
                             _reason(c, state, ranked, rank)))
    return entries, False


def cull(groups: list[CullGroup], profile: str,
         floor: float = DEFAULT_QUALITY_FLOOR,
         overrides: dict[int, str] | None = None) -> Proposal:
    """Cull a whole shoot.

    `overrides` maps photo_id → state the user previously set. Overrides are
    sacred (design 01 invariant 5): regeneration must preserve every one.
    """
    overrides = overrides or {}
    proposal = Proposal()

    for group in groups:
        entries, no_good = cull_group(group, profile, floor)
        if no_good:
            proposal.no_good_frame_groups.append(group.group_id)
        proposal.entries.extend(entries)

    # User overrides replace engine states wholesale (design 06 §4).
    for i, e in enumerate(proposal.entries):
        if e.photo_id in overrides:
            proposal.entries[i] = Entry(
                e.photo_id, e.group_id, overrides[e.photo_id], e.rank,
                "user override — preserved across regeneration")

    _apply_coverage_guard(groups, proposal, overrides)
    return proposal


def _apply_coverage_guard(groups: list[CullGroup], proposal: Proposal,
                          overrides: dict[int, str]) -> None:
    """design 06 §6: if every frame of a person cluster would be rejected,
    promote its best to pick regardless of score. 'No photo of the bride's
    grandmother' is a delivery failure no per-photo score flags."""
    by_photo = proposal.by_photo()
    candidates = {c.photo_id: c for g in groups for c in g.members}

    person_photos: dict[int, list[int]] = {}
    for c in candidates.values():
        for pid in c.person_ids:
            person_photos.setdefault(pid, []).append(c.photo_id)

    for pid, photo_ids in person_photos.items():
        states = {ph: by_photo[ph].state for ph in photo_ids if ph in by_photo}
        if not states or any(s in ("pick", "alt") for s in states.values()):
            continue
        # All rejected. Promote the best-scoring frame — unless the user
        # explicitly rejected it themselves (overrides outrank the guard).
        eligible = [ph for ph in photo_ids if ph not in overrides]
        if not eligible:
            continue
        best = max(eligible, key=lambda ph: candidates[ph].total)
        old = by_photo[best]
        replacement = Entry(
            old.photo_id, old.group_id, "pick", old.rank,
            f"coverage guard — only frames of person {pid}, best promoted")
        idx = proposal.entries.index(old)
        proposal.entries[idx] = replacement
        by_photo[best] = replacement
