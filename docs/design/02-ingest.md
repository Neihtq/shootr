# 02 — Ingest & Library

**Milestone:** M1 · **Depends on:** [01](01-domain-model.md) · **Feeds:** [03](03-analysis-engine.md)

Turns a folder the user points at into `photo` rows, fast, incrementally, and safely when
the drive is external.

---

## 1. Constraint that shapes everything

The library is **not on this Mac** (SPEC §1). It's an external or network volume. So:

- Scans must survive **mid-run disconnection** without corrupting state.
- Re-scans must be **incremental** — a 10,000-photo rescan that re-reads every file is
  unusable at USB/Thunderbolt bandwidth.
- Paths are **unstable**; identity is content-based (§01).
- We must **never write into the library** during ingest. Ingest is read-only. The only
  writes to user directories happen in §07, explicitly and confirmably.

---

## 2. Pipeline

```
 discover ──► fast-path filter ──► identify ──► probe metadata ──► upsert
 (walk)       (mtime+size)         (hash)       (EXIF + RAW info)   (SQLite)
                   │
                   └── unchanged → skip entirely (no read, no hash, no probe)
```

### Stage 1 — Discover
`os.scandir` recursion (not `glob`), which gives `stat` for free from the directory entry
and avoids a second syscall per file. Extension allowlist: `cr2 cr3 arw raf nef dng
jpg jpeg heic tif tiff`. Skips: `.` files, `@eaDir`, `.Trashes`, `Lightroom Settings`,
`*_previews.lrdata`, `.lrcat*`.

Also detects the **volume UUID** (`diskutil info -plist`) so a library re-mounted at a
different path resolves to the same `library` row rather than duplicating it.

### Stage 2 — Fast-path filter
If `(rel_path, mtime, size)` matches an existing row → **skip**. No file read, no hash.
This is what makes rescans cheap: the common case is "nothing changed", and it costs one
directory read per folder.

### Stage 3 — Identify
`content_id = blake3(size || first_64KB || last_64KB)` (§01). Two 64 KB reads instead of
a 60 MB read — ~500× less I/O, which matters over a bus. Handles:
- **Moved file**: same `content_id`, new path → update path, keep analysis. This is the
  payoff of content identity.
- **Modified file**: same path, changed mtime/size, different `content_id` → invalidate
  analysis.
- **Duplicate**: same `content_id`, different path, both present → keep both `photo`
  rows? **No** — one Photo, and record the extra path. Analyzing the same capture twice
  wastes minutes and pollutes grouping with fake near-duplicates.

### Stage 4 — Probe metadata
EXIF only, no pixel decode. This is a **separate, cheaper pass** than analysis (§03) on
purpose: metadata alone is enough to create shoots, sort by time, detect brackets, and
show the user a populated grid within seconds — while heavy analysis runs behind it.

Fields → `photo` columns per §01: `captured_at`, `subsec`, camera/lens, ISO, shutter,
aperture, focal length, `exposure_bias`, orientation, dimensions.

`SubSecTimeOriginal` matters: burst frames share a whole-second timestamp, and without
subsecond precision, burst ordering (§05) is arbitrary. Where a camera omits it, fall back
to filename sequence number.

**Implementation:** the Swift helper (§03) exposes `probe`, using ImageIO
(`CGImageSourceCopyPropertiesAtIndex`) — no pixel decode, no exiftool dependency, and it
handles all 893 RAW models the same way the decoder does. Avoids a Python EXIF library
disagreeing with Core Image about the same file.

### Stage 5 — Upsert
Batched transactions (500 rows). `UNIQUE(library_id, content_id)` makes re-ingest
idempotent.

---

## 3. RAW/JPEG/sidecar pairing

Group by `(directory, basename_without_extension)`:

| Present | Result |
|---|---|
| `IMG_1234.CR3` | Photo (raw) |
| `IMG_1234.CR3` + `IMG_1234.JPG` | one Photo, raw primary, `jpeg_sibling` set |
| `IMG_1234.CR3` + `IMG_1234.xmp` | Photo, `sidecar_path` set |
| `IMG_1234.JPG` only | Photo (jpeg) |
| `IMG_1234.CR3` + `IMG_1234-2.CR3` | two Photos (different basenames) |

RAW is always primary when present — it's what LrC edits and what we must not corrupt.
Pairing is **directory-scoped**: same basename in two folders is two different captures.

---

## 4. Shoot assignment

Ingest proposes shoots; it never finalizes them, because only the user knows the genre
(which sets the profile, §04).

Proposal: split on **capture-time gaps > 4 h**, then intersect with directory structure —
if the user's folders already separate sessions, trust the folders. Each proposal is
presented for confirmation with a profile picker. A one-day two-part wedding shouldn't
silently become two shoots, nor should a week of travel become one.

---

## 5. Failure handling

| Failure | Behavior |
|---|---|
| Volume disappears mid-scan | Job → `failed` with `volume_offline`; rows already committed stay valid; resume continues from the fast-path filter |
| File unreadable / permission denied | Mark `photo.missing=1`, record error, continue. One bad file must not abort a 10k scan |
| Corrupt RAW (probe fails) | Row created with metadata NULL, flagged; analysis will skip it |
| Library root missing at startup | Mark library offline, show last-known contents read-only. Never delete rows because a drive is unplugged |
| `content_id` collision, differing full hash | Escalate to full-file hash, log loudly (§01) |

**Rule: absence is never destructive.** A missing file sets `missing=1`. It never removes
analysis, selections, or user overrides — those are expensive or irreplaceable, and the
drive is probably just unplugged.

---

## 6. Performance targets

For 10,000 files on an external SSD:

| Scenario | Target | Dominated by |
|---|---|---|
| First scan | < 90 s | EXIF probe (two 64 KB reads + ImageIO per file) |
| Rescan, nothing changed | < 5 s | directory `stat` only |
| Rescan, 200 new | < 10 s | 200 probes |

Parallelism: `min(8, cpu_count)` threads. I/O-bound on external buses, so more threads
mostly add seek contention rather than throughput. Tune after the §03 benchmark, on the
real drive.

---

## 7. Open questions

- **HEIC/compressed-RAW variants** (Canon CRAW, Sony lossy) — decode identically via Core
  Image, but sharpness measurement (§03) may behave differently on lossy data. Flag them
  in `raw_format` so the benchmark can compare.
- **Network volumes (SMB/NFS)** — `mtime` granularity and `stat` cost are worse; the
  fast path may need a content-sampling fallback. Deferred until the user has one.
- Should ingest read existing `.xmp` **during** ingest to show prior ratings immediately?
  Cheap and useful, but risks conflating the user's existing LrC state with ours. Current
  answer: read into `lr_history` only, never into `score` or `selection` (§07).
