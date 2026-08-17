# 11 — Web Client

**Milestone:** M1 (primary frontend) · **Depends on:** [10](10-api.md)

React + Vite review UI. Built **first** because the scoring logic is still moving and this is
where you inspect *why* a photo scored what it did.

---

## 1. The job this UI has to do

Not "browse photos" — LrC already does that better. The job is: **let the user accept or
overrule the engine fast, and understand why it decided what it did.**

That yields one dominant screen (group review) and one dominant interaction (compare frames
within a group, at enough magnification to judge eye focus).

---

## 2. Screens

```
Libraries ──► Shoots ──► [ Group Review ]  ◄── the screen that matters
                              │
                              ├─ Evidence panel   (why this score)
                              ├─ Compare view     (2–4 frames, synced zoom)
                              └─ Export dialog    (diff + confirm, §07)
```

Everything else is scaffolding: library setup, shoot confirmation with profile picker
(§02.4), job progress, and settings for weights/thresholds.

### Group Review layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Shoot: Nguyen Wedding    profile: event    4,210/10,000 analyzed│
├──────────┬──────────────────────────────────────────┬───────────┤
│ Groups   │  Group 88 · 9 frames · shot 15:22:08     │ Evidence  │
│          │                                          │           │
│ ▸ 86  (4)│  ┌────┐ ┌────┐ ┌────┐ ┌────┐            │ eye_focus │
│ ▸ 87  (6)│  │PICK│ │ALT │ │ rej│ │ rej│  ...       │ ████ 0.82 │
│ ▾ 88  (9)│  └────┘ └────┘ └────┘ └────┘            │  left eye │
│ ▸ 89  (3)│                                          │ eyes_open │
│ ⚑ 90 HDR │  [selected frame, large]                 │ ████ 0.94 │
│          │   ◦ eye overlay  ◦ sharpness map         │ sharpness │
│          │                                          │ ██   0.55 │
│          │  "sharpest eyes in group (0.82 vs 0.61)" │ flags:    │
│          │  [✓ keep] [→ promote alt] [compare]      │ near_edge │
└──────────┴──────────────────────────────────────────┴───────────┘
```

Groups are the primary navigation, not a flat photo grid — the cull unit is the group (§05),
so a flat grid would force the user to reconstruct grouping mentally.

Bracket groups (⚑ HDR) are visually distinct and have no cull controls, making the §04.6
guard visible rather than implicit.

---

## 3. The evidence panel is the point

Per §04.1 and README rule 5, every score decomposes. The panel renders `score.components`
directly from the API — bars with per-metric value, weight, contribution, and the evidence
object.

Three overlays make abstract numbers verifiable on the actual pixels:

| Overlay | Shows | Answers |
|---|---|---|
| **Eye crop** | full-res crop of each eye, side by side | "is the eye actually sharp?" |
| **Sharpness map** | 16×16 tile heatmap over the frame | "where did focus land?" |
| **Composition** | face/pose boxes, thirds grid, flagged edges | "is this flag fair?" |

The sharpness map is what makes "focus missed — it hit the shoulder" (§04.2's key failure
mode) legible in one glance instead of a claim the user has to take on faith.

`null` components render as "—", never a zero bar (§10.3). Displaying "not measured" as
"scored zero" would make every landscape look broken.

---

## 4. Compare view

The interaction that actually decides culls: 2–4 frames from a group, **synced pan and
zoom**, snapped to the primary face by default at 100%.

Synced zoom is the requirement — the whole judgement is "which of these two nearly identical
frames has sharper eyes", and that's impossible unless both are at the same magnification on
the same feature. Keyboard: `1-4` select, `Z` toggle 100%/fit, `←/→` cycle frames.

Needs the 2048 px thumbnail plus on-demand eye crops (§10.4); full-res RAW in a browser is
too slow, which is the honest argument for the native client (§12) rather than aesthetics.

---

## 5. Keyboard-first

Culling is repetitive; mouse-driven review is too slow to be worth using.

```
J / K or ← →   prev / next frame        P   pick
Space          toggle pick               X   reject
Z              100% / fit                A   promote alt
1-5            set rating                G   next group
C              compare mode              ⇧G  prev group
E              evidence panel            /   filter
```

Modeled on LrC's own bindings (`P`/`X`, `J`/`K`) so it doesn't fight existing muscle memory.

Every user action posts to `PATCH /api/selections/{id}/entries/{pid}`, setting
`user_override=1` (§06.4). Optimistic UI with rollback on error — at this interaction speed,
waiting for a round trip per keystroke is unusable.

---

## 6. Progressive analysis

Analysis takes 20–30 min for 10k photos (§09.1). The UI must be useful **during** it, not
after — otherwise the user stares at a progress bar.

Since ingest populates metadata in a fast separate pass (§02.4), the grid fills within
seconds. Then:

- Unanalyzed photos show thumbnail + metadata, greyed score area.
- Groups appear as grouping completes per scene.
- SSE progress (§09.5) drives a header bar with rate, ETA, and **failed count**.
- Failed photos are listed and inspectable — not silently absent.

---

## 7. Export dialog

Wraps the §07 safety protocol. Calls `export/preview` first and shows the returned diff:

```
Writing to 1,204 files:
  ✓ 1,180 new sidecars
  ⚠ 24 existing sidecars WITH develop settings  ← requires explicit confirm
  ⓘ 12 DNG files will be skipped (§07.3.1)
  Backups → ~/Library/Application Support/Shootr/backups/

  [ Cancel ]  [ Skip conflicts ]  [ Overwrite 24 (backed up) ]
```

No default-yes on the destructive option, and the conflict count is stated before any write.
The client only renders the engine's diff — it never decides what counts as a conflict
(§10.2).

---

## 8. Stack

| Concern | Choice | Rationale |
|---|---|---|
| Build | Vite + TypeScript | fast HMR; types keep the API contract honest |
| State | TanStack Query | server-state caching, invalidation, SSE-friendly |
| Virtualization | TanStack Virtual | 10k-row grids need it |
| Styling | Tailwind | speed over ceremony for a single-user tool |
| Charts | none in M1 | evidence bars are plain divs |

No global state manager. Server state is the source of truth (§10.1); Redux-style stores
here mostly create opportunities to cache stale scores and drift from the engine.

Dark UI by default, neutral greys — a colored chrome around photos biases color judgement,
which matters once style prediction (§08) is being reviewed.

---

## 9. Open questions

- **Thumbnail prefetch strategy** for fast `J`/`K` scrubbing — likely prefetch ±5 frames at
  the current size. Needs measurement against real decode latency.
- **1,000+ group navigation**: a flat group list may need scene-level collapsing.
- Should the compare view support **before/after** for style predictions (M3)? Probably, but
  it needs a rendering path for `crs:` params outside LrC — which §08.5 flags as
  approximate at best.
