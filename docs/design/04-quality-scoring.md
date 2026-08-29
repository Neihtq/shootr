# 04 — Quality Scoring

**Milestone:** M1 · **Depends on:** [03](03-analysis-engine.md) · **Feeds:** [06](06-culling.md)

Turns measurements into a ranking. Pure function, no I/O, instantly recomputable (§01).

---

## 1. Design stance: evidence, not a verdict

A single opaque 0–100 score is the standard way these tools fail. When the number
disagrees with your judgement, you can't tell whether the tool saw something you missed or
just miscounted — so you stop trusting it and go back to manual culling.

So scoring emits a **record**, not a number:

```jsonc
{
  "total": 0.71,
  "components": {
    "eye_focus":   { "value": 0.82, "weight": 0.35, "contrib": 0.287,
                     "evidence": { "eye": "left", "sharp_norm": 0.82,
                                   "frame_max_tile": [7,4], "face_px_height": 640 } },
    "eyes_open":   { "value": 0.94, "weight": 0.25, "contrib": 0.235,
                     "evidence": { "open_l": 0.93, "open_r": 0.95, "source": "mediapipe" } },
    "sharpness":   { "value": 0.55, "weight": 0.15, "contrib": 0.082 },
    "composition": { "value": 0.60, "weight": 0.15, "contrib": 0.090 },
    "face_quality":{ "value": 0.71, "weight": 0.10, "contrib": 0.071 }
  },
  "flags": ["subject_near_edge:0.04"],
  "primary_subject": { "face_idx": 0, "why": "largest_and_most_central" },
  "weights_hash": "ev1-a3f2"
}
```

Every number traces to a measurement. The UI (§11) renders this directly: click a photo,
see *why*. `weights_hash` makes a score reproducible and tells us when a rescore is needed.

---

## 2. Metrics

### 2.1 Eye focus — the metric that matters most
Consumes `eye_sharp_norm` from §03 (already normalized against frame max and face height).

```
eye_focus = max(eye_sharp_norm[left], eye_sharp_norm[right])
```

**`max`, not mean:** the near eye in focus is correct portrait technique. Shallow DoF at
f/1.4 makes the far eye legitimately soft — averaging would penalize a properly focused
photo. But if **both** eyes are soft while the frame has a sharp region, focus missed —
that's the failure case, and `max` catches it correctly.

Piecewise mapping (calibration targets, to be fit in M2):

| `eye_sharp_norm` | score | meaning |
|---|---|---|
| ≥ 0.70 | 1.0 | tack sharp |
| 0.45–0.70 | 0.6–1.0 | usable |
| 0.25–0.45 | 0.2–0.6 | soft, questionable |
| < 0.25 | 0.0–0.2 | focus missed |

**Cliff behavior is intentional.** Focus is close to binary in practice — a mis-focused
portrait is unrecoverable, not "slightly worse". A linear score would let many mediocre
frames outrank one sharp frame in aggregate.

Guards: if no face → metric is `null`, not `0` (see §5). If `frame_sharpness_max` is very
low, the whole frame is soft → route to motion-blur, don't report focus miss.

### 2.2 Eyes open / blink
`min(open_l, open_r)` — **min, not max**: one closed eye ruins the frame. Asymmetry is
itself a signal (mid-blink, wink).

Partial blinks are the hard case and the most common real failure: the "eyes at 40% open"
frame that looks fine in a thumbnail grid and terrible at full size.

**The curve is per-`eye_source`** — first validation round (2026-08-20, 33 hand-labelled
faces from a real event shoot via `engine/tools/label_blinks.py`; raw data
`docs/benchmarks/2026-08-20-blink-labels/`) showed the detectors' raw scales differ
enough that one shared curve measurably mis-scores: labelled-closed eyes sat at 0.00–0.41
under EAR but 0.33–0.59 under MediaPipe blendshapes. The shared curve's effective cut
(raw 0.60 → score 0.4) false-rejected 21.7% of open eyes under EAR.

**Refit 2026-08-29** on the merged labelled set (285 faces: the 33-face round plus 252
faces from a real wedding's blink-rejected keepers — `docs/benchmarks/
2026-08-29-blink-labels-wedding/`). The larger set overturned the first round's EAR
numbers: merged EAR opens have p50 = 0.32 with closed values spanning 0.0–1.0 — no
usable cut exists (its best still false-rejects ~20% of open eyes at 44% false-accept).
**EAR therefore abstains** (`ABSTAIN_EYE_SOURCES` in scoring.py): `eyes_open` is `null`
for `ear_landmarks` faces per §5 — detector abstained, not genuinely bad. On the
wedding this single decision was 26% of all keeper false-rejects.

Calibrated curves (`EYES_OPEN_CURVES`; score 0.4 = culling's "eyes closed" boundary).
Costs are asymmetric (§06.7) — and the wedding's truly-closed faces were on frames the
user *kept*, so false-accept tolerance matches real culling:

| source | separation (raw → score 0.4) | on merged labelled set |
|---|---|---|
| `mediapipe_blendshapes` | 0.50 | false-reject 2.2%, false-accept 78% — overlap is real (expressions) |
| `ear_landmarks` | — | **abstains** (no separation; see above) |
| unknown source | 0.60 (generic fallback curve) | uncalibrated |

Every new eye source ships with its own labelling round before its scores drive
culling; the labelling tool makes growing the set an hour of keystrokes.

**Detector reliability remains a live risk** (§03.5). Because this metric is *dominant*
for portrait/event, a bad detector actively discards good photos. Mitigations:
`eye_source` recorded per face and surfaced in the component evidence; a confidence gate
that **abstains** rather than guesses when yaw is extreme (profile views have no reliable
eye signal); and per-source validation as above — an unvalidated source gets the generic
curve and a labelling round, not trust.

Multi-person frames: score the **primary subject** (§3), but flag
`other_subject_blinking` — in group shots that's usually the reason to prefer another
frame, and it should be visible rather than buried in an average.

### 2.3 Overall sharpness / motion blur
From the 16×16 tile map: `sharpness_mean`, `sharpness_max`, and the distribution.

- **Uniformly low** → camera shake / motion blur → low score.
- **High variance** → a sharp plane exists → normal shallow-DoF photo, fine.

For **landscape** this metric becomes dominant and changes meaning entirely — see §4.3.

### 2.4 Composition — flags with evidence, never a score
A learned "composition score" would be an opaque model overruling deliberate artistic
choices — exactly what a photographer will refuse to trust. So: **detectors that state
facts**, and the user weights them.

| Flag | Detection | Notes |
|---|---|---|
| `face_clipped` | face bbox intersects frame edge | near-certain defect |
| `limb_cut_at_joint` | pose joint within ε of frame edge | cut at knee/elbow/wrist reads as an error; cut mid-thigh is fine |
| `subject_near_edge:<d>` | primary subject centroid < N% from edge | often intentional — soft signal |
| `no_headroom` | top of head clipped or < 1% margin | |
| `lead_room_inverted` | face yaw points toward the *near* edge | subject looking out of frame |
| `horizon_tilt:<deg>` | `VNDetectHorizonRequest` | landscape-relevant; portraits often tilt deliberately |
| `thirds_distance:<d>` | subject centroid vs. nearest thirds intersection | soft number, never binary |

`limb_cut_at_joint` needs the anatomical nuance: cutting **at** a joint is the classic
error, cutting **between** joints is normal. Flagging every limb crossing the frame edge
would fire on nearly every environmental portrait and get the whole flag set ignored.

Composition score = weighted flag penalties, each individually visible so the user can
disagree with one without discarding the metric.

### 2.5 Face capture quality
Vision's `faceCaptureQuality` — an independent cross-check trained on different data than
our hand-rolled metrics. Low weight (0.10): it's a useful second opinion but a black box,
and it conflates focus/exposure/expression in ways we can't decompose.

---

## 3. Primary subject selection

Most metrics need a subject. Ranking:

1. Largest face **near** a saliency peak (`VNGenerateAttentionBasedSaliency`).
2. Largest face, if saliency is uninformative.
3. Saliency peak alone, when there are no faces.
4. Frame center, as last resort.

Recorded with a `why` string. Wrong subject selection produces confusingly wrong scores in
group shots, so it must be inspectable and (in the UI) overridable.

---

## 4. Profiles

The user shoots all four genres (SPEC §2), so one weight set cannot work. Profile lives on
the `shoot` (§01) and only changes weights + which metrics apply — never measurements.

### 4.1 Weights

| Metric | Portrait | Event | Landscape | Street |
|---|---|---|---|---|
| eye_focus | **0.35** | **0.35** | — | 0.10 |
| eyes_open | **0.25** | **0.25** | — | 0.05 |
| sharpness | 0.15 | 0.15 | **0.45** | 0.15 |
| composition | 0.15 | 0.08 | **0.35** | 0.05 |
| face_quality | 0.10 | 0.10 | — | 0.05 |
| exposure | 0.05 | 0.07 | 0.20 | 0.10 |
| *moment/uniqueness* | — | — | — | **0.55** |

### 4.2 Street is deliberately different
Face-centric scoring is **actively harmful** here: faces are small, incidental, or
intentionally out of focus; motion blur is often the point. Technical metrics get low
weight, and `moment` dominates — but "moment" is not something we can measure honestly.

**Honest position:** for street, the app **ranks weakly and defers to the user**. It
provides dedup and technical-disaster filtering (`eyes_open` on a large primary face,
severe blur), not aesthetic selection. Claiming otherwise would produce confident garbage.
`moment` is a placeholder for future work (scene-uniqueness within a shoot), not an
implemented metric in M1.

### 4.3 Landscape needs different sharpness logic
Not "is the subject sharp" but "**is the intended focus plane sharp, and does DoF cover
the scene**". From the tile map:

- `focus_plane_coverage` — fraction of tiles above a sharpness threshold.
- `focus_plane_location` — where the sharp region sits (foreground vs. mid vs. far),
  cross-referenced with aperture and focal length from EXIF.
- `corner_softness` — lens performance at the edges.
- `horizon_tilt` becomes a real defect rather than a stylistic note.

Plus `exposure` weight rises (clipping matters more) and `eyes_*` are inapplicable.

### 4.4 Per-group profile hints
A wedding contains ceremony candids, posed family groups, and venue detail shots. §01 has
no per-photo profile override in M1; instead the scorer applies **hints** based on group
content:

- group has 1–2 large faces → portrait-leaning weights
- group has > 6 faces → group-shot handling (`other_subject_blinking` gains weight)
- group has no faces → suppress face metrics, redistribute to sharpness/composition

This is renormalization within a profile, not a new profile. Keeps one user-visible knob
while avoiding face metrics dominating a detail shot of the rings.

---

## 5. Missing metrics: abstain, don't zero

A landscape has no eyes. Scoring `eye_focus = 0` would rank every landscape as terrible.

**Rule: inapplicable metrics are `null` and their weight is redistributed proportionally
across applicable metrics.** Distinguish three cases explicitly:

| Case | Handling |
|---|---|
| Not applicable (no faces in a landscape) | `null`, redistribute weight |
| Detector abstained (extreme yaw, low confidence) | `null`, redistribute, flag `low_confidence` |
| Genuinely bad (eyes measured, clearly closed) | real low score |

Conflating "couldn't measure" with "measured badly" is the single most likely source of
wrong rankings in this design, which is why it gets its own invariant.

---

## 6. Bracket guard

Frames differing by `exposure_bias` in a regular sequence within a short time window are
**exposure brackets**, not a burst. All are keepers — the dark one is *supposed* to be
dark.

Detection: ≥ 3 frames, < 2 s apart, `exposure_bias` forming a symmetric progression
(e.g. −2/0/+2), near-identical scene embedding. Marked `group.is_bracket=1` (§01) and:

- **exposure metric is suppressed** within brackets (clipping is intentional),
- **culling never selects within a bracket** (§06).

Getting this wrong destroys HDR sets by keeping only the middle frame — a silent,
irreversible-feeling data loss from the user's perspective. Explicitly on the test list.

---

## 7. Calibration (M2)

Hand-tuned weights are a starting guess. The real target is the user's own history:
`lr_history` (§01) holds thousands of past pick/reject/star decisions read from a catalog
copy (§07).

Approach: fit metric→outcome weights per profile using pick/reject as labels, with
regularization toward the hand-tuned priors so a sparse or noisy history can't produce
wild weights. Report **agreement rate with past decisions** as the headline quality number
— that's the only measure of "is this scoring any good" that means anything.

Caveat to keep honest: historical picks are confounded by client requirements, delivery
quotas, and duplicates already removed. It's noisy ground truth, not gospel — hence
regularization and a visible agreement metric rather than blind fitting.

**First fit, measured (2026-08-29,** `engine/tools/fit_weights.py`**, real wedding,
559 keepers / 961 shot groups):** the split verdict the architecture predicted.
*Between* groups the engine agrees strongly (98.9% of the user's keepers sat in groups
the engine also picked from). *Within* a shot group, ordering by these six metrics is
statistically chance: hand-tuned priors 53.0% holdout pairwise accuracy, best
regularized fit 53.2% — so **the priors stay** (same bar as §08.7: a fit that doesn't
beat the baseline doesn't ship). Cheap non-score signals also fail (earlier-in-burst
54%, face count/size ~50%). The limiting factor is not weighting but *measurement*:
within a burst, technical quality barely varies and the user's choice is expression and
gesture — which nothing in §2 measures. The path to within-group agreement is an
expression/peak-moment metric (MediaPipe's landmarker already emits smile/brow
blendshapes in the analyzer we run — a near-free candidate), validated per §2.2's
labelling discipline before it drives culling. Until then, within-group `keep_n`
breadth is the honest mitigation, not tighter ordering.
