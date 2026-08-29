# Style learning first pass — k-NN clears the median bar (design 08 §7)

Data: the real wedding's 560 edited photos (`lr_history.develop`, 111 global
params each) joined to their Vision scene embeddings. WB (Temperature/Tint)
excluded: the analyzer does not yet emit `analysis.frame.as_shot_wb`, and
absolute Kelvin would learn the light source, not the user (08 §2.2) —
recorded contract gap.

**Families discovered, not assumed (08 §3):** 8, inside ONE wedding —
lighting contexts (e.g. +ColorGradeMidtoneHue/−Saturation vs
+Highlights/+Exposure/+Vibrance), sizes 147/142/123/59/36/20/18/15. The
user's looks split by light, not by our genre profiles, exactly as the doc
predicted.

**The mandated comparison** (family median vs k-NN over scene similarity,
softmax blend, clamped to family range): leave-one-photo-out flattered k-NN
(12/12 wins) because burst siblings leak — a neighbor's edit is nearly the
photo's own. The honest split, **leave-one-shot-group-out**, still gives
**k-NN 11/12 wins**, coverage 99.1%:

| param | k-NN MAE | median MAE |
|---|---|---|
| Exposure2012 (EV) | **0.282** | 0.347 |
| Blacks2012 | **6.5** | 9.8 |
| Highlights2012 | **11.7** | 14.4 |
| Contrast2012 | **1.97** | 2.57 |
| Dehaze | **1.14** | 1.96 |
| ColorGradeMidtoneHue | 0.336 | **0.283** (median wins — opt-out candidate) |

Verdict: the model earns its keep on this shoot; the median does NOT ship
as the preset. Caveats: one shoot, one wedding's style space; direction
agreement 87–100%; the delta-vs-absolute distinction is untested until a
second camera/shoot arrives (within one shoot they coincide up to a
constant).

Shipped: `shootr.style` (families, k-NN, confidence gate, clamping),
`shootr.xmp.write_develop` (crs writer via the Rule-2 protocol; a sidecar
with ANY existing crs content raises DevelopConflict — deliberately no
override flag), `engine/tools/eval_style.py` (this table).
