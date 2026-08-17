# 12 — Native Client (SwiftUI)

**Milestone:** M4 (after the API stabilizes) · **Depends on:** [10](10-api.md), [03](03-analysis-engine.md)

A macOS app over the same API. Built **second**, deliberately.

---

## 1. Why it's worth building — and why not first

The honest argument is **not** aesthetics. It's that the core culling interaction is
image-throughput-bound, and a browser can't win it:

| Capability | Web (§11) | Native |
|---|---|---|
| Full-res RAW at 100% | 2048 px JPEG via HTTP | direct `CIRAWFilter` → Metal, no re-encode |
| Zoom/pan at 100% | re-fetch larger renditions | GPU-resident, instant |
| Scrub 10 frames/sec | HTTP + JPEG decode per frame | decode pipeline in-process |
| Memory over 10k thumbs | browser heap pressure | `NSCache` + real eviction |
| Color management | sRGB, browser-dependent | Display P3, ColorSync-correct |

Color management is the underrated one: judging white balance and skin tone (§08) in a
browser's color pipeline is unreliable, and this app asks the user to evaluate exactly that.

**Why second:** it shares the API, and building both while the contract is still moving means
implementing every change twice. The web client is where scoring gets iterated; once
`/api/photos/{id}` stops changing shape, the native client is largely mechanical.

**Requires full Xcode** — currently only CLI tools are installed (SPEC §1). Not a blocker
until M4.

---

## 2. Architecture

```
SwiftUI views
   │
   ├── APIClient (async/await, Codable mirrors of §10 payloads)
   │        └── same endpoints as web — zero logic difference
   │
   └── ImagePipeline  ← the reason this client exists
            └── reuses shootr-analyze `render`, or links CIRAWFilter directly
```

**Two image paths, chosen per view:**
- **Grid/filmstrip** → HTTP thumbnails from the API (cached, shared with web; no reason to
  duplicate).
- **Loupe/compare at 100%** → local `CIRAWFilter` decode of the original file, bypassing the
  API entirely.

The local path is only available when the library volume is mounted and reachable by the app.
When it isn't, fall back to API thumbnails — so the app degrades to web-equivalent rather
than breaking.

**Display decode path only** (§03.2): Apple defaults on. The native client must never
compute measurements; those come from the API (§10.1). A second, subtly different sharpness
implementation here would produce scores that disagree with the web client — exactly the
divergence the API seam exists to prevent.

---

## 3. Scope

**Ships with:** shoot list, group review, evidence panel, compare view with synced zoom,
keyboard culling, export dialog.

**Deliberately omitted:** library setup, catalog import, weight tuning, style-family
management. These are configuration done once, they're the fastest-moving parts of the API,
and duplicating them doubles maintenance for near-zero benefit. The native app is a
**culling instrument**; the web app remains the control panel.

Stating that boundary matters — "feature parity between two frontends" is how a two-client
project becomes unmaintainable.

---

## 4. Where native genuinely wins

- **Compare view**: 2–4 RAWs at 100% with synced zoom, GPU-resident. The decisive
  eye-sharpness judgement (§11.4) happens here.
- **Filmstrip scrubbing**: hold `J`, see frames at full quality without network latency.
- **Trackpad gestures**: pinch zoom, two-finger pan — matches how photographers already
  work in LrC.
- **System integration**: Quick Look, Services, drag-out to Finder/LrC, full-screen.

Design constraint: **identical keybindings to the web client** (§11.5). Two UIs with
different shortcuts for the same task is worse than one UI.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| Drift from web client | API is the only source of domain values; no scoring code in Swift |
| Duplicated UI logic diverging | native scope is intentionally a subset (§3) |
| Memory blowup on 10k thumbs | `NSCache` with byte-size limits; `autoreleasepool` per decode (§03.6) |
| GPU contention with a running analyze job | throttle local decodes while a job is active — the engine's throughput matters more than UI smoothness |
| Xcode/toolchain divergence from the helper | share one Swift package for decode; don't fork the code |

The GPU-contention point is real and easy to miss: the analysis pool already saturates the
GPU (§03.6). A native client aggressively decoding previews during a 10k analyze run will
slow the job it's waiting on.

---

## 6. Open questions

- **Sandboxing / App Store**: sandboxing complicates arbitrary library paths and reading LrC
  catalogs. Since this is a personal tool, ship unsandboxed and developer-signed. Revisit only
  if distribution becomes a goal.
- **Bundle the engine?** Shipping Python + FastAPI inside a `.app` (so the native client can
  launch the engine itself) is convenient but a packaging project of its own. M4 assumes the
  engine is already running.
- **Does the native client eventually replace the web one?** Possibly, for daily use — but the
  web client stays the iteration surface and the config UI. Not a decision needed now.
