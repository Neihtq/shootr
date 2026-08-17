"""Ingest & library scanning (docs/design/02-ingest.md).

discover → fast-path filter → identify → probe metadata → upsert

Ingest is READ-ONLY against the library (design 02 §1): the only writes to
user directories happen in the Lightroom export path, explicitly. Absence is
never destructive — a missing file sets ``missing=1``, nothing else.

The metadata probe is pluggable: M1 uses the Swift helper's ``probe`` command
(design 02 §2 stage 4); tests inject a fake. Ingest itself never decodes
pixels.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from blake3 import blake3

log = logging.getLogger("shootr.ingest")

RAW_EXTENSIONS = {"cr2", "cr3", "arw", "raf", "nef", "dng"}
IMAGE_EXTENSIONS = RAW_EXTENSIONS | {"jpg", "jpeg", "heic", "tif", "tiff"}
SIDECAR_EXTENSION = "xmp"

# Directory names that are never photo sources (design 02 §2 stage 1).
SKIP_DIRS = {"@eaDir", ".Trashes", "Lightroom Settings"}
SKIP_DIR_SUFFIXES = ("_previews.lrdata",)

_CHUNK = 64 * 1024  # head/tail read size for content identity


# ---------------------------------------------------------------------------
# Stage 1 — Discover


@dataclass(frozen=True)
class DiscoveredFile:
    rel_path: str
    abs_path: Path
    size: int
    mtime: float

    @property
    def ext(self) -> str:
        return self.abs_path.suffix.lstrip(".").lower()

    @property
    def basename(self) -> str:
        return self.abs_path.stem

    @property
    def directory(self) -> str:
        return str(Path(self.rel_path).parent)


def discover(root: Path) -> Iterator[DiscoveredFile]:
    """os.scandir recursion — stat comes free with the directory entry
    (design 02 §2 stage 1). One unreadable directory must not abort the walk."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = os.scandir(current)
        except OSError:
            continue
        with entries:
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if name in SKIP_DIRS or name.endswith(SKIP_DIR_SUFFIXES):
                        continue
                    if ".lrcat" in name:
                        continue
                    stack.append(Path(entry.path))
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in IMAGE_EXTENSIONS and ext != SIDECAR_EXTENSION:
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                yield DiscoveredFile(
                    rel_path=str(Path(entry.path).relative_to(root)),
                    abs_path=Path(entry.path),
                    size=st.st_size,
                    mtime=st.st_mtime,
                )


# ---------------------------------------------------------------------------
# Stage 3 — Identify


def content_id(path: Path, size: int) -> str:
    """blake3(size ‖ first 64KB ‖ last 64KB) — design 01 §2. Two 64 KB reads
    instead of a 60 MB read; ~500× less I/O over an external bus."""
    h = blake3(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(_CHUNK))
        if size > _CHUNK:
            f.seek(max(_CHUNK, size - _CHUNK))
            h.update(f.read(_CHUNK))
    return h.hexdigest()


def full_hash(path: Path) -> str:
    """Escalation path for content_id collisions (design 01 §2)."""
    h = blake3()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Stage 4 — Probe (pluggable; Swift helper in production)

# Maps probe-JSON keys → photo columns. A probe returns any subset.
PROBE_FIELDS = (
    "captured_at", "subsec", "camera_model", "lens_model", "iso", "shutter",
    "aperture", "focal_length", "exposure_bias", "orientation",
    "width", "height",
)

Prober = Callable[[Path], dict | None]


def null_prober(path: Path) -> dict | None:
    """Probe-less fallback: rows get NULL metadata, flagged by analysis later
    (design 02 §5 corrupt-RAW row). Real prober = Swift helper `probe`."""
    return {}


# ---------------------------------------------------------------------------
# Pairing (design 02 §3) — directory-scoped basename grouping


@dataclass
class PhotoCandidate:
    primary: DiscoveredFile
    jpeg_sibling: str | None = None
    sidecar_path: str | None = None


def pair_files(files: list[DiscoveredFile]) -> list[PhotoCandidate]:
    """RAW primary; JPEG with a RAW sibling becomes a rendition; lone JPEG is
    its own Photo. Same basename in two directories = two captures."""
    by_key: dict[tuple[str, str], list[DiscoveredFile]] = {}
    for f in files:
        by_key.setdefault((f.directory, f.basename), []).append(f)

    candidates: list[PhotoCandidate] = []
    for group in by_key.values():
        raws = [f for f in group if f.ext in RAW_EXTENSIONS]
        jpegs = [f for f in group if f.ext in ("jpg", "jpeg", "heic", "tif", "tiff")]
        sidecars = [f for f in group if f.ext == SIDECAR_EXTENSION]
        sidecar = sidecars[0].rel_path if sidecars else None

        if raws:
            candidates.append(PhotoCandidate(
                primary=raws[0],
                jpeg_sibling=jpegs[0].rel_path if jpegs else None,
                sidecar_path=sidecar,
            ))
            # Extra RAWs sharing a basename (shouldn't happen) each stand alone.
            candidates.extend(PhotoCandidate(primary=r) for r in raws[1:])
        elif jpegs:
            candidates.append(PhotoCandidate(primary=jpegs[0], sidecar_path=sidecar))
        # Orphan sidecars are ignored: nothing to attach to.
    return candidates


# ---------------------------------------------------------------------------
# Stage 2 + 5 — scan (fast-path filter, identify, probe, upsert)


@dataclass
class ScanResult:
    added: int = 0
    updated_path: int = 0  # moved files — analysis kept (the identity payoff)
    invalidated: int = 0  # modified in place — analysis dropped
    unchanged: int = 0  # fast-path skips
    duplicates: int = 0  # same content elsewhere; not re-added
    errors: list[tuple[str, str]] = field(default_factory=list)


def scan(conn: sqlite3.Connection, library_id: int, root: Path,
         prober: Prober = null_prober, batch_size: int = 500) -> ScanResult:
    """Incremental, idempotent scan. Commits in batches so a mid-run unplug
    keeps completed rows valid (design 02 §5)."""
    result = ScanResult()

    known: dict[str, tuple[float, int, int]] = {}  # rel_path → (mtime, size, id)
    by_content: dict[str, int] = {}
    for row in conn.execute(
        "SELECT id, rel_path, mtime, file_size, content_id FROM photo "
        "WHERE library_id = ?", (library_id,)
    ):
        known[row["rel_path"]] = (row["mtime"], row["file_size"], row["id"])
        by_content[row["content_id"]] = row["id"]

    all_files = []
    seen_paths: set[str] = set()
    for f in discover(root):
        seen_paths.add(f.rel_path)
        # Fast-path filter (design 02 §2 stage 2): unchanged → no read at all.
        prev = known.get(f.rel_path)
        if prev and prev[0] == f.mtime and prev[1] == f.size:
            result.unchanged += 1
            continue
        all_files.append(f)

    pending = 0
    for cand in pair_files(all_files):
        f = cand.primary
        try:
            cid = content_id(f.abs_path, f.size)
        except OSError as e:
            result.errors.append((f.rel_path, str(e)))
            continue

        prev = known.get(f.rel_path)
        existing_id = by_content.get(cid)

        if existing_id is not None and (prev is None or prev[2] != existing_id):
            # Same content, new/different path: moved file or duplicate.
            row = conn.execute(
                "SELECT rel_path, file_size FROM photo WHERE id = ?",
                (existing_id,)).fetchone()
            old_path = row["rel_path"]
            # Collision check (design 01 §2): same content_id but different
            # size cannot be the same capture — head/tail hash collided.
            # Escalate to full-file hash and log loudly; silent wrongness
            # here would be severe.
            if row["file_size"] != f.size or (
                (root / old_path).is_file()
                and old_path != f.rel_path
                and full_hash(root / old_path) != full_hash(f.abs_path)
            ):
                log.error(
                    "content_id collision: %s vs %s share %s but differ in "
                    "full hash — treating as distinct photos",
                    old_path, f.rel_path, cid[:16])
                existing_id = None  # not the same capture after all
                cid = full_hash(f.abs_path)  # store the unambiguous id

        if existing_id is not None and (prev is None or prev[2] != existing_id):
            old_path = conn.execute(
                "SELECT rel_path FROM photo WHERE id = ?",
                (existing_id,)).fetchone()["rel_path"]
            if old_path in seen_paths and old_path != f.rel_path:
                # Original still present → duplicate. One Photo per capture:
                # analyzing it twice pollutes grouping (design 02 §2 stage 3).
                result.duplicates += 1
                continue
            conn.execute(
                "UPDATE photo SET rel_path = ?, filename = ?, mtime = ? "
                "WHERE id = ?",
                (f.rel_path, f.abs_path.name, f.mtime, existing_id),
            )
            result.updated_path += 1
        elif prev is not None:
            # Same path, changed bytes → modified: invalidate analysis.
            photo_id = prev[2]
            conn.execute("DELETE FROM analysis WHERE photo_id = ?", (photo_id,))
            conn.execute(
                "UPDATE photo SET content_id = ?, file_size = ?, mtime = ?, "
                "jpeg_sibling = ?, sidecar_path = ?, missing = 0 WHERE id = ?",
                (cid, f.size, f.mtime, cand.jpeg_sibling, cand.sidecar_path,
                 photo_id),
            )
            by_content[cid] = photo_id
            result.invalidated += 1
        else:
            meta = _safe_probe(prober, f, result)
            cols = {
                "library_id": library_id,
                "content_id": cid,
                "rel_path": f.rel_path,
                "filename": f.abs_path.name,
                "raw_format": f.ext.upper(),
                "file_size": f.size,
                "mtime": f.mtime,
                "jpeg_sibling": cand.jpeg_sibling,
                "sidecar_path": cand.sidecar_path,
                **{k: meta.get(k) for k in PROBE_FIELDS},
            }
            names = ", ".join(cols)
            marks = ", ".join("?" for _ in cols)
            cur = conn.execute(
                f"INSERT INTO photo ({names}) VALUES ({marks})",
                tuple(cols.values()),
            )
            by_content[cid] = cur.lastrowid
            result.added += 1

        pending += 1
        if pending >= batch_size:
            conn.commit()
            pending = 0

    # Files gone from disk: mark missing, never delete (design 02 §5).
    for rel_path, (_, _, photo_id) in known.items():
        if rel_path not in seen_paths:
            conn.execute("UPDATE photo SET missing = 1 WHERE id = ?", (photo_id,))
        else:
            conn.execute(
                "UPDATE photo SET missing = 0 WHERE id = ? AND missing = 1",
                (photo_id,),
            )
    conn.commit()
    return result


def _safe_probe(prober: Prober, f: DiscoveredFile, result: ScanResult) -> dict:
    """Probe failure = corrupt RAW: row created with NULL metadata, flagged,
    scan continues (design 02 §5)."""
    try:
        return prober(f.abs_path) or {}
    except Exception as e:  # noqa: BLE001 — one bad file must not abort 10k
        result.errors.append((f.rel_path, f"probe: {e}"))
        return {}


# ---------------------------------------------------------------------------
# Shoot proposals (design 02 §4)


@dataclass(frozen=True)
class ShootProposal:
    photo_ids: tuple[int, ...]
    start: str | None
    end: str | None
    directories: tuple[str, ...]


def propose_shoots(conn: sqlite3.Connection, library_id: int) -> list[ShootProposal]:
    """One proposal per folder — the folder IS the shoot.

    Photographers who organize by folder (the common case, confirmed by the
    user) mean one session per folder; second-guessing that with capture-time
    gaps splits all-day or multi-day shoots that belong together.

    Rule: photos directly in the library root → the whole library is one
    proposal (the user pointed at a single shoot folder, nested subfolders
    included). Otherwise → one proposal per top-level subfolder (the user
    pointed at an archive of shoot folders).

    Proposals only; the user confirms, combines, and picks the profile.
    Photos without EXIF dates are included — folder membership doesn't need
    a timestamp.
    """
    rows = conn.execute(
        "SELECT id, captured_at, rel_path FROM photo "
        "WHERE library_id = ? AND shoot_id IS NULL "
        "ORDER BY captured_at IS NULL, captured_at, subsec, rel_path",
        (library_id,),
    ).fetchall()
    if not rows:
        return []

    def top_level(rel_path: str) -> str:
        parts = Path(rel_path).parts
        return parts[0] if len(parts) > 1 else "."

    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(top_level(r["rel_path"]), []).append(r)

    # Loose photos at the root mean the root itself is the shoot.
    if "." in groups:
        groups = {".": rows}

    proposals: list[ShootProposal] = []
    for key in sorted(groups):
        seg = groups[key]
        dated = [r["captured_at"] for r in seg if r["captured_at"]]
        proposals.append(ShootProposal(
            photo_ids=tuple(r["id"] for r in seg),
            start=min(dated) if dated else None,
            end=max(dated) if dated else None,
            directories=tuple(sorted({str(Path(r["rel_path"]).parent)
                                      for r in seg})),
        ))
    return proposals
