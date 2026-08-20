# Shootr — Project Context

Offline photography culling + edit-assistance app for macOS. Scores photos on technical
quality, groups them, proposes a cull selection, pushes selects to Lightroom Classic,
learns the user's editing style, and writes predicted develop settings back. All on-device.

**Current state: design complete, zero code written.** Do not assume any implementation
exists. If asked to build, start from the design docs and the benchmark gate below.

---

## Where things are

| Path | What |
|---|---|
| `SPEC.md` | Requirements, locked decisions, verified environment |
| `docs/design/README.md` | **Start here** — domain map + cross-cutting rules |
| `docs/design/01..12-*.md` | One doc per domain (see index in that README) |

Docs cross-reference by number (`§04` = quality scoring). When changing behavior, update
the owning doc — don't let code and design drift.

---

## Non-negotiable rules

These are correctness/safety invariants, not preferences. Violating one is a bug.

1. **Never write to a live `.lrcat`.** Copy it (with `-wal` and `-shm`), read the copy
   with `mode=ro`. Undocumented schema + LrC holds locks = corrupting years of user work.
2. **Culling never deletes.** Selection is metadata only; rejects are marked, never removed.
3. **Never silently overwrite user XMP.** Read → diff → back up → confirm → atomic write,
   and preserve fields we don't own (keywords, GPS, crop, local edits).
4. **Measurement decodes disable all enhancement.** `CIRAWFilter` applies sharpening, noise
   reduction, and exposure boost *by default* — measuring on that measures Apple's
   processing, not the photograph. Two separate decode paths: measurement vs. display.
5. **Scores carry evidence.** No opaque numbers; every score traces to inspectable
   per-metric values with weights and contributions.
6. **Logic lives in the Python engine.** Clients render; they never score, group, or select.
   Any client-side arithmetic on scores is a design bug — it's how two frontends diverge.
7. **All work is resumable.** External drives get unplugged mid-run; per-photo checkpointing
   is structural, not an optimization.
8. **Inapplicable metrics are `null`, not `0`.** A landscape has no eyes. Zeroing would rank
   every landscape as terrible. Distinguish "not applicable" / "detector abstained" /
   "genuinely bad" — conflating these is the likeliest source of wrong rankings.

---

## Architecture in brief

```
Python engine (3.14)  ──spawns──►  shootr-analyze (Swift CLI)
  owns SQLite (WAL)                RAW decode · Vision · sharpness · JSONL out
  ingest, clustering, style,
  XMP writing, job queue
        │
   FastAPI on 127.0.0.1 only
        ├── React/Vite web client   (M1, primary — the iteration surface)
        └── SwiftUI native client   (M4, subset — a culling instrument)
```

**Key design decision:** `analysis` (expensive, profile-independent measurements) is
separate from `score` (cheap, profile-dependent, always recomputable). This is why
retuning weights or changing a shoot's genre costs milliseconds instead of re-decoding
10,000 files. Never conflate them; never make `score` the cache key.

**Platform direction (2026-08-20):** Windows and Linux are on the roadmap (design 13).
One measurement semantics everywhere — a per-platform analyzer fork is the same class
of bug as client-side scoring. Post-M2, a cross-platform analyzer (onnxruntime +
libraw) behind the same JSONL contract becomes canonical on all platforms;
Vision/CIRAWFilter survive only in the macOS display path. Don't add new
Vision-dependent *measurement* features without checking design 13's component table.

**Photo identity is content-based**, not path-based: `blake3(size ‖ first 64KB ‖ last 64KB)`.
External drives remount at different paths.

---

## Verified environment facts (checked 2026-07-30, don't re-derive)

- **Apple M5 Pro**, 20-core GPU, 48 GB, Metal 4.
- **Swift 6.3.2, macOS 26 SDK, CLI tools only — no full Xcode.** Engine and helper build
  fine; Xcode is needed only for the SwiftUI client (M4).
- **`CIRAWFilter` handles all target formats natively**: 893 models — Canon 166, Sony 112,
  Fuji 59 (incl. X-Trans: X-T/X-Pro/GFX). **libraw is not needed.**
- **Vision covers more than expected** — these replace external deps:
  `VNGenerateImageFeaturePrintRequest` (scene embedding, replaces DINOv2/CLIP),
  `VNDetectHumanBodyPoseRequest` (replaces MediaPipe Pose),
  `VNGenerateAttentionBasedSaliencyImageRequest`, `VNDetectHorizonRequest`,
  `VNDetectFaceCaptureQualityRequest` (rev 3), `VNDetectFaceLandmarksRequest` (rev 3, 76-pt).
- **Only remaining external ML need: blink/eyes-closed.** Vision has no native eye-open
  signal. Isolated, swappable component.
- **Python 3.14.6** at `/opt/homebrew/bin/python3.14`; wheels available for mediapipe,
  onnxruntime, torch, scikit-learn. Node v24.18.0. SQLite 3.53.3 (`mode=ro` and
  `immutable=1` both work).
- **No photos, no LrC catalog, no Adobe apps on this Mac.** The library is external.

---

## Locked requirements

- **RAW formats:** Canon CR2/CR3, Sony ARW, Fuji RAF.
- **Genres: all four** — events/weddings, posed portraits, landscape/travel, street.
  Hence per-shoot scoring **profiles**; there is no universal weight set.
- **Both frontends** ship: web first, native second (API must stabilize first).
- **Style data available:** LrC catalogs with edits, XMP sidecars, exported JPEG+RAW pairs.
- **Throughput target:** 3,000–10,000 photos per shoot.
- **Edit delivery:** per-photo XMP sidecar `crs:` values, global params only.

---

## Build order

1. **M1 — cull loop on real photos**: ingest → analyze → score → group → select → write
   picks to XMP + LrC, reviewable in the web app.
2. **M2** — calibrate scoring against the user's catalog pick/reject/star history.
3. **M3** — style learning (k-NN → look families → XMP `crs:` writer).
4. **M4** — SwiftUI client over the stable API.
5. **M5** — optional LrC Lua plugin.

---

## ⚠ Blocking: benchmark gate before M1 coding is locked

Needs real sample files (mixed CR3/ARW/RAF, bursts, brackets, deliberate focus misses,
high-ISO). See `docs/design/03-analysis-engine.md` §7. It decides:

- CFA green-plane vs. scaled-decode sharpness → whether to build per-vendor CFA parsing.
- Default decode scale; whether Sony ARW's small embedded preview is usable at all.
- Per-photo latency → **if eye-sharpness needs full-res decode per face, throughput drops
  ~10× and the 10k target becomes an overnight batch, not interactive.**
- Which blink detector ships (accuracy vs. hand-labelled frames).

Building the Swift helper's `probe`/`analyze` commands is useful regardless of the outcome.

---

## Known risks — stay honest about these

- **Blink detection drives a dominant metric** for portraits/events. A bad detector actively
  discards good photos. Must be validated against hand-labelled frames before it influences
  culling. Abstain on extreme yaw rather than guess.
- **Street ranking is weak by design.** Doc 04 says so plainly: dedup and
  technical-disaster filtering only, not aesthetic selection. `moment` is a placeholder, not
  an implemented metric. Don't let it drift into implying otherwise.
- **Style learning must beat "apply the family's median edit to everything."** If it can't,
  ship the median as a preset and drop the model.
- **Local adjustments (brushes, gradients, AI masks) are permanently out of scope** for
  style transfer — spatial and per-photo; there's no honest way to transfer them.
- **LrC catalog schema is undocumented and version-specific.** Validate tables/columns
  before querying; degrade to sidecar-only rather than guessing.
- **Exposure brackets must never be culled as bursts.** Getting this wrong destroys HDR sets
  and feels like data loss to the user. Explicit test case.

---

## Working preferences

- Verify platform/API claims by compiling or running a probe — this project has already had
  assumptions corrected that way (Vision coverage, `CIRAWFilter` defaults). Don't write
  design or code from recollection about Apple frameworks or LrC internals.
- Prefer flags with evidence over opaque learned scores anywhere the user's artistic intent
  is involved. A photographer will not trust a number that overrules them without reason.
- State limitations plainly in docs and UI rather than implying capability we lack.
