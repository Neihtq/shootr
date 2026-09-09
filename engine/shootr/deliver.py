"""Deliver the selects as FILES into a folder the user chooses (design 07 §3.2b).

For the workflow that has nothing to do with Lightroom: cull, then hand over a
folder of keepers. Three modes — hardlink (no disk cost), copy, move — planned
first and executed only on confirmation.

The safety properties are the design, not decoration:

- **Rejects are never touched.** Scope defaults to `pick` alone.
- **A move never risks the original.** Same volume: `os.replace`, atomic. Across
  volumes: copy, verify by size *and* content id, and only then unlink. A
  failure anywhere leaves the source where it was.
- **Nothing is overwritten.** A name collision gets a numbered suffix and is
  reported in the plan.
- **The library does not lie afterwards.** Moved inside the root, `rel_path` is
  updated and the photo keeps its analysis (identity is content-based, §02);
  moved outside, it is marked `missing=1` — non-destructive and honest.
- **Sidecars and JPEG siblings travel with the RAW**, or the ratings orphan and
  the pair the app deliberately tracks together gets split.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .ingest import content_id

MODES = ("hardlink", "copy", "move")
DEFAULT_STATES = ("pick",)


class DeliveryImpossible(RuntimeError):
    """The mode cannot work here — stated before anything is written."""


@dataclass
class DeliveryItem:
    photo_id: int
    source: Path
    dest: Path
    companions: list[tuple[Path, Path]] = field(default_factory=list)
    renamed: bool = False          # a name collision forced a suffix


@dataclass
class DeliveryPlan:
    mode: str
    dest_dir: Path
    items: list[DeliveryItem] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    missing_source: list[str] = field(default_factory=list)
    bytes_needed: int = 0
    cross_volume: bool = False
    free_bytes: int | None = None

    @property
    def enough_space(self) -> bool:
        if self.mode != "copy" or self.free_bytes is None:
            return True
        return self.free_bytes > self.bytes_needed


def _companions(photo: Path) -> list[Path]:
    """Files that must travel with the RAW: its sidecar and its JPEG sibling.

    Deduplicated by inode, not by name: macOS filesystems are case-insensitive
    by default, so `IMG_1.jpg` and `IMG_1.JPG` are the SAME file and a
    name-based probe would deliver it twice.
    """
    out: list[Path] = []
    seen: set[tuple[int, int]] = set()
    for ext in (".xmp", ".XMP", ".jpg", ".JPG", ".jpeg", ".JPEG"):
        cand = photo.with_suffix(ext)
        if not cand.is_file():
            continue
        st = cand.stat()
        key = (st.st_dev, st.st_ino)
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def plan(entries: list[tuple[int, Path, str]], dest_dir: Path, mode: str,
         states: tuple[str, ...] = DEFAULT_STATES) -> DeliveryPlan:
    """Dry run. `entries` = (photo_id, path, selection state)."""
    if mode not in MODES:
        raise DeliveryImpossible(f"unknown mode {mode!r}; have {MODES}")
    p = DeliveryPlan(mode=mode, dest_dir=dest_dir)

    chosen = [(pid, src) for pid, src, state in entries if state in states]
    # Volume check up front: hardlinks cannot cross devices, and a user should
    # learn that before selecting 900 files.
    probe = dest_dir if dest_dir.exists() else dest_dir.parent
    for _, src in chosen[:1]:
        try:
            p.cross_volume = (src.stat().st_dev != probe.stat().st_dev)
        except OSError:
            p.cross_volume = False
    if mode == "hardlink" and p.cross_volume:
        raise DeliveryImpossible(
            "hardlinks cannot cross volumes — the folder must be on the same "
            "drive as the photos. Use copy instead.")

    taken: set[str] = set()
    for pid, src in chosen:
        if not src.is_file():
            p.missing_source.append(str(src))
            continue
        target = dest_dir / src.name
        renamed = False
        if target.exists():
            if mode == "hardlink" and _same_file(src, target):
                p.already_present.append(src.name)
                continue
            stem, suffix, i = src.stem, src.suffix, 2
            while (dest_dir / f"{stem}_{i}{suffix}").exists() or \
                    f"{stem}_{i}{suffix}" in taken:
                i += 1
            target = dest_dir / f"{stem}_{i}{suffix}"
            renamed = True
        elif target.name in taken:
            stem, suffix, i = src.stem, src.suffix, 2
            while f"{stem}_{i}{suffix}" in taken:
                i += 1
            target = dest_dir / f"{stem}_{i}{suffix}"
            renamed = True
        taken.add(target.name)

        companions = [(c, target.with_suffix(c.suffix)) for c in _companions(src)]
        p.items.append(DeliveryItem(pid, src, target, companions, renamed))
        if mode == "copy":
            p.bytes_needed += src.stat().st_size + sum(
                c.stat().st_size for c, _ in companions)

    if mode == "copy":
        try:
            p.free_bytes = shutil.disk_usage(probe).free
        except OSError:
            p.free_bytes = None
    return p


def _same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino
    except OSError:
        return False


def _move_one(src: Path, dst: Path) -> None:
    """Move that never risks the original.

    Same volume: `os.replace` is atomic. Across volumes: copy, verify by size
    AND content id, unlink only then — so a failure at any point leaves the
    source exactly where it was.
    """
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass  # cross-device; fall through to verified copy
    shutil.copy2(src, dst)
    if dst.stat().st_size != src.stat().st_size or \
            content_id(dst, dst.stat().st_size) != \
            content_id(src, src.stat().st_size):
        dst.unlink(missing_ok=True)
        raise DeliveryImpossible(
            f"copy of {src.name} did not verify; original left untouched")
    src.unlink()


@dataclass
class DeliveryReport:
    mode: str
    delivered: list[int] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    companions: int = 0
    relinked: int = 0      # library rows whose path was updated
    marked_missing: int = 0


def execute(conn: sqlite3.Connection, p: DeliveryPlan,
            library_root: Path | None = None) -> DeliveryReport:
    """Run a plan. Per-file failures are collected, never fatal — one
    unreadable photo must not abandon the other 200."""
    if p.mode == "copy" and not p.enough_space:
        raise DeliveryImpossible(
            f"needs {p.bytes_needed / 1e9:.1f} GB, "
            f"{(p.free_bytes or 0) / 1e9:.1f} GB free")
    p.dest_dir.mkdir(parents=True, exist_ok=True)
    r = DeliveryReport(mode=p.mode)

    for item in p.items:
        try:
            for src, dst in [(item.source, item.dest), *item.companions]:
                if p.mode == "hardlink":
                    os.link(src, dst)
                elif p.mode == "copy":
                    shutil.copy2(src, dst)
                else:
                    _move_one(src, dst)
                if src != item.source:
                    r.companions += 1
        except (OSError, DeliveryImpossible) as e:
            r.failed.append((item.source.name, str(e)))
            continue
        r.delivered.append(item.photo_id)
        if item.renamed:
            r.renamed.append(item.dest.name)

        # Only a move changes where the photo lives, so only a move can leave
        # the library's paths wrong.
        if p.mode == "move":
            if library_root and _inside(item.dest, library_root):
                with conn:
                    conn.execute(
                        "UPDATE photo SET rel_path = ?, filename = ? "
                        "WHERE id = ?",
                        (str(item.dest.relative_to(library_root)),
                         item.dest.name, item.photo_id))
                r.relinked += 1
            else:
                with conn:
                    conn.execute("UPDATE photo SET missing = 1 WHERE id = ?",
                                 (item.photo_id,))
                r.marked_missing += 1
    return r


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
