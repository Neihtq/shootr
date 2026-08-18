"""XMP sidecar writeback (design 07 §1 Rule 2, §3).

The only module that writes into the user's directories. Protocol, every
time: read → diff → back up → (confirm upstream) → atomic write. Fields we
don't own are preserved by *editing the existing XML*, never regenerating
from a template — sidecars carry keywords, GPS, crop, local adjustments, and
third-party plugin data that a regeneration would silently destroy.

Selects mapping (design 06 §1): pick → xmp:Rating 3 + label; alt → Rating 2;
reject → NOTHING written by default.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Fields this app owns. Everything else in a sidecar is preserved verbatim.
OWNED = ("xmp:Rating", "xmp:Label")

RATING_RE = re.compile(r'xmp:Rating="(-?\d+)"')
LABEL_RE = re.compile(r'xmp:Label="([^"]*)"')
DESCRIPTION_TAG_RE = re.compile(r"<rdf:Description\b[^>]*>")
CRS_ATTR_RE = re.compile(r"\bcrs:\w+=")
CRS_TAG_RE = re.compile(r"<crs:\w+")

MINIMAL_SIDECAR = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="shootr">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


@dataclass(frozen=True)
class SidecarDiff:
    """What a write would change — the engine-computed diff behind the
    export/preview endpoint (design 10 §2)."""

    path: str
    exists: bool
    old_rating: int | None
    new_rating: int | None
    old_label: str | None
    new_label: str | None
    has_develop_settings: bool  # existing crs: values → explicit confirm

    @property
    def changes_anything(self) -> bool:
        return (self.old_rating != self.new_rating
                or self.old_label != self.new_label)


@dataclass
class ExportPlan:
    new_sidecars: list[SidecarDiff] = field(default_factory=list)
    updates: list[SidecarDiff] = field(default_factory=list)
    conflicts: list[SidecarDiff] = field(default_factory=list)  # crs: present
    skipped_dng: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


STATE_RATING = {"pick": 3, "alt": 2}
STATE_LABEL = {"pick": "Shootr Pick", "alt": None}


def sidecar_path_for(photo_path: Path) -> Path:
    return photo_path.with_suffix(".xmp")


def read_sidecar_state(xmp_path: Path) -> tuple[int | None, str | None, bool]:
    """(rating, label, has_develop_settings) from an existing sidecar."""
    text = xmp_path.read_text(errors="replace")
    rating = int(m.group(1)) if (m := RATING_RE.search(text)) else None
    label = m.group(1) if (m := LABEL_RE.search(text)) else None
    has_crs = bool(CRS_ATTR_RE.search(text) or CRS_TAG_RE.search(text))
    return rating, label, has_crs


def plan_export(entries: list[tuple[Path, str]]) -> ExportPlan:
    """Dry run (design 10 §2): compute the exact diff before any write.
    `entries` = (photo_path, state). Rejects are excluded by the caller —
    they write nothing by default (design 06 §1)."""
    plan = ExportPlan()
    for photo_path, state in entries:
        if photo_path.suffix.lower() == ".dng":
            # A .dng.xmp does nothing; embedding into the RAW is not a risk
            # worth taking (design 07 §3.1). Warn and skip.
            plan.skipped_dng.append(str(photo_path))
            continue
        new_rating = STATE_RATING.get(state)
        new_label = STATE_LABEL.get(state)
        if new_rating is None:
            continue  # reject: nothing written

        xmp = sidecar_path_for(photo_path)
        if xmp.exists():
            old_rating, old_label, has_crs = read_sidecar_state(xmp)
            diff = SidecarDiff(
                path=str(xmp), exists=True,
                old_rating=old_rating, new_rating=new_rating,
                old_label=old_label, new_label=new_label,
                has_develop_settings=has_crs)
            if not diff.changes_anything:
                plan.unchanged.append(str(xmp))
            elif has_crs:
                plan.conflicts.append(diff)
            else:
                plan.updates.append(diff)
        else:
            plan.new_sidecars.append(SidecarDiff(
                path=str(xmp), exists=False,
                old_rating=None, new_rating=new_rating,
                old_label=None, new_label=new_label,
                has_develop_settings=False))
    return plan


def apply_export(plan: ExportPlan, backup_dir: Path,
                 confirm_conflicts: bool = False) -> list[str]:
    """Execute a plan. Conflicts (sidecars with develop settings) are written
    only with confirm_conflicts=True — never a silent default-yes
    (design 07 §1). Returns paths written."""
    written: list[str] = []
    for diff in plan.new_sidecars:
        _write_sidecar(Path(diff.path), diff, backup_dir)
        written.append(diff.path)
    for diff in plan.updates:
        _write_sidecar(Path(diff.path), diff, backup_dir)
        written.append(diff.path)
    if confirm_conflicts:
        for diff in plan.conflicts:
            _write_sidecar(Path(diff.path), diff, backup_dir)
            written.append(diff.path)
    return written


def _write_sidecar(xmp_path: Path, diff: SidecarDiff, backup_dir: Path) -> None:
    if xmp_path.exists():
        _backup(xmp_path, backup_dir)
        text = xmp_path.read_text(errors="replace")
    else:
        text = MINIMAL_SIDECAR
    text = _set_owned_fields(text, diff.new_rating, diff.new_label)
    _atomic_write(xmp_path, text)


def _set_owned_fields(text: str, rating: int | None, label: str | None) -> str:
    """Edit only the fields we own, in place. The document around them is
    preserved byte-for-byte (design 07 §1 step 6)."""
    if rating is not None:
        if RATING_RE.search(text):
            text = RATING_RE.sub(f'xmp:Rating="{rating}"', text, count=1)
        else:
            text = _insert_attr(text, f'xmp:Rating="{rating}"')
    if label is not None:
        if LABEL_RE.search(text):
            text = LABEL_RE.sub(f'xmp:Label="{label}"', text, count=1)
        else:
            text = _insert_attr(text, f'xmp:Label="{label}"')
    return text


def _insert_attr(text: str, attr: str) -> str:
    m = DESCRIPTION_TAG_RE.search(text)
    if not m:
        raise ValueError("sidecar has no rdf:Description element")
    tag = m.group(0)
    return text.replace(tag, tag[:-1] + f"\n    {attr}>", 1)


def _backup(xmp_path: Path, backup_dir: Path) -> Path:
    """Timestamped copy under app support, keyed by filename
    (design 07 §1 step 3). Runs before every overwrite, unconditionally."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    dest = backup_dir / xmp_path.stem / f"{stamp}.xmp"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(xmp_path.read_bytes())
    return dest


def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the SAME directory, fsync, os.replace (design 07 §1
    step 5) — a crash or unplug mid-write can't leave a torn sidecar."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".xmp.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def export_csv(entries: list[tuple[Path, str]], out: Path) -> None:
    """The practical path (design 07 §3.2): a list the user can act on in
    LrC regardless of sidecar/DNG issues."""
    lines = ["path,state"]
    lines += [f"{p},{s}" for p, s in entries if s in ("pick", "alt")]
    out.write_text("\n".join(lines) + "\n")


def export_hardlinks(entries: list[tuple[Path, str]], dest: Path) -> int:
    """Hardlink "Selects" folder (design 07 §3.2): no disk cost, no
    duplication, works regardless of sidecar/DNG issues. Links picks only.
    Same-volume constraint is inherent to hardlinks; cross-volume raises
    and the caller reports it rather than silently copying gigabytes."""
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for photo_path, state in entries:
        if state != "pick" or not photo_path.is_file():
            continue
        link = dest / photo_path.name
        if link.exists():
            if link.stat().st_ino == photo_path.stat().st_ino:
                continue  # already linked to this exact file
            link = dest / f"{photo_path.stem}_{n}{photo_path.suffix}"
        os.link(photo_path, link)
        n += 1
    return n
