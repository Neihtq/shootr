# 06 — Culling & Selection

**Milestone:** M1 (M2 calibration) · **Depends on:** [04](04-quality-scoring.md), [05](05-grouping.md) · **Feeds:** [07](07-lightroom.md)

Proposes which photos to keep. **Never deletes anything** (README rule 2).

---

## 1. What "culling" means here

The app produces a **proposal**, not a decision. Three states per photo:

| State | Meaning | LrC mapping (§07) |
|---|---|---|
| `pick` | recommended keeper | flag = pick, rating ≥ 3 |
| `alt` | credible runner-up in its group | rating 2, no flag |
| `reject` | passed over | **no flag written by default** |

The `alt` tier exists because "keep 1 of 9" is often wrong — the engine's second choice is
frequently the human's first (a better expression the metrics can't see). Surfacing a
ranked alternate is cheap and preserves the user's ability to disagree quickly.

**`reject` writes nothing to disk by default.** Writing reject flags into the user's
catalog risks a mis-scored good photo being hidden behind a filter and never seen again.
Opt-in only, and clearly labelled.

---

## 2. Algorithm

Per shot group (the cull unit, §05):

```
1. exclude bracket groups           → all frames pick (§04.6)
2. if group size == 1               → pick if above floor, else alt
3. rank members by score.total
4. keep_n = f(group_size, profile)
5. apply diversity rule (§2.2)
6. apply quality floor (§2.3)
7. top keep_n → pick;  next m → alt;  rest → reject
8. attach reason string to every entry
```

### 2.1 How many to keep

Fixed "keep 1 per group" is wrong — a 3-frame group and a 30-frame group are different
situations. Sublinear scaling:

```
keep_n = clamp(ceil(group_size * rate), 1, cap)
```

| Profile | rate | cap | rationale |
|---|---|---|---|
| Portrait | 0.35 | 5 | pose variations are all deliverable |
| Event | 0.20 | 3 | aggressive; volume is the problem being solved |
| Landscape | 0.50 | 4 | few frames, all often distinct |
| Street | 0.60 | 6 | weak ranking (§04.4) → keep more, defer to user |

Street keeps the most *because* the engine ranks worst there. Aggressiveness should scale
with confidence, not be uniform.

### 2.2 Diversity rule

Ranking alone can select 3 near-identical frames from a 20-frame group — technically the
top 3, but useless: the user gets no real choice and no coverage.

Within a group, after picking the top frame, penalize candidates by similarity to
already-picked ones:

```
adjusted = score - λ * max_similarity_to_selected      (λ ≈ 0.25)
```

Similarity from scene embedding + pose distance. Result: picks spread across expressions
and poses rather than clustering on one instant.

For **group photos** diversity has a specific meaning worth special-casing: prefer the
frame where *the fewest people are blinking*, using `other_subject_blinking` (§04.2).
Across a 6-frame group shot there is often no frame with everyone perfect — the useful
answer is the one with the fewest problems, which is a set-level property, not a per-photo
score.

### 2.3 Quality floor

Some groups contain nothing worth keeping (whole burst mis-focused). Keeping the "best of
bad" wastes the user's review time and misrepresents the engine's confidence.

If the top frame is below `floor` (default 0.35, profile-tunable) → mark `alt`, not `pick`,
and flag the group `no_good_frame`. The photos remain fully visible; the engine just
declines to recommend. Deliberately never auto-rejects a whole group silently.

---

## 3. Reason strings

Every entry carries a human-readable justification, generated from score components (§04):

- `pick` — "sharpest eyes in group (0.82 vs 0.61 next), both eyes open"
- `alt` — "second sharpest; slightly softer eyes but better expression margin"
- `reject` — "eyes closed (0.21)" / "focus missed — sharp plane on shoulder" /
  "near-duplicate of pick #1 (similarity 0.94)"

Non-negotiable for trust: a proposal you can't interrogate is one you'll re-check manually,
which defeats the tool's purpose. This is the user-facing half of the evidence stance in
§04.1.

---

## 4. User override

`selection_entry.user_override=1` (§01 invariant 5). Overrides are **sacred**:

- Regenerating a selection with new params preserves every overridden entry.
- Changing weights, thresholds, or `keep_n` never silently reverts a user decision.
- The UI shows engine-vs-user disagreement explicitly.

Those disagreements are also the highest-value training signal available — the user
correcting the engine on *their own* photos is better calibration data than historical
catalog flags (§7), because it's a direct judgment on a specific proposal.

---

## 5. Regeneration semantics

Selections are versioned (`selection` rows, §01). Changing parameters creates a **new**
selection rather than mutating the old one, so the user can compare and roll back. Once
`exported_at` is set (pushed to LrC), the selection is frozen — later regeneration makes a
new version, because the previous one now corresponds to state on disk.

---

## 6. Failure modes to guard

| Risk | Guard |
|---|---|
| Bracket set culled to 1 frame | §04.6 detection + hard exclusion; explicit test |
| Blink detector wrong → good frames rejected | abstain on low confidence (§04.5); `alt` tier; reject flags not written by default |
| Grouping over-merged → distinct pose discarded | diversity rule; user split/merge (§05.7) |
| Grouping over-split → no dedup benefit | visible group-count stats so the user sees it |
| Every frame of a critical moment rejected | quality floor produces `alt`, never an empty group |
| Only-photo-of-a-person rejected | **coverage guard**: if a `person` cluster's every frame would be rejected, promote its best to `pick` regardless of score |

The coverage guard matters most for weddings: "no photo of the bride's grandmother"
is a delivery failure that no technical score would flag, since each individual frame may
genuinely be poor.

---

## 7. Calibration (M2)

Two sources of ground truth, different quality:

1. **`lr_history`** — thousands of past decisions, noisy (confounded by client needs and
   duplicates already deleted before import). Used for weight priors (§04.7).
2. **`user_override`** — few but precise, directly on our proposals. Used for online
   adjustment.

Headline metric: **agreement rate with the user's own picks**, reported per profile. Also
tracked, and more important than aggregate accuracy: **false-reject rate on frames the user
promoted** — recommending a mediocre photo wastes a moment of review; discarding a great one
loses a deliverable. The two errors are not symmetric, and the metrics shouldn't treat them
as if they were.
