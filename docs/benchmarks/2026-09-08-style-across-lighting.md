# Does style prediction hold up across lighting? (design 08 §4, §7)

Leave-one-shot-group-out over the 560-photo history, stratified by ISO as a
proxy for how much light there was. Errors are mean absolute, in the
parameter's own units (EV for exposure, slider points for highlights).

| lighting | n | abstained | Exposure k-NN | Exposure median | Highlights k-NN | Highlights median |
|---|---|---|---|---|---|---|
| ISO ≤400 (daylight) | 191 | 1% | **0.315** | 0.348 | **15.3** | 17.4 |
| ISO 500–1600 (indoor) | 248 | 1% | **0.296** | 0.320 | **8.4** | 8.9 |
| ISO 2000–6400 (dim) | 114 | 0% | **0.302** | 0.402 | **12.4** | 22.5 |
| ISO >6400 (very dark) | 7 | 0% | 0.128 | 0.371 | 6.0 | 0.0 |

Two things to take from this:

**Accuracy is flat across lighting.** Exposure error sits at 0.30–0.32 EV in
all three well-populated buckets. Prediction does not degrade as the light
gets worse, which is the outcome the look-family design was betting on —
families were discovered to split by *lighting* rather than by genre
(`2026-08-30-style-knn-eval.md`), so conditioning on family is implicitly
conditioning on light.

**Per-photo retrieval earns its keep most where light is mixed.** k-NN beats
the family median by 9% on exposure in daylight but 25% in dim light, and by
45% on highlights there (12.4 vs 22.5). That is the expected shape: in
consistent light a constant offset is nearly as good, while in mixed light a
single median is wrong for most frames and the neighbours carry the signal.
The bottom row is n=7 — noise, and its median column is an artifact of the
tiny sample; ignore it.

## Two caveats this table does not show

1. **Abstention is ~1% here because every photo has same-shoot neighbours.**
   Leave-one-group-out removes the burst siblings but not the wedding. On a
   genuinely unfamiliar shoot the honest expectation is a far higher
   abstention rate — the confidence gate is doing its job when that happens,
   not failing.
2. **Colour temperature is not predicted at all.** Temperature/Tint are
   excluded (§2.2 needs an as-shot baseline the analyzer doesn't emit), so
   "handles colour conditions" means Vibrance/Saturation/ColorGrade, not
   white balance. WB stays the user's.

## Implementation gap worth naming

§4 specifies similarity over the scene embedding **plus** tabular features
that matter for exposure decisions: luminance histogram summary, clipping
fractions, as-shot WB, ISO, and skin-tone samples. Only the embedding is
implemented. Lighting is therefore handled implicitly (the embedding encodes
appearance) and through family conditioning — which this table says already
works — but the explicit features remain unbuilt, and they are the obvious
next lever if a future shoot shows lighting-dependent error.
