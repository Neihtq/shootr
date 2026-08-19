# 05 — Grouping & Clustering

**Milestone:** M1 · **Depends on:** [03](03-analysis-engine.md) · **Feeds:** [06](06-culling.md)

Builds the hierarchy that culling operates on. The **shot group** is the unit that matters:
"you fired 9 frames of this pose, keep 1–2."

---

## 1. Four levels, different purposes

```
scene   (ceremony / portraits at the lake / reception)   ← navigation
  └ shot   (the 9 frames of one pose)                    ← THE CULL UNIT
      └ pose   (which pose, across the session)          ← portrait sessions only
person  (orthogonal axis: who is in frame)               ← cross-cuts everything
```

Levels 1–3 nest; `person` is orthogonal — one photo has one shot group but can contain
three people. Modeled as a separate `group.level='person'` tree rather than a nesting
level (§01).

Doing this hierarchically rather than as one flat clustering matters because the right
similarity threshold differs by an order of magnitude between "same event" and "same
press of the shutter." A single threshold either merges distinct poses or splits a burst.

---

## 2. Scene grouping

**Signals:** capture-time gaps + loose scene-embedding similarity.

```
new scene when:  time_gap > 8 min
             OR (time_gap > 90 s AND embedding_distance > 0.45)
```

Time alone over-splits (a lull in the ceremony isn't a new scene); embedding alone
over-merges (two different rooms with similar walls). The conjunction is what works:
a long gap is decisive; a short gap needs visual confirmation.

Embedding = `VNGenerateImageFeaturePrintRequest` (§03), cosine distance via Vision's own
`computeDistance`. Thresholds are starting values to be tuned on real files — noted as
tunable, not fixed.

Scenes are for **navigation and labeling**, not culling decisions. Errors here are cosmetic.

---

## 3. Shot grouping — the important one

A "shot" = consecutive frames of substantially the same composition and subject pose.
This is where culling happens, so both error directions are costly:

- **Over-merge** (two poses in one group) → the app discards a good alternate pose.
- **Over-split** (one burst into three groups) → the app keeps 3 near-identical frames and
  saves the user nothing.

**Sequential, not global, clustering.** Bursts are contiguous in time; k-means or DBSCAN
over the whole shoot ignores that and can group frames from opposite ends of a wedding.
Walk photos in capture order (`captured_at`, `subsec`) and start a new group when *any*
boundary condition fires:

```
boundary if:
     time_gap > 8 s   [portrait/event]                (shutter released)
                20 s  [landscape] · 5 s [street]
  OR embedding_distance > 0.20                        (framing/scene changed)
  OR embedding_distance(group_first_frame) > 0.25     (cumulative drift)
  OR (face_count changed AND embedding_distance > 0.10)
                                                      (people entered/left)
  OR primary_face_identity changed                    (different subject)
  OR pose_distance > 0.35   [portrait profile only]   (subject repositioned)
  OR is_bracket boundary                              (§04.6)
```

`subsec` matters here (§02): without subsecond ordering, burst frames sharing a
whole-second timestamp sort arbitrarily and sequential clustering breaks.

**Two of those clauses are guarded, both measured on a real 1232-frame event shoot
(2026-08) after it over-split into 527 groups with 282 singletons — half the shoot
was one-frame groups, which saves the user nothing:**

- **The face-count clause needs corroboration.** Vision's detector flickers between
  frames of the same shot: 26% of near-identical consecutive pairs (distance ≤ 0.10,
  ≤ 10 s apart) disagreed on face count, median delta 1, max 7. Uncorroborated, this
  single clause turned 130 real groups into 527. Requiring the framing to have moved
  too keeps real entrances and drops the flicker.
- **The time gap alone must not cut a setup.** At 3 s it split 146 consecutive pairs
  whose embeddings were near-identical. Frames that *are* near-identical sit p95 =
  4.3 s / p99 = 12 s apart, so portrait/event needs ≥ 8 s. The embedding check is the
  real gate; the gap only catches "walked away and came back".

**Cumulative drift cap** (`0.25` against the group's *first* frame). Sequential
chaining only ever compares neighbours, so a slow pan walks a group arbitrarily far
from where it began — the same shoot produced a 39-frame group whose first and last
frames were 0.354 apart, past the per-step gate that never fired. Looser than the
per-step threshold: genuine burst drift is real, unbounded drift is over-merge.

Result on that shoot: 204 groups, 35 singletons, median 3 frames.

**Camera burst metadata** (Canon/Sony/Fuji drive-mode and frame-sequence tags) is a
stronger signal than any inference when present — checked first, with the heuristics as
fallback. Availability across the three vendors is unverified; the benchmark set (§03.7)
should confirm.

### Bracket exclusion
Brackets are detected first (§04.6) and sealed as `is_bracket=1` groups. They must never
be merged into a normal shot group, or a 3-frame HDR set gets culled to 1.

---

## 4. Pose grouping

**Portrait profile only.** For events, shot groups already capture pose; for landscape and
street it's meaningless.

`VNDetectHumanBodyPoseRequest` joints → normalized vector:
1. Translate to hip midpoint.
2. Scale by torso length (shoulder-to-hip) — makes it distance-invariant.
3. Drop low-confidence joints; compare only jointly-visible pairs.

Purpose is **cross-session**: "show me every frame of the seated pose" across a session,
even when separated in time. Agglomerative clustering over the whole shoot (not
sequential) — the opposite of shot grouping, because here we *want* time-distant matches.

Genuinely weak when the subject is seated, occluded, or tightly cropped (no hips/shoulders
visible → normalization fails). Abstain rather than emit a garbage cluster: photos with
insufficient pose confidence go unassigned, not into a junk group.

---

## 5. Person identity

Vision faceprints → agglomerative clustering within a shoot.

Enables the most useful selection query in practice: *"best photo of each guest"* — often
more valuable than scene-based grouping for wedding delivery, since coverage of people is
what clients notice.

Honest limitations: faceprints degrade on profile views, small faces, harsh backlight, and
across large age gaps. Within a single event (consistent lighting, hours apart at most)
they work well; **across shoots they should not be trusted** — no persistent person
database in M1. Users can label clusters (`person.label`), and labels are per-shoot.

Conservative threshold: prefer splitting one person into two clusters over merging two
people. A merged cluster silently corrupts "best of each person"; a split is visible and
mergeable in the UI.

---

## 6. Cost and scale

At 10k photos:

| Step | Complexity | Cost |
|---|---|---|
| Scene | O(n) sequential | ms |
| Shot | O(n) sequential | ms |
| Pose | O(n²) agglomerative | ~50M float ops on ≤ ~2k posed frames — fine |
| Person | O(f²) on faces | ~20k faces → needs blocking |

Person clustering is the only quadratic risk. Mitigation: block by scene first, then merge
cluster representatives across scenes — reduces the comparison set by roughly an order of
magnitude. Brute-force numpy is fine at these sizes; no vector index needed until
whole-library scale (§01 open question).

All grouping is **cheap and recomputable** — it reads `analysis` and never re-decodes.
Re-running with different thresholds costs seconds, which is what makes the thresholds
tunable in the UI rather than baked in.

---

## 7. User control

Grouping errors are inevitable and must be correctable, since a wrong group directly
produces a wrong cull:

- **Split group** — user marks a frame as starting a new group.
- **Merge groups** — combine adjacent groups.
- **Move photo** between groups.
- **Threshold sliders** per shoot, with live regroup (cheap, per §6).

Manual edits are pinned and survive regrouping — same principle as `user_override` (§01
invariant 5). If re-running clustering silently erased manual splits, the user would lose
work and stop making corrections.

---

## 8. Open questions

- **Camera burst tags**: confirm availability for CR3/ARW/RAF in the benchmark set. If
  reliable, promote from "checked first" to primary and demote the heuristics.
- **Embedding thresholds** (0.20 shot / 0.45 scene) are guesses. Tune against
  hand-grouped real bursts; expect them to differ per genre (a wedding dance floor changes
  faster than a portrait session).
- **Scene-level pose for group photos**: when 8 people rearrange, per-person pose is
  noisy. Deferred.
