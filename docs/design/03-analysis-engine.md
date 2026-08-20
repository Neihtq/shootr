# 03 — Analysis Engine (Swift)

**Milestone:** M1 · **Depends on:** [02](02-ingest.md) · **Feeds:** [04](04-quality-scoring.md), [05](05-grouping.md)

The compiled Swift helper. Decodes RAW, runs Vision, measures sharpness, emits JSON.
This is the only component that touches pixels.

> **Lifespan note ([13](13-portability.md), 2026-08-20):** Windows/Linux are on the
> roadmap, so post-M2 a cross-platform analyzer (onnxruntime + libraw) implementing
> this same JSONL contract (§4) becomes canonical on all platforms; this Swift
> helper then persists only as the macOS display-path renderer. The contract, the
> correctness rules (§2), and the sharpness design (§3) all carry over unchanged —
> they are decode-source-agnostic by construction.

---

## 1. Why a separate Swift binary

Vision and Core Image are Apple-only. Calling them per-image through pyobjc means
bridging an `NSDictionary` of results and a `CVPixelBuffer` per photo — measurably slow
and awkward, and it puts the ObjC autorelease-pool lifecycle inside the Python process.
A compiled helper gets native speed, clean memory behavior (one pool per image, released
on exit), and a crash boundary: a corrupt RAW that kills the decoder takes down one
subprocess, not a 10,000-photo run.

The cost is process startup, so the helper is **batchable** (§4).

---

## 2. THE critical correctness rule

`CIRAWFilter` applies **sharpening, noise reduction, and an exposure boost by default.**
Measuring sharpness on a default decode measures *Apple's sharpening kernel*, not whether
your subject was in focus. Two photos with different real focus can converge to similar
measured sharpness after processing; noise reduction also destroys the high-frequency
signal that focus measurement depends on.

**Every measurement decode must disable all enhancement:**

```swift
let f = CIRAWFilter(imageURL: url)!
f.isSharpeningEnabled       = false   // inputEnableSharpening
f.noiseReductionAmount      = 0       // inputNoiseReductionAmount
f.boostAmount               = 0       // inputBoost — no tone curve boost
f.isGamutMappingEnabled     = false   // inputDisableGamutMap
f.isLensCorrectionEnabled   = false   // geometry must not shift measured positions
f.scaleFactor               = scale   // inputScaleFactor — decode small, not downsample
```

All verified present on this SDK (SPEC §1).

**Two separate decode paths, never confused:**

| Path | Settings | Used for |
|---|---|---|
| **Measurement** | all enhancement off, linear where possible | sharpness, exposure, WB stats |
| **Display** | Apple defaults on, sRGB | previews for the UI, style-learning features |

Mixing them is a silent-wrongness bug: scores would drift with Apple's decoder version.
`analysis.decode_mode` records which path produced a measurement.

---

## 3. Sharpness measurement

The core question is *"was the eye in focus"*, not *"is this image sharp"*.

### 3.1 Normalization is the whole trick
Absolute sharpness numbers are meaningless — they vary with face size in frame, ISO, lens,
subject texture, and focal length. What's diagnostic is **relative**:

```
eye_sharpness_norm = HF_energy(eye_crop) / HF_energy(sharpest_tile_in_frame)
eye_sharpness_abs  = HF_energy(eye_crop) / face_pixel_height     (scale-invariant)
```

The ratio to the sharpest region separates the two failure modes that a single number
conflates:

| ratio | whole frame | diagnosis |
|---|---|---|
| high | sharp | in focus ✓ |
| **low** | **sharp** | **focus missed — hit the ear/shoulder. The real error.** |
| high | soft | motion blur / camera shake (whole frame soft) |
| low | soft | unusable |

Without normalization, "focus missed the eye" and "everything is slightly soft" look
identical, and the tool would reject good frames while keeping mis-focused ones.

### 3.2 Metric
**Tenengrad** (Sobel gradient energy) over **Laplacian variance**: less noise-sensitive,
which matters at the ISO 3200–12800 that indoor wedding work lives at. Laplacian variance
is a noise amplifier, and noise is exactly what's abundant in the frames whose focus is
hardest to judge.

Computed on the **green channel / luminance only** — chroma interpolation invents detail.

### 3.3 Frame sharpness map
16×16 tile grid of Tenengrad energy, stored in `analysis.frame`. Serves:
- the normalization denominator (max tile),
- **landscape focus-plane detection** — where is the sharp plane, and does DoF cover the
  scene (§04),
- motion-blur detection (uniformly low across all tiles).

### 3.4 CFA vs. scaled decode — **unresolved, benchmark gate**
Measuring on the **raw CFA green plane** avoids demosaic-invented detail entirely and is
theoretically the cleanest focus signal. But:
- **Bayer** (Canon, Sony): green is a regular half-lattice — trivial to extract.
- **X-Trans** (Fuji): irregular 6×6 pattern, ~55% green — needs a positional mask, and
  neighbor spacing is non-uniform, so gradient kernels need care.
- Core Image gives no direct CFA access; this needs raw-bytes parsing, which is real work
  across three vendors.

**Decision deferred to measurement, not argument.** If scaled decode with enhancement
fully disabled correlates well enough with CFA sharpness on real files, the CFA path is
not worth its complexity. Benchmark protocol in §7. `decode_mode` exists so either
outcome is representable.

---

## 4. CLI contract

```
shootr-analyze probe    --files <list.json>              → JSONL metadata (§02)
shootr-analyze analyze  --files <list.json> --scale 0.5   → JSONL measurements
shootr-analyze render   --file <raw> --size 2048 --out <p> → display JPEG
shootr-analyze version                                    → engine version + Vision revs
```

JSONL on stdout, one object per photo, flushed per photo so Python records progress
incrementally (§09) — a batch that dies at photo 400 of 500 keeps 400 results.
File lists come via a temp JSON file, not argv (argv has length limits at 10k scale).

**Batch size 32–64:** amortizes startup while keeping the crash blast radius small and
memory bounded.

Errors are per-photo objects (`{"path":…,"error":…}`), never a nonzero exit. One corrupt
RAW must not fail the batch.

### Output shape
```jsonc
{
  "path": "...", "content_id": "...",
  "decode_mode": "scaled", "engine_version": "0.1.0+vision3",
  "frame": {
    "sharpness_tiles": [[...16x16 floats...]],
    "sharpness_max": 0.83, "sharpness_mean": 0.31,
    "histogram": { "y": [...256], "clipped_hi": 0.004, "clipped_lo": 0.001 },
    "as_shot_wb": { "temp": 5450, "tint": 8 },       // for §08 delta prediction
    "horizon_angle": -1.7,                            // VNDetectHorizonRequest
    "exposure_bias": 0.0
  },
  "saliency": { "attention_bbox": [...], "objectness_bbox": [...] },
  "faces": [{
    "idx": 0, "bbox": [...], "roll": 0.02, "yaw": -0.11, "pitch": 0.0,
    "capture_quality": 0.71,
    "eyes": { "l": {"sharp_norm":0.78,"open":0.93}, "r": {...} },
    "landmarks": { "leftEye": [...], "rightEye": [...] },
    "faceprint": "base64"
  }],
  "embedding": { "scene": "base64 float32", "dim": 768 },
  "pose": [{ "joints": {...} }],
  "timing_ms": { "decode": 210, "vision": 95, "sharpness": 40 }
}
```

`timing_ms` is not decoration — it's how we find the bottleneck at 10k scale and validate
the throughput target.

---

## 5. Vision usage

All native, no external models (README capability table):

| Request | Purpose |
|---|---|
| `VNDetectFaceRectanglesRequest` (rev 3) | face bboxes, roll/yaw/pitch |
| `VNDetectFaceLandmarksRequest` (rev 3, 76-pt) | eye contours → eye crops |
| `VNDetectFaceCaptureQualityRequest` (rev 3) | Apple's own face-quality score |
| `VNGenerateImageFeaturePrintRequest` (rev 2) | scene embedding (§05) |
| `VNDetectHumanBodyPoseRequest` | pose vector (§05), limb-cut flags (§04) |
| `VNGenerateAttentionBasedSaliencyImageRequest` | subject placement (§04) |
| `VNGenerateObjectnessBasedSaliencyImageRequest` | subject extent |
| `VNDetectHorizonRequest` | horizon level for landscape (§04) |

Requests batch into one `VNImageRequestHandler` per image — one decode, one pixel buffer,
all requests. Running them separately would decode repeatedly.

**Resolution matters and differs per request.** Face detection works fine at ~1000 px, but
eye-region sharpness needs real resolution — at 1/4 scale an eye is a handful of pixels and
the measurement is noise. So:
1. Detection pass at reduced scale (fast, finds faces).
2. **Eye-sharpness pass re-decodes only the eye ROIs at full scale** via
   `CIRAWFilter` + crop, so we pay full-res cost on ~0.1% of the pixels.

That two-tier approach is what makes accurate focus measurement affordable at 10k scale.

### Blink detection — the one gap
Vision has **no native eye-open/closed signal** (verified: no such property on
`VNFaceObservation`). Options:

1. **Landmark eye-aspect-ratio** from the 76-pt constellation — zero dependencies, but
   sensitive to yaw and known to be unreliable on squints and partial blinks.
2. **MediaPipe blendshapes** (`eyeBlinkLeft/Right`) — purpose-built and much more
   reliable, at the cost of a Python-side dependency and a second detector pass.
3. Small dedicated ONNX eye-state classifier on eye crops.

**Design:** ship (1) in the helper as a baseline and always populate `eye_open_*` with
`eye_source` recording provenance; add (2) as a swappable Python-side refiner. Blink is a
*dominant* metric for portraits and events (§04), so being wrong is expensive — it needs
an explicit accuracy check against hand-labelled frames before it drives any culling.

---

## 6. Concurrency & memory

- Python spawns **N helper processes**, N = `min(6, performance_core_count)`, each doing
  batches serially.
- Core Image RAW decode is GPU-backed; too many concurrent decoders thrash VRAM and the
  Metal command queue. GPU saturation, not CPU, is the expected limit on a 20-core M5 Pro.
- One `autoreleasepool` per image inside the batch loop — without it, `CIImage`/
  `CVPixelBuffer` accumulate and a 64-image batch can balloon past several GB.
- `CIContext` is created **once per process** and reused; per-image contexts recompile
  Metal shaders.

---

## 7. Benchmark gate (must run before M1 coding is locked)

Needs the real sample set (SPEC §11): mixed CR3/ARW/RAF, bursts, brackets, deliberate
focus misses, high-ISO frames.

| Question | Method | Decides |
|---|---|---|
| CFA vs. scaled sharpness | correlate both against hand-labelled focus hit/miss | whether to build CFA parsing |
| Sufficient decode scale | sweep 0.25/0.5/1.0, measure eye-sharpness accuracy | default `scale` |
| ARW preview viability | compare embedded preview vs. scaled decode accuracy | whether preview path is usable at all |
| X-Trans behavior | Fuji subset vs. Bayer subset | whether Fuji needs its own path |
| Per-photo latency | `timing_ms` percentiles | validates 3k–10k target |
| Blink accuracy | EAR vs. MediaPipe vs. labels | which blink source ships |

**Explicit risk:** if eye-sharpness needs full-res decode on every face, throughput drops
roughly an order of magnitude and the 10k target needs rethinking (overnight batch rather
than interactive). Better to discover this on 200 real files than after building the UI.
