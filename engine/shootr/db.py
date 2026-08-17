"""SQLite storage. Single writer: only the engine mutates the DB (design 01).

Forward-only numbered migrations (design 01 §5). ``analysis.engine_version``
is deliberately separate from schema version: an algorithm change invalidates
measurements without a schema migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Migration 1 — full schema per docs/design/01-domain-model.md §3.
_MIGRATION_1 = """
CREATE TABLE library (
  id           INTEGER PRIMARY KEY,
  root_path    TEXT NOT NULL,
  volume_uuid  TEXT,
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
  rel_path      TEXT NOT NULL,
  filename      TEXT NOT NULL,
  raw_format    TEXT,
  file_size     INTEGER NOT NULL,
  mtime         REAL NOT NULL,
  captured_at   TEXT,
  subsec        INTEGER,
  camera_model  TEXT,
  lens_model    TEXT,
  iso           INTEGER,
  shutter       REAL,
  aperture      REAL,
  focal_length  REAL,
  exposure_bias REAL,
  orientation   INTEGER,
  width         INTEGER,
  height        INTEGER,
  jpeg_sibling  TEXT,
  sidecar_path  TEXT,
  missing       INTEGER NOT NULL DEFAULT 0,
  UNIQUE (library_id, content_id)
);
CREATE INDEX photo_shoot_time ON photo(shoot_id, captured_at, subsec);
CREATE INDEX photo_content    ON photo(content_id);

CREATE TABLE analysis (
  photo_id       INTEGER PRIMARY KEY REFERENCES photo(id) ON DELETE CASCADE,
  engine_version TEXT NOT NULL,
  decode_mode    TEXT NOT NULL,
  frame          TEXT NOT NULL,
  saliency       TEXT,
  analyzed_at    TEXT NOT NULL
);

CREATE TABLE person (
  id        INTEGER PRIMARY KEY,
  shoot_id  INTEGER REFERENCES shoot(id) ON DELETE CASCADE,
  label     TEXT
);

CREATE TABLE face (
  id             INTEGER PRIMARY KEY,
  photo_id       INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  idx            INTEGER NOT NULL,
  bbox           TEXT NOT NULL,
  roll           REAL, yaw REAL, pitch REAL,
  capture_quality REAL,
  eye_sharp_l    REAL, eye_sharp_r REAL,
  eye_open_l     REAL, eye_open_r REAL,
  eye_source     TEXT,
  landmarks      TEXT,
  faceprint      BLOB,
  person_id      INTEGER REFERENCES person(id) ON DELETE SET NULL,
  UNIQUE (photo_id, idx)
);
CREATE INDEX face_photo ON face(photo_id);

CREATE TABLE embedding (
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL,
  vec      BLOB NOT NULL,
  dim      INTEGER NOT NULL,
  PRIMARY KEY (photo_id, kind)
);

CREATE TABLE score (
  photo_id     INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  profile      TEXT NOT NULL,
  total        REAL NOT NULL,
  components   TEXT NOT NULL,
  flags        TEXT NOT NULL,
  weights_hash TEXT NOT NULL,
  PRIMARY KEY (photo_id, profile)
);

CREATE TABLE "group" (
  id         INTEGER PRIMARY KEY,
  shoot_id   INTEGER NOT NULL REFERENCES shoot(id) ON DELETE CASCADE,
  level      TEXT NOT NULL CHECK (level IN ('scene','shot','pose','person')),
  parent_id  INTEGER REFERENCES "group"(id) ON DELETE CASCADE,
  is_bracket INTEGER NOT NULL DEFAULT 0,
  label      TEXT
);

CREATE TABLE group_member (
  group_id INTEGER NOT NULL REFERENCES "group"(id) ON DELETE CASCADE,
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  PRIMARY KEY (group_id, photo_id)
);

CREATE TABLE selection (
  id          INTEGER PRIMARY KEY,
  shoot_id    INTEGER NOT NULL REFERENCES shoot(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,
  params      TEXT NOT NULL,
  exported_at TEXT
);

CREATE TABLE selection_entry (
  selection_id INTEGER NOT NULL REFERENCES selection(id) ON DELETE CASCADE,
  photo_id     INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  group_id     INTEGER REFERENCES "group"(id) ON DELETE SET NULL,
  state        TEXT NOT NULL CHECK (state IN ('pick','alt','reject')),
  rank         INTEGER,
  reason       TEXT,
  user_override INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (selection_id, photo_id)
);

CREATE TABLE lr_history (
  photo_id    INTEGER PRIMARY KEY REFERENCES photo(id) ON DELETE CASCADE,
  pick_flag   INTEGER,
  rating      INTEGER,
  color_label TEXT,
  develop     TEXT
);

CREATE TABLE edit_prediction (
  id          INTEGER PRIMARY KEY,
  photo_id    INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  look_family TEXT,
  params      TEXT NOT NULL,
  model_kind  TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  applied_at  TEXT
);

CREATE TABLE job (
  id          INTEGER PRIMARY KEY,
  shoot_id    INTEGER REFERENCES shoot(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  state       TEXT NOT NULL CHECK (state IN
                ('pending','running','done','failed','cancelled')),
  total       INTEGER,
  completed   INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE job_item (
  job_id   INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  photo_id INTEGER NOT NULL REFERENCES photo(id) ON DELETE CASCADE,
  state    TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  error    TEXT,
  PRIMARY KEY (job_id, photo_id)
);
CREATE INDEX job_item_pending ON job_item(job_id, state);
"""

MIGRATIONS: list[str] = [_MIGRATION_1]


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the engine DB and apply pending migrations."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    _migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    current = schema_version(conn)
    for number, sql in enumerate(MIGRATIONS, start=1):
        if number <= current:
            continue
        with conn:  # one transaction per migration
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) "
                "VALUES (?, datetime('now'))",
                (number,),
            )
