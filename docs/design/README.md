# Shootr — Design Documents

Detailed design per domain. Parent requirements: [`../../SPEC.md`](../../SPEC.md).

## Domain map

```
                        ┌──────────────────────────┐
                        │ 01 Domain model & storage│  ← every domain depends on this
                        └────────────┬─────────────┘
                                     │
   ┌───────────────┬─────────────────┼──────────────────┬─────────────────┐
   │               │                 │                  │                 │
┌──▼───────┐  ┌────▼─────────┐  ┌────▼──────┐   ┌───────▼──────┐  ┌───────▼──────┐
│02 Ingest │─►│03 Analysis   │─►│04 Quality │──►│05 Grouping   │─►│06 Culling    │
│  library │  │   engine     │  │  scoring  │   │  & clustering│  │  & selection │
└──────────┘  │  (Swift)     │  └───────────┘   └──────────────┘  └───────┬──────┘
              └──────────────┘                                            │
                                                    ┌─────────────────────┴────────┐
                                                    │                              │
                                            ┌───────▼────────┐          ┌──────────▼──────┐
                                            │07 Lightroom    │◄─────────│08 Style learning│
                                            │   integration  │          │                 │
                                            └────────────────┘          └─────────────────┘

   ┌──────────────────────────────────────────────────────────────────────────┐
   │ 09 Orchestration (jobs, resumability)   10 API contract                   │
   │ 11 Web client                           12 Native client                  │
   └──────────────────────────────────────────────────────────────────────────┘
```

## Documents

| # | Domain | Owns | Milestone |
|---|---|---|---|
| [01](01-domain-model.md) | Domain model & storage | Entities, SQLite schema, identity, invariants | M1 |
| [02](02-ingest.md) | Ingest & library | Scanning, RAW probing, hashing, external volumes | M1 |
| [03](03-analysis-engine.md) | Analysis engine (Swift) | RAW decode, Vision, sharpness measurement | M1 |
| [04](04-quality-scoring.md) | Quality scoring | Metrics, normalization, profiles, evidence | M1 |
| [05](05-grouping.md) | Grouping & clustering | Scene/shot/pose/identity hierarchy | M1 |
| [06](06-culling.md) | Culling & selection | Selection algorithm, calibration | M1/M2 |
| [07](07-lightroom.md) | Lightroom integration | Catalog read, XMP write, safety | M1/M3 |
| [08](08-style-learning.md) | Style learning | k-NN, look families, delta prediction | M3 |
| [09](09-orchestration.md) | Orchestration | Job queue, resumability, progress | M1 |
| [10](10-api.md) | API contract | HTTP surface both clients share | M1 |
| [11](11-web-client.md) | Web client | React review UI | M1 |
| [12](12-native-client.md) | Native client | SwiftUI app | M4 |
| [13](13-portability.md) | Portability | Windows/Linux; the canonical cross-platform measurement stack | post-M2 |

## Cross-cutting rules

These bind every document. Violations are bugs, not trade-offs.

1. **Never write to a live `.lrcat`.** Read from a copy only. (§07)
2. **Culling never deletes.** Selection is metadata; rejects are marked. (§06)
3. **Never silently overwrite user XMP.** Back up, diff, confirm. (§07)
4. **Measurement decodes disable all enhancement.** Sharpening, noise reduction, and
   boost off — otherwise you measure Apple's processing, not the photograph. (§03)
5. **Scores carry evidence.** No opaque numbers; every score traces to inspectable
   per-metric values. (§04)
6. **Logic lives in the engine.** Clients render; they never score, group, or select. (§10)
7. **All work is resumable.** External drives get unplugged mid-shoot. (§09)

## Platform capabilities (verified 2026-07-30)

> **Superseded in direction by [13](13-portability.md) (2026-08-20):** Windows and
> Linux are on the roadmap, so the cross-platform stack becomes the canonical
> analyzer post-M2 and Vision/Core Image retreat to the macOS display path. The
> table below remains accurate for what ships in M1–M2 on this machine.

Vision covers more than initially assumed, which removes three dependencies:

| Capability | API | Replaces |
|---|---|---|
| Scene embedding | `VNGenerateImageFeaturePrintRequest` (rev 2) | DINOv2 / CLIP |
| Body pose | `VNDetectHumanBodyPoseRequest` | MediaPipe Pose |
| Subject placement | `VNGenerateAttentionBasedSaliencyImageRequest`, `…ObjectnessBased…` | hand-rolled saliency |
| Horizon angle | `VNDetectHorizonRequest` | hand-rolled |
| Face quality | `VNDetectFaceCaptureQualityRequest` (rev 3) | — |
| Face landmarks | `VNDetectFaceLandmarksRequest` (rev 3, 76-pt) | — |
| RAW decode | `CIRAWFilter`, 893 models (Canon 166 / Sony 112 / Fuji 59) | libraw |

**Remaining external ML dependency:** blink/eyes-closed only. Vision exposes no native
eye-open signal, so this is an isolated swappable component (§04).
