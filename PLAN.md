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
  - Which blink detector ships (EAR vs. MediaPipe vs. ONNX, against hand-labelled frames)
- Obtain sample folder + LrC catalog copy from user (`SPEC §11`)
- Confirm LrC version and whether "Automatically write changes into XMP" is enabled

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
- ~~Directory walker (`os.scandir`, extension allowlist, skip-list)~~ — volume UUID
  detection (`diskutil`) still to do
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
- Body pose + objectness saliency requests (grouping consumes pose vectors; deferred
  with pose-vector construction)
- Faceprint extraction (`VNGenerateFaceprint` API needs verification on this SDK)
- MediaPipe blendshape refiner (Python side, swappable)
- Worker-pool concurrency (N processes, backpressure) — belongs to orchestration (`09`)
- ⚠ Validate against real RAWs: enhancement-off properties on CR3/ARW/RAF, eye-sharpness
  accuracy, per-photo latency — the benchmark gate

### Scoring (`04`)
- ~~Evidence-record output: per-metric value/weight/contrib/evidence + `weights_hash` (§1)~~
- ~~Eye focus: max-of-eyes, piecewise cliff curve, soft-frame → motion-blur routing (§2.1)~~
- ~~Eyes open: min-of-eyes, steep partial-blink band (§2.2)~~
- ~~Overall sharpness from tile stats (§2.3)~~
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
- `limb_cut_at_joint` detector — needs body-pose joints (deferred with pose requests)
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
- Camera burst-tag check (CR3/ARW/RAF drive-mode metadata) before heuristics — needs
  real files to verify tag availability (§8)
- Scene-blocking for person clustering at >20k faces (§6) — brute force fine at shoot scale
- Pose vector *construction* (hip-translate, torso-scale, joint-confidence filter) —
  belongs to the Swift helper / analysis side; grouping consumes the normalized vector

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
- asyncio coordinator, N helper subprocesses, 2N-batch backpressure — M1 runs
  batches synchronously; parallel pool is a drop-in upgrade (checkpoint contract
  unchanged), size it from the benchmark
- Progress: rolling 60 s rate + ETA + SSE stream — lands with the API (`10`);
  counts/failed already queryable via `jobs.progress`
- Helper hang timeout (30 s/photo) — needs the subprocess pool

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

- Catalog copy reader: copy `.lrcat`+`-wal`+`-shm`, open `mode=ro`, version probe,
  validate-before-query, degrade to sidecar-only (`07 §2`)
- Extract picks/ratings/labels/develop into `lr_history`; match by
  filename+time+size; report coverage and unmatched counts
- Fit metric→outcome weights per profile, regularized toward hand-tuned priors (`04 §7`)
- Refit piecewise curve breakpoints (currently doc guesses)
- Headline metrics: agreement rate per profile; false-reject rate on user-promoted
  frames tracked separately (asymmetric cost, `06 §7`)
- Online adjustment from `user_override` entries

## M3 — Style learning

- Delta targets: value − as-shot baseline; Temp as log-ratio, Tint linear (`08 §2`)
- Look-family clustering over edit-history deltas, labelled with traits + thumbnails (§3)
- k-NN predictor: family-filtered, softmax-weighted blend, confidence as first-class
  output (§4)
- Guardrails: confidence gate (abstain), clamp to family's observed range, highlight-clip
  sanity check, per-parameter opt-out, PV match (§6)
- Baseline comparison: must beat "family median as preset" or ship the preset (§7)
- Evaluation: per-parameter MAE in real units, direction agreement, coverage
- XMP `crs:` writer via the `07 §1` Rule-2 protocol; `ProcessVersion` discipline
- JPEG+RAW pair validation (trends/direction, not pixel equality)
- Gradient-boosted trees only if k-NN measurably underperforms

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
- GPU throttling while an analyze job runs — deferred until the worker pool
  exists (single-worker M1 can't contend with itself)
- Quick Look / drag-out integration — post-M1 nicety

## M5 — Optional LrC Lua plugin

- Collections + flags/ratings set from inside LrC (best UX, no catalog risk)
- Only if M1's manual "Read Metadata from File" flow proves too clunky

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
