# DINOv2 grouping thresholds — full-shoot re-measure (design 13 §4 item)

All 1,232 CR3s of the real event shoot analyzed with the Python analyzer
(DINOv2 ViT-L scene embedding, cosine distance on L2-normalized vectors);
capture times from the existing probe rows. Method = the 2026-08 measurement
methodology that set the Vision thresholds.

## Distance scale — DINOv2 is tighter than Vision feature prints

Consecutive pairs ≤ 10 s apart (n = 1,111):

| quantile | cosine distance |
|---|---|
| p50 | 0.040 |
| p75 | 0.090 |
| p90 | 0.199 |
| p95 | 0.311 |
| p99 | 0.659 |

Near-identical pairs sit p99 = 5.0 s apart (Vision measurement: 12 s) —
the 8 s event time-gap still clears it.

Face-count flicker on near-identical pairs (dist ≤ 0.10, ≤ 10 s): **26%**
(226/873) — identical to the Vision-side measurement. The flicker is a
property of *shooting real events*, not of either detector; the
corroboration clause stays mandatory.

## Threshold sweep vs the reviewed Vision structure (204 groups / 35 singletons)

| per-step | anchor | corr | groups | singletons | boundary agreement |
|---|---|---|---|---|---|
| 0.20 (Vision values) | 0.25 | 0.10 | 301 | 84 | 90.7% |
| 0.25 | 0.32 | 0.12 | 274 | 74 | — |
| 0.30 | 0.38 | 0.15 | 244 | 55 | 94.2% |
| **0.35** | **0.45** | **0.18** | **225** | **46** | **95.5%** |

Reusing the Vision-tuned values verbatim over-splits (301 groups, 84
singletons — the exact failure mode the 2026-08 fix removed). At the scaled
set (0.35/0.45/0.18) the structure closely matches what the user reviewed:
225 vs 204 groups, and the largest group (43 frames, a single 43 s burst)
maps to exactly one Vision group — no over-merge detected at any tested
setting.

## Conclusion

- DINOv2 needs its own threshold set; the measured values are
  **SHOT_EMBEDDING_DIST 0.35 · SHOT_ANCHOR_DIST 0.45 ·
  SHOT_FACE_COUNT_CORROBORATION_DIST 0.18** (event/portrait; landscape and
  street to be re-measured on matching shoots — only event data exists).
- Residual difference at that set is mild extra splitting (~10%), the cheap
  error direction (over-merge discards alternates; over-split only wastes
  clicks) and single-shoot tuning shouldn't be pushed tighter than that.
- NOT shipped as code: thresholds stay Vision-tuned until the analyzer
  cutover, at which point grouping.py's constants switch to this set in the
  same commit (one measurement semantics — constants must match the
  embedding that is actually canonical).
