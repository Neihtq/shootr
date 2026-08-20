"""Score → group → select against real DB rows.

Bridges the pure modules (scoring, grouping, culling) and SQLite. Selection
regeneration semantics per design 06 §5: new params = new selection row;
exported selections are frozen; user overrides carry forward.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from datetime import datetime, timezone, datetime as _dt

from . import culling, flags, grouping, scoring


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Scoring pass


def _measurements_for(row: sqlite3.Row, faces: list[sqlite3.Row],
                      in_bracket: bool) -> scoring.Measurements:
    frame = json.loads(row["frame"]) if row["frame"] else {}
    saliency = json.loads(row["saliency"]) if row["saliency"] else None

    face_ms = []
    face_dicts = []
    for f in faces:
        bbox = json.loads(f["bbox"])
        face_ms.append(scoring.FaceMeasurement(
            idx=f["idx"], bbox=tuple(bbox), yaw=f["yaw"],
            capture_quality=f["capture_quality"],
            left=scoring.Eye(f["eye_sharp_l"], f["eye_open_l"]),
            right=scoring.Eye(f["eye_sharp_r"], f["eye_open_r"]),
            eye_source=f["eye_source"],
        ))
        face_dicts.append({"idx": f["idx"], "bbox": bbox, "yaw": f["yaw"]})

    sal_bbox = (saliency or {}).get("attention_bbox")
    m = scoring.Measurements(
        frame=scoring.FrameMeasurement(
            sharpness_max=frame.get("sharpness_max"),
            sharpness_mean=frame.get("sharpness_mean"),
            sharpness_tiles=frame.get("sharpness_tiles"),
            clipped_hi=frame.get("clipped_hi"),
            clipped_lo=frame.get("clipped_lo"),
            horizon_angle=frame.get("horizon_angle"),
        ),
        faces=face_ms,
        saliency_bbox=tuple(sal_bbox) if sal_bbox else None,
        in_bracket=in_bracket,
    )
    primary, _ = scoring.select_primary_subject(m)
    detected = flags.detect_flags(
        face_dicts, primary.idx if primary else None, sal_bbox,
        frame.get("horizon_angle"))
    return scoring.Measurements(
        frame=m.frame, faces=m.faces, saliency_bbox=m.saliency_bbox,
        composition_flags=detected, in_bracket=in_bracket)


def score_shoot(conn: sqlite3.Connection, shoot_id: int) -> int:
    """(Re)score every analyzed photo in the shoot. Cheap by design —
    profile changes cost only this (design 01)."""
    profile = conn.execute(
        "SELECT profile FROM shoot WHERE id = ?", (shoot_id,)
    ).fetchone()["profile"]

    bracket_ids = {
        r["photo_id"] for r in conn.execute(
            'SELECT gm.photo_id FROM group_member gm '
            'JOIN "group" g ON g.id = gm.group_id '
            'WHERE g.shoot_id = ? AND g.is_bracket = 1', (shoot_id,))
    }

    n = 0
    with conn:
        for row in conn.execute(
            "SELECT p.id, a.frame, a.saliency FROM photo p "
            "JOIN analysis a ON a.photo_id = p.id WHERE p.shoot_id = ?",
            (shoot_id,),
        ).fetchall():
            faces = conn.execute(
                "SELECT * FROM face WHERE photo_id = ? ORDER BY idx",
                (row["id"],),
            ).fetchall()
            m = _measurements_for(row, faces, row["id"] in bracket_ids)
            rec = scoring.score(m, profile)
            conn.execute(
                "INSERT OR REPLACE INTO score (photo_id, profile, total, "
                "components, flags, weights_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], profile, rec.total,
                 json.dumps(rec.components), json.dumps(rec.flags),
                 rec.weights_hash),
            )
            n += 1
    return n


# ---------------------------------------------------------------------------
# Grouping pass


def group_shoot(conn: sqlite3.Connection, shoot_id: int) -> int:
    """Rebuild scene/shot groups from analysis rows. Person/pose levels come
    later (faceprints not yet extracted end-to-end)."""
    profile = conn.execute(
        "SELECT profile FROM shoot WHERE id = ?", (shoot_id,)
    ).fetchone()["profile"]

    photos = []
    for row in conn.execute(
        "SELECT p.id, p.captured_at, p.subsec, p.exposure_bias, "
        "(SELECT COUNT(*) FROM face f WHERE f.photo_id = p.id) AS n_faces, "
        "e.vec, e.dim FROM photo p "
        "LEFT JOIN embedding e ON e.photo_id = p.id AND e.kind = 'scene' "
        "WHERE p.shoot_id = ? AND p.captured_at IS NOT NULL "
        "ORDER BY p.captured_at, p.subsec",
        (shoot_id,),
    ).fetchall():
        emb = None
        if row["vec"] is not None and row["dim"]:
            emb = struct.unpack(f'{row["dim"]}f', row["vec"])
        photos.append(grouping.PhotoFeatures(
            photo_id=row["id"],
            captured_at=_dt.fromisoformat(row["captured_at"]),
            subsec=row["subsec"] or 0,
            exposure_bias=row["exposure_bias"] or 0.0,
            embedding=emb,
            face_count=row["n_faces"],
        ))

    shots = grouping.group_shots(photos, profile=profile)
    scenes = grouping.group_scenes(photos)

    with conn:
        conn.execute('DELETE FROM "group" WHERE shoot_id = ?', (shoot_id,))
        for level, groups in (("scene", scenes), ("shot", shots)):
            for g in groups:
                cur = conn.execute(
                    'INSERT INTO "group" (shoot_id, level, is_bracket) '
                    "VALUES (?, ?, ?)",
                    (shoot_id, level, int(g.is_bracket)),
                )
                conn.executemany(
                    "INSERT INTO group_member (group_id, photo_id) "
                    "VALUES (?, ?)",
                    [(cur.lastrowid, pid) for pid in g.member_ids],
                )
    return len(shots)


# ---------------------------------------------------------------------------
# Selection pass


def create_selection(conn: sqlite3.Connection, shoot_id: int,
                     params: dict | None = None) -> int:
    """New selection over current scores/groups. Carries forward user
    overrides from the latest prior selection (design 06 §4) — regeneration
    must preserve every overridden entry."""
    params = params or {}
    profile = conn.execute(
        "SELECT profile FROM shoot WHERE id = ?", (shoot_id,)
    ).fetchone()["profile"]
    floor = params.get("floor", culling.DEFAULT_QUALITY_FLOOR)

    overrides: dict[int, str] = {}
    prior = conn.execute(
        "SELECT id FROM selection WHERE shoot_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1", (shoot_id,)
    ).fetchone()
    if prior:
        overrides = {
            r["photo_id"]: r["state"] for r in conn.execute(
                "SELECT photo_id, state FROM selection_entry "
                "WHERE selection_id = ? AND user_override = 1", (prior["id"],))
        }

    groups = []
    for g in conn.execute(
        'SELECT id, is_bracket FROM "group" '
        "WHERE shoot_id = ? AND level = 'shot'", (shoot_id,)
    ).fetchall():
        members = []
        for r in conn.execute(
            "SELECT gm.photo_id, s.total, s.components, s.flags, "
            "e.vec, e.dim FROM group_member gm "
            "JOIN score s ON s.photo_id = gm.photo_id AND s.profile = ? "
            "LEFT JOIN embedding e ON e.photo_id = gm.photo_id "
            "  AND e.kind = 'scene' "
            "WHERE gm.group_id = ?",
            (profile, g["id"]),
        ).fetchall():
            comps = json.loads(r["components"])
            emb = None
            if r["vec"] is not None and r["dim"]:
                emb = tuple(struct.unpack(f'{r["dim"]}f', r["vec"]))
            # The group-photo signal (design 06 §2.2): frames where fewer
            # non-primary subjects blink win ties in group shots.
            blinking = 0
            for flag in json.loads(r["flags"]):
                if flag.startswith("other_subject_blinking:"):
                    blinking = int(flag.split(":")[1])
            members.append(culling.CullCandidate(
                photo_id=r["photo_id"], total=r["total"], embedding=emb,
                eye_focus=(comps.get("eye_focus") or {}).get("value"),
                eyes_open=(comps.get("eyes_open") or {}).get("value"),
                other_subjects_blinking=blinking,
            ))
        if members:
            groups.append(culling.CullGroup(
                g["id"], members, is_bracket=bool(g["is_bracket"])))

    proposal = culling.cull(groups, profile, floor=floor, overrides=overrides)

    with conn:
        cur = conn.execute(
            "INSERT INTO selection (shoot_id, created_at, params) "
            "VALUES (?, ?, ?)",
            (shoot_id, _now(), json.dumps({**params, "profile": profile})),
        )
        sel_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO selection_entry (selection_id, photo_id, group_id, "
            "state, rank, reason, user_override) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(sel_id, e.photo_id, e.group_id, e.state, e.rank, e.reason,
              int(e.photo_id in overrides))
             for e in proposal.entries],
        )
    return sel_id


def override_entry(conn: sqlite3.Connection, selection_id: int,
                   photo_id: int, state: str) -> None:
    """User disagrees with the engine → user_override=1, sacred thereafter.
    Frozen (exported) selections reject changes: they correspond to state on
    disk (design 06 §5)."""
    if state not in ("pick", "alt", "reject"):
        raise ValueError(f"invalid state: {state!r}")
    frozen = conn.execute(
        "SELECT exported_at FROM selection WHERE id = ?", (selection_id,)
    ).fetchone()
    if frozen and frozen["exported_at"]:
        raise ValueError("selection is frozen (already exported); regenerate")
    with conn:
        conn.execute(
            "UPDATE selection_entry SET state = ?, user_override = 1, "
            "reason = 'user override' "
            "WHERE selection_id = ? AND photo_id = ?",
            (state, selection_id, photo_id),
        )
