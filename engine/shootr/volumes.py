"""Volume identity (design 02): external drives remount at different paths,
so a library is identified by (volume UUID, path relative to the mount
point), not by its absolute path.

macOS: `diskutil info -plist <path>` gives VolumeUUID + MountPoint. Other
platforms return (None, None) for now — volume semantics on NTFS/ext4 are
a post-M2 portability item (design 13); everything degrades to plain
root-path matching, which is what the code did before this module.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path


def volume_info(path: Path) -> tuple[str | None, str | None]:
    """(volume_uuid, mount_point) for the volume holding `path`."""
    if sys.platform != "darwin":
        return None, None
    try:
        res = subprocess.run(
            ["diskutil", "info", "-plist", str(path)],
            capture_output=True, timeout=10)
        if res.returncode != 0:
            return None, None
        info = plistlib.loads(res.stdout)
        return info.get("VolumeUUID"), info.get("MountPoint")
    except Exception:  # noqa: BLE001 — identity is best-effort, never fatal
        return None, None


def volume_identity(root: Path) -> tuple[str | None, str | None]:
    """(volume_uuid, root's path relative to the mount point) or (None, None).

    The relative path is what survives a remount; the absolute root does not.
    """
    uuid, mount = volume_info(root)
    if not uuid or not mount:
        return None, None
    try:
        rel = str(root.resolve().relative_to(Path(mount)))
    except ValueError:
        return None, None
    return uuid, rel
