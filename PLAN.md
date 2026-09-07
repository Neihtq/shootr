# Shootr — Project Plan

Tracks implementation against the design docs (`docs/design/`). Crossed-out = built and
tested. Keep this file updated as work lands; when behavior diverges from a design doc,
update the owning doc too (CLAUDE.md rule).

**Legend:** ~~done~~ · ⚠ blocked · unmarked = not started

---

## Blocking gate (before M1 analysis code is locked)

- ⚠ **Benchmark gate** (`03 §7`) — needs real sample files (mixed CR3/ARW/RAF, bursts,
  brackets, deliberate focus misses, high-ISO). Decides:
  - CFA green-plane vs. scaled-decode sharpness → whether to build per-vendor CFA parsing
  - Default decode scale (0.25 / 0.5 / 1.0 sweep)
  - Whether Sony ARW embedded preview is usable at all
  - Per-photo latency → validates the 3k–10k interactive target (or reframes as overnight batch)
  - ~~Which blink detector ships (against hand-labelled frames)~~ — tooling
    (`engine/tools/label_blinks.py`) + first round done 2026-08-20: 33 faces
    labelled; **blendshapes separate cleanly (FR/FA 0%) where EAR overlaps**
    (FR 4.3%/FA 16.7% at its best cut). Per-source calibrated curves shipped
    (`EYES_OPEN_CURVES`, 04 §2.2). Provisional at n=6 closed — grow the labelled
    set opportunistically; refit in M2
- ~~Obtain sample folder + LrC catalog copy from user (`SPEC §11`)~~ — real edited
  wedding landed 2026-08-28 (`~/Pictures/Peter and Thuan`, 4,447 CR3/CR2, 559-keeper
  cull recovered from the catalog on this Mac); ARW/RAF still pending (user: wait)
- Confirm whether "Automatically write changes into XMP" is enabled — LrC DB version
  is 1504001 (read from the catalog); sidecars in the shoot folder are NOT Lightroom's
  (third-party ratings/labels — never treat as user intent)

The Swift helper's `probe`/`analyze` commands (below) are useful regardless of the gate's
outcome and can be built now.

---

## M1 — Cull loop on real photos

### Engine foundation
- ~~Python package scaffold (`engine/`, installable, pytest wired)~~
- ~~SQLite schema — all 15 tables, CHECK constraints, indexes (`01 §3`)~~
- ~~WAL / foreign-keys / synchronous pragmas + forward-only migration runner (`01 §5`)~~
- ~~Schema invariant tests (profile CHECK, selection-state CHECK, content-id uniqueness,
  multi-profile scores)~~

### Ingest (`02`)
- ~~Directory walker (`os.scandir`, extension allowlist, skip-list)~~
- ~~Volume UUID detection~~ — `shootr.volumes` + migration 2 (2026-08-30): library
  identity is (volume UUID, path-relative-to-mount); a remounted drive heals
  `root_path` in place, legacy rows backfill on resolve, non-macOS degrades to
  path matching (NTFS/ext4 semantics ride design 13)
- ~~Fast-path filter (`rel_path`+`mtime`+`size` → skip unchanged)~~
- ~~Content identity: `blake3(size ‖ first 64KB ‖ last 64KB)` with collision
  escalation to full hash + loud logging, wired into scan~~
- ~~Moved / modified / duplicate handling (one Photo per capture)~~
- ~~RAW+JPEG+sidecar pairing by directory-scoped basename~~
- ~~Metadata probe seam (pluggable `Prober`, NULL-metadata fallback on failure)~~
- ~~Real Swift-helper prober (`shootr.helper.swift_prober`) wired end-to-end~~
- ~~Shoot proposal: 4-hour gaps ∩ directory structure, proposals never finalized~~
- ~~Per-file error tolerance; `missing=1` never destructive~~ — volume-offline *pause*
  belongs to orchestration (`09`)
- Performance targets: first scan <90 s, no-change rescan <5 s (10k files) — needs a
  real external drive to measure

### Analysis engine — Swift helper (`03`)
- ~~Package scaffold (SwiftPM; ShootrKit library + CLI so the M4 client can share
  decode code)~~
- ~~`probe` command — ImageIO EXIF extraction (incl. SubSecTimeOriginal), JSONL out~~
- ~~`analyze` command — measurement decode (**all CIRAWFilter enhancement off**), JSONL
  flushed per photo, per-photo error objects, batch file-list input~~
- ~~`render` command — display decode path (Apple defaults on), sized JPEG out~~
- ~~`version` command — engine version + Vision revisions~~
- ~~`selftest` command — pure-math unit checks (no XCTest/swift-testing with
  CLI-tools-only; pytest drives it)~~
- ~~Tenengrad sharpness: 16×16 tile map on luminance~~
- ~~Vision request batch: face landmarks (rev 3), capture quality, feature print,
  attention saliency, horizon — one `VNImageRequestHandler` per image~~
- ~~Two-tier eye sharpness: detection at decode scale, eye-ROI re-decode at full res,
  normalized against sharpest frame tile~~
- ~~Blink baseline: landmark eye-aspect-ratio, `eye_source` provenance~~
- ~~Python driver (`shootr.helper`): temp-file lists, incremental JSONL, `swift_prober`
  wired into ingest~~
- ~~Body pose request~~ — `VNDetectHumanBodyPoseRequest` in the helper's Vision batch,
  raw joints in the JSONL `pose` field (2026-09-07); measured on real frames: 53/60
  detect bodies, 41 normalizable. Objectness saliency still not requested (attention
  saliency covers the current consumers)
- Faceprint extraction (`VNGenerateFaceprint` API needs verification on this SDK)
- ~~MediaPipe blendshape refiner (Python side, swappable)~~ — shipped as
  `engine/tools/backfill_blendshapes.py` 2026-08-29 (SCRFD+MediaPipe over stored
  face rows, bbox-IoU match, provenance-honest); validated on the wedding: blink
  false-rejects 68 → 30, survivors are honest expression-overlap cases.
  Promoted to `shootr.eye_refiner` and wired into the analyze job's finalize
  2026-08-30 — fresh shoots refine automatically; tool remains as CLI
- ~~Validate against real RAWs~~ — CR3/CR2 on the wedding, ARW/RAF on public CC0
  samples (2026-08-30): both analyzers agree on all five Sony/Fuji files after two
  RAF fixes; no format-specific decode failure; latency parity. Eye-sharpness accuracy
  on ARW/RAF still unmeasured (samples have no faces)

### Scoring (`04`)
- ~~Evidence-record output: per-metric value/weight/contrib/evidence + `weights_hash` (§1)~~
- ~~Eye focus: max-of-eyes, piecewise cliff curve, soft-frame → motion-blur routing (§2.1)~~
- ~~Eyes open: min-of-eyes, steep partial-blink band (§2.2)~~
- ~~Overall sharpness from tile stats (§2.3)~~ — **made population-relative
  2026-09-07** (`sharpness_basis` + `pipeline.sharpness_populations`): absolute
  Tenengrad is not comparable across bodies/exposures/scenes. Wrongly-flagged
  frames 62 → 4, keepers wrongly flagged 5 → 0, pick recall 33.1% → 34.3%
  (`docs/benchmarks/2026-09-07-relative-sharpness.md`)
- ~~Composition flags with individually visible penalties, never a learned score (§2.4)~~
- ~~Face capture quality as low-weight cross-check (§2.5)~~
- ~~Exposure metric with clipping penalties~~
- ~~Primary-subject selection with recorded `why` (§3)~~
- ~~Four profile weight sets; street honestly weak, `moment` excluded not zeroed (§4)~~
- ~~Null-redistribution: inapplicable/abstained → `null`, weight renormalized (§5)~~
- ~~Yaw-based abstention on eye metrics (§2.2)~~
- ~~Bracket suppression of exposure metric (§6)~~
- ~~Composition flag *detectors*: face_clipped, subject_near_edge, no_headroom,
  lead_room_inverted, horizon_tilt, thirds_distance — from analysis rows (§2.4)~~
- ~~`limb_cut_at_joint` detector~~ — `pose.limb_cut_at_joint` (2026-09-07): only
  cut-*sensitive* joints (elbow/wrist/knee/ankle) within 2% of an edge, so it does not
  fire on every environmental portrait
- ~~Landscape focus-plane logic: tile coverage + corner softness (§4.3)~~ — plane
  location vs. EXIF cross-reference deferred to M2 (needs calibration data)
- ~~Per-group profile hints: no-faces named + renormalized, group-shot composition
  boost (§4.4)~~
- ~~Bracket *detection*: ≥3 frames, <2 s, symmetric exposure-bias progression,
  near-identical embedding (§6)~~ — lives in `grouping.py` (it produces groups)

### Grouping (`05`)
- ~~Scene grouping: time gaps + loose embedding threshold (§2)~~
- ~~Shot grouping: sequential walk, multi-condition boundaries (time/embedding/
  face-count/identity/pose/bracket) (§3)~~
- ~~Bracket detection: ≥3 frames, <2 s, progression through zero with symmetric
  extremes, sealed before shot grouping (§04.6)~~
- ~~Pose grouping: agglomerative, cross-session, abstain on low confidence (§4)~~
- ~~Person identity: faceprint clustering, split-biased threshold, orthogonal axis (§5)~~
- ~~User corrections: split/merge pins re-applied after regroup, never break brackets (§7)~~
- ~~Camera burst-tag *availability check*~~ — measured 2026-08-30 (05 §8): CR3 has
  per-frame drive mode (CMT walker only — rides the analyzer cutover as a negative
  gate); CR2-via-exifread unreliable; ARW/RAF pending samples. Gate wiring deferred
  to the cutover's probe contract
- Scene-blocking for person clustering at >20k faces (§6) — brute force fine at shoot scale
- ~~Pose vector construction~~ — `shootr.pose` (2026-09-07): hip-translate, torso-scale,
  confidence filter, and **abstention** when hips/shoulders are missing or coverage is
  sparse; wired into `group_shoot` (portrait profile only, per 05 §4) and persisted as
  raw joints on `analysis.pose` (migration 3)
- Pose in the **Python analyzer** — the Swift path emits `pose`, the cross-platform one
  does not yet, so the cutover would lose pose grouping and limb-cut flags. Needs a
  skeleton mapped onto Vision's joint names (design 13 lists ViTPose-L; MediaPipe Pose
  is the cheap interim)

### Culling (`06`)
- ~~Three-state proposal (pick/alt/reject), rejects write nothing by default (§1)~~
- ~~Bracket groups excluded — all frames pick (§2 step 1)~~
- ~~Sublinear `keep_n` per profile (§2.1)~~
- ~~Diversity rule: greedy similarity penalty, λ=0.25 (§2.2)~~
- ~~Group-photo special case: fewest-people-blinking preferred (§2.2), fed by the
  `other_subject_blinking` flag from scoring through the DB pipeline~~
- ~~Quality floor → `alt` + `no_good_frame`, never auto-reject (§2.3)~~
- ~~Reason strings on every entry (§3)~~
- ~~User overrides sacred across regeneration (§4)~~
- ~~Coverage guard: person cluster never fully rejected (§6)~~
- ~~Selection versioning: new selection per param change, frozen once exported,
  overrides carried forward (§5) — `pipeline.create_selection`/`override_entry`~~
- ~~Wire culling to real `score`/`group` rows (`pipeline.py`: score_shoot,
  group_shoot, create_selection end-to-end against SQLite)~~

### Orchestration (`09`)
- ~~Job/job_item state machine, idempotent resume ("select where state ≠ done")~~
- ~~One job per (shoot, kind) uniqueness (§7)~~
- ~~Commit in ~50-item transactions; per-photo flush consumption (analyze runner)~~
- ~~Failure matrix: corrupt RAW attempts++, helper crash requeues unfinished only,
  volume-offline **pause** (never fail items), stale-`running` reset on startup,
  attempts≥3 permanent fail, job marked failed if any item failed~~
- ~~Cancellation: keep completed work, resume later (§6)~~
- ~~Measurement persistence: analysis + face + embedding rows from helper JSONL~~
- ~~N-worker helper pool~~ — threads-over-subprocesses in `run_analyze_job`
  (2026-08-30), checkpoint contract unchanged, one worker's crash/stall banks the
  others' work and requeues only the unreported. Sized on real CR3s (M5 Pro):
  1.47 s/photo → 0.47 at the default 4 workers (10k ≈ 1.3 h); 8 workers reach
  0.28 s/photo at 65% efficiency. `SHOOTR_WORKERS` overrides
- ~~Progress: rolling 60 s rate + ETA + SSE stream~~ — shipped with the API (`10`)
- ~~Helper hang timeout~~ — already shipped as the helper-layer stall watchdog
  (`SHOOTR_STALL_TIMEOUT`, default 120 s per silent batch, SIGKILL escalation);
  per-worker under the pool, verified by the stall-gate test

### API (`10`)
- ~~FastAPI app factory; `main()` binds `127.0.0.1` only~~
- ~~Libraries/shoots endpoints + shoot proposals + profile PATCH (= rescore only)~~
- ~~Photos: paginated list with cursor, detail with full evidence payload,
  sharpness-map endpoint~~
- ~~Pipeline: analyze (job), group, score, select; groups list; selection entries
  PATCH → `user_override=1`; frozen selections reject changes (409)~~
- ~~Export: `export/preview` dry-run diff; export blocks on conflicts without
  `confirm_overwrite` (409 `sidecar_conflict`); freezes selection~~
- ~~Jobs: status, cancel~~
- ~~Error envelope: stable codes, `retryable` flag, machine-readable~~
- ~~Thumbnails: `render` + content-addressed cache keyed `content_id_size`, ETag +
  `Cache-Control: immutable`~~
- ~~Eye-crop endpoint (M1: full-res face-region render; dedicated helper crop command
  can tighten later)~~
- ~~Grouping corrections: split/merge endpoints; brackets immutable (409)~~
- ~~SSE progress stream (`/api/jobs/stream`, `once=` snapshot mode for polling/tests)~~
- ~~Background job runner (`runner.JobRunner` thread) wired to the analyze endpoint;
  stale-`running` reset on startup in `main()`~~
- ~~Rolling-rate/ETA in job progress (60 s window; job status endpoint)~~
- ~~Group-correction *move* endpoint (brackets immutable; emptied source deleted)~~

### Lightroom selects writeback (`07 §3`)
- ~~XMP sidecar writer: rating/label mapping, read→diff→backup→confirm→atomic-write~~
- ~~Preserve unknown fields (edit-in-place, never regenerate; crs:/keywords/plugin
  data survive byte-for-byte — tested)~~
- ~~DNG detection → warn and skip (no embedded-XMP writes)~~
- ~~Rejects write nothing by default~~
- ~~CSV file-list export~~
- ~~Hardlink "Selects" folder (`xmp.export_hardlinks`; API/UI hookup when wanted)~~
- LrC-running + live-catalog refusal check (belongs with catalog *import*, M2)

### Web client (`11`)
- ~~Vite + TS + TanStack Query + Tailwind scaffold; `/api` proxy to the engine~~
- ~~Typed API layer mirroring doc 10 payloads; error envelope unwrapped to
  `EngineError` with stable codes~~
- ~~Library setup + shoot list with pipeline actions (analyze/group/score/select)~~
- ~~Group Review screen: group nav (brackets ⚑ HDR, no cull controls), frame strip
  with pick/alt/reject states, selected-frame viewer~~
- ~~Evidence panel: component bars with value/weight/evidence; `null` renders "—"
  with abstention reason, never a zero bar~~
- ~~Overlays: full-res eye crops with per-eye numbers; 16×16 sharpness heatmap
  (Vision bottom-left origin flipped for CSS)~~
- ~~Keyboard bindings (LrC-compatible P/X/J/K, G groups, E evidence, S map)~~
- ~~Optimistic override PATCH with rollback (TanStack onMutate/onError)~~
- ~~SSE job header with always-visible failed count~~
- ~~Export dialog: engine diff, conflict count stated before write, no default-yes,
  LrC "Read Metadata" caveat shown after~~
- ~~Compare view: 2–4 frames, one shared transform (synced pan/zoom), primary-face
  snap at 100%, keyboard 1–4/Z/Esc, per-pane eye-sharpness readout~~
- ~~Shoot-proposal confirmation UI: editable name + profile picker per proposal~~
- ~~Composition overlay (O): thirds grid + face boxes — both clients~~
- ~~Thumbnail prefetch for J/K scrubbing — both clients (web ±5 thumbs, native
  ±2 loupe decodes)~~
- TanStack Virtual for >1k-group lists (plain scroll fine at current scale)

---

## M2 — Calibration

**First agreement measurement done 2026-08-29** on the real wedding (4,448 frames,
1.91 h, 0 failures — first CR2 run, clean): moment coverage 98.6% (only 8/559
keepers in pick-less groups) but pick recall 32% — within-group ordering is the
gap. 26% of false-rejects are blink false-positives from the live path still
running EAR (`eye_source='ear_landmarks'`; blendshapes exist only in the Python
analyzer) → fixed same day by the blendshape backfill (68 → 30 blink false-rejects;
headline barely moved, confirming within-group ordering as the fitting target).
Full numbers + addendum: `docs/benchmarks/2026-08-29-first-cull-agreement.md`.

- ~~Catalog copy reader~~ — `shootr.lr_catalog` (2026-08-30): LrC-running refusal,
  copy with `-wal`/`-shm`, `immutable=1` on quiesced copies / recover-then-`query_only`
  on live-WAL copies, version probe, validate-before-query → `CatalogInvalid` degrades
  to sidecar-only. CLI: `engine/tools/import_lr_history.py`
- ~~Extract picks/ratings/labels/develop into `lr_history`~~ — filename+time(+size
  when the catalog has it) matcher with reported unmatched/ambiguous counts; develop
  parsed from the Lua `text` (crs XMP fallback — 07 §2 preference inverted on real
  data) into JSON. Real run: 560/560 matched, develop on all 560 (111 global params) —
  M3's raw material is in the DB
- ~~Fit metric→outcome weights per profile, regularized toward hand-tuned priors
  (`04 §7`)~~ — fit 2026-08-29 (`engine/tools/fit_weights.py`): within-group ordering
  is chance (priors 53.0% holdout pairwise, best fit 53.2%) → **priors retained**;
  within-group agreement needs an expression/peak-moment *measurement*, not weights
  (04 §7 records the numbers). Refit per new shoot as history grows
- ~~Refit piecewise curve breakpoints (currently doc guesses)~~ — eyes_open refit on
  the merged 285-face label set: blendshapes 0.4-boundary moved 0.62 → 0.50, EAR now
  *abstains* (no usable separation; was 26% of keeper false-rejects). Other curves
  still doc guesses
- ~~Headline metrics: agreement rate per profile; false-reject rate on user-promoted
  frames tracked separately (asymmetric cost, `06 §7`)~~ — first event-profile numbers
  on the wedding: moment coverage 98.9%, pick recall 33%, false-reject 46.9%
  (near-duplicate substitution dominates), blink-reason false-rejects 68 → 20
- Online adjustment from `user_override` entries

## M3 — Style learning — core built + evaluated 2026-08-30

First pass on the real wedding (`docs/benchmarks/2026-08-30-style-knn-eval.md`):
**k-NN beats the family median 11/12 params on leave-one-shot-group-out**
(Exposure MAE 0.282 vs 0.347 EV, coverage 99.1%) — the model ships, not the preset.
8 look families discovered inside one wedding (they split by light, not genre).

- ~~Delta targets~~ — modern crs sliders (default 0 → delta = value); **Temp/Tint
  excluded**: `analysis.frame.as_shot_wb` is a recorded analyzer-contract gap (§2.2)
- ~~Look-family clustering~~ — `style.cluster_families` (agglomerative, correlation
  distance, no scipy) + trait labels; family thumbnails = UI work, pending
- ~~k-NN predictor~~ — family-filtered softmax blend, confidence first-class (§4)
- ~~Guardrails~~ — confidence gate (abstain), clamp to family range, PV written with
  every prediction; highlight-clip sanity check + per-parameter opt-out (UI) pending;
  never-overwrite is `DevelopConflict` with deliberately no override flag
- ~~Baseline comparison~~ (§7) — run honest (group-excluded); median wins only
  ColorGradeMidtoneHue → first opt-out candidate
- ~~Evaluation~~ — `engine/tools/eval_style.py`; re-run per new shoot imported
- ~~XMP `crs:` writer~~ — `xmp.write_develop` via the `07 §1` Rule-2 protocol;
  `ProcessVersion` stamped on every write
- ~~API endpoints~~ — `/api/style/families` (traits + sample thumbnails + median),
  `/predict` (read-only, neighbors named, auto-suggested family), `/export-develop`
  (abstentions write nothing; user-edited sidecars = reported conflicts, no
  override). Client UI (family picker, prediction preview, per-param opt-outs,
  highlight-clip check) — not started, both clients
- JPEG+RAW pair validation (trends/direction, not pixel equality) — needs exported pairs
- Gradient-boosted trees only if k-NN measurably underperforms — not currently indicated

## M4 — Native client (SwiftUI) — pulled forward; core built 2026-08

- ~~Requires full Xcode~~ — disproved by probe: SwiftUI builds with CLI tools via
  SwiftPM + `-parse-as-library`; `make-app.sh` bundles a signed `.app`
- ~~APIClient: Codable mirrors of `10` payloads, zero domain logic~~
- ~~ImagePipeline: local CIRAWFilter loupe (display path only, via shared ShootrKit),
  API-thumbnail fallback when volume unreachable, NSCache with byte-cost eviction~~
- ~~Scope subset: shoot list, group review (sidebar/filmstrip/loupe), evidence panel
  with null→"—", keyboard culling, bracket immutability~~
- ~~Keybindings matching web client (J/K/G/P/A/X/E + arrows, Space toggle-pick,
  Esc back, Home/End, Z 100%-with-face-snap + drag pan)~~
- ~~Library management (scope change per user 2026-08: native replaces web as the
  control panel) — NSOpenPanel folder picker, library add/remove with confirm,
  proposal cards with genre picker, create-&-analyze with live job status~~
- ~~Compare view: 2–4 panes, one shared pan/zoom transform, face-snapped 100%,
  `C` to open~~
- ~~Export dialog: engine diff, explicit conflict confirm, DNG notice, LrC
  read-metadata caveat~~
- ~~Sharpness heatmap overlay (`S`), aligned to the fitted image~~
- ~~Shoot settings sheet: rename + genre switch (instant rescore)~~
- ~~Trackpad pinch to zoom on the loupe~~
- ~~Loupe prefetch (±2)~~
- GPU throttling while an analyze job runs — pool exists now (default 4 workers,
  deliberately not 8: headroom for interactive use is the current mitigation).
  Build real throttling only if browsing-during-analysis measurably stutters;
  `SHOOTR_WORKERS=2` is the user-side dial in the meantime
- Quick Look / drag-out integration — post-M1 nicety

## M5 — Optional LrC Lua plugin

- Collections + flags/ratings set from inside LrC (best UX, no catalog risk)
- Only if M1's manual "Read Metadata from File" flow proves too clunky

## Post-M2 — Portability (Windows, Linux) — direction set 2026-08-20, design 13

Decision: Windows and Linux are on the roadmap → the cross-platform measurement
stack becomes canonical on ALL platforms (one measurement semantics everywhere;
per-platform analyzer forks are forbidden — same class of bug as client-side
scoring). Vision/Core Image retreat to the macOS display path. Full rationale,
component table, and adoption criteria: `docs/design/13-portability.md`.

Model tier (user decision, same date): accuracy-first — SOTA models where
sensible, large weights and slower culling accepted. Hardware floor = **M4
MacBook 24 GB** (the i9/RTX 2070S machine is transitional and gates nothing).
Candidates: DINOv2 ViT-L embedding, AdaFace IR-101 identity, SCRFD-10G faces,
ViTPose-L, BiRefNet subject segmentation (retires the saliency "honest loss").
Sharpness stays Tenengrad — evidence rule outranks benchmarks (13 §1.5, §2.1).

Arriving early on their own merits (accuracy, not portability):
- ~~Blink via MediaPipe blendshapes, validated against hand-labelled frames~~ —
  landed 2026-08-29/30: `shootr.eye_refiner` in the analyze job, curves refit on
  285 labelled faces, EAR abstains
- ArcFace/SCRFD (InsightFace) when faceprint extraction lands — fixes 05 §5's
  stated Vision weaknesses on Mac too

Analyzer built 2026-08-20 (`analyzer/`, console script `shootr-analyze-py`;
swap in via `SHOOTR_HELPER`). Adoption remains a post-A/B user decision:
- ~~Canonical analyzer: second implementation of the 03 §4 JSONL contract
  (Python + onnxruntime + rawpy/libraw, no Swift)~~ *(decode/sharpness ports
  numerically Swift-parity-tested; SCRFD-10G faces, MediaPipe blendshapes
  blink, ArcFace faceprints, DINOv2-L embedding, BiRefNet saliency, classical
  horizon; model registry with pinned sha256 download-on-first-run; probe
  includes a CR3 ISO-BMFF CMT walker — exifread can't read CR3 containers)~~
- ~~A/B harness~~ (`engine/tools/ab_analyzers.py`): sharpness Spearman, face/
  eye-open side-by-side (the blink labelling aid), embedding neighbor Jaccard,
  grouping stability (05 thresholds are embedding-specific — re-measure,
  don't reuse), timing → 10k projection vs the overnight-on-M4 bar
- ~~First gate run~~ (60 real CR3s, `docs/benchmarks/2026-08-20-analyzer-ab-60.md`):
  sharpness ρ 0.812 · faces 77 vs 56 (recall edge, unverified) · blendshapes
  discriminate where EAR saturates · grouping stable untuned (15 vs 14 groups)
  · python 14.4 h/10k = over the overnight bar
- ~~Throughput optimization~~ (2026-08-21): BiRefNet 512²-fp16 official variant
  (saliency 5.0 s → 1.1 s; was 70% of the budget) + largest-CC bbox (also fixes
  stray-activation boxes) + cached model_rgb → **median 2.12 s, 5.9 h/10k,
  WITHIN the overnight bar**, identical accuracy numbers
  (`docs/benchmarks/2026-08-21-analyzer-ab-60-optimized.md`)
- ~~Face-recall spot-check~~ (user-judged all 21 disputed): 8 real recall wins,
  13 phantoms ALL refused by the MediaPipe stage → phantom-safe on dominant
  metrics (`docs/benchmarks/2026-08-21-face-recall/`)
- ~~Grouping thresholds re-measured~~ on the full 1,232-frame shoot: DINOv2
  needs its own set (0.35/0.45/0.18 → 225 groups, 95.5% boundary agreement,
  no over-merge); constants switch in the cutover commit
  (`docs/benchmarks/2026-08-21-dinov2-grouping-thresholds.md`)
- Remaining adoption items: ~~ARW/RAF decode+probe~~ validated on public CC0 samples
  2026-08-30 (two RAF bugs found and fixed); still unmeasured on those formats:
  **eye-sharpness/face accuracy** (the samples contain no faces). Then the cutover
  decision itself (engine_version bump + full re-analysis + threshold constants +
  blendshapes curve becomes the live one) — and it should not ship before the
  absolute-sharpness-threshold issue above is resolved, since the cutover makes
  the cross-vendor stack canonical everywhere
- Component-wise adoption after A/B + labelled frames; single `engine_version`
  cutover (`py-0.1.0+<registry-hash>`); eat the re-analysis while small
- AdaFace IR-101 still unpinned (no official ONNX artifact) — ArcFace R50
  floor active; CoreML EP measured pathological on DINOv2-L (~20 min compile,
  then fails) → CPU default on macOS, `SHOOTR_ORT_PROVIDERS` to override
- ~~Web client absorbs library management~~ (2026-08-30) — add-by-path with scan
  summary, remove with explicit no-default-yes dialog, proposal cards with genre
  picker + create-&-analyze; on non-Mac platforms web is the only surface
- Then the ports are packaging + platform ingest (volume identity/offline
  semantics on NTFS/ext4, 02 §)

---

## Cross-cutting invariants (enforced continuously, tests named for doc rules)

- ~~Culling never deletes; `reject` = "not chosen" (`01` inv 1–2)~~ *(engine-level;
  re-verify at API/export layers when built)*
- ~~Inapplicable metrics `null`, never 0 (`04 §5`)~~
- ~~Bracket sets never culled internally (`04 §6`)~~
- ~~`user_override=1` survives regeneration (`01` inv 5)~~
- Never write to a live `.lrcat` (`07 §1`) — M1 export / M2 import
- ~~Never silently overwrite user XMP (`07 §1`)~~ *(read→diff→backup→confirm→atomic;
  unknown-field preservation has a byte-for-byte test)*
- ~~Measurement decodes disable all enhancement (`03 §2`)~~ *(implemented; property
  behavior on real CR3/ARW/RAF still needs the benchmark to confirm)*
- Logic lives in the engine; clients render (`10 §1`) — API enforces it by carrying
  evidence/reasons in every payload; re-verify when clients are built
- All work resumable via per-photo checkpoints (`09`) — orchestration
