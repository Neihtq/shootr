# When does a trained model beat retrieval? Measured — and the answer is per-parameter

Design 08 §4 defers a trained model to "Phase 2, only if k-NN measurably
underperforms", and I previously told the user nothing at n=560 suggested a
trained model would clear the bar. **That was reasoning, not measurement, and
measurement partly contradicts it.**

Method (`engine/tools/style_learning_curve.py`): shot-group-aware 4-fold
splits so burst siblings never straddle train/test; history subsampled **by
group** so a small history is a plausible smaller catalog rather than a
thinned one; families and medians fit on train only; ridge from the 768-d
scene embedding to the delta, λ chosen on a slice of train, never on test.

Mean absolute error, in the parameter's own units:

| history | method | Exposure2012 (EV) | Highlights2012 | Shadows2012 |
|---|---|---|---|---|
| ~84 | k-NN | 0.401 | 19.73 | 19.76 |
| | median | 0.485 | 22.50 | 21.11 |
| | **ridge** | **0.366** | **19.60** | **17.91** |
| ~280 | k-NN | 0.348 | **15.83** | **14.94** |
| | median | 0.403 | 16.69 | 16.84 |
| | **ridge** | **0.322** | 18.39 | 16.82 |
| ~560 | k-NN | 0.344 | **14.81** | **13.96** |
| | median | 0.373 | 16.65 | 16.64 |
| | **ridge** | **0.303** | 17.95 | 16.71 |

## What this says

**The crossover is not one number — it is per parameter, and for exposure it
has already happened.** Ridge beats k-NN on `Exposure2012` at *every* history
size, including ~84 photos, and by 12% at full size (0.303 vs 0.344 EV).
Exposure behaves like a fairly global function of the scene: a linear model
over the embedding captures it, and keeps improving as history grows.

**Highlights and shadows go the other way.** k-NN leads clearly at ~280 and
~560 (14.8 vs 17.9; 14.0 vs 16.7) and is still improving, while ridge has
gone flat. These read as local and idiosyncratic — "on frames like *this* I
pull highlights hard" — which is what retrieval is for and what a single
global linear map cannot represent.

**k-NN is saturating on exposure** (0.348 → 0.346 → 0.344 over the last three
sizes) but **not on the tonal parameters** (19.7 → 14.8 on highlights, still
falling). So more history still helps retrieval — just not uniformly.

## Answering "many shoots × ~500 edited each"

At 5–10 shoots (2,500–5,000 edited photos) a trained model becomes viable in
the range where gradient-boosted trees are normally the right tool, and
ridge's continued improvement suggests headroom the tonal parameters do not
show. But scale is not the only axis: **more shoots means more *diverse*
data, not merely more of the same.** A single global model must fit every
look at once, whereas retrieval selects the relevant subset for free — which
is exactly why §3 conditions on look families. A trained model at that scale
would need family conditioning (or enough capacity to rediscover it), and the
comparison should be re-run per user rather than assumed.

## Recommendation, not yet implemented

A **per-parameter hybrid**, chosen by this harness on the user's own history:
ridge (or GBT) where it measurably wins, retrieval where it does not. Two
costs to weigh before shipping it, both real:

1. **Inspectability.** "Edited like these five photos" is the explanation that
   makes the feature trustworthy (§4). A ridge coefficient vector is not an
   explanation, so exposure would lose its *why* even as it gains accuracy.
2. **Guardrails.** k-NN clamps to the family's observed range, so its worst
   case is a bland edit. An unclamped linear model extrapolates — the failure
   mode §6 exists to prevent. Any trained parameter needs the same clamp and
   abstention wired around it before it may write.
