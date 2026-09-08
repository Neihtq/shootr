"""Grouping & clustering (docs/design/05-grouping.md).

Builds the hierarchy culling operates on. The SHOT group is the cull unit.
All grouping reads `analysis` outputs and never re-decodes — cheap and
recomputable, which is what makes thresholds tunable live (design 05 §6).

Order of operations matters: brackets are detected FIRST and sealed
(design 05 §3) so a 3-frame HDR set can never be merged into a normal shot
group and culled to one frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Starting thresholds — explicitly tunable, not fixed (design 05 §2, §8).
SCENE_TIME_GAP_S = 8 * 60
SCENE_SHORT_GAP_S = 90
SCENE_EMBEDDING_DIST = 0.45
# Shot time gap is profile-dependent: a portrait/event burst is seconds
# apart, but landscape cadence is compose–wait–shoot. Measured on real files
# (271 landscape frames, 2026-08): consecutive frames <10 s apart have
# median embedding distance 0.020 — the embedding check is the real gate;
# the time gap only needs to catch "walked away and came back".
#
# Raised for portrait/event after measuring a real 1232-frame event shoot
# (2026-08): at 3 s the time gap alone split 146 consecutive pairs whose
# embeddings were near-identical — a photographer shooting the same setup
# every ~3.5 s got one group per frame, which saves them nothing. Frames
# that ARE near-identical (dist <= 0.10) sit p95 = 4.3 s apart, p99 = 12 s,
# so the gap has to clear ~12 s to stop cutting through single setups.
SHOT_TIME_GAP_S: dict[str, float] = {
    "portrait": 8.0,
    "event": 8.0,
    "landscape": 20.0,
    "street": 5.0,
}
SHOT_EMBEDDING_DIST = 0.20
# Cumulative drift cap. Sequential chaining compares each frame only to its
# predecessor, so a slowly panning sequence can walk arbitrarily far from
# where the group started: the same shoot produced a 39-frame group whose
# first and last frames were 0.354 apart, well past the per-step gate. Every
# frame is also checked against the group's FIRST frame, which bounds a
# group to one recognizable setup. Looser than the per-step threshold —
# genuine burst drift is real, unbounded drift is over-merge (design 05 §3).
SHOT_ANCHOR_DIST = 0.25
# A face-count change is only trusted as a boundary when the framing also
# moved. Vision's detector flickers on the same shot — on the event shoot
# above, 26% of near-identical consecutive pairs (dist <= 0.10, <= 10 s)
# disagreed on face count, median delta 1, max 7. Treating that as "people
# entered or left" was the single largest source of over-splitting: it alone
# turned 130 real groups into 527. Corroboration keeps the signal for actual
# entrances (where framing shifts too) and drops the flicker.
SHOT_FACE_COUNT_CORROBORATION_DIST = 0.10
POSE_DIST = 0.35

BRACKET_MAX_GAP_S = 2.0
BRACKET_MIN_FRAMES = 3
BRACKET_EMBEDDING_DIST = 0.10

PERSON_MERGE_DIST = 0.35  # conservative: prefer split over merge (§5)
POSE_MERGE_DIST = 0.35
MIN_POSE_CONFIDENCE = 0.5  # below → unassigned, never a junk cluster (§4)


@dataclass(frozen=True)
class PhotoFeatures:
    """Per-photo inputs, all from `analysis`/`face` rows."""

    photo_id: int
    captured_at: datetime
    subsec: int = 0
    exposure_bias: float = 0.0
    embedding: tuple[float, ...] | None = None  # scene feature print
    face_count: int = 0
    primary_faceprint: tuple[float, ...] | None = None
    pose: tuple[float, ...] | None = None  # normalized keypoint vector
    pose_confidence: float = 0.0
    faceprints: tuple[tuple[float, ...], ...] = ()

    def sort_key(self) -> tuple:
        return (self.captured_at, self.subsec)


@dataclass
class Group:
    level: str  # scene | shot | pose | person
    member_ids: list[int]
    is_bracket: bool = False
    parent: "Group | None" = None


@dataclass
class GroupingResult:
    scenes: list[Group] = field(default_factory=list)
    shots: list[Group] = field(default_factory=list)
    poses: list[Group] = field(default_factory=list)
    persons: list[Group] = field(default_factory=list)


def _dist(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> float:
    """Cosine distance; unknown embeddings compare as maximally distant so a
    missing measurement never causes a silent merge."""
    if a is None or b is None:
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


def _gap_s(a: PhotoFeatures, b: PhotoFeatures) -> float:
    base = (b.captured_at - a.captured_at).total_seconds()
    return base + (b.subsec - a.subsec) / 1000.0


# ---------------------------------------------------------------------------
# Bracket detection (design 04 §6) — runs before everything else


def detect_brackets(photos: list[PhotoFeatures]) -> list[list[PhotoFeatures]]:
    """≥3 frames, <2 s apart, exposure_bias forming a progression through
    zero with symmetric extremes (e.g. -2/0/+2), near-identical scene.
    Getting this wrong destroys HDR sets (explicit test case)."""
    photos = sorted(photos, key=PhotoFeatures.sort_key)
    brackets: list[list[PhotoFeatures]] = []
    run: list[PhotoFeatures] = []

    def flush():
        if len(run) >= BRACKET_MIN_FRAMES and _is_bracket_run(run):
            brackets.append(list(run))
        run.clear()

    for photo in photos:
        if not run:
            run.append(photo)
            continue
        close = _gap_s(run[-1], photo) <= BRACKET_MAX_GAP_S
        similar = _dist(run[-1].embedding, photo.embedding) <= BRACKET_EMBEDDING_DIST
        differs = photo.exposure_bias != run[-1].exposure_bias
        if close and similar and differs:
            run.append(photo)
        else:
            flush()
            run.append(photo)
    flush()
    return brackets


def _is_bracket_run(run: list[PhotoFeatures]) -> bool:
    biases = [p.exposure_bias for p in run]
    if len(set(biases)) < len(biases):
        return False  # repeated bias → burst with dial wiggle, not a bracket
    lo, hi = min(biases), max(biases)
    if lo >= 0 or hi <= 0:
        return False  # brackets straddle the metered exposure
    return abs(lo + hi) <= 0.5  # symmetric progression, e.g. -2/0/+2


# ---------------------------------------------------------------------------
# Scene grouping (§2) — navigation only; errors are cosmetic


def group_scenes(photos: list[PhotoFeatures]) -> list[Group]:
    ordered = sorted(photos, key=PhotoFeatures.sort_key)
    if not ordered:
        return []
    groups = [Group("scene", [ordered[0].photo_id])]
    for prev, cur in zip(ordered, ordered[1:]):
        gap = _gap_s(prev, cur)
        # Long gap decisive; short gap needs visual confirmation (§2).
        if gap > SCENE_TIME_GAP_S or (
            gap > SCENE_SHORT_GAP_S
            and _dist(prev.embedding, cur.embedding) > SCENE_EMBEDDING_DIST
        ):
            groups.append(Group("scene", []))
        groups[-1].member_ids.append(cur.photo_id)
    return groups


# ---------------------------------------------------------------------------
# Shot grouping (§3) — THE cull unit; sequential, never global


def group_shots(photos: list[PhotoFeatures],
                profile: str = "event") -> list[Group]:
    """Walk in capture order; new group when ANY boundary fires. k-means over
    a whole shoot would happily group frames from opposite ends of a wedding.
    Brackets are sealed as their own is_bracket groups."""
    ordered = sorted(photos, key=PhotoFeatures.sort_key)
    if not ordered:
        return []

    bracket_ids: dict[int, int] = {}  # photo_id → bracket index
    bracket_runs = detect_brackets(ordered)
    for i, run in enumerate(bracket_runs):
        for p in run:
            bracket_ids[p.photo_id] = i

    groups: list[Group] = []
    emitted_brackets: set[int] = set()
    current: Group | None = None
    prev: PhotoFeatures | None = None
    anchor: PhotoFeatures | None = None  # first frame of `current`

    for cur in ordered:
        b = bracket_ids.get(cur.photo_id)
        if b is not None:
            if b not in emitted_brackets:
                groups.append(Group(
                    "shot",
                    [p.photo_id for p in bracket_runs[b]],
                    is_bracket=True,
                ))
                emitted_brackets.add(b)
            current = None  # bracket is also a shot boundary
            anchor = None
            prev = cur
            continue

        if current is None or prev is None \
                or _shot_boundary(prev, cur, profile, anchor):
            current = Group("shot", [])
            groups.append(current)
            anchor = cur  # first frame of the new group
        current.member_ids.append(cur.photo_id)
        prev = cur

    return groups


def _shot_boundary(prev: PhotoFeatures, cur: PhotoFeatures, profile: str,
                   anchor: PhotoFeatures | None = None) -> bool:
    """`anchor` is the group's first frame — see SHOT_ANCHOR_DIST. Passing
    None disables the drift check (callers testing a single step)."""
    if _gap_s(prev, cur) > SHOT_TIME_GAP_S.get(profile, 3.0):
        return True  # shutter released
    if _dist(prev.embedding, cur.embedding) > SHOT_EMBEDDING_DIST:
        return True  # framing/scene changed
    if anchor is not None and anchor.photo_id != prev.photo_id \
            and _dist(anchor.embedding, cur.embedding) > SHOT_ANCHOR_DIST:
        return True  # drifted too far from where this group started
    if prev.face_count != cur.face_count and _dist(
            prev.embedding, cur.embedding
    ) > SHOT_FACE_COUNT_CORROBORATION_DIST:
        return True  # people entered/left (framing corroborates it)
    if _dist(prev.primary_faceprint, cur.primary_faceprint) > PERSON_MERGE_DIST \
            and prev.primary_faceprint is not None \
            and cur.primary_faceprint is not None:
        return True  # different subject
    if profile == "portrait" and prev.pose is not None and cur.pose is not None \
            and _dist(prev.pose, cur.pose) > POSE_DIST:
        return True  # subject repositioned (portrait only, §3)
    return False


# ---------------------------------------------------------------------------
# Pose grouping (§4) — portrait only, agglomerative, cross-session


def group_poses(photos: list[PhotoFeatures]) -> list[Group]:
    """Agglomerative over the whole shoot — the opposite of shot grouping,
    because here time-distant matches are the point ("every frame of the
    seated pose"). Low-confidence poses stay unassigned, never junk-clustered."""
    eligible = [p for p in photos
                if p.pose is not None and p.pose_confidence >= MIN_POSE_CONFIDENCE]
    clusters = _agglomerate(
        [(p.photo_id, p.pose) for p in eligible], POSE_MERGE_DIST)
    return [Group("pose", ids) for ids in clusters]


# ---------------------------------------------------------------------------
# Person identity (§5) — conservative threshold, per-shoot only


def group_persons(photos: list[PhotoFeatures]) -> list[Group]:
    """Cluster faceprints within a shoot. Threshold prefers splitting one
    person in two over merging two people: a merge silently corrupts
    "best of each person"; a split is visible and mergeable in the UI."""
    items: list[tuple[int, tuple[float, ...]]] = []
    for p in photos:
        for fp in p.faceprints:
            items.append((p.photo_id, fp))
    clusters = _agglomerate(items, PERSON_MERGE_DIST)
    # One photo can appear in several person groups (three people in frame).
    return [Group("person", sorted(set(ids))) for ids in clusters]


def _agglomerate(items: list[tuple[int, tuple[float, ...]]],
                 threshold: float) -> list[list[int]]:
    """Single-linkage agglomerative clustering, brute force. Fine at shoot
    scale (design 05 §6); revisit with blocking if faces exceed ~20k."""
    clusters: list[tuple[list[int], list[tuple[float, ...]]]] = []
    for pid, vec in items:
        best = None
        best_d = threshold
        for cluster in clusters:
            d = min(_dist(vec, v) for v in cluster[1])
            if d <= best_d:
                best, best_d = cluster, d
        if best is None:
            clusters.append(([pid], [vec]))
        else:
            best[0].append(pid)
            best[1].append(vec)
    return [ids for ids, _ in clusters]


# ---------------------------------------------------------------------------
# User corrections (§7) — pins survive regrouping


@dataclass(frozen=True)
class Pin:
    """A manual correction. `split_before` starts a new group at that photo;
    `merge_with_prev` joins a photo's group to the preceding one."""

    photo_id: int
    kind: str  # split_before | merge_with_prev


def apply_pins(shots: list[Group], pins: list[Pin]) -> list[Group]:
    """Re-applied after every regroup: if re-running clustering silently
    erased manual splits, users would lose work and stop correcting (§7)."""
    result = [Group(g.level, list(g.member_ids), g.is_bracket) for g in shots]

    for pin in pins:
        if pin.kind == "split_before":
            for i, g in enumerate(result):
                if pin.photo_id in g.member_ids and not g.is_bracket:
                    at = g.member_ids.index(pin.photo_id)
                    if at == 0:
                        break  # already a group start
                    head, tail = g.member_ids[:at], g.member_ids[at:]
                    result[i] = Group(g.level, head, g.is_bracket)
                    result.insert(i + 1, Group(g.level, tail))
                    break
        elif pin.kind == "merge_with_prev":
            for i, g in enumerate(result):
                if pin.photo_id in g.member_ids:
                    if i == 0 or g.is_bracket or result[i - 1].is_bracket:
                        break  # never merge into/out of a bracket
                    result[i - 1].member_ids.extend(g.member_ids)
                    del result[i]
                    break
    return result
