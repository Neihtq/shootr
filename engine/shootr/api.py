"""HTTP API (docs/design/10-api.md). The seam both clients share.

Contract rules enforced here:
- Clients never compute domain values — every response carries the engine's
  evidence, verdicts, and reasons.
- Long work returns a job id.
- Errors use the stable envelope: {code, message, detail, retryable}.
- Bind 127.0.0.1 ONLY (main() below); never 0.0.0.0 — that would expose the
  photo library to the local network.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import db, helper, jobs, pipeline, xmp
from .ingest import backfill_metadata, propose_shoots, scan
from .runner import JobRunner


def error(status: int, code: str, message: str, retryable: bool = False,
          detail: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={
        "code": code, "message": message, "detail": detail or {},
        "retryable": retryable})


# Request models at module level: `from __future__ import annotations` makes
# annotations strings, and FastAPI can only resolve them against module
# globals — function-local models would silently become query params.

class LibraryIn(BaseModel):
    root_path: str


class ShootIn(BaseModel):
    library_id: int
    name: str
    profile: str
    photo_ids: list[int]


class ShootPatch(BaseModel):
    name: str | None = None
    profile: str | None = None


class SelectIn(BaseModel):
    floor: float | None = None


class EntryPatch(BaseModel):
    state: str


class ExportIn(BaseModel):
    confirm_overwrite: bool = False


class SplitIn(BaseModel):
    at_photo_id: int


class MergeIn(BaseModel):
    group_ids: list[int]


class MoveIn(BaseModel):
    photo_id: int
    to_group_id: int


def create_app(db_path: str | Path, backup_dir: str | Path,
               cache_dir: str | Path | None = None,
               runner: JobRunner | None = None,
               web_dist: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="shootr", docs_url=None, redoc_url=None)
    app.state.db_path = str(db_path)
    app.state.backup_dir = Path(backup_dir)
    app.state.cache_dir = Path(cache_dir) if cache_dir \
        else Path(db_path).parent / "thumbs"
    app.state.cache_dir.mkdir(parents=True, exist_ok=True)
    # Injectable for tests; None = jobs are created but drained externally.
    app.state.runner = runner
    if runner:
        runner.start()

    def conn() -> sqlite3.Connection:
        # One connection per request keeps things simple for a single-user
        # localhost app; WAL allows concurrent readers during jobs.
        return db.connect(app.state.db_path)

    @app.exception_handler(HTTPException)
    async def envelope(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "code": "error", "message": str(exc.detail), "detail": {},
            "retryable": False}
        return JSONResponse(status_code=exc.status_code,
                            content={"error": detail})

    # -- health --------------------------------------------------------------

    @app.get("/api/health")
    def health():
        c = conn()
        try:
            version = db.schema_version(c)
            return {"engine_version": "0.1.0", "schema_version": version}
        finally:
            c.close()

    # -- libraries & shoots ---------------------------------------------------

    @app.post("/api/libraries")
    def create_library(body: LibraryIn):
        root = Path(body.root_path)
        if not root.is_dir():
            raise error(400, "volume_offline",
                        f"Library root not found: {root}", retryable=True)
        c = conn()
        try:
            # Re-adding a known path = rescan, never a duplicate library.
            # Scans are idempotent (fast-path filter), so this is cheap.
            existing = c.execute(
                "SELECT id FROM library WHERE root_path = ?",
                (str(root),)).fetchone()
            if existing:
                lib_id = existing["id"]
            else:
                with c:
                    cur = c.execute(
                        "INSERT INTO library (root_path, created_at) "
                        "VALUES (?, datetime('now'))", (str(root),))
                    lib_id = cur.lastrowid
            # The Swift helper prober fills captured_at etc. — without it,
            # shoot proposals would have no capture times. `batch_prober`
            # is the one that matters for throughput: per-file spawning
            # took ~100 ms/file, which blew past client HTTP timeouts on a
            # 1200-RAW folder while the scan kept running server-side.
            kwargs: dict = {}
            if helper.helper_available():
                kwargs["prober"] = helper.swift_prober
                kwargs["batch_prober"] = helper.probe_many
            result = scan(c, lib_id, root, **kwargs)
            # Heal rows left with NULL metadata by an older/broken probe:
            # the fast-path filter would skip them forever otherwise.
            backfilled = 0
            if "batch_prober" in kwargs:
                backfilled = backfill_metadata(
                    c, lib_id, root, kwargs["batch_prober"])
            return {"id": lib_id, "root_path": str(root),
                    "scan": {"added": result.added,
                             "unchanged": result.unchanged,
                             "errors": len(result.errors),
                             "backfilled": backfilled}}
        finally:
            c.close()

    @app.delete("/api/libraries/{library_id}")
    def delete_library(library_id: int):
        """Removes the library's rows from the app database — photos,
        analysis, shoots, selections cascade. NEVER touches files on disk;
        nothing in this app deletes user files (design README rule 2)."""
        c = conn()
        try:
            row = c.execute("SELECT id FROM library WHERE id = ?",
                            (library_id,)).fetchone()
            if not row:
                raise error(404, "file_missing", f"No library {library_id}")
            exported = c.execute(
                "SELECT COUNT(*) AS n FROM selection s "
                "JOIN shoot sh ON sh.id = s.shoot_id "
                "WHERE sh.library_id = ? AND s.exported_at IS NOT NULL",
                (library_id,)).fetchone()["n"]
            with c:
                c.execute("DELETE FROM library WHERE id = ?", (library_id,))
            return {"deleted": library_id,
                    "note": ("selections already exported to XMP remain in "
                             "your files" if exported else None)}
        finally:
            c.close()

    @app.get("/api/libraries")
    def list_libraries():
        c = conn()
        try:
            return [
                {"id": r["id"], "root_path": r["root_path"],
                 "online": Path(r["root_path"]).is_dir()}
                for r in c.execute("SELECT * FROM library")
            ]
        finally:
            c.close()

    @app.get("/api/libraries/{library_id}/shoot-proposals")
    def shoot_proposals(library_id: int):
        c = conn()
        try:
            return [
                {"photo_ids": list(p.photo_ids), "start": p.start,
                 "end": p.end, "directories": list(p.directories)}
                for p in propose_shoots(c, library_id)
            ]
        finally:
            c.close()

    @app.post("/api/shoots")
    def create_shoot(body: ShootIn):
        if body.profile not in ("portrait", "event", "landscape", "street"):
            raise error(400, "invalid_profile",
                        f"Unknown profile: {body.profile}")
        c = conn()
        try:
            with c:
                cur = c.execute(
                    "INSERT INTO shoot (library_id, name, profile, "
                    "created_at) VALUES (?, ?, ?, datetime('now'))",
                    (body.library_id, body.name, body.profile))
                shoot_id = cur.lastrowid
                c.executemany(
                    "UPDATE photo SET shoot_id = ? WHERE id = ?",
                    [(shoot_id, pid) for pid in body.photo_ids])
            return {"id": shoot_id}
        finally:
            c.close()

    @app.patch("/api/shoots/{shoot_id}")
    def patch_shoot(shoot_id: int, body: ShootPatch):
        c = conn()
        try:
            if body.name:
                with c:
                    c.execute("UPDATE shoot SET name = ? WHERE id = ?",
                              (body.name, shoot_id))
            rescored = 0
            if body.profile:
                if body.profile not in ("portrait", "event", "landscape",
                                        "street"):
                    raise error(400, "invalid_profile",
                                f"Unknown profile: {body.profile}")
                with c:
                    c.execute("UPDATE shoot SET profile = ? WHERE id = ?",
                              (body.profile, shoot_id))
                # Profile change = rescore only, zero re-decoding (design 01).
                rescored = pipeline.score_shoot(c, shoot_id)
            return {"id": shoot_id, "rescored": rescored}
        finally:
            c.close()

    @app.get("/api/shoots")
    def list_shoots():
        """`busy_job_id` marks shoots with work in flight.

        Derived from the job table, not tracked per client: a shoot that is
        mid-analysis has no groups or scores yet, so opening it shows an
        empty or half-built review. Clients gate navigation on this, and
        because it is server state a reload or the other frontend sees the
        same thing.

        A job stopped by an offline volume, a helper crash/stall, or a
        restart also sits in 'pending' but is NOT progressing — treating it
        as busy would lock the shoot indefinitely with no worker draining
        it. `error IS NULL` excludes those, and `stopped_reason` reports
        them instead, so the clients can offer a resume rather than
        pretending the shoot was never analyzed.
        """
        c = conn()
        try:
            return [
                dict(r) for r in c.execute(
                    "SELECT s.*, COUNT(p.id) AS photo_count, "
                    "(SELECT MAX(id) FROM selection WHERE shoot_id = s.id) "
                    "  AS latest_selection_id, "
                    "(SELECT COUNT(*) FROM photo p2 "
                    " JOIN analysis a ON a.photo_id = p2.id "
                    " WHERE p2.shoot_id = s.id) AS analyzed_count, "
                    "(SELECT MAX(id) FROM job WHERE shoot_id = s.id "
                    " AND state IN ('pending','running') "
                    " AND error IS NULL) AS busy_job_id, "
                    "(SELECT error FROM job WHERE shoot_id = s.id "
                    " AND kind = 'analyze' AND state = 'pending' "
                    " AND error IS NOT NULL "
                    " ORDER BY id DESC LIMIT 1) AS stopped_reason "
                    "FROM shoot s "
                    "LEFT JOIN photo p ON p.shoot_id = s.id GROUP BY s.id")
            ]
        finally:
            c.close()

    # -- photos ----------------------------------------------------------------

    @app.get("/api/photos/{photo_id}")
    def photo_detail(photo_id: int):
        """The evidence-bearing payload the review UI is built on
        (design 10 §3). null components mean not-applicable/abstained and
        must render as "—", never a zero bar."""
        c = conn()
        try:
            p = c.execute("SELECT * FROM photo WHERE id = ?",
                          (photo_id,)).fetchone()
            if not p:
                raise error(404, "file_missing", f"No photo {photo_id}")
            out = {k: p[k] for k in p.keys()
                   if k not in ("mtime", "content_id")}
            out["missing"] = bool(p["missing"])

            a = c.execute("SELECT * FROM analysis WHERE photo_id = ?",
                          (photo_id,)).fetchone()
            out["analysis"] = None
            if a:
                frame = json.loads(a["frame"])
                frame.pop("sharpness_tiles", None)  # own endpoint below
                out["analysis"] = {
                    "decode_mode": a["decode_mode"],
                    "engine_version": a["engine_version"], "frame": frame}

            out["faces"] = [
                {"idx": f["idx"], "bbox": json.loads(f["bbox"]),
                 "yaw": f["yaw"], "capture_quality": f["capture_quality"],
                 "eyes": {"left": {"sharp_norm": f["eye_sharp_l"],
                                   "open": f["eye_open_l"]},
                          "right": {"sharp_norm": f["eye_sharp_r"],
                                    "open": f["eye_open_r"]}},
                 "eye_source": f["eye_source"]}
                for f in c.execute(
                    "SELECT * FROM face WHERE photo_id = ? ORDER BY idx",
                    (photo_id,))
            ]

            # Score rows for several profiles coexist (PK photo_id+profile,
            # design 01); serve the one matching the shoot's CURRENT
            # profile — an arbitrary row can be stale or the wrong genre.
            s = c.execute(
                "SELECT sc.* FROM score sc "
                "JOIN photo p ON p.id = sc.photo_id "
                "JOIN shoot sh ON sh.id = p.shoot_id "
                "WHERE sc.photo_id = ? AND sc.profile = sh.profile",
                (photo_id,)).fetchone()
            out["score"] = None
            if s:
                out["score"] = {
                    "profile": s["profile"], "total": s["total"],
                    "components": json.loads(s["components"]),
                    "flags": json.loads(s["flags"]),
                    "weights_hash": s["weights_hash"]}

            g = c.execute(
                'SELECT g.id, g.is_bracket, COUNT(gm2.photo_id) AS size '
                'FROM group_member gm JOIN "group" g ON g.id = gm.group_id '
                "JOIN group_member gm2 ON gm2.group_id = g.id "
                "WHERE gm.photo_id = ? AND g.level = 'shot' GROUP BY g.id",
                (photo_id,)).fetchone()
            out["group"] = ({"shot_id": g["id"], "size": g["size"],
                             "is_bracket": bool(g["is_bracket"])}
                            if g else None)

            e = c.execute(
                "SELECT se.* FROM selection_entry se "
                "JOIN selection s ON s.id = se.selection_id "
                "WHERE se.photo_id = ? "
                "ORDER BY s.created_at DESC, s.id DESC LIMIT 1",
                (photo_id,)).fetchone()
            out["selection"] = (
                {"state": e["state"], "rank": e["rank"],
                 "reason": e["reason"],
                 "user_override": bool(e["user_override"])}
                if e else None)
            return out
        finally:
            c.close()

    def _photo_abs_path(c, photo_id: int) -> tuple[Path, str]:
        row = c.execute(
            "SELECT p.rel_path, p.content_id, l.root_path FROM photo p "
            "JOIN library l ON l.id = p.library_id WHERE p.id = ?",
            (photo_id,)).fetchone()
        if not row:
            raise error(404, "file_missing", f"No photo {photo_id}")
        path = Path(row["root_path"]) / row["rel_path"]
        if not path.is_file():
            raise error(404, "volume_offline",
                        f"File not reachable: {row['rel_path']}",
                        retryable=True)
        return path, row["content_id"]

    @app.get("/api/photos/{photo_id}/thumb")
    def thumbnail(photo_id: int, size: int = 1024):
        """Content-addressed cache (design 10 §4): key = content_id + size,
        so a cached thumbnail is never stale. Display decode path — never
        the measurement path."""
        if size not in (256, 1024, 2048):
            raise error(400, "invalid_size", "size must be 256|1024|2048")
        c = conn()
        try:
            src, content_id = _photo_abs_path(c, photo_id)
        finally:
            c.close()
        cached = app.state.cache_dir / f"{content_id}_{size}.jpg"
        if not cached.is_file():
            if not helper.helper_available():
                raise error(503, "decode_failed",
                            "Swift helper not built", retryable=True)
            try:
                helper.render(src, cached, size=size)
            except Exception as e:
                raise error(500, "decode_failed", str(e))
        return FileResponse(
            cached, media_type="image/jpeg",
            headers={"ETag": f'"{content_id}:{size}"',
                     "Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/api/photos/{photo_id}/eye-crop")
    def eye_crop(photo_id: int, face: int = 0, eye: str = "left"):
        """Full-res eye crop — the "prove the eye is sharp" view (design 10
        §4). Uncached and full resolution by design: downscaling it would
        defeat the purpose."""
        if eye not in ("left", "right"):
            raise error(400, "invalid_eye", "eye must be left|right")
        c = conn()
        try:
            src, content_id = _photo_abs_path(c, photo_id)
            f = c.execute(
                "SELECT bbox FROM face WHERE photo_id = ? AND idx = ?",
                (photo_id, face)).fetchone()
            if not f:
                raise error(404, "file_missing",
                            f"No face {face} on photo {photo_id}")
        finally:
            c.close()
        # M1: render the face region at full size via the display path; a
        # dedicated eye-crop helper command can tighten this later.
        out = app.state.cache_dir / f"eyecrop_{content_id}_{face}_{eye}.jpg"
        if not out.is_file():
            if not helper.helper_available():
                raise error(503, "decode_failed",
                            "Swift helper not built", retryable=True)
            try:
                helper.render(src, out, size=4096)
            except Exception as e:
                raise error(500, "decode_failed", str(e))
        return FileResponse(out, media_type="image/jpeg")

    @app.get("/api/photos/{photo_id}/sharpness-map")
    def sharpness_map(photo_id: int):
        c = conn()
        try:
            a = c.execute("SELECT frame FROM analysis WHERE photo_id = ?",
                          (photo_id,)).fetchone()
            if not a:
                raise error(404, "file_missing",
                            f"No analysis for photo {photo_id}")
            frame = json.loads(a["frame"])
            return {"tiles": frame.get("sharpness_tiles"),
                    "max": frame.get("sharpness_max"),
                    "mean": frame.get("sharpness_mean")}
        finally:
            c.close()

    @app.get("/api/shoots/{shoot_id}/photos")
    def shoot_photos(shoot_id: int, state: str | None = None,
                     cursor: int = 0, limit: int = 200):
        c = conn()
        try:
            rows = c.execute(
                "SELECT p.id, p.filename, p.captured_at, p.missing, "
                "s.total, se.state FROM photo p "
                "JOIN shoot sh ON sh.id = p.shoot_id "
                "LEFT JOIN score s ON s.photo_id = p.id "
                "AND s.profile = sh.profile "
                "LEFT JOIN selection_entry se ON se.photo_id = p.id "
                "AND se.selection_id = (SELECT MAX(id) FROM selection "
                "                       WHERE shoot_id = ?) "
                "WHERE p.shoot_id = ? AND p.id > ? "
                + ("AND se.state = ? " if state else "")
                + "ORDER BY p.id LIMIT ?",
                ([shoot_id, shoot_id, cursor]
                 + ([state] if state else []) + [limit]),
            ).fetchall()
            items = [dict(r) for r in rows]
            return {"items": items,
                    "next_cursor": items[-1]["id"] if len(items) == limit
                    else None}
        finally:
            c.close()

    # -- pipeline ---------------------------------------------------------------

    @app.post("/api/shoots/{shoot_id}/analyze")
    def start_analyze(shoot_id: int):
        c = conn()
        try:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM photo WHERE shoot_id = ? AND missing = 0 "
                "AND id NOT IN (SELECT photo_id FROM analysis)",
                (shoot_id,))]
            # A job stopped by a helper crash/stall, an offline drive, or a
            # restart stays 'pending' with `error` set. It's the same work,
            # already checkpointed per photo — resume it rather than 409ing.
            # Without this, "Analyze & cull" on an interrupted shoot is a
            # permanent conflict and the user has no way forward.
            stopped = c.execute(
                "SELECT id FROM job WHERE shoot_id = ? AND kind = 'analyze' "
                "AND state = 'pending' AND error IS NOT NULL "
                "ORDER BY id DESC LIMIT 1", (shoot_id,)).fetchone()
            if stopped:
                job_id = stopped["id"]
                with c:
                    c.execute("UPDATE job SET error = NULL WHERE id = ?",
                              (job_id,))
                ids = jobs.pending_items(c, job_id)
            else:
                try:
                    job_id = jobs.create_job(c, shoot_id, "analyze", ids)
                except jobs.JobConflict as e:
                    raise error(409, "job_conflict", str(e))
            chained = False
            if ids and app.state.runner:
                root = c.execute(
                    "SELECT l.root_path FROM shoot s "
                    "JOIN library l ON l.id = s.library_id "
                    "WHERE s.id = ?", (shoot_id,)).fetchone()["root_path"]
                app.state.runner.submit(job_id, Path(root))
            elif not ids:
                # Everything already analyzed: run the cheap derived steps
                # inline so "Analyze & cull" is one action either way.
                jobs.finish_job(c, job_id)
                pipeline.group_shoot(c, shoot_id)
                pipeline.score_shoot(c, shoot_id)
                pipeline.create_selection(c, shoot_id)
                chained = True
            return {"job_id": job_id, "total": len(ids),
                    "chained": chained}
        finally:
            c.close()

    @app.post("/api/shoots/{shoot_id}/group")
    def run_group(shoot_id: int):
        c = conn()
        try:
            n = pipeline.group_shoot(c, shoot_id)
            # Brackets may have changed → rescore (exposure suppression).
            pipeline.score_shoot(c, shoot_id)
            return {"shot_groups": n}
        finally:
            c.close()

    @app.post("/api/shoots/{shoot_id}/score")
    def run_score(shoot_id: int):
        c = conn()
        try:
            return {"scored": pipeline.score_shoot(c, shoot_id)}
        finally:
            c.close()

    @app.post("/api/shoots/{shoot_id}/select")
    def run_select(shoot_id: int, body: SelectIn | None = None):
        c = conn()
        try:
            params = {}
            if body and body.floor is not None:
                params["floor"] = body.floor
            sel = pipeline.create_selection(c, shoot_id, params)
            return {"selection_id": sel}
        finally:
            c.close()

    @app.get("/api/shoots/{shoot_id}/groups")
    def groups(shoot_id: int):
        c = conn()
        try:
            out = []
            for g in c.execute(
                'SELECT * FROM "group" WHERE shoot_id = ? AND level = ?',
                (shoot_id, "shot"),
            ):
                members = [r["photo_id"] for r in c.execute(
                    "SELECT photo_id FROM group_member WHERE group_id = ?",
                    (g["id"],))]
                out.append({"id": g["id"], "level": g["level"],
                            "is_bracket": bool(g["is_bracket"]),
                            "photo_ids": members})
            return out
        finally:
            c.close()

    @app.get("/api/selections/{selection_id}")
    def selection(selection_id: int):
        c = conn()
        try:
            s = c.execute("SELECT * FROM selection WHERE id = ?",
                          (selection_id,)).fetchone()
            if not s:
                raise error(404, "file_missing",
                            f"No selection {selection_id}")
            entries = [dict(r) for r in c.execute(
                "SELECT photo_id, group_id, state, rank, reason, "
                "user_override FROM selection_entry "
                "WHERE selection_id = ? ORDER BY group_id, rank",
                (selection_id,))]
            return {"id": s["id"], "shoot_id": s["shoot_id"],
                    "created_at": s["created_at"],
                    "exported_at": s["exported_at"],
                    "params": json.loads(s["params"]), "entries": entries}
        finally:
            c.close()

    @app.patch("/api/selections/{selection_id}/entries/{photo_id}")
    def patch_entry(selection_id: int, photo_id: int, body: EntryPatch):
        c = conn()
        try:
            try:
                pipeline.override_entry(c, selection_id, photo_id, body.state)
            except ValueError as e:
                raise error(409, "selection_frozen", str(e)) \
                    if "frozen" in str(e) else error(400, "invalid_state",
                                                     str(e))
            return {"photo_id": photo_id, "state": body.state,
                    "user_override": True}
        finally:
            c.close()

    # -- export -------------------------------------------------------------

    def _export_entries(c, selection_id) -> list[tuple[Path, str]]:
        rows = c.execute(
            "SELECT se.state, p.rel_path, l.root_path "
            "FROM selection_entry se "
            "JOIN photo p ON p.id = se.photo_id "
            "JOIN library l ON l.id = p.library_id "
            "WHERE se.selection_id = ? AND se.state IN ('pick','alt')",
            (selection_id,)).fetchall()
        return [(Path(r["root_path"]) / r["rel_path"], r["state"])
                for r in rows]

    @app.post("/api/selections/{selection_id}/export/preview")
    def export_preview(selection_id: int):
        """Dry run (design 10 §2): the engine decides what's a conflict;
        clients only display."""
        c = conn()
        try:
            plan = xmp.plan_export(_export_entries(c, selection_id))
            return {
                "new_sidecars": len(plan.new_sidecars),
                "updates": len(plan.updates),
                "conflicts": [
                    {"path": d.path, "old_rating": d.old_rating,
                     "new_rating": d.new_rating,
                     "has_develop_settings": True}
                    for d in plan.conflicts],
                "skipped_dng": plan.skipped_dng,
                "unchanged": len(plan.unchanged),
                "backup_dir": str(app.state.backup_dir),
            }
        finally:
            c.close()

    @app.post("/api/selections/{selection_id}/export")
    def export(selection_id: int, body: ExportIn | None = None):
        c = conn()
        try:
            confirm = bool(body and body.confirm_overwrite)
            plan = xmp.plan_export(_export_entries(c, selection_id))
            if plan.conflicts and not confirm:
                raise error(
                    409, "sidecar_conflict",
                    f"{len(plan.conflicts)} sidecars have develop settings; "
                    "confirm_overwrite required",
                    detail={"conflicts": [d.path for d in plan.conflicts]})
            written = xmp.apply_export(plan, app.state.backup_dir,
                                       confirm_conflicts=confirm)
            with c:
                c.execute(
                    "UPDATE selection SET exported_at = datetime('now') "
                    "WHERE id = ?", (selection_id,))
            return {"written": len(written),
                    "skipped_dng": plan.skipped_dng,
                    "unchanged": len(plan.unchanged)}
        finally:
            c.close()

    # -- grouping corrections (design 05 §7) ----------------------------------

    @app.post("/api/groups/{group_id}/split")
    def split_group(group_id: int, body: SplitIn):
        c = conn()
        try:
            g = c.execute(
                'SELECT * FROM "group" WHERE id = ?', (group_id,)).fetchone()
            if not g:
                raise error(404, "file_missing", f"No group {group_id}")
            if g["is_bracket"]:
                raise error(409, "bracket_immutable",
                            "Bracket groups cannot be split")
            members = [r["photo_id"] for r in c.execute(
                "SELECT gm.photo_id FROM group_member gm "
                "JOIN photo p ON p.id = gm.photo_id "
                "WHERE gm.group_id = ? ORDER BY p.captured_at, p.subsec",
                (group_id,))]
            if body.at_photo_id not in members:
                raise error(400, "invalid_state",
                            "at_photo_id not in group")
            at = members.index(body.at_photo_id)
            if at == 0:
                return {"id": group_id, "new_group_id": None}
            tail = members[at:]
            with c:
                cur = c.execute(
                    'INSERT INTO "group" (shoot_id, level, is_bracket) '
                    "VALUES (?, ?, 0)", (g["shoot_id"], g["level"]))
                new_id = cur.lastrowid
                c.executemany(
                    "UPDATE group_member SET group_id = ? "
                    "WHERE group_id = ? AND photo_id = ?",
                    [(new_id, group_id, pid) for pid in tail])
            return {"id": group_id, "new_group_id": new_id}
        finally:
            c.close()

    @app.post("/api/groups/merge")
    def merge_groups(body: MergeIn):
        if len(body.group_ids) < 2:
            raise error(400, "invalid_state", "need >= 2 groups")
        c = conn()
        try:
            rows = c.execute(
                f'SELECT * FROM "group" WHERE id IN '
                f"({','.join('?' * len(body.group_ids))})",
                body.group_ids).fetchall()
            if len(rows) != len(body.group_ids):
                raise error(404, "file_missing", "group not found")
            if any(r["is_bracket"] for r in rows):
                raise error(409, "bracket_immutable",
                            "Bracket groups cannot be merged")
            target, *rest = body.group_ids
            with c:
                for gid in rest:
                    c.execute(
                        "UPDATE OR IGNORE group_member SET group_id = ? "
                        "WHERE group_id = ?", (target, gid))
                    c.execute('DELETE FROM "group" WHERE id = ?', (gid,))
            return {"id": target}
        finally:
            c.close()

    @app.post("/api/groups/{group_id}/move")
    def move_photo(group_id: int, body: MoveIn):
        c = conn()
        try:
            src = c.execute('SELECT * FROM "group" WHERE id = ?',
                            (group_id,)).fetchone()
            dst = c.execute('SELECT * FROM "group" WHERE id = ?',
                            (body.to_group_id,)).fetchone()
            if not src or not dst:
                raise error(404, "file_missing", "group not found")
            if src["is_bracket"] or dst["is_bracket"]:
                raise error(409, "bracket_immutable",
                            "Bracket groups cannot be modified")
            member = c.execute(
                "SELECT 1 FROM group_member WHERE group_id = ? "
                "AND photo_id = ?", (group_id, body.photo_id)).fetchone()
            if not member:
                raise error(400, "invalid_state", "photo not in group")
            with c:
                c.execute(
                    "UPDATE group_member SET group_id = ? "
                    "WHERE group_id = ? AND photo_id = ?",
                    (body.to_group_id, group_id, body.photo_id))
                # Empty groups vanish rather than lingering as clutter.
                left = c.execute(
                    "SELECT COUNT(*) AS n FROM group_member "
                    "WHERE group_id = ?", (group_id,)).fetchone()["n"]
                if left == 0:
                    c.execute('DELETE FROM "group" WHERE id = ?', (group_id,))
            return {"photo_id": body.photo_id,
                    "group_id": body.to_group_id,
                    "source_deleted": left == 0}
        finally:
            c.close()

    # -- jobs ---------------------------------------------------------------

    def _job_snapshot(c, last: dict[int, tuple]) -> list[str]:
        out = []
        active = c.execute(
            "SELECT id FROM job WHERE state IN ('pending','running') OR "
            "updated_at > datetime('now', '-10 seconds')").fetchall()
        for row in active:
            p = jobs.progress(c, row["id"])
            key = (p.state, p.completed, p.failed)
            if last.get(p.job_id) != key:
                last[p.job_id] = key
                out.append(json.dumps({
                    "job_id": p.job_id, "kind": p.kind, "state": p.state,
                    "total": p.total, "completed": p.completed,
                    "failed": p.failed}))
        return out

    @app.get("/api/jobs/stream")
    async def jobs_stream(once: bool = False):
        """SSE progress (design 09 §5): poll the jobs tables, emit on change.
        The checkpoint state IS the progress state, so no runner coupling.
        `once=true` emits the current snapshot and closes (polling clients,
        tests). Registered before /api/jobs/{job_id} or the int parser would
        shadow the path."""

        async def events():
            last: dict[int, tuple] = {}
            while True:
                c = conn()
                try:
                    for payload in _job_snapshot(c, last):
                        yield f"data: {payload}\n\n"
                finally:
                    c.close()
                if once:
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: int):
        c = conn()
        try:
            row = c.execute("SELECT id FROM job WHERE id = ?",
                            (job_id,)).fetchone()
            if not row:
                raise error(404, "file_missing", f"No job {job_id}")
            p = jobs.progress(c, job_id)
            return {"job_id": p.job_id, "kind": p.kind, "state": p.state,
                    "total": p.total, "completed": p.completed,
                    "failed": p.failed, "rate_per_sec": p.rate_per_sec,
                    "eta_sec": p.eta_sec}
        finally:
            c.close()

    @app.delete("/api/jobs/{job_id}")
    def cancel(job_id: int):
        c = conn()
        try:
            jobs.cancel_job(c, job_id)
            return {"job_id": job_id, "state": "cancelled"}
        finally:
            c.close()

    # -- static web UI ---------------------------------------------------------
    # The built Vite app is a static bundle; serving it here removes the
    # Node dependency at runtime (bundled-app mode). /api keeps priority —
    # routes are matched before the mount.
    if web_dist and Path(web_dist).is_dir():
        from fastapi.responses import RedirectResponse
        from fastapi.staticfiles import StaticFiles

        @app.get("/")
        def root_redirect():
            return RedirectResponse("/ui/")

        app.mount("/ui", StaticFiles(directory=str(web_dist), html=True),
                  name="ui")

    return app


def _default_web_dist() -> Path | None:
    """Locate a built web UI: bundled Resources first (relative to the
    embedded engine), then the repo checkout for development."""
    candidates = [
        Path(__file__).resolve().parents[2] / "web-dist",  # app bundle
        Path(__file__).resolve().parents[2] / "web" / "dist",  # repo
    ]
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


def main() -> None:
    """Entry point. 127.0.0.1 ONLY (design 10 §1 rule 4)."""
    import uvicorn

    app_dir = Path.home() / "Library" / "Application Support" / "Shootr"
    app_dir.mkdir(parents=True, exist_ok=True)
    db_path = app_dir / "shootr.db"

    # Startup recovery (design 09 §4): items claimed by a dead worker.
    c = db.connect(db_path)
    n = jobs.reset_stale_running(c)
    c.close()
    if n:
        print(f"reset {n} stale running items from a previous session")

    app = create_app(db_path, app_dir / "backups",
                     runner=JobRunner(db_path),
                     web_dist=_default_web_dist())
    uvicorn.run(app, host="127.0.0.1", port=8721)


if __name__ == "__main__":
    main()
