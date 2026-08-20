# Shootr

Offline photo culling and edit-assistance for macOS. Scores photos on
technical quality (sharpness, eye focus, blinks), groups bursts, proposes a
cull selection, and writes picks to XMP sidecars for Lightroom Classic — all
on-device, no cloud.

**Never deletes, never modifies your photos.** Culling is metadata only;
RAW files are read-only throughout; sidecar writes are backed up, diffed,
and confirmed.

## Requirements

- **Apple Silicon Mac, recent macOS** — decoding and face analysis use
  Apple's Core Image (`CIRAWFilter`) and Vision frameworks (built against
  the macOS 26 SDK; needs Vision face-landmarks rev 3)
- **Xcode Command Line Tools** (`xcode-select --install`) — full Xcode not
  needed
- **Python 3.14** (`brew install python@3.14`)
- **Node 20+** — only for the web UI (optional; the native app covers
  everything)

## Quick start — self-contained app

```bash
git clone git@github.com:Neihtq/shootr.git && cd shootr
native/make-app.sh --bundled     # ~100 MB .app; downloads a relocatable
                                 # Python on first run (cached in .cache/)
open native/ShootrApp.app
```

Double-clicking the app starts everything: it launches its own embedded
engine (or reuses one already running on port 8721) and stops it on quit.
The web UI is served by the same engine at **http://127.0.0.1:8721/ui** —
the URL is shown in the app header. No Python, Node, or terminal needed on
the target machine; copy the `.app` to any Apple Silicon Mac and it runs.

Building `--bundled` needs Node once (for the web UI build); plain
`native/make-app.sh` skips all of that and expects the engine run from
source, as below.

## Setup (development, from source)

```bash
git clone git@github.com:Neihtq/shootr.git && cd shootr

# Python engine
python3.14 -m venv .venv
.venv/bin/pip install -e engine

# Swift analysis helper (the RAW decoder — required)
(cd helper && swift build)

# Native app bundle
native/make-app.sh
```

## Run

```bash
# Terminal 1 — the engine (leave running)
cd engine && ../.venv/bin/python -m shootr.api

# The app
open native/ShootrApp.app
```

In the app: **Add library…** → pick a photo folder → confirm the proposed
shoot with a genre (portrait / event / landscape / street — this sets how
photos are judged) → **Create & analyze** → review.

### Review keyboard

Press `?` in either client for this list in-app.

| Key | Action |
|---|---|
| `← →` / `J K` | previous / next frame |
| `↑ ↓` / `G` / `⇧G` | previous / next group |
| `Home` / `End` | first / last frame in group (native) |
| `P` / `A` / `X` | pick / alt / reject |
| `Space` | toggle pick ↔ reject |
| `Z` | 100% zoom (snaps to primary face), drag to pan |
| `C` | compare against the group's runner-ups (synced zoom) |
| `S` | sharpness heatmap — where did focus land? |
| `O` | composition overlay — thirds grid + face boxes |
| `E` | evidence panel |
| `?` | shortcut list + how the verdicts are chosen |
| `Esc` | back to shoots |

### What the overlays show

- **`S` — sharpness heatmap.** The frame is measured on a grid of tiles;
  each tile's red intensity is its sharpness **normalized to the sharpest
  tile in that same photo**. So it answers *where did focus land*, not
  *what's wrong here* — a soft photo still shows bright tiles wherever it's
  least soft. If the reddest region isn't on your subject's eyes, focus
  missed.
- **`O` — composition overlay.** Rule-of-thirds grid plus **amber** face
  boxes, one per detected face. Use it to check whether a face-based flag is
  fair before trusting it.

### How pick / alt / reject are chosen

All three are **proposed automatically**, per group, from each frame's
quality score under the shoot's genre. The genre sets the weights — for
`event`, eye focus (0.35) and eyes-open (0.25) dominate; for `landscape`
there are no face metrics at all and sharpness (0.45) and composition (0.35)
carry it. Per group, in order:

1. **Exposure bracket** → every frame `pick`. Brackets are never culled.
2. **Single-frame group** → `pick` if it clears the quality floor, else `alt`.
3. Otherwise rank by score with a **diversity penalty** (a frame that looks
   too much like one already picked loses ground), then prefer the variant
   with the fewest blinking subjects among near-ties.
4. Keep the top few → `pick`; the next one → `alt`; the rest → `reject`. How
   many depends on genre and group size (event keeps ~20%, capped at 3;
   street ~60%, capped at 6).
5. If **no** frame clears the floor, the whole group becomes `alt` — the
   engine declines to recommend rather than picking the least-bad frame.

| State | Means | On export |
|---|---|---|
| `pick` | recommended keeper | 3★ |
| `alt` | credible runner-up — the engine's second choice is often the human's first. Also the "won't call it" state from steps 2 and 5. | 2★ |
| `reject` | **not chosen** — never deleted, never moved | nothing written |

Every entry carries its reasoning, shown in the bar under the photo
(*"near-duplicate of pick #1 (similarity 0.91)"*, *"best in group (0.81 vs
0.78 next)"*). Press `E` for the per-metric scores behind it. Changing a
verdict sets `user_override`, which wins over the engine and survives every
regroup and re-cull. Full rules: `docs/design/06-culling.md`.

**Export…** writes picks as ratings into `.xmp` sidecars (3★ pick, 2★ alt;
rejects write nothing). In Lightroom: select the photos, then
*Metadata → Read Metadata from Files*.

### Web UI (optional)

```bash
cd web && npm install && npm run dev   # http://localhost:5173
```

Same features over the same engine; the native app is the daily driver.

## Development

```bash
.venv/bin/pytest engine/tests          # engine test suite
helper/.build/debug/shootr-analyze selftest   # Swift pure-math checks
(cd web && npm run build)              # web type-check + build
```

### Cross-platform analyzer (experimental, design 13)

A second analyzer implements the same contract as the Swift helper on
Python + ONNX + libraw — the measurement stack that will run on Windows and
Linux. Model weights (~2.5 GB) download on first use with checksum
verification.

```bash
.venv/bin/pip install -e analyzer
.venv/bin/shootr-analyze-py verify-models      # registry / cache status
.venv/bin/shootr-analyze-py selftest           # must match the Swift numerics

# Swap the whole measurement stack (thumbnails stay on CIRAWFilter):
SHOOTR_HELPER=.venv/bin/shootr-analyze-py \
SHOOTR_RENDER_HELPER=helper/.build/debug/shootr-analyze \
SHOOTR_STALL_TIMEOUT=600 \
  ../.venv/bin/python -m shootr.api

# Compare both analyzers on real photos (the design 13 §4 adoption gate):
.venv/bin/python engine/tools/ab_analyzers.py <photo-dir> --limit 100

# Validate blink detection against your own eyes (~1 h, one keystroke per
# face). Blink drives a dominant scoring metric; it may not influence
# culling until this has been run:
.venv/bin/python engine/tools/label_blinks.py prepare <photo-dir> --limit 40
.venv/bin/python engine/tools/label_blinks.py serve    # O/C/U per face
.venv/bin/python engine/tools/label_blinks.py report   # accuracy + threshold
```

The Swift helper remains the default; switching is a measured decision, not
a default (see `docs/design/13-portability.md`).

Design docs live in `docs/design/` (start with the README there);
implementation status is tracked in `PLAN.md`.

## Notes

- App state (scan data, scores, selections) lives per-machine in
  `~/Library/Application Support/Shootr/`. It never syncs between machines;
  exported XMP sidecars travel with the photos themselves.
- Port `8721` must be free (`lsof -ti :8721 | xargs kill` if a previous
  engine is stuck).
- DNG files are analyzed and culled normally but skipped at export —
  their metadata lives inside the file, and this app does not modify RAWs.
