# ARW/RAF validation on public samples — two bugs fixed, one design flaw found

The Sony/Fuji gate items did not need the user's photos, only *some* ARW and
RAF files. Five CC0 samples from raw.pixls.us: Sony ILCE-7M3, ILCE-7M4
(uncompressed **and** lossless-compressed — the two container variants), and
two X-Trans bodies (X-T50, X-E5).

## 1. Swift helper: clean on all five

`probe` read model, ISO, exposure bias, capture time and true dimensions for
every file, X-Trans included. CIRAWFilter needed nothing added.

## 2. Python analyzer: two real bugs, both now fixed

| bug | symptom | fix |
|---|---|---|
| RAF is not a TIFF container | `exifread` returned **no tags**; every Fuji file came back `probe_failed` | `analyzer/shootr_analyzer/raf.py` unwraps the header's embedded Exif JPEG (same class of fix as `cr3.py`) |
| RAF Exif describes the *preview* | reported 4416×2944 vs the true 7728×5152 — the two analyzers would disagree on every Fuji photo | `raw_dimensions()` reads the CFA header's `0x0111` tag; now matches Swift exactly |

Post-fix both analyzers agree on all five files. Full `analyze` (decode →
SCRFD → blendshapes → DINOv2 → BiRefNet) runs on ARW and X-Trans RAF with no
format-specific failure. Latency: decode 0.10–0.38 s, vision ~1.3 s, i.e.
**no format cliff** — Sony/Fuji cost what Canon costs.

## 3. ARW embedded preview → **model-dependent; never trust it for measurement**

The gate asked "is Sony ARW's small embedded preview usable at all". It is
not a property of the format:

| body | RAW | embedded preview |
|---|---|---|
| ILCE-7M3 (2018) | 6024×4024 | 1616×1080 (27% linear) |
| ILCE-7M4 (2021) | 7028×4688 | **7008×4672 (full size)** |
| X-T50 | 7752×5178 | 4416×2944 (57%) |

Rule rather than constant: previews are fine for thumbnails when big enough,
and the size must be **checked per file at runtime** (rawpy exposes it
cheaply). Measurement never reads the preview. Item closed.

## 4. ⚠ Design flaw found: `sharpness_max` is not comparable across sources

The X-E5 sample — a **visibly sharp** cityscape (archived render:
`2026-08-30-sharpness-repro/`) — measures `sharpness_max = 0.00065`, below
`MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS` (0.005). Verified through the real
scorer, not inferred:

```
DSCF0202.RAF → sharpness component = 0.0
               evidence = {"diagnosis": "motion_blur_or_shake"}
               landscape total = 0.35   (at the quality floor)
```

Across five files all judged sharp by eye, `current` spans **615×**
(0.00065 … 0.40). Absolute Tenengrad on a linear-gamma decode tracks the
scene's own level and contrast, and every threshold in `scoring.py`
(`MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS`, `FRAME_SHARPNESS_CURVE`) was
calibrated on one bright Canon shoot.

**This is already live in the user's own data**, not merely a Sony/Fuji
issue: within the single wedding, `sharpness_max` spans 0.0003 … 0.43
(1400×), **62 photos (1.39%) are flagged `motion_blur_or_shake`, and the
user kept 5 of them.**

### Two obvious fixes measured — both rejected

| candidate | cross-source spread | within-shoot ρ vs current | blur ladder σ=0.7 |
|---|---|---|---|
| current (absolute) | 615× | 1.000 | 0.706 |
| **ranged** (p99.5→235 rescale) | 30.5× | 0.598 | 0.722 |
| **varnorm** (Σ∣∇I∣² / Σ(I−Ī)²) | **1.4×** | 0.186 | **1.227** ✗ |

- `ranged` neither fixes comparability (30× spread; the reproducer still
  sits 16× below the next sharp file) nor preserves ordering (ρ 0.60 —
  it reshuffles a shoot, invalidating the calibration for no gain).
- `varnorm` collapses the spread beautifully and is **broken as a focus
  metric**: blur *raises* it (σ=0.7 → 1.227), and the blurred reproducer
  outscores the sharp one (0.8×). Variance falls faster than gradient
  energy, so it is anti-correlated with focus.

So this is not a constant tweak, and not solvable by the two obvious
normalizations. Tool: `engine/tools/sharpness_norm_probe.py`.

### Where the flaw actually lives

Design 03 §3.1 already says absolute Tenengrad is content-dependent and
"only ratios are diagnostic" — and the *within-frame* uses honor that (tile
map for focus planes, eye sharpness normalized against the frame's sharpest
tile). The violation is the **absolute thresholds** that turn an
incomparable number into a score: 04 §2.3's curve and the motion-blur floor.

**Recommended direction (needs a decision — it changes scoring semantics):**
score frame sharpness by its **percentile within the shoot** (or scene
group) instead of against global constants. That is ratio-based per §3.1,
self-calibrating per camera and lighting, and culling is already comparative
— we choose *within* groups. It fits the architecture: `score` is the cheap,
always-recomputable half, and the shoot's distribution is already in hand.
Cost: re-validation against the 559-keeper ground truth, and the
motion-blur "disaster" floor needs a per-shoot robust low percentile rather
than 0.005.
