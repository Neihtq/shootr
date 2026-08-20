"""JSONL emission — the output half of the helper contract (design 03 §4).

One object per photo, flushed per line: a batch that dies at photo 400 of 500
keeps 400 results. Per-photo failures are {"path", "error"} objects on stdout,
never a nonzero exit — one corrupt RAW must not fail the batch. Sorted keys to
match the Swift encoder, so diffs between the two analyzers' output are clean.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _jsonable(value: Any) -> Any:
    """numpy scalars leak out of ONNX/cv2 results; refuse silently-lossy
    types but convert numeric scalars."""
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)}")


def emit_line(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                default=_jsonable))
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(path: str, error: str) -> None:
    emit_line({"path": path, "error": error})


def prune_nulls(obj: Any) -> Any:
    """Drop None values recursively — the Swift encoder omits nil optionals,
    and the engine's readers use .get() throughout, so absent == null."""
    if isinstance(obj, dict):
        return {k: prune_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [prune_nulls(v) for v in obj]
    return obj
