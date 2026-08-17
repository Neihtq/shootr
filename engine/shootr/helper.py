"""Python side of the Swift helper contract (design 03 §4).

Spawns `shootr-analyze`, feeds it file lists via temp JSON (argv has length
limits at 10k scale), consumes JSONL per line so progress is incremental —
a batch that dies at photo 400 of 500 keeps 400 results.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

DEFAULT_HELPER = Path(__file__).resolve().parents[2] / "helper" / ".build" \
    / "debug" / "shootr-analyze"


def helper_path() -> Path:
    env = os.environ.get("SHOOTR_HELPER")
    return Path(env) if env else DEFAULT_HELPER


def helper_available() -> bool:
    return helper_path().is_file()


def _run_jsonl(command: str, files: list[Path],
               extra_args: list[str] | None = None) -> Iterator[dict]:
    """Run a batch subcommand, yielding one dict per JSONL line as it
    arrives. Per-photo errors come through as {"path":…,"error":…} objects,
    never a nonzero exit (design 03 §4)."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    ) as f:
        json.dump([str(p) for p in files], f)
        list_path = f.name
    try:
        proc = subprocess.Popen(
            [str(helper_path()), command, "--files", list_path,
             *(extra_args or [])],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Vision logs noise to stderr
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                yield json.loads(line)
        proc.wait()
    finally:
        os.unlink(list_path)


def probe_batch(files: list[Path]) -> Iterator[dict]:
    yield from _run_jsonl("probe", files)


def analyze_batch(files: list[Path], scale: float = 0.5) -> Iterator[dict]:
    yield from _run_jsonl("analyze", files, ["--scale", str(scale)])


def swift_prober(path: Path) -> dict | None:
    """Ingest `Prober` implementation (design 02 §2 stage 4). One file per
    call — ingest batches at a higher level; fine for M1."""
    for result in probe_batch([path]):
        if "error" in result:
            raise RuntimeError(result["error"])
        return result
    return None


def render(raw: Path, out: Path, size: int = 2048) -> None:
    subprocess.run(
        [str(helper_path()), "render", "--file", str(raw),
         "--size", str(size), "--out", str(out)],
        check=True, capture_output=True,
    )
