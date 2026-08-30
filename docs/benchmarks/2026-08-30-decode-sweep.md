# Decode-path gate items closed on Canon files (design 03 §7)

Two of the benchmark gate's four questions needed no new formats — only
real RAWs, which we now have. 40 CR3s from the wedding, measured through
the canonical analyzer's own decode and Tenengrad code
(`engine/tools/decode_sweep.py`).

## 1. Default decode scale → **0.5 confirmed; drop 0.25**

Ranking agreement with a full-res decode (Spearman ρ on `sharpness_max`
across the 40 photos) and cost per photo:

| path | ρ vs full-res | s/photo |
|---|---|---|
| scale 0.25 | 0.914 | 0.20 |
| **scale 0.5** | **0.965** | **0.21** |
| scale 1.0 | 1.000 | 0.68 |
| CFA green plane | 0.958 | 0.23 |

0.5 keeps full-res ordering at ~⅓ the cost. **0.25 is strictly worse than
0.5 with no speed benefit** — rawpy's `half_size` decode serves both, and
0.25 merely resamples afterwards, losing ranking fidelity for nothing. The
sweep option stays for diagnostics; the default is unchanged and now
measured rather than assumed.

## 2. CFA green plane vs demosaiced luminance → **don't adopt; question closed**

| measure | scale 0.5 luminance | CFA green plane |
|---|---|---|
| ρ vs full-res ordering | **0.965** | 0.958 |
| cost | **0.21 s** | 0.23 s |
| blur-ladder drop at σ=0.7 | 0.174 | **0.205** |
| monotone across σ ladder | 8/8 | 8/8 |

CFA is marginally *more* sensitive to slight blur (steeper fall at σ=0.7)
but ranks real photos slightly *worse* and costs the same. No adoption
case. Blur-ladder caveat stated in the tool: Gaussian blur is not optical
defocus, so this compares paths, it does not measure absolute accuracy.

**The gate's actual question — "whether to build per-vendor CFA parsing" —
is answered NO, and for a reason independent of Sony/Fuji:** the
implemented CFA path masks green sites via libraw's `raw_colors`, which is
pattern-agnostic (X-Trans included). There was never a per-vendor parser to
build, and the surface it produces doesn't beat luminance anyway. Closed.

## Gate status after this

| Question | Status |
|---|---|
| CFA vs scaled decode → per-vendor parsing? | **closed: no** (this doc) |
| Default decode scale | **closed: 0.5** (this doc) |
| Per-photo latency vs the 10k target | **closed**: 0.47 s/photo at 4 workers, 10k ≈ 1.3 h (`PLAN.md`) |
| Which blink detector ships | **closed**: blendshapes; EAR abstains (2026-08-29 refit) |
| ARW embedded preview usable? | open — needs an ARW file (public samples suffice) |
