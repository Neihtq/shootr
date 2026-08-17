# 01 — Domain Model & Storage

**Milestone:** M1 · **Depended on by:** all domains

Every other domain reads and writes through this schema. Getting identity and
invariants right here is what keeps the rest honest.

---

## 1. Entities

```
Library ──1:N── Shoot ──1:N── Photo ──1:N── Face
                  │             │
                  │             ├──1:1── Analysis   (raw measurements)
                  │             ├──1:1── Score      (derived, per profile)
                  │             ├──1:N── Embedding
                  │             └──1:N── EditPrediction
                  │
                  ├──1:N── Group  ──1:N── GroupMember ──► Photo
                  ├──1:1── Selection ──1:N── SelectionEntry ──► Photo
                  └──1:N── Job
```

- **Library** — a root the user pointed us at. May be on a removable volume.
- **Shoot** — a unit of work with one **scoring profile** (portrait / event / landscape
  / street). Usually one folder or one day. The profile lives here because the user
  shoots all four genres (SPEC §2).
- **Photo** — one capture. A RAW + optional sidecar + optional JPEG sibling are **one**
  Photo, not three.
- **Analysis** — measured facts from the engine. Expensive, cached, profile-independent.
- **Score** — derived from Analysis by profile weights. Cheap, recomputable, **never**
  the cache key.
- **Group** — a cluster at one level of the hierarchy (§05).
- **Selection** — a proposed cull result the user can accept, edit, or regenerate.

### The Analysis/Score split is the key design decision

Analysis is expensive (RAW decode + Vision, ~seconds/photo) and **independent of
profile**. Score is cheap and **profile-dependent**. Keeping them separate means
retuning weights or switching a shoot from "event" to "portrait" is instant and requires
**zero re-decoding** of 10,000 files. Conflating them would make every weight tweak a
multi-hour rescan — which in practice means you'd stop tuning, and untuned weights are
useless weights.

---

## 2. Identity

**Photo identity = content, not path.** External drives remount at different paths;
users reorganize folders. Path-based identity would orphan every analysis.

```
content_id = blake3(file_size || first_64KB || last_64KB)
```

Partial hashing, not full-file: a 60 MB RAW × 10,000 files is 600 GB of reads per scan.
Head+tail+size is enough to distinguish captures in practice, and cheap enough to run on
every scan. `mtime` + `size` form a fast-path cache check so unchanged files skip
hashing entirely.

**Deliberately not used for identity:**
- *Path* — breaks on remount/reorg.
- *EXIF capture time* — burst frames share a timestamp to the second.
- *Full-file hash* — correct but too slow for routine rescans.
- *Camera serial + shutter count* — ideal in theory, unreliably present across
  Canon/Sony/Fuji.

**Collision handling:** if two files share a `content_id` but differ in full-file hash,
promote to full hash and log. Expected frequency: effectively zero; silent wrongness here
would be severe, so it's checked rather than assumed.

### RAW + JPEG + sidecar grouping
Same directory, same basename, different extension → one Photo. The RAW is primary; the
JPEG becomes a rendition; the `.xmp` becomes sidecar state. A JPEG with no RAW sibling is
its own Photo. Basename collisions across directories are *not* merged.

---

## 3. Schema

SQLite, WAL mode. Owned exclusively by the Python engine (README rule 6).

```sql
PRAGMA journal_mode = WAL;      -- concurrent reads during long analysis runs
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;    -- WAL + NORMAL is durable enough; FULL is too slow here

CREATE TABLE library (
  id           INTEGER PRIMARY KEY,
  root_path    TEXT NOT NULL,
  volume_uuid  TEXT,                    -- survives remount at a different path
  created_at   TEXT NOT NULL
);

CREATE TABLE shoot (
  id           INTEGER PRIMARY KEY,
  library_id   INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  profile      TEXT NOT NULL CHECK (profile IN
                 ('portrait','event','landscape','street')),
  created_at   TEXT NOT NULL
);

CREATE TABLE photo (
  id            INTEGER PRIMARY KEY,
  library_id    INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
  shoot_id      INTEGER REFERENCES shoot(id) ON DELETE SET NULL,
  content_id    TEXT NOT NULL,
  rel_path      TEXT NOT NULL,          -- relative to library root
  filename      TEXT NOT NULL,
  raw_format    TEXT,                   -- CR3 | ARW | RAF | JPEG | ...
  file_size     INTEGER NOT NULL,
  mtime         REAL NOT NULL,
  captured_at   TEXT,                   -- EXIF DateTimeOriginal
  subsec        INTEGER,                -- disambiguates burst frames
  camera_model  TEXT,
  lens_model    TEXT,
  iso           INTEGER,
  shutter       REAL,
  aperture      REAL,
  focal_length  REAL,
  exposure_bias REAL,                   -- bracket detection (§04)
  orientation   INTEGER,
  width         INTEGER,
  height        INTEGER,
  jpeg_sibling  TEXT,                   -- rel path if RAW+JPEG pair
  sidecar_path  TEXT,
  missing       INTEGER NOT NULL DEFAULT 0,  -- volume offline / file gone
  UNIQUE (library_id, content_id)
);
CREATE INDEX photo_shoot_time ON photo(shoot_id, captured_at, subsec);
CREATE INDEX photo_content    ON photo(content_id);

-- Expensive, profile-independent measurements. Versioned so an engine upgrade
-- can invalidate precisely instead of nuking the whole cache.
CREATE TABLE analysis (
  photo_id       INTEGER PRIMARY KEY REFERENCES photo(id) ON DELETE CASCADE,
  engine_version TEXT NOT NULL,
  decode_mode    TEXT NOT NULL,         -- cfa | scaled | preview  (§03 benchmark)
  frame          TEXT NOT NULL,         -- JSON: sharpness map, histogram, WB, horizon
  saliency       TEXT,                  -- JSON: attention/objectness bbox
  analyzed_at    TEXT NOT NULL
);

CREATE TABLE face (
  id             INTEGER PRIMARY KEY,
  photo_id       INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  idx            INTEGER NOT NULL,
  bbox           TEXT NOT NULL,         -- JSON [x,y,w,h] normalized
  roll           REAL, yaw REAL, pitch REAL,
  capture_quality REAL,                 -- Vision VNFaceObservation.faceCaptureQuality
  eye_sharp_l    REAL, eye_sharp_r REAL,   -- normalized (§04)
  eye_open_l     REAL, eye_open_r REAL,    -- 0..1; NULL if detector unavailable
  eye_source     TEXT,                  -- which blink detector produced it
  landmarks      TEXT,                  -- JSON 76-pt
  faceprint      BLOB,                  -- Vision faceprint for identity clustering
  person_id      INTEGER REFERENCES person(id) ON DELETE SET NULL,
  UNIQUE (photo_id, idx)
);
CREATE INDEX face_photo ON face(photo_id);

CREATE TABLE person (
  id        INTEGER PRIMARY KEY,
  shoot_id  INTEGER REFERENCES shoot(id) ON DELETE CASCADE,
  label     TEXT                        -- user-assigned, optional
);

CREATE TABLE embedding (
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL,               -- scene | pose
  vec      BLOB NOT NULL,               -- float32
  dim      INTEGER NOT NULL,
  PRIMARY KEY (photo_id, kind)
);

-- Derived. Recomputed freely; profile is part of the key so multiple
-- profiles can coexist for comparison.
CREATE TABLE score (
  photo_id     INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  profile      TEXT NOT NULL,
  total        REAL NOT NULL,
  components   TEXT NOT NULL,           -- JSON per-metric values (evidence)
  flags        TEXT NOT NULL,           -- JSON composition flags
  weights_hash TEXT NOT NULL,           -- which weight set produced this
  PRIMARY KEY (photo_id, profile)
);

CREATE TABLE "group" (
  id         INTEGER PRIMARY KEY,
  shoot_id   INTEGER NOT NULL REFERENCES shoot(id) ON DELETE CASCADE,
  level      TEXT NOT NULL CHECK (level IN ('scene','shot','pose','person')),
  parent_id  INTEGER REFERENCES "group"(id) ON DELETE CASCADE,
  is_bracket INTEGER NOT NULL DEFAULT 0,   -- never cull across these (§04)
  label      TEXT
);

CREATE TABLE group_member (
  group_id INTEGER NOT NULL REFERENCES "group"(id) ON DELETE CASCADE,
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  PRIMARY KEY (group_id, photo_id)
);

CREATE TABLE selection (
  id         INTEGER PRIMARY KEY,
  shoot_id   INTEGER NOT NULL REFERENCES shoot(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  params     TEXT NOT NULL,             -- keep-per-group, thresholds
  exported_at TEXT                      -- when pushed to LrC/XMP
);

CREATE TABLE selection_entry (
  selection_id INTEGER NOT NULL REFERENCES selection(id) ON DELETE CASCADE,
  photo_id     INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  group_id     INTEGER REFERENCES "group"(id) ON DELETE SET NULL,
  state        TEXT NOT NULL CHECK (state IN ('pick','alt','reject')),
  rank         INTEGER,
  reason       TEXT,                    -- human-readable justification
  user_override INTEGER NOT NULL DEFAULT 0,  -- user disagreed with engine
  PRIMARY KEY (selection_id, photo_id)
);

-- Historical ground truth read from an LrC catalog COPY (§07). Trains
-- calibration in M2. Kept apart from our own scores.
CREATE TABLE lr_history (
  photo_id    INTEGER PRIMARY KEY REFERENCES photo(id) ON DELETE CASCADE,
  pick_flag   INTEGER,                  -- -1 reject, 0 none, 1 pick
  rating      INTEGER,
  color_label TEXT,
  develop     TEXT                      -- JSON crs: params (§08)
);

CREATE TABLE edit_prediction (
  id          INTEGER PRIMARY KEY,
  photo_id    INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  look_family TEXT,
  params      TEXT NOT NULL,            -- JSON crs: deltas (§08)
  model_kind  TEXT NOT NULL,            -- knn | regressor
  created_at  TEXT NOT NULL,
  applied_at  TEXT                      -- when written to XMP
);

CREATE TABLE job (
  id          INTEGER PRIMARY KEY,
  shoot_id    INTEGER REFERENCES shoot(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,            -- scan | analyze | group | select | export
  state       TEXT NOT NULL CHECK (state IN
                ('pending','running','done','failed','cancelled')),
  total       INTEGER, completed INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  created_at  TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- Per-photo job progress: this is what makes a 10k run resumable (§09).
CREATE TABLE job_item (
  job_id   INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  state    TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  error    TEXT,
  PRIMARY KEY (job_id, photo_id)
);
CREATE INDEX job_item_pending ON job_item(job_id, state);
```

---

## 4. Invariants

Enforced in code (and by CHECK/UNIQUE where SQLite can):

1. **No deletion of user files, ever.** Nothing in this schema stores a path we delete.
   `missing=1` records absence; it never triggers cleanup of disk content.
2. **`selection_entry.state='reject'` means "not chosen"** — never "delete". Rejects stay
   queryable so the user can audit what was passed over.
3. **`analysis` is immutable per `engine_version`.** Re-analysis writes a new row version,
   never mutates measurements in place, so scores stay reproducible.
4. **`score` is always derivable.** Dropping the whole table must cost only CPU. If
   anything in `score` can't be recomputed from `analysis` + weights, it belongs in
   `analysis`.
5. **`user_override=1` is sacred.** Regenerating a selection must preserve overridden
   entries. Silently discarding the user's own picks would destroy trust in the tool.
6. **`is_bracket` groups are never culled internally** (§04 bracket guard).

---

## 5. Migrations

`schema_version` table; forward-only numbered migrations applied at startup in a
transaction. `analysis.engine_version` is separate from schema version — a Vision or
sharpness-algorithm change invalidates measurements without changing table shape, and
must invalidate *only* affected columns. Full recompute of 10k photos is hours, so
precision here is worth the bookkeeping.

---

## 6. Open questions

- Should `shoot` allow **per-photo profile override**? A wedding contains posed portraits
  *and* candids. Current answer: no in M1 — group-level profile hints in §05 handle it.
  Revisit if the single profile proves too coarse in real use.
- Should `embedding` move to a vector index (sqlite-vec / faiss)? At 10k photos brute
  force is ~ms and needs no dependency. Revisit at 100k+ (whole-library indexing).
