# 10 — API Contract

**Milestone:** M1 · **Depended on by:** [11](11-web-client.md), [12](12-native-client.md)

The seam between the engine and both clients. **This contract is what makes two frontends
affordable** — if logic leaks across it, they diverge and become two half-working apps.

---

## 1. Contract rules

1. **Clients never compute domain values.** No scoring, grouping, selecting, or threshold
   logic in React or SwiftUI. They render what the engine says.
2. **Every response carries evidence, not just verdicts** (§04.1) — so both clients can show
   *why* without reimplementing anything.
3. **Additive evolution only.** New fields are optional; existing fields don't change meaning.
   The SwiftUI client (M4) will lag the web client, so the API must not break under it.
4. **Localhost only.** Bind `127.0.0.1`. No auth in M1, but never bind `0.0.0.0` — that would
   expose the user's photo library to the local network.
5. **Long work returns a job, not a result.** Anything over ~1 s becomes a `job_id` (§09).

Rule 1 is the one that gets violated under deadline pressure — "just compute the total in the
grid component" is how the divergence starts. Any client-side arithmetic on scores is a
design bug.

---

## 2. Surface

```
GET    /api/health                          → engine version, Vision revs, db state

# Libraries & shoots
POST   /api/libraries                       { root_path } → library (starts scan job)
GET    /api/libraries                       → [library] with online/offline state
GET    /api/libraries/{id}/shoot-proposals  → proposed shoots (§02.4), unconfirmed
POST   /api/shoots                          { library_id, name, profile, photo_ids }
GET    /api/shoots                          → [shoot] with counts + job state
PATCH  /api/shoots/{id}                     { name?, profile? }   ← profile change = rescore only

# Photos
GET    /api/shoots/{id}/photos              ?group=&state=&sort=&cursor=  → paginated
GET    /api/photos/{id}                     → photo + analysis + score + faces + flags
GET    /api/photos/{id}/thumb               ?size=256|1024|2048   → JPEG (cached)
GET    /api/photos/{id}/eye-crop            ?face=0&eye=left      → full-res eye crop
GET    /api/photos/{id}/sharpness-map       → 16x16 tile grid (overlay)

# Pipeline
POST   /api/shoots/{id}/analyze             → job_id
POST   /api/shoots/{id}/group               { thresholds? } → job_id
POST   /api/shoots/{id}/select              { params } → selection_id
GET    /api/shoots/{id}/groups              → hierarchy with member ids
GET    /api/selections/{id}                 → entries with reasons + overrides
PATCH  /api/selections/{id}/entries/{pid}   { state } → sets user_override=1

# Grouping corrections (§05.7)
POST   /api/groups/{id}/split               { at_photo_id }
POST   /api/groups/merge                    { group_ids }
POST   /api/groups/{id}/move                { photo_id, to_group_id }

# Lightroom (§07)
POST   /api/selections/{id}/export/preview  → dry-run diff: what would be written
POST   /api/selections/{id}/export          { targets, confirm_overwrite } → job_id
POST   /api/catalogs/import                 { lrcat_path } → job_id (copies, reads)

# Style (M3)
GET    /api/style/families                  → look families + representative thumbs
POST   /api/shoots/{id}/predict-edits       { family_id } → job_id
GET    /api/photos/{id}/edit-prediction     → params + confidence + neighbor thumbs

# Jobs
GET    /api/jobs/{id}                       → state, progress, failed count
DELETE /api/jobs/{id}                       → cancel
GET    /api/jobs/stream                     → SSE progress (§09.5)
```

### Why `export/preview` exists as its own endpoint
Writing to the user's library is the highest-risk action in the app (§07). A dry run that
returns the exact diff — which files, which fields, which existing values would be
overwritten — lets both clients implement the §07 Rule 2 confirmation step **without
either one deciding what's safe**. The engine decides; the client displays.

---

## 3. Representative payloads

`GET /api/photos/{id}` — the evidence-bearing response the review UI is built on:

```jsonc
{
  "id": 4821, "filename": "IMG_4821.CR3", "raw_format": "CR3",
  "captured_at": "2026-06-14T15:22:08.340", "camera_model": "Canon EOS R5",
  "iso": 800, "shutter": 0.004, "aperture": 1.8, "exposure_bias": 0.0,
  "missing": false,
  "analysis": {
    "decode_mode": "scaled", "engine_version": "0.1.0+vision3",
    "frame": { "sharpness_max": 0.83, "sharpness_mean": 0.31,
               "clipped_hi": 0.004, "horizon_angle": -1.7 }
  },
  "faces": [{
    "idx": 0, "bbox": [0.31,0.22,0.18,0.24], "yaw": -0.11,
    "capture_quality": 0.71, "is_primary": true,
    "eyes": { "left": {"sharp_norm":0.82,"open":0.93},
              "right":{"sharp_norm":0.64,"open":0.95} },
    "eye_source": "mediapipe"
  }],
  "score": {                        // shape per §04.1 — components + evidence
    "profile": "event", "total": 0.71,
    "components": { "eye_focus": {"value":0.82,"weight":0.35,"contrib":0.287,
                                  "evidence":{"eye":"left","frame_max_tile":[7,4]}} },
    "flags": ["subject_near_edge:0.04"],
    "weights_hash": "ev1-a3f2"
  },
  "group": { "shot_id": 88, "size": 9, "is_bracket": false },
  "selection": { "state": "pick", "rank": 1,
                 "reason": "sharpest eyes in group (0.82 vs 0.61 next), both eyes open",
                 "user_override": false }
}
```

`null` vs `0` is semantically load-bearing here: a `null` component means *not applicable or
abstained* (§04.5), and clients must render it as "—", never as a zero bar. Documented
explicitly because it's the easiest place for a client to introduce a wrong display.

---

## 4. Images

Thumbnails are the API's bandwidth-critical path — a 10,000-photo grid at 256 px is ~10k
requests.

- Generated on demand by the Swift helper (`render`, §03.4), then cached on disk keyed by
  `content_id` + size + orientation.
- `ETag` = `content_id:size`; `Cache-Control: immutable`. Content-addressed, so a cached
  thumbnail is never stale.
- **Display decode path** (§03.2) — Apple defaults on. Never the measurement path.
- `eye-crop` is full-res and uncached (rare, on-demand) — it's the "prove the eye is sharp"
  view, and downscaling it would defeat the purpose.

---

## 5. Errors

```jsonc
{ "error": { "code": "volume_offline",
             "message": "Library volume 'Shoots2026' is not mounted.",
             "detail": { "library_id": 3, "volume_uuid": "..." },
             "retryable": true } }
```

Stable machine-readable `code` (both clients switch on it), human `message`, structured
`detail`, and `retryable`. Codes: `volume_offline`, `file_missing`, `decode_failed`,
`catalog_locked`, `catalog_schema_unsupported`, `sidecar_conflict`, `job_conflict`,
`dng_writeback_unsupported`.

`sidecar_conflict` and `catalog_schema_unsupported` map directly to the §07 safety rules —
they must reach the user as a decision, never be swallowed and retried.

---

## 6. Non-goals for M1

- **No auth / multi-user.** Single-user localhost.
- **No remote access.** Explicitly out of scope; the library is private data.
- **No websockets** — SSE is sufficient for one-directional progress and much simpler.
- **No GraphQL.** The query surface is small and fixed; REST + cursor pagination is enough.
