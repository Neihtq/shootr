# 08 — Style Learning

**Milestone:** M3 · **Depends on:** [07](07-lightroom.md) · **Feeds:** [07](07-lightroom.md) (XMP write)

Learns the user's editing style from their history and predicts develop settings for new
photos. **Riskiest subsystem** — scoped narrowly on purpose.

---

## 1. What is and isn't learnable

**Learnable:** a mapping from image features → global `crs:` parameters. These are
deterministic functions of the whole image, and the user's choices are consistent enough to
regress against.

**Not learnable (v1):** local adjustments — brushes, radial/linear gradients, AI
subject/sky masks. They're spatial and specific to one photo's content. Excluded as a
stated boundary, not a gap to fill later (§07.4).

**Also not attempted:** crop and straighten. Crop is compositional intent, not style —
predicting it would mean second-guessing the photographer on the one decision most clearly
theirs.

---

## 2. Two design decisions that make this work at all

### 2.1 Predict deltas, not absolutes
Training on absolute values makes the model learn the *camera*, not the *user*. A Sony
under-exposes relative to Canon; a model fed absolute Exposure2012 learns "Sony photos need
+0.4" and generalizes to nothing.

```
target = user_final_value - as_shot_baseline
```

The baseline comes from `analysis.frame.as_shot_wb` and Adobe's default rendering (§03).
Prediction adds the delta back onto the new photo's baseline.

### 2.2 Temperature as a ratio, not Kelvin
White balance in Kelvin is dominated by the light source, not taste. A model predicting
absolute Kelvin learns "indoor ≈ 3200K, daylight ≈ 5500K" — the camera already knows that.

What's actually stylistic is the *deviation*: this user runs ~8% warmer than as-shot.

```
temp_target = log(user_temp / as_shot_temp)     # log-ratio: symmetric, additive
tint_target = user_tint - as_shot_tint          # tint is a small linear offset
```

Log-ratio because warming 3200→3500 and 5500→6000 are the same perceptual move but very
different Kelvin deltas.

---

## 3. Look families

The user shoots weddings, portraits, landscape, and street (SPEC §2). They almost certainly
do not edit them the same way. A single model averages incompatible styles and produces
something that fits none — moody wedding grading applied to a bright travel photo.

**Cluster the edit history into look families**, then condition prediction on the family
chosen for the shoot:

1. Feature vector per edited photo = its `crs:` **delta** parameters (§2), standardized.
2. Cluster (agglomerative, correlation distance) — 3–8 families typical.
3. Label each family with its distinguishing traits ("warm +low contrast +lifted blacks")
   and representative thumbnails so the user recognizes it.
4. User picks a family per shoot, or accepts the auto-suggestion from scene similarity.

Families are **discovered, not assumed** — deriving them from actual edits beats mapping
them onto our four scoring profiles, since a user's real looks may split differently
(e.g. "golden hour" vs "overcast" rather than by genre).

---

## 4. Model: k-NN first, deliberately

**Start with retrieval, not training.** For each new photo, find the k most visually
similar photos in the edit history and blend their deltas.

```
neighbors = top_k(cosine(scene_embedding, history_embeddings), k=8)
           filtered to the selected look family
weights   = softmax(similarity / τ)
prediction = Σ weights * neighbor_deltas          # per parameter
confidence = f(neighbor_similarity, delta_variance)
```

Why this before a trained model:

- **Works at a few hundred photos.** A neural regressor needs thousands.
- **Inspectable** — "edited like these 5 photos", with thumbnails. When it's wrong the user
  sees *why* immediately. A trained model gives an unexplainable number.
- **No training step**, so it improves the moment new edits are imported.
- **Strong baseline.** It's the bar any trained model must clear — and in similar
  photo-to-parameter problems, retrieval is often competitive.

Similarity uses the Vision scene embedding (§03) plus a few tabular features that matter
for exposure decisions: luminance histogram summary, clipping fractions, as-shot WB, ISO,
and skin-tone samples from detected face regions.

**Confidence is a first-class output.** When the nearest neighbors are dissimilar or
disagree, the honest answer is "no confident prediction" — the app then writes nothing
rather than guessing (§6).

### Phase 2 (only if k-NN measurably underperforms)
Gradient-boosted trees (one per parameter) on the same features. Small data, tabular,
handles nonlinearity, still somewhat interpretable via feature importance. Torch is
available but a deep model is not justified at this data scale — and it would forfeit the
inspectability that makes the feature trustworthy.

---

## 5. Data sources

All three the user has (SPEC §2), in quality order:

| Source | Gives | Quality |
|---|---|---|
| **XMP sidecars** | `crs:` params directly, documented namespace | **best** — no parsing ambiguity |
| **Catalog copy** | develop settings + pick/reject history | good; Lua-text parsing risk (§07.2) |
| **JPEG + RAW pairs** | rendered result only | weakest — parameters must be *inferred* |

The JPEG+RAW pairs are not used for training. Their real value is **validation**: render our
prediction and compare against the user's actual export. That's an end-to-end check that
catches systematic errors (wrong process version, sign flips, baseline mismatch) which
parameter-space error metrics would miss entirely.

**Rendering for validation requires applying `crs:` params outside Lightroom** — Core Image
approximates but does not reproduce Adobe's pipeline. So validation compares *trends and
direction*, not pixel equality. Stated as a limitation rather than pretending we can
round-trip exactly.

---

## 6. Guardrails

Style prediction writes to the user's files (§07), so it fails safe:

| Guard | Behavior |
|---|---|
| **Confidence gate** | below threshold → no prediction written, marked "needs manual edit" |
| **Clamping** | predictions clamped to the range observed in that family's history — never invent an edit more extreme than the user has ever made |
| **Sanity check** | predicted exposure that would clip > 2% of highlights is rejected/damped |
| **Per-parameter opt-out** | user can disable prediction for any parameter (e.g. keep WB manual) |
| **Never overwrite existing edits** | §07 Rule 2 protocol, unconditionally |
| **Process-version match** | refuse to apply predictions learned on a different PV (§07.4) |

Clamping deserves emphasis: an extrapolating regressor producing +3 EV because a photo sits
outside the training distribution is both plausible and destructive. Bounding to observed
history makes the worst case "a bland edit", not "a ruined one".

---

## 7. Evaluation

Held-out set of the user's own edits, reported per look family:

- **Per-parameter MAE** in user-meaningful units (EV for exposure, mireds for WB) — "±0.15
  EV" is interpretable; normalized RMSE is not.
- **Direction agreement** — did we get the sign right? Often more important than magnitude;
  a slightly-too-warm photo is fine, a cool photo when the user always warms is wrong.
- **% of photos where prediction is "close enough to keep"** — the metric that reflects the
  actual goal (a good starting point), judged by the user on a sample.
- **Coverage** — fraction where confidence cleared the gate. A model that's accurate on 20%
  of photos and abstains on the rest may still be genuinely useful; one that confidently
  predicts everything at mediocre accuracy is not.

Baseline to beat: **"apply the family's median edit to everything."** If per-photo
prediction can't beat a constant offset, the honest conclusion is to ship the median as a
preset and drop the model. That comparison is cheap and worth running first.

---

## 8. Open questions

- **Adobe's baseline rendering** is proprietary; "as-shot baseline" is therefore
  approximate. May introduce systematic bias, partly absorbed by delta training. Measure via
  the JPEG-pair validation.
- **Camera profile** (`crs:CameraProfile` — Adobe Standard vs. Camera Neutral vs. custom)
  substantially changes what a given parameter does. Must be a conditioning feature; if the
  user mixes profiles, families may need to split by profile.
- **Tone curves and HSL** are high-dimensional and correlated. Likely needs PCA to a few
  components rather than per-point regression.
- **Style drift over time** — a 2019 look differs from 2026. Consider recency weighting, or
  let time-based clustering surface it as separate families.
