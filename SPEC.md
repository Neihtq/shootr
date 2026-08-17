# Shootr — Photography Culling & Style Assistant

Offline photo-culling and edit-assistance app for macOS. Scores photos on technical
quality, groups them, proposes a cull selection, pushes selects into Lightroom Classic,
learns your editing style, and writes predicted develop settings back to LrC — all
on-device.

**Status:** specification / pre-implementation. No code yet.

---

## 1. Verified environment (this machine, 2026-07-30)

| Component | Finding | Consequence |
|---|---|---|
| Chip | Apple M5 Pro, 20-core GPU, 48 GB, Metal 4 | GPU RAW decode + parallel workers viable for 10k/shoot |
| Swift | 6.3.2, macOS 26 SDK, **CLI tools only (no Xcode)** | Engine + helper build now; Xcode needed only for SwiftUI client |
| Vision | `VNDetectFaceCaptureQualityRequest` rev 3, `VNDetectFaceLandmarksRequest` rev 3 (76-pt) compile | Primary face/eye detector |
| Core Image | `CIRAWFilter` + `inputScaleFactor`; 893 camera models | Native scaled RAW decode; **libraw not needed** |
| RAW coverage | Canon 166, Sony 112, Fuji 59 (incl. X-Trans: X-T/X-Pro/GFX) | All three target formats decode natively |
| Python | 3.14.6 at `/opt/homebrew/bin/python3.14`; mediapipe/onnxruntime/torch/sklearn wheels present | Orchestration + ML in Python |
| Node | v24.18.0 | Web client toolchain |
| Photos/catalog/Adobe | **None present on this Mac** | Library is external; ingest must handle removable/absent sources |

**Unverified until real files are available (must benchmark before committing):**
- CFA-green-plane sharpness vs. scaled-decode sharpness — which is accurate enough. Determines pipeline complexity.
- Whether Sony ARW scaled decode is fast enough to skip the embedded preview entirely.
- X-Trans green-mask sharpness (6×6 irregular pattern) if CFA path is chosen.
- Real per-photo latency on M5 Pro → confirms the 3k–10k throughput target.

---

## 2. Decisions locked with user

- **RAW formats:** Canon (CR2/CR3), Sony (ARW), Fuji (RAF) + others via Core Image.
- **Genres:** events/weddings, posed portraits, landscape/travel, street. → **scoring profiles**, no universal weight set.
- **Frontends:** both a **local web app** (primary, built first) and a **native SwiftUI app** (second), over one shared HTTP API. Neither client holds logic.
- **Style data available:** LrC catalog(s) with edits + XMP sidecars + exported JPEG/RAW pairs.
- **First milestone:** cull loop on real photos, reviewable in web app, writing picks to XMP + LrC.
- **Throughput target:** 3,000–10,000 photos/shoot → resumable, checkpointed batch pipeline.
- **Edit delivery:** per-photo XMP sidecar `crs:` values (with the safety rules in §7).

---

## 3. Architecture

Single source of truth = **SQLite**. Only the Python API mutates it. Both clients are
dumb renderers over the HTTP API. Logic never leaves the engine.

```
                 ┌─────────────────────────────────────────────┐
   External      │  Python engine (3.14)                        │
   library  ───► │  ingest · orchestration · clustering ·       │
   (RAW/XMP/      │  style model · XMP writer · SQLite owner     │
    catalog)      └───────┬──────────────────────┬──────────────┘
                          │ spawns per-image      │ owns
                 ┌────────▼─────────┐    ┌────────▼────────┐
                 │ Swift helper CLI │    │  SQLite (WAL)   │
                 │ (JSON in/out):   │    │  shoots, photos,│
                 │ CIRAWFilter decode│   │  faces, scores, │
                 │ Vision faces/eyes │   │  groups, selects│
                 │ CFA sharpness     │   │  edits, jobs    │
                 │ preview render    │   └─────────────────┘
                 └──────────────────┘             ▲
                          ▲                        │ read/write
                 ┌────────┴────────────────────────┴───────────┐
                 │  FastAPI local HTTP (127.0.0.1 only)         │
                 └───────┬──────────────────────────┬───────────┘
                    React/Vite web            SwiftUI native
                    (built first)             (built second)
```

**Why the language split:** Vision + Core Image are Apple-only and slow/awkward over
pyobjc for per-image calls, so a compiled Swift helper does decode + detection and
emits JSON. Everything ML/clustering/statistical stays in Python where the ecosystem
is. The SwiftUI client reuses the same helper for fast RAW preview rendering — that,
not aesthetics, is the reason it's worth building.

### Swift helper contract
- `decode --scale <f> --out <path> <raw>` → scaled RGB/preview for rendering.
- `analyze <raw>` → JSON: faces (bbox, roll/yaw, captureQuality, landmarks, per-eye
  open/closed + eye-region sharpness), frame sharpness map, CFA-plane sharpness,
  histogram/WB stats, EXIF subset.
- Batchable (accepts a file list) to amortize process startup.

---

## 4. Scoring (per profile)

Emit **auditable per-metric evidence**, never a single opaque score. Final rank =
profile-weighted combination; every input inspectable in the UI.

**Metrics**
- *Eye/face focus* — high-frequency energy in eye region **normalized** against the
  sharpest region in frame and against face pixel-height. Catches "focus hit the ear,
  not the eye"; robust to soft whole frames, ISO, lens. Measured on CFA green plane if
  benchmark favors it, else scaled decode.
- *Blink / eyes-closed* — MediaPipe blendshapes `eyeBlinkLeft/Right` (beats hand-rolled
  eye-aspect-ratio), cross-checked against Vision eye landmarks.
- *Overall / focus-plane sharpness* — per-face for portraits; frame-wide sharpness map
  for landscape (is the intended plane sharp, does DoF cover the scene).
- *Composition* — **flags with evidence**, not a score: `face_clipped`,
  `limb_cut_at_joint`, `subject_within_Npct_of_edge`, `no_headroom`,
  `lead_room_inverted`, plus rule-of-thirds distance as a soft number.
- *Face capture quality* — Vision's `captureQuality` as an independent cross-check.

**Profile weight matrix**

| Signal | Portrait | Event | Landscape | Street |
|---|---|---|---|---|
| Eye focus | dominant | dominant | n/a | off |
| Blink/expression | dominant | high | n/a | off |
| Overall sharpness | moderate | moderate | dominant (focus-plane) | low (motion may be intentional) |
| Composition flags | strict | loose | thirds/horizon-level | very loose |
| Burst dedup | moderate | aggressive | light (brackets≠burst) | light |

**Bracket guard:** frames separated by `ExposureBiasValue` steps are exposure brackets,
not a cull-able burst — never dedup them against each other.

---

## 5. Grouping (hierarchical)

1. **Session/scene** — capture-time gaps + loose embedding similarity (DINOv2/CLIP via
   CoreML/MLX).
2. **Shot group** — tight embedding + time proximity. This is the **cull unit** ("9
   frames of one pose → keep 1–2").
3. **Pose** — MediaPipe pose landmarks → normalized keypoint vector. Its own axis for
   posed portraits; for events the shot-group already captures it.
4. **Person identity** — Vision faceprints; group by who's in frame (often more useful
   than scenery for selects).

---

## 6. Culling

- Per group, propose top selects by profile-weighted score.
- **Never deletes.** Output = a selection (flags/ratings/collection membership). Rejects
  are marked, not removed.
- **Calibration (later milestone):** read historical pick/reject/star decisions from a
  **copy** of the LrC catalog and fit weights to the user's actual past choices. This is
  labelled ground truth worth more than hand-tuned defaults.

---

## 7. Lightroom Classic integration

**Hard rule: never write to the live `.lrcat`.** Undocumented schema + LrC holds locks →
corruption. Reading a **copy** is safe.

**Selects delivery (M1):** XMP sidecar flags/ratings/color labels + a "Selects"
collection; user reviews in LrC. (Lua plugin is a later, optional UX upgrade.)

**Edit delivery:** per-photo XMP sidecar `crs:` values, with safeguards:
- Detect and **never silently overwrite** existing sidecar edits — back up, diff, and
  require explicit confirmation.
- Predictions land as a *starting point* in develop history; user tweaks from there.
- Scope: **global `crs:` params only** — Exposure, Contrast, Highlights/Shadows/
  Whites/Blacks, Temp/Tint, Vibrance, Saturation, Clarity, Texture, Dehaze, tone curve,
  HSL, color grading. **Local adjustments (brushes/gradients/AI masks) explicitly
  excluded** — they're spatial/per-photo and cannot be honestly transferred in v1.

---

## 8. Style learning

- **Predict deltas from as-shot/neutral**, not absolutes. Predict **Temp as a ratio to
  as-shot**, not Kelvin — otherwise the model just learns the camera's average.
- **Cluster edit history into look families** (weddings ≠ street ≠ landscape); condition
  prediction on the family chosen for the shoot. One averaged style fits nothing.
- **Start with k-NN retrieval** before training: find k most visually similar edited
  photos, blend their settings. Works at a few hundred edits, inspectable ("edited like
  these 5"), and is the baseline a trained model must beat.
- **Data sources** (complementary): catalog copy → develop settings + pick/reject
  ground truth; sidecars → `crs:` params directly; JPEG+RAW pairs → validate that a
  rendered prediction matches the actual export.

---

## 9. Data pipeline (throughput 3k–10k)

- **Resumable, checkpointed batch jobs** — per-photo status in SQLite (`jobs` table);
  crash/unplug resumes without reprocessing.
- Parallel Swift-helper workers sized to GPU/CPU; scaled decode, not full-res per frame.
- Content-hash cache keyed on file + mtime; re-ingest is incremental.
- Progress streamed to clients (SSE/websocket) — no "hold it all in one run and hope".
- Source library is external/removable: handle absent volumes, verify hashes on
  reconnect.

---

## 10. Build order

1. **M1 — Cull loop on real photos** *(first)*: ingest → Swift-helper analyze → score
   (profiles) → group → select → write picks to XMP + LrC "Selects" collection →
   review in web app. Includes: SQLite schema, FastAPI, Swift helper, resumable jobs,
   React grid with per-metric overlays + eye-crop zoom.
2. **M2 — Calibrate scoring** against catalog pick/reject/star history.
3. **M3 — Style learning**: k-NN baseline → look-family clustering → XMP `crs:` writer
   with overwrite safeguards.
4. **M4 — SwiftUI native client** over the stable API (reuses Swift helper for render).
5. **M5 — (optional) LrC Lua plugin** for in-catalog apply.

**Benchmark gate before M1 coding starts:** on real user files, decide CFA-plane vs.
scaled-decode sharpness, confirm ARW preview handling, and measure per-photo latency.

---

## 11. Open items needing real files
- Provide a sample folder (mixed CR3/ARW/RAF, some bursts, some brackets) + a catalog
  copy for the benchmark gate and scoring calibration.
- Confirm LrC version and whether "Automatically write changes into XMP" is enabled.
