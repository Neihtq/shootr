# First cull-agreement measurement — real edited wedding, 4,448 frames

The M2 ground-truth shoot arrived: `/Users/qthienng/Pictures/Peter and Thuan`,
a finished wedding edit. 4,447 RAWs on disk (3,877 CR3 + 570 CR2, two bodies);
the user's LrC catalog contains exactly 559 of them (12.6% keep rate) — catalog
membership IS the cull. Extracted from a copy of the live catalog
(`~/Pictures/Lightroom/Lightroom Catalog.lrcat`, DB version 1504001) opened
`immutable=1`; loaded into `lr_history`.

**Sidecar caveat:** all 4,447 XMPs carry ratings/labels from some other tool
(binary 0/5 ratings + 5-color taxonomy, no Adobe fingerprints, contradicts the
real cull — 1,327 claimed "5-star" vs 559 actual keeps). User: ignore them.
Ingest must never treat sidecar ratings as user intent by default.

## Run

Live Swift pipeline end-to-end (analyze → group → score → select, profile
`event`, shoot 3, selection 12): **4,448/4,448 frames, 0 failures, 1.91 h**
(~1.55 s/frame single-worker) → the 10k interactive target holds on real
mixed CR2/CR3. 961 groups. First-ever CR2 run: no decode or measurement
anomalies; CR2 body actually agrees *better* than CR3 (34% vs 50%
false-reject on keepers).

## Agreement vs the user's cull

| engine \ user | kept in LR (559) | left behind (3,889) |
|---|---|---|
| pick (1,256) | 179 | 1,077 |
| alt | 116 | 670 |
| reject | 264 | 2,142 |

- Keeper recall as pick: **32.0%** · as pick-or-alt: 52.8%
- False-reject rate on keepers: **47.2%** (the asymmetric headline, 06 §7)
- Engine keep rate 28% vs user 12.6% — `keep_n` is loose for this user

## The number that matters: moment coverage 98.6%

Of 380 keepers not picked, only **8** sat in a group with no pick at all.
372 were "the engine picked a different frame of the same moment" — reject
reasons are dominated by `near-duplicate of pick`. So the architecture
(group → pick within group) is sound; **within-group ordering is the gap**:
142/380 non-picked keepers ranked 6th-or-worse in their group by engine
score, median gap to the group's top 0.092. Not a near-miss threshold
problem — a genuine ordering disagreement (user picks expression/moment,
engine picks technical). This is exactly what M2 weight fitting is for.

## Blink false-positive cluster — known risk confirmed on real data

68 of 264 false-rejects (26%) carry `eyes closed` reasons, 47 of them in one
continuous 17:15–18:09 segment. Every one has `eye_source='ear_landmarks'`:
the live Swift path still runs the **EAR baseline** — the eye source the
2026-08-20 labelling round measured at FA 16.7% — because the MediaPipe
blendshape refiner only exists in the Python analyzer. Multi-face frames +
min-of-eyes over EAR 0.2–0.4 values → "closed". CLAUDE.md's "a bad detector
actively discards good photos" risk, demonstrated. (Face pitch/yaw are also
stored as 0 on these rows, so yaw abstention can't fire — check helper
population before relying on it.)

**Action ordering consequence:** bringing blendshapes to the live eye path —
either wiring the refiner into the Swift pipeline or the analyzer cutover
itself — is now the highest-leverage single fix; it addresses ~26% of
false-rejects before any weight fitting. The 68 frames are also ready-made
hand-label candidates to grow the n=6 closed-eye calibration set.

## M2 inputs now available

- `lr_history`: 559 keeper rows (pick_flag, rating) for shoot 3
- Catalog has develop settings on essentially every keeper
  (`Adobe_imageDevelopSettings`, 559/560) → M3 style data exists in the
  same catalog, not just cull data
- Still waiting: ARW/RAF samples (user: "need to wait a little")
