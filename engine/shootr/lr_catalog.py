"""Lightroom Classic catalog reader — M2 ground truth (design 07 §2).

Reads a **copy** of the user's `.lrcat` and imports pick/rating/label and
develop-XMP into `lr_history`. The live catalog is never opened: the schema
is undocumented, LrC holds locks, and rule 1 (README) exists because getting
this wrong corrupts years of work.

Defensive stance (07 §2 — the schema is not a contract):
- refuse to copy while LrC is running (a mid-write copy can be torn);
- probe `Adobe_variablesTable` for the version and record it;
- validate expected tables/columns BEFORE querying; on mismatch raise
  `CatalogInvalid` so the caller degrades to sidecar-only, never guesses;
- every extraction is best-effort with a reported coverage number;
- match catalog rows to `photo` rows by filename + capture time
  (+ file size when the catalog carries it — often it doesn't), never by
  path: paths differ across machines and mounts. Unmatched and ambiguous
  rows are counted, not silently dropped.

Develop settings: 07 §2 guessed the `Adobe_AdditionalMetadata.xmp` blob
(4-byte length prefix + zlib) would be the tractable source. Measured on a
real LrC 15 catalog (2026-08-30): the blob carries `crs:` on 1 of 560
edited photos — LrC only serializes develop into it on explicit
save-to-XMP. `Adobe_imageDevelopSettings.text` (a serialized Lua table)
had every edit. So: parse the Lua text for **global scalar params** (nested
tables are local adjustments and curves — out of style scope per README),
fall back to `crs:` attributes from the blob, store JSON in
`lr_history.develop`.

WAL note, measured on a real LrC 15 catalog: plain `mode=ro` fails on a
WAL-journal catalog (SQLite needs the `-shm`); a quiesced copy opens with
`immutable=1`. If the copy came with a live `-wal`, we open it read-write
once — it is OUR private copy — so SQLite recovers the WAL, then lock the
connection with `PRAGMA query_only`.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "AgLibraryFile": {"id_local", "folder", "idx_filename", "extension"},
    "AgLibraryFolder": {"id_local", "rootFolder", "pathFromRoot"},
    "AgLibraryRootFolder": {"id_local", "absolutePath"},
    "Adobe_images": {"id_local", "rootFile", "pick", "rating",
                     "colorLabels", "captureTime"},
    "Adobe_variablesTable": {"name", "value"},
}
# Missing optional tables lose a field, not the import.
OPTIONAL_COLUMNS: dict[str, set[str]] = {
    "Adobe_AdditionalMetadata": {"image", "xmp"},
    "Adobe_imageDevelopSettings": {"image", "text"},
    "AgLibraryFileAssetMetadata": {"fileId", "fileSize"},
}

LRC_PROCESS_PATTERN = "Adobe Lightroom Classic"


class CatalogBusy(RuntimeError):
    """Lightroom Classic appears to be running — refuse to copy."""


class CatalogInvalid(RuntimeError):
    """Schema validation failed; degrade to sidecar-only (07 §2)."""

    def __init__(self, missing: dict[str, set[str]]):
        self.missing = missing
        super().__init__(f"catalog schema mismatch: {missing}")


def lrc_running() -> bool:
    res = subprocess.run(["pgrep", "-f", LRC_PROCESS_PATTERN],
                         capture_output=True)
    return res.returncode == 0


def copy_catalog(src: Path, dest_dir: Path, force: bool = False) -> Path:
    """Copy `.lrcat` (+ `-wal`/`-shm` siblings) into dest_dir.

    Refuses while LrC runs unless `force`: a copy taken mid-write can be
    torn, and the WAL siblings must be from the same instant as the main
    file to be coherent.
    """
    if not force and lrc_running():
        raise CatalogBusy(
            "Lightroom Classic is running; quit it (or pass force=True "
            "to copy anyway and accept a possibly-torn snapshot)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sib = src.with_name(src.name + suffix)
        if sib.exists():
            shutil.copy2(sib, dest.with_name(dest.name + suffix))
    return dest


def open_copy(path: Path) -> sqlite3.Connection:
    wal = path.with_name(path.name + "-wal")
    if wal.exists():
        # Our private copy: a brief writable open lets SQLite recover the
        # WAL into the main file; query_only then locks us read-only.
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA query_only = 1")
    else:
        conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class CatalogInfo:
    db_version: str | None
    missing: dict[str, set[str]]
    optional_missing: dict[str, set[str]]

    @property
    def valid(self) -> bool:
        return not self.missing


def probe(conn: sqlite3.Connection) -> CatalogInfo:
    def missing_of(spec: dict[str, set[str]]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for table, cols in spec.items():
            have = {r["name"] for r in
                    conn.execute(f'PRAGMA table_info("{table}")')}
            if not have:
                out[table] = cols
            elif cols - have:
                out[table] = cols - have
        return out

    missing = missing_of(REQUIRED_COLUMNS)
    version = None
    if "Adobe_variablesTable" not in missing:
        row = conn.execute(
            "SELECT value FROM Adobe_variablesTable "
            "WHERE name = 'Adobe_DBVersion'").fetchone()
        version = row["value"] if row else None
    return CatalogInfo(version, missing, missing_of(OPTIONAL_COLUMNS))


@dataclass
class LrRecord:
    filename: str
    folder_path: str
    capture_time: str | None  # ISO, catalog-local, may carry millis
    file_size: int | None
    pick: float | None
    rating: float | None
    color_label: str | None
    develop: dict | None  # global scalar params only


def _decode_xmp(blob) -> str | None:
    """4-byte big-endian length prefix + zlib stream; best-effort."""
    if not isinstance(blob, bytes) or len(blob) < 6:
        return None
    try:
        return zlib.decompress(blob[4:]).decode("utf-8", errors="replace")
    except zlib.error:
        return None


def _scalar(raw: str):
    raw = raw.strip().rstrip(",")
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return None


def parse_develop_lua(text: str | None) -> dict | None:
    """Global scalar params from `Adobe_imageDevelopSettings.text`.

    The value is a serialized Lua table (`s = { Key = value, ... }`).
    Only depth-1 `Key = scalar` lines are read; nested tables (masks,
    tone-curve point arrays, AI settings) are local/spatial and out of
    style-transfer scope (README rule; design 08).
    """
    if not text:
        return None
    out: dict = {}
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 1 and "=" in stripped and not stripped.endswith("{"):
            key, _, raw = stripped.partition("=")
            val = _scalar(raw)
            if val is not None and key.strip().isidentifier():
                out[key.strip()] = val
        depth += line.count("{") - line.count("}")
    return out or None


_CRS_ATTR = re.compile(r'crs:(\w+)="([^"]*)"')


def parse_develop_crs(xmp: str | None) -> dict | None:
    """`crs:` attribute values from a develop XMP packet (fallback source)."""
    if not xmp or "crs:" not in xmp:
        return None
    out = {}
    for key, raw in _CRS_ATTR.findall(xmp):
        val = _scalar(raw)
        out[key] = raw if val is None else val
    return out or None


def extract(conn: sqlite3.Connection, info: CatalogInfo | None = None
            ) -> Iterator[LrRecord]:
    info = info or probe(conn)
    if not info.valid:
        raise CatalogInvalid(info.missing)
    has_xmp = "Adobe_AdditionalMetadata" not in info.optional_missing
    has_dev = "Adobe_imageDevelopSettings" not in info.optional_missing
    has_size = "AgLibraryFileAssetMetadata" not in info.optional_missing

    sql = """
        SELECT lf.idx_filename AS filename,
               rf.absolutePath || f.pathFromRoot AS folder_path,
               i.captureTime AS capture_time,
               i.pick, i.rating, i.colorLabels AS color_label
               {xmp_col} {dev_col} {size_col}
        FROM AgLibraryFile lf
        JOIN AgLibraryFolder f ON f.id_local = lf.folder
        JOIN AgLibraryRootFolder rf ON rf.id_local = f.rootFolder
        JOIN Adobe_images i ON i.rootFile = lf.id_local
        {xmp_join} {dev_join} {size_join}
    """.format(
        xmp_col=", am.xmp AS xmp_blob" if has_xmp else ", NULL AS xmp_blob",
        dev_col=(", ds.text AS dev_text" if has_dev
                 else ", NULL AS dev_text"),
        size_col=(", fam.fileSize AS file_size" if has_size
                  else ", NULL AS file_size"),
        xmp_join=("LEFT JOIN Adobe_AdditionalMetadata am "
                  "ON am.image = i.id_local" if has_xmp else ""),
        dev_join=("LEFT JOIN Adobe_imageDevelopSettings ds "
                  "ON ds.image = i.id_local" if has_dev else ""),
        size_join=("LEFT JOIN AgLibraryFileAssetMetadata fam "
                   "ON fam.fileId = lf.id_local" if has_size else ""))
    for r in conn.execute(sql):
        develop = (parse_develop_lua(r["dev_text"])
                   or parse_develop_crs(_decode_xmp(r["xmp_blob"])))
        yield LrRecord(
            filename=r["filename"],
            folder_path=r["folder_path"],
            capture_time=r["capture_time"],
            file_size=r["file_size"],
            pick=r["pick"],
            rating=r["rating"],
            color_label=r["color_label"] or None,
            develop=develop)


@dataclass
class MatchReport:
    catalog_rows: int = 0
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    with_develop: int = 0
    db_version: str | None = None
    unmatched_samples: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.matched / self.catalog_rows if self.catalog_rows else 0.0


def _seconds(ts: str | None) -> str | None:
    return ts[:19] if ts else None  # strip millis for comparison


def import_history(app_conn: sqlite3.Connection, records: Iterator[LrRecord],
                   library_id: int | None = None) -> MatchReport:
    """Match records to photo rows and upsert lr_history.

    Filename first; capture time (to the second), then file size break
    ties. Ambiguity is reported, never guessed (07 §2).
    """
    scope = "WHERE library_id = ?" if library_id else ""
    args = (library_id,) if library_id else ()
    by_name: dict[str, list[sqlite3.Row]] = {}
    for row in app_conn.execute(
            f"SELECT id, filename, captured_at, file_size FROM photo {scope}",
            args):
        by_name.setdefault(row["filename"].lower(), []).append(row)

    report = MatchReport()
    rows = []
    for rec in records:
        report.catalog_rows += 1
        cands = by_name.get(rec.filename.lower(), [])
        if len(cands) > 1 and rec.capture_time:
            want = _seconds(rec.capture_time)
            cands = [c for c in cands
                     if _seconds(c["captured_at"]) == want] or cands
        if len(cands) > 1 and rec.file_size:
            cands = [c for c in cands
                     if c["file_size"] == rec.file_size] or cands
        if not cands:
            report.unmatched += 1
            if len(report.unmatched_samples) < 10:
                report.unmatched_samples.append(rec.filename)
            continue
        if len(cands) > 1:
            report.ambiguous += 1
            continue
        report.matched += 1
        if rec.develop:
            report.with_develop += 1
        rows.append((cands[0]["id"], rec.pick, rec.rating,
                     rec.color_label,
                     json.dumps(rec.develop) if rec.develop else None))
    with app_conn:
        app_conn.executemany(
            "INSERT OR REPLACE INTO lr_history "
            "(photo_id, pick_flag, rating, color_label, develop) "
            "VALUES (?, ?, ?, ?, ?)", rows)
    return report
