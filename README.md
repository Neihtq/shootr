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

| Key | Action |
|---|---|
| `← →` / `J K` | previous / next frame |
| `↑ ↓` / `G` / `⇧G` | previous / next group |
| `P` / `A` / `X` | pick / alt / reject |
| `Space` | toggle pick ↔ reject |
| `Z` | 100% zoom (snaps to primary face), drag to pan |
| `C` | compare against the group's runner-ups (synced zoom) |
| `S` | sharpness heatmap — where did focus land? |
| `O` | composition overlay — thirds grid + face boxes |
| `E` | evidence panel |
| `Esc` | back to shoots |

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
