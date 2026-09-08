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

**Measured 2026-09-08 and the trigger is already partly met**
(`docs/benchmarks/2026-09-08-knn-vs-trained.md`): plain ridge over the scene embedding
beats k-NN on `Exposure2012` at *every* history size (0.303 vs 0.344 EV at n=560), while
k-NN leads clearly on Highlights/Shadows and is still improving with data. The crossover
is therefore **per parameter, not a single sample count** — exposure looks like a global
function of the scene, tonal moves look local and idiosyncratic. The indicated design is
a per-parameter hybrid selected by the §7 harness on each user's own history, with two
non-negotiables: any trained parameter keeps §6's clamp and abstention, and the UI must
say when a value came from a model rather than from named neighbour photos, since "edited
like these five" is the explanation that earns trust.

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
| **Process-version match** | refuse to apply predictions learned on a different PV (§07.4). Implemented 2026-09-08 (`select_process_version`): history is narrowed to one PV before clustering *and* prediction — this is what makes importing a second, older catalog safe rather than silently corrupting the blend. A *known* different PV is excluded; a *missing* PV is kept but counted, since absence is not evidence of incompatibility, and the prediction response reports both numbers. |

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

## 7a. The UI surface (both clients, design 2026-09-07)

The engine side is built and measured (§7); this is what the clients must render. Same
rule as everywhere else: **clients render, they never compute** (§10.1) — no client-side
arithmetic on predictions, no client-side confidence maths.

**Screen 1 — Look families.** A list from `GET /api/style/families`: each family's photo
count, its trait label ("+Highlights +Exposure +Vibrance"), thumbnails of its sample
photos (via the existing thumbnail endpoint), and its median edit. This is how the user
recognizes their own looks. Read-only; families are discovered, not editable.

**Screen 2 — Predict for a shoot.** `POST /api/shoots/{id}/style/predict` is a *preview*
and must be presented as one: nothing is written until the user asks. Per photo, show
the predicted parameters, the confidence, and — the point of choosing k-NN — the
**neighbour photos the blend came from**, as thumbnails. "Edited like these five" is the
explanation; a bare number is not. The family is auto-suggested and overridable.

**Abstentions are first-class, never blanks.** A photo below the confidence gate shows
"no confident prediction — needs manual edit" with the reason from the engine
(`low_confidence`, `no_similar_history`, `family_too_small`, `not_analyzed`), exactly as
§5's null-vs-zero rule works for scores. An empty parameter list must never read as
"no changes needed".

**Per-parameter opt-out** (§6) is **server-side** — `GET`/`PUT /api/style/preferences`,
stored in the `preference` table — not a client toggle. It changes what gets written into
the user's files, so a client-local switch would let web and native write different edits
from the same click. Excluded params are reported per photo with their predicted value
(`excluded`), because "we had a number and you told us not to write it" is a different
statement from "we had nothing". Ship with `ColorGradeMidtoneHue` excluded by default —
measured: the family median beats k-NN on it
(`docs/benchmarks/2026-08-30-style-knn-eval.md`).

**Write dialog.** Same shape as the selects export dialog (§11.7): state the counts
before writing — how many will be written, how many abstain, how many are conflicts —
and require explicit confirmation. Conflicts (a sidecar already holding the user's own
develop settings) are **reported and skipped with no override control at all**; there is
no confirm checkbox to add, because the engine has no override parameter. Say plainly
that these were left untouched. After writing, repeat the §07.3.1 "Read Metadata from
File" caveat.

**Never imply we transfer local adjustments.** Brushes, gradients and AI masks are out
of scope permanently (§1); the UI states that where a user would reasonably expect them.

Both clients ship this (web first, per the standing rule that a UI feature lands in
both); the keyboard path in the native client follows §12's existing bindings.

---

## 7b. Style models are user-created objects (design 2026-09-08)

Everything above describes *a* predictor. This section defines how the user
controls it, because the single-shoot history this was first measured on is
not representative of a career and no automatic choice made from it deserves
to be permanent.

A **style model** is a named, persisted object the user creates:

| field | meaning |
|---|---|
| `name` | the user's label ("Weddings 2024–26", "Landscape") |
| `method` | which learner — see the registry below |
| `scope` | which libraries the edit history comes from: one, several, or all |
| `params` | method knobs (k and τ for retrieval, λ for ridge) |
| `metrics` | what §7's harness measured **for this model**, so models are comparable |
| `trained_at`, `process_version`, `history_n` | provenance |

Four operations, all explicit:

1. **Learn** — create a model: pick a name, a method, and the libraries to
   learn from. Nothing is learned implicitly on import.
2. **Relearn** — re-run the same model against current history. This is how
   new shoots take effect; the button exists because the user decides when
   their style has moved, not us.
3. **Compare** — models sit side by side with the metrics from the same
   harness, so "is the new method actually better *for me*" is answered by
   numbers on the user's own edits.
4. **Choose** — which model predicts for a given shoot.

### Method registry

Methods are pluggable and each declares whether it needs a fitting step:

| method | fits? | why it's offered |
|---|---|---|
| `knn` | no | inspectable ("edited like these photos"), works at hundreds of photos, improves the moment history grows |
| `ridge` | yes | measured to beat retrieval on exposure at every history size tested (`2026-09-08-knn-vs-trained.md`) |
| `gbt` | yes | the §4 Phase-2 candidate; expected to matter in the thousands, not yet implemented |

**No method is privileged and none is auto-selected.** The measurement that
found ridge better on exposure came from one wedding; treating it as a
conclusion would be exactly the overreach this section exists to prevent. The
harness reports, the user decides.

### Invariants that survive method choice

- §6's guardrails apply to **every** method: clamping to observed range,
  confidence gate and abstention, the highlight-clip check, per-parameter
  opt-out, never overwriting user develop settings.
- §7a's inspectability requirement holds: a prediction must say where it came
  from. Retrieval names neighbour photos; a fitted method must say it was
  fitted, and from how much history — an unexplained number is not acceptable
  just because it is more accurate.
- One process version per model (§6): scope may span catalogs, but history is
  narrowed to a single PV before fitting, and the model records which.

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
