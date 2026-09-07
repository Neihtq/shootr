# Sharpness made comparable — the absolute-threshold flaw, fixed and validated

Closes the open correctness issue from `2026-08-30-arw-raf-validation.md` §4:
`sharpness_max` was compared against global constants even though absolute
Tenengrad is not comparable across cameras, exposures or scenes.

## The fix

Sharpness is now judged as a **ratio to the photo's own population** — same
shoot, same camera body (`pipeline.sharpness_populations`). One helper
(`scoring.sharpness_basis`) decides relative-vs-absolute so the score curve,
the unusable-frame floor and the eye-focus guard can never disagree.

Keyed by camera because a two-body shoot is two populations. The reference
shoot: R6m2 median 0.0364 (n=3,878), 6D Mark II median 0.0445 (n=570) — only
1.2× apart here, but a Canon+Fuji shoot would differ ~50× and the keying is
what stops that from reading as "one body is always soft".

No population (fewer than 12 frames from that body) → the absolute curve
still produces a score, but **the hard verdict is suppressed**: we cannot
tell an unusable frame from an uncalibrated camera, so we score and never
accuse. The basis is stated in the evidence either way.

## Calibrating the floor by looking at the frames

Keeper counts alone would have set the floor wrong. Rendering the disputed
band settled it:

| rel | frame | verdict |
|---|---|---|
| 0.007 | out-of-focus frame of the floor (`IMG_3412`) | genuine accident |
| 0.056 | **first dance** — smoke, darkness, red uplight (`2I3A6726`) | **sharp keeper**, almost no high-frequency content |

So low gradient energy does **not** imply blur, and the old
`motion_blur_or_shake` label overclaimed: magnitude cannot separate shake
from defocus from a scene that simply has no detail. The floor is now
deliberately extreme (`rel < 0.03`), the diagnosis renamed
`no_usable_detail`, and everything above it is carried smoothly by the curve
so an atmospheric frame scores low without being branded broken.

## Validation on the reference shoot (4,448 frames, 560 keepers)

| | before (absolute) | after (relative) |
|---|---|---|
| frames flagged unusable | 62 (1.39%) | **4 (0.09%)** |
| **keepers flagged** | **5** | **0** |
| keeper recall as pick | 33.1% | **34.3%** |
| false-reject rate | 46.9% | 46.8% |
| rescore cost | — | 11 s |

The bug is gone (zero keepers wrongly flagged) and pick recall improved
slightly. The false-reject rate is unchanged, as expected: it is dominated by
within-group ordering, which is a separate measured problem (04 §7).

The Fuji reproducer, re-scored: **0.74** inside a Fuji population (was 0.0
with a motion-blur accusation), and no accusation at all as a lone import.

## Residual limitations, stated

- A shoot with fewer than 12 frames from a body still scores on the
  Canon-fit absolute curve, so a low-detail frame there scores near 0 — no
  false accusation, but a low score. Fixable only with an absolute
  scene-detail reference we do not have.
- Scores now depend on the shoot's population, so adding photos to a shoot
  can shift existing scores. Acceptable by design (`score` is the cheap,
  always-recomputable half) but worth remembering when comparing runs.
- `weights_hash` includes the new curves, so stale scores are visibly stale.
