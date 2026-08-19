"""Python side of the Swift helper contract (design 03 §4).

Spawns `shootr-analyze`, feeds it file lists via temp JSON (argv has length
limits at 10k scale), consumes JSONL per line so progress is incremental —
a batch that dies at photo 400 of 500 keeps 400 results.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("shootr.helper")

DEFAULT_HELPER = Path(__file__).resolve().parents[2] / "helper" / ".build" \
    / "debug" / "shootr-analyze"


class HelperStalled(RuntimeError):
    """Helper stopped producing output — killed by the watchdog."""


def helper_path() -> Path:
    env = os.environ.get("SHOOTR_HELPER")
    return Path(env) if env else DEFAULT_HELPER


def helper_available() -> bool:
    return helper_path().is_file()


# Watchdog: kill a helper that stops producing output for this long.
# CIRAWFilter has been observed blocking indefinitely in open() inside
# ImageIO on the first file of a batch — 0% CPU, never returns. Without a
# timeout the job sits "running" forever, and clients that gate on a busy
# job would keep the shoot locked with no way out. Per-line rather than
# total: a large batch is legitimately slow, a stalled one is silent.
# 120 s is ~40x the p99 single-photo analyze (~1.4 s at scale 0.5).
STALL_TIMEOUT_S = 120.0

# Probe reads EXIF only (~1.7 ms/file measured), so silence means stuck, not
# slow. Kept well above the timeout an ingest of a cold external drive needs
# for its first file — spin-up, not decode, is what makes probe slow.
PROBE_STALL_TIMEOUT_S = 30.0


def _run_jsonl(command: str, files: list[Path],
               extra_args: list[str] | None = None,
               stall_timeout: float = STALL_TIMEOUT_S) -> Iterator[dict]:
    """Run a batch subcommand, yielding one dict per JSONL line as it
    arrives. Per-photo errors come through as {"path":…,"error":…} objects,
    never a nonzero exit (design 03 §4).

    Raises `HelperStalled` if the helper produces nothing for
    `stall_timeout`. The caller treats that like a crash: results already
    yielded are banked, the rest are requeued (analyze_runner), so a resume
    retries the stuck file rather than losing the batch.
    """
    import selectors

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    ) as f:
        json.dump([str(p) for p in files], f)
        list_path = f.name
    proc = None
    try:
        proc = subprocess.Popen(
            [str(helper_path()), command, "--files", list_path,
             *(extra_args or [])],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Vision logs noise to stderr
        )  # binary: we frame lines ourselves, see below
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        sel = selectors.DefaultSelector()
        sel.register(fd, selectors.EVENT_READ)
        # Raw os.read + our own line framing rather than readline(): a
        # readable stream can still block *inside* readline() when only part
        # of a line has arrived, and an analyze line (256 sharpness tiles +
        # embedding) can exceed the pipe buffer and be split across writes.
        # That would put the block back where the watchdog can't see it.
        buf = b""
        while True:
            if not sel.select(timeout=stall_timeout):
                raise HelperStalled(
                    f"{command} produced no output for {stall_timeout:.0f}s "
                    f"(batch of {len(files)}, "
                    f"first: {files[0] if files else '?'})"
                )
            chunk = os.read(fd, 65536)
            if not chunk:  # EOF — normal end of batch
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                raw = raw.strip()
                if raw:
                    yield json.loads(raw)
        if buf.strip():  # last line without a trailing newline
            yield json.loads(buf.strip())
        proc.wait()
    finally:
        # A stalled helper ignores nothing else: terminate, then SIGKILL if
        # it is wedged in a syscall and won't unwind.
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        os.unlink(list_path)


def probe_batch(files: list[Path]) -> Iterator[dict]:
    yield from _run_jsonl("probe", files,
                          stall_timeout=PROBE_STALL_TIMEOUT_S)


def analyze_batch(files: list[Path], scale: float = 0.5) -> Iterator[dict]:
    yield from _run_jsonl("analyze", files, ["--scale", str(scale)])


def swift_prober(path: Path) -> dict | None:
    """Ingest `Prober` implementation (design 02 §2 stage 4).

    Single-file fallback only. One subprocess spawn per file costs ~100 ms,
    of which the probe itself is ~1.7 ms — spawn dominates by 60x. Ingest
    pre-probes in batches via `probe_many`; this path exists for the files
    that batch missed.
    """
    for result in probe_batch([path]):
        if "error" in result:
            raise RuntimeError(result["error"])
        return result
    return None


def probe_many(paths: list[Path], chunk: int = 400) -> dict[str, dict]:
    """Probe many files with one subprocess per `chunk`, keyed by path.

    Chunked rather than one giant call so a helper crash costs one chunk,
    not the whole scan. Per-file `error` rows are dropped: the caller
    creates the photo row with NULL metadata (design 02 §5), same as a
    probe that was never attempted.

    A crashed or stalled chunk keeps the results it already yielded and
    leaves the rest as gaps, which ingest fills with per-file probes. That
    costs ~100 ms per gap and re-hits the stuck file once — acceptable, and
    unlike aborting it still gets the user a complete scan.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(paths), chunk):
        batch = paths[i:i + chunk]
        try:
            for result in probe_batch(batch):
                path = result.get("path")
                if path and "error" not in result:
                    out[path] = result
        except Exception as exc:  # noqa: BLE001 — never abort a scan
            log.warning("probe chunk %d-%d failed (%s): %s; "
                        "falling back to per-file probing",
                        i, i + len(batch), type(exc).__name__, exc)
    return out


def render(raw: Path, out: Path, size: int = 2048) -> None:
    subprocess.run(
        [str(helper_path()), "render", "--file", str(raw),
         "--size", str(size), "--out", str(out)],
        check=True, capture_output=True,
    )
