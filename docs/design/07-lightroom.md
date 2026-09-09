# 07 — Lightroom Classic Integration

**Milestone:** M1 (selects) / M3 (edits) · **Depends on:** [06](06-culling.md), [08](08-style-learning.md)

The only domain that **writes into the user's data**. Highest data-loss risk in the app;
designed defensively throughout.

---

## 1. Two hard rules

### Rule 1 — Never touch a live `.lrcat`
The catalog is SQLite with an undocumented, version-specific schema, and LrC holds locks
while running. Writing to it risks corrupting years of work with no clean recovery. Reading
a *running* catalog can also return torn state mid-transaction.

**Therefore: copy first, read the copy, never write either.**

```python
# copy .lrcat + -wal + -shm together — WAL contains committed data
# not yet checkpointed into the main file. Copying only the .lrcat
# silently loses recent edits.
shutil.copy2(cat);  shutil.copy2(cat + "-wal");  shutil.copy2(cat + "-shm")
conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)   # verified available
```

`mode=ro` (not `immutable=1`) for the copy: `immutable` tells SQLite to ignore the WAL,
which would hide recent edits. Both modes verified working on Python 3.14 / SQLite 3.53.

Also refuse to proceed if LrC is running *and* the user pointed at the live catalog for
anything other than a copy operation — detected via process check.

### Rule 2 — Never silently overwrite user XMP
An existing `.xmp` beside a RAW may contain hours of the user's develop work. Blind
overwrite is unrecoverable.

**Write protocol, every time:**
1. **Read** the existing sidecar, if any.
2. **Diff** — what would change; are there existing `crs:` develop values?
3. **Back up** to `<app-support>/backups/<content_id>/<timestamp>.xmp` before any write.
4. **Confirm** — if existing develop settings would be modified, require explicit user
   confirmation (never a silent default-yes).
5. **Atomic write** — temp file in the same directory, `fsync`, then `os.replace`.
6. **Preserve unknown fields** — never regenerate the file from our own schema; only
   modify the specific properties we own.

Step 6 matters more than it sounds: sidecars contain keywords, GPS, crop, local
adjustments, and third-party plugin data. Regenerating from a template would destroy all of
it while looking like a successful write.

---

## 2. Reading the catalog (M2 ground truth)

Extract into `lr_history` (§01): pick flag, rating, color label, develop settings.

Relevant tables (LrC 11–14 shape; **schema is undocumented and version-specific**):

| Table | Provides |
|---|---|
| `AgLibraryFile` | filename, `AgLibraryFolder` ref |
| `AgLibraryFolder` + `AgLibraryRootFolder` | path reconstruction |
| `Adobe_images` | `pick`, `rating`, `colorLabels`, `captureTime` |
| `Adobe_AdditionalMetadata` | `xmp` blob |
| `Adobe_imageDevelopSettings` | `text` — develop params (Lua-ish serialized) |

**Defensive stance, since the schema is not a contract:**
- Probe `Adobe_variablesTable` for the catalog version and record it.
- Validate expected tables/columns exist **before** querying; on mismatch, degrade to
  sidecar-only ingestion rather than guessing.
- Treat every extraction as best-effort with a reported coverage number ("read 8,412 of
  9,003 photos").
- Match catalog rows to our `photo` rows by **filename + capture time + file size**, not
  path (paths differ across machines/mounts). Report unmatched counts rather than
  silently dropping.

Develop settings in `Adobe_imageDevelopSettings.text` are a serialized Lua table, not JSON.
**Measured 2026-08-30 on a real LrC 15 catalog (DB version 1504001): the preference
inverts.** The `Adobe_AdditionalMetadata.xmp` blob (4-byte length prefix + zlib) carried
`crs:` develop values on 1 of 560 edited photos — LrC only serializes develop into it on
explicit save-to-XMP — while the Lua `text` had every edit (111 global params each).
Implemented (`shootr.lr_catalog`): parse the Lua table's depth-1 scalars (nested tables
are masks/curves — local, out of style scope), fall back to `crs:` XMP attributes, store
JSON in `lr_history.develop`. The WAL lesson from the same run: a quiesced copy opens
with `immutable=1` (plain `mode=ro` fails without the `-shm`); a copy with a live `-wal`
gets one writable open to recover, then `PRAGMA query_only`.

---

## 3. Writing selects (M1)

Two mechanisms, both shipped:

### 3.1 XMP sidecars — the reliable path
Write `xmp:Rating` and `xmp:Label`, and pick/reject as ratings per §06's mapping. User then
runs **Metadata → Read Metadata from File** in LrC.

Caveats stated plainly to the user in the UI:
- LrC does **not** watch sidecars; the read step is manual.
- "Read Metadata from File" **overwrites catalog metadata from the file** — if the user has
  catalog-only edits not yet written to XMP, those are lost. This is LrC's behavior, not
  ours, but we must warn before recommending it.
- Reject flags are not representable in XMP as flags (only ratings/labels), so pick/reject
  round-trips imperfectly. We use ratings + a color label instead of pretending.

For **DNG** files, metadata belongs *inside* the file, not a sidecar. Writing a `.dng.xmp`
does nothing. DNG needs either embedded-XMP writing (risky — modifying the user's RAW) or
must be declared unsupported for select-writeback. **M1 decision: warn and skip DNG
writeback**; embedding into a user's RAW is not a risk worth taking for a convenience
feature.

**Generalized 2026-09-07:** the same reasoning covers every format that carries its
metadata internally — JPEG, HEIC, TIFF, PNG — so `EMBEDDED_METADATA_SUFFIXES` skips all of
them and the plan reports them as `skipped_embedded` (both clients name the formats). This
matters because JPEG-only culling otherwise *appears* to export and silently delivers
nothing. Those picks are still delivered by §3.2's CSV list and hardlink folder, which
don't depend on sidecar semantics.

### 3.2 Collection list — the practical path
Also emit a plain-text/CSV file list the user can drag into LrC, plus an optional
`.lrcat`-independent "Selects" folder of **hardlinks** (not copies — no disk cost, no
duplication). Works regardless of sidecar/DNG issues.

### 3.2b Delivering the selects as files (no Lightroom at all)

Requested 2026-09-09: someone who wants only the culling has no use for sidecars they
must import. They want the keepers as *files*, in a folder they choose.

**Two separate actions, not one dialog with a mode dropdown** (user's correction, same
day). Moving someone's originals is a different kind of act from producing a second view
of them, and burying it as the third option in a picker makes the most consequential
choice the easiest to click by accident:

| action | mode(s) | disk cost | originals |
|---|---|---|---|
| **Deliver files…** | hardlink (default), copy | none / full size | untouched, still in place |
| **Move keepers…** | move | none | **relocated to the chosen folder** |

`Deliver files…` never offers move; `Move keepers…` never does anything else. One code
path in the engine (`deliver.plan`/`execute` take a mode), two deliberately separate
doors in the UI, each with its own confirmation and its own keyboard shortcut.

Rules this must obey, and why:

- **Rejects are never touched.** Default scope is `pick`; `alt` is opt-in. Rule 2
  (culling never deletes) is about the *engine* never removing a photo on its own
  judgement — a user pointing at a folder and asking for their picks is a different act,
  and it still must not put a rejected frame at risk.
- **A move is never a delete-then-hope.** Same volume uses `os.replace` (atomic).
  Across volumes it copies, verifies the copy by size **and content id**, and only then
  unlinks the source. A failure at any point leaves the original where it was.
- **The library never lies afterwards.** A moved photo inside the library root gets its
  `rel_path` updated in place (identity is content-based, so its analysis survives —
  §02). Moved outside, it is marked `missing=1`, which is non-destructive and honest,
  rather than leaving a path that resolves to nothing.
- **Sidecars and JPEG siblings travel with the RAW.** Leaving a `.xmp` behind orphans the
  ratings; leaving the JPEG behind splits a pair the app deliberately keeps together.
- **Dry run first, always.** The plan states counts, name collisions, whether the mode is
  even possible (hardlinks cannot cross volumes), and for copies whether the destination
  has room. Nothing is written without explicit confirmation, and nothing overwrites an
  existing file — collisions get a numbered suffix and are reported.

### 3.3 Lua plugin (M5, optional)
The official SDK can create collections and set flags/ratings from *inside* LrC — best UX
and no catalog-safety issue, since LrC does the writing. Deferred: it's a separate
language/toolchain and the SDK's develop-settings API is limited.

---

## 4. Writing edits (M3)

Per-photo `crs:` values into the sidecar, following the §1 Rule 2 protocol.

**Scope — global parameters only:**
`crs:Exposure2012`, `Contrast2012`, `Highlights2012`, `Shadows2012`, `Whites2012`,
`Blacks2012`, `Temperature`, `Tint`, `Vibrance`, `Saturation`, `Clarity2012`, `Texture`,
`Dehaze`, `ToneCurvePV2012*`, `HueAdjustment*`/`SaturationAdjustment*`/
`LuminanceAdjustment*` (HSL), `ColorGrade*`.

**Explicitly excluded:** local adjustments — brushes, gradients, AI subject/sky masks.
They're spatial and per-photo; there is no honest way to transfer them from a style model
(SPEC §7). Not a temporary gap — a stated boundary.

**Version discipline:** write `crs:ProcessVersion` matching the user's LrC version and
`crs:Version`. Mismatched process versions cause LrC to reinterpret the same numbers
differently — the same Exposure value renders differently across process versions, so
predictions calibrated on PV6 edits must not be written as PV3.

Delivery is **additive, reversible-friendly**: predictions land as a develop starting point
the user tweaks. Combined with per-write backups (§1) and the option to write to a
**virtual copy / snapshot** instead of the master where the plugin path is available.

---

## 5. Safety summary

| Threat | Mitigation |
|---|---|
| Catalog corruption | never write; copy incl. `-wal`/`-shm`; `mode=ro`; refuse live catalog |
| Lost develop work in sidecar | read → diff → backup → confirm → atomic write; preserve unknown fields |
| Silent metadata loss via "Read Metadata from File" | warn before recommending |
| Schema drift across LrC versions | version probe; validate before query; degrade, don't guess |
| Wrong photo matched | match on filename+time+size; report unmatched |
| Torn write on crash/unplug | temp + fsync + `os.replace` in same directory |
| DNG sidecar no-op | detect and skip with warning |
| Process-version mismatch | write explicit `ProcessVersion`; refuse cross-PV application |

---

## 6. Open questions (need the user's actual setup — SPEC §11)

- **LrC version** → catalog schema shape and process version.
- Is **"Automatically write changes into XMP"** enabled? If yes, sidecars are the reliable
  style-learning source; if no, the catalog copy is the only complete source.
- Are the RAWs **DNG-converted**? Would make §3.1 writeback largely unavailable and push
  toward the plugin path sooner.
- Multiple catalogs, or one? Multiple means per-catalog look families may differ (§08).
