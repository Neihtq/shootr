# 13 — Portability (Windows, Linux)

**Milestone:** post-M2 (staged; see §5) · **Affects:** [03](03-analysis-engine.md),
[05](05-grouping.md), [11](11-web-client.md), [12](12-native-client.md)

> **Status (2026-08-20):** the canonical analyzer EXISTS — `analyzer/` package,
> console script `shootr-analyze-py`, swapped in via `SHOOTR_HELPER` with zero
> engine changes. Decode/sharpness are numerically Swift-parity-tested; probe
> matches Swift field-for-field on real CR3s (needed a hand-rolled ISO-BMFF
> CMT-box walker — exifread can't read CR3 containers). Model registry has
> pinned sha256 artifacts for SCRFD-10G, ArcFace R50 (floor — AdaFace has no
> official ONNX artifact yet), MediaPipe FaceLandmarker, DINOv2 ViT-L+S,
> BiRefNet. The §4 gate harness is `engine/tools/ab_analyzers.py`. **Adoption
> is NOT decided** — it waits on hand-labelled blink frames and the threshold
> re-measurement below. Two floor-hardware findings, both measured: the
> CoreML EP is pathological on DINOv2-L (~20 min compile, then fails → CPU is
> the macOS default, override with `SHOOTR_ORT_PROVIDERS`), and mediapipe
> 1.0.x SIGABRTs in Metal init on macOS 26 (pinned `<1.0`).
>
> **First §4 gate run** (60 CR3s from a real wedding shoot, scale 0.5, full
> report `docs/benchmarks/2026-08-20-analyzer-ab-60.md`):
> - Sharpness ranking Spearman **0.812** — decent, not identical; the top
>   disagreements cluster in one burst (2I3A8815–8821) and need eyeballing.
> - Face counts: **40/60 agree; python finds 77 faces to Vision's 56** —
>   consistent with SCRFD's expected recall edge on small/profile faces, but
>   "more" isn't verified as "correct" until spot-checked.
> - Eye-open: EAR saturates at 1.0 where blendshapes spread 0.31–0.99 — the
>   discrimination the blink metric needs, pending labels.
> - Embedding neighbor Jaccard **0.580**; grouping on untuned thresholds
>   14 vs 15 groups, same singleton count — surprisingly stable, but
>   thresholds still need re-measuring on the full shoot before adoption.
> - Throughput, M4, CPU EP: swift median 1.41 s → 3.9 h/10k; python was
>   14.4 h/10k on the first run — **optimized 2026-08-21 to median 2.12 s →
>   5.9 h/10k, WITHIN the overnight bar** at identical accuracy numbers
>   (`docs/benchmarks/2026-08-21-analyzer-ab-60-optimized.md`). What did it:
>   BiRefNet 512²-fp16 official variant replaces the 1024² full model
>   (1.07 s vs 5.03 s — saliency was 70% of the budget; the engine consumes
>   only a coarse bbox, and boxes match on real frames), largest-connected-
>   component bbox instead of all-mask-pixels (also *fixes* stray-activation
>   boxes stretching across the frame), and `model_rgb()` cached per photo
>   (was recomputed 3×). Remaining gap to Swift is decode+faces dominated;
>   acceptable per §1.5.

Decision (2026-08-20): Shootr will eventually run on Windows and Linux. That converts
the measurement stack from "Apple frameworks, with swaps where they're weak" to
"**one cross-platform stack is the canonical analyzer**, with Apple frameworks
surviving only outside measurement semantics."

---

## 1. The rule that drives everything

**One measurement semantics, everywhere.** The same photo must produce the same
analysis row on every platform. Per-platform measurement backends (Vision on Mac,
ONNX elsewhere) would make scores non-comparable across machines: different
sharpness, different embeddings, different face counts → different groups →
different culls. That is the same class of bug as clients doing their own score
arithmetic (README rule 6), and it rules out the "port later, fork the analyzer"
path entirely.

Corollary: swapping any measurement component bumps `engine_version` and
invalidates every `analysis` row. Re-analysis cost grows with every library a user
ingests, so **the swap gets cheaper the earlier it happens** — which is why the
canonical stack is decided now, before whole-library scale.

## 1.5 Hardware floor and model budget (user decision, 2026-08-20)

**The floor is an Apple Silicon M4 MacBook, 24 GB unified memory.** A
Windows/Linux machine (older Intel i9 + RTX 2070 Super 8 GB, 24 GB RAM) exists as
a *transitional* target — it will be upgraded, so it constrains nothing
permanently: it must run, degraded throughput and int8 weights acceptable there,
but no model is rejected for its sake.

**Accuracy is prioritized where sensible; latency and model size are explicitly
subordinate.** The user accepts slower culling and large weights. Model selection
rule: *the most accurate available model whose inference fits comfortably within
the M4's 24 GB unified memory in fp16, single image + small batch, alongside
decode buffers.* That admits ViT-L-class backbones for every component
simultaneously with headroom — the lightweight picks below are compatibility
floors, not targets.

Bounds on "where sensible":

- **Not the sharpness metric.** Tenengrad on green/CFA stays — learned IQA is an
  opaque number, and the evidence rule (§04.1) outranks benchmark accuracy. Same
  for aesthetic/"moment" scoring: excluded for trust reasons, not compute.
- **Throughput reframing.** The 3k–10k target survives, but "interactive" may
  degrade toward long-batch. Per this decision that is an accepted trade, not the
  product change §3 previously called it — the §4 gate still measures it (a 10×
  regression needs numbers, not a shrug), but the verdict threshold is "10k usable
  overnight on the M4", not "interactive". M4 has no CUDA: the real throughput
  question on the floor machine is CoreML-EP coverage per model, measured, not
  assumed.
- Weights ship fp16; int8 is a measured fallback for the transitional
  CUDA-8GB-class machine only, and quantization must pass the same §4 accuracy
  checks.

## 2. What moves, what stays

Three buckets. Only the first two involve Apple code at all; the third — the whole
engine, all grouping/culling/scoring logic, XMP, LrC reading, both the API and web
client — is already portable Python/SQLite/TS and is most of the system.

### 2.1 Measurement components → cross-platform canonical

Model tiers follow the §1.5 accuracy-first rule: the "canonical" column is the
compatibility floor; the "accuracy-first" column is what ships if it passes the §4
gate on floor hardware. Named models are candidates as of 2026-08 — re-survey the
state of the art at build time; the *budget* (§1.5) is the durable decision, not
the model names, and every candidate still passes the same §4 gate.

| Component | Today (Apple) | Floor (portable) | Accuracy-first (fits §1.5) | Accuracy delta vs. Vision |
|---|---|---|---|---|
| Face detect + landmarks | Vision rev 3 | SCRFD-2.5G (InsightFace, ONNX) | SCRFD-10G | ≈ / better on small+profile faces |
| Face identity | Vision faceprints (deferred) | ArcFace r50 (InsightFace) | **AdaFace IR-101** — stronger precisely on low-quality/blurred faces, i.e. event work | **better** — fixes the §05.5 weaknesses (profiles, backlight, small faces) |
| Eyes open/closed | none (the known gap) | MediaPipe blendshapes → labelled-frame validation (§03.5) | same — validation against hand-labels is the accuracy lever here, not model size | **better** — was already the plan |
| Face quality | `VNDetectFaceCaptureQualityRequest` | CR-FIQA(S) | CR-FIQA(L) | ≈ / better |
| Scene embedding | `VNGenerateImageFeaturePrintRequest` | DINOv2-small (ONNX) | **DINOv2 ViT-L/14 with registers** (~0.6 GB fp16) | unproven on our shoots — must A/B before adoption (§4) |
| Body pose | `VNDetectHumanBodyPoseRequest` | RTMPose-m | **ViTPose-L** | ≈ / better |
| Horizon | `VNDetectHorizonRequest` | classical line detection (Hough/LSD) | same — already the accurate option; a model adds opacity, not accuracy | ≈, and *more* deterministic |
| Saliency / subject box | Vision attention+objectness saliency | face/subject-box reformulation | **BiRefNet** subject segmentation (~0.9 GB fp16) — a genuine *upgrade* on Vision's saliency, retiring the "honest loss" | **better** (was: worse) |
| Measurement RAW decode | `CIRAWFilter`, enhancement off | **libraw** (rawpy) | same — decode accuracy is about determinism, not weights | **better for measurement** — deterministic across OS updates, direct CFA access (answers §03.4 for free) |

Deliberately non-neural at any budget: the sharpness metric (Tenengrad, §03.3) and
horizon. Accuracy-first does not mean neural-first — it means best *inspectable*
answer per component (§1.5).

A pinned ONNX model also fixes a defect Vision cannot: Apple's models change
silently across macOS updates, and `engine_version` can't pin them. The canonical
stack is reproducible by construction.

### 2.2 Apple code that survives — display path only, never measurement

- **Display decode on macOS stays `CIRAWFilter`**: its per-camera rendering is
  visibly better than libraw's default output, and loupe/compare quality is why the
  native client exists (§12.4). §03.2 already mandates measurement/display as two
  separate paths; this makes the split load-bearing: *measurement = libraw
  everywhere, display = best available per platform.*
- **The SwiftUI client stays macOS-only.** Windows/Linux get the web UI. Note this
  raises the bar on web: the 2026-08 scope change made *native* the control panel
  (PLAN M4), but on non-Mac platforms web is the only surface — so library
  management and anything else that migrated native-first must exist in web before
  a port ships. The both-clients parity rule was already pointing this way. Display
  decode there = engine-rendered previews (`render` command / thumb endpoints),
  which already exist.

### 2.3 Already portable — untouched

Sharpness metric (Tenengrad — our math, §03.3), exposure/clipping stats, all of
grouping/culling/scoring, ingest + content identity, XMP writer, LrC catalog
reader, job orchestration, FastAPI, web client. Note the engine's only
Mac-specific seam is *spawning the helper*; the JSONL contract (§03.4) is the port
boundary and does not change shape.

## 3. Cost, stated plainly

- **Model weights**: ~2–3 GB in the bundle at the accuracy-first tier (§2.1) vs.
  zero for OS-shipped Vision. Accepted per §1.5. Distribution consequence: the
  `.app`/installer either ships them or downloads-on-first-run with a checksum
  (the bundled-Python precedent in `make-app.sh` already does the latter).
- **Speed**: Vision is ANE-accelerated for free. onnxruntime needs per-platform
  execution providers (CoreML on Mac, CUDA/DirectML on Windows, CUDA/CPU on
  Linux) to be competitive. Per §1.5 the accepted bar on floor hardware is
  "10k usable overnight", not "interactive" — but §4 still measures it, because a
  regression past even that bar is a real failure, and better-than-the-bar is
  still worth having (batch size, fp16, EP tuning).
- **Memory discipline**: on the M4 floor, 24 GB unified memory holds the full
  accuracy-first tier resident alongside decode buffers — no staging needed. On
  the transitional 8 GB-VRAM machine the same analyzer must instead stage the
  pipeline (decode+embedding pass, then face pass, then pose/segmentation pass)
  or serialize model loads. Staging is an analyzer-internal execution concern;
  the JSONL contract and the measured *results* are identical either way — only
  wall-clock differs.
- **Two analyzers during transition** (§4): the cost of proving equivalence rather
  than assuming it.

## 4. Adoption is measured, not argued

Same rule as everything else in this project. The canonical analyzer is a second
implementation of the existing JSONL contract (Python + onnxruntime + rawpy — no
Swift). Both analyzers run over the same real shoots; adoption per component
requires:

1. **Agreement or superiority on labelled data** — blink vs. hand-labelled frames,
   identity clusters vs. known guests, sharpness ranking vs. hand-labelled focus
   hits/misses (the §03.7 protocol, reused).
2. **Grouping stability** — DINOv2 replaces feature prints only if groups on
   "Hamy and Luan"-class shoots are as good or better under the *same tuned
   thresholds procedure* (05 §3 thresholds are embedding-specific and will need
   re-measuring; the 2026-08 measurement methodology is the template).
3. **Throughput within target** — `timing_ms` percentiles projected to 10k,
   measured on the M4 floor (§1.5 bar: usable overnight; the transitional CUDA
   machine is informational, not gating).

The analysis/score split makes all of this cheap to trial: a candidate embedding is
one new `embedding.kind`; nothing downstream changes until cutover.

## 5. Sequencing — every step justified even if the ports slip

1. **Now (M1/M2, no new platform work):** blink via MediaPipe (needed regardless);
   ArcFace/SCRFD when faceprints land (better on Mac too). Both are canonical-stack
   components arriving on their own merits.
2. **Post-M2** (once calibration provides the agreement-rate metric that judges
   swaps): build the canonical analyzer against the JSONL contract; run the §4
   comparison; adopt component-wise; single `engine_version` cutover; eat the
   re-analysis while libraries are small.
3. **Then** the ports themselves are packaging problems (installer, service
   lifecycle, paths/volumes on NTFS/ext4), not measurement problems — plus the
   platform-specific ingest work: volume identity and offline detection (§02) are
   currently written against macOS volume semantics.

## 6. Non-goals

- Native Windows/Linux clients. Web only.
- Porting the Swift helper itself. It is superseded by the canonical analyzer on
  all platforms; on macOS it may persist as the display-path renderer only.
- Cross-platform GPU parity guarantees. Determinism target is per-component
  numerical agreement within tolerance, not bit-identical floats.
