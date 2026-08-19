"""Stall-watchdog tests, driven by fake helper scripts rather than the Swift
binary so the failure modes are deterministic.

Why this exists: a `shootr-analyze` child was observed wedged at 0% CPU with
`CIRAWFilter` blocking in `open()` inside ImageIO — it never returned and
`proc.wait()` never came back. With clients gating shoot navigation on "is a
job in flight", an unbounded hang doesn't just stall analysis, it locks the
shoot with no way out.
"""

import os
import textwrap
import time
from pathlib import Path

import pytest

from shootr import helper
from shootr.helper import HelperStalled


def fake_helper(tmp_path: Path, body: str) -> Path:
    """Write an executable stand-in for `shootr-analyze`."""
    p = tmp_path / "fake-helper"
    p.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    p.chmod(0o755)
    return p


@pytest.fixture
def use_fake(monkeypatch):
    def _use(path: Path):
        monkeypatch.setenv("SHOOTR_HELPER", str(path))
    return _use


def test_stalled_helper_raises_instead_of_blocking(tmp_path, use_fake):
    # Emits one result, then hangs forever — the observed ImageIO signature.
    use_fake(fake_helper(tmp_path, """
        echo '{"path":"/lib/a.CR3","frame":{}}'
        sleep 300
    """))
    started = time.monotonic()
    got = []
    with pytest.raises(HelperStalled):
        for r in helper._run_jsonl("analyze", [Path("/lib/a.CR3")],
                                   stall_timeout=1.0):
            got.append(r)
    elapsed = time.monotonic() - started
    # Bounded by the timeout, not by the helper's 300s sleep.
    assert elapsed < 10
    # Results that arrived before the stall are still delivered: the caller
    # banks them and requeues the rest (design 09 §3).
    assert got == [{"path": "/lib/a.CR3", "frame": {}}]


def test_stalled_helper_is_killed_not_orphaned(tmp_path, use_fake):
    """A wedged helper holds the RAW file open and burns a subprocess slot.
    Leaking one per batch would exhaust both over a 10k run."""
    pidfile = tmp_path / "pid"
    use_fake(fake_helper(tmp_path, f"""
        echo $$ > {pidfile}
        echo '{{"path":"/lib/a.CR3","frame":{{}}}}'
        sleep 300
    """))
    with pytest.raises(HelperStalled):
        list(helper._run_jsonl("analyze", [Path("/lib/a.CR3")],
                               stall_timeout=1.0))
    pid = int(pidfile.read_text().strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return  # reaped
        time.sleep(0.05)
    pytest.fail(f"helper pid {pid} survived the watchdog")


def test_slow_but_progressing_helper_is_not_killed(tmp_path, use_fake):
    """Per-line, not total: a big batch is legitimately slow. Bounding total
    runtime would kill healthy 10k runs."""
    use_fake(fake_helper(tmp_path, """
        for i in 1 2 3 4 5 6; do
          echo "{\\"path\\":\\"/lib/$i.CR3\\",\\"frame\\":{}}"
          sleep 0.3
        done
    """))
    # Total ~1.8s with a 1.0s per-line timeout — must complete.
    results = list(helper._run_jsonl("analyze", [Path("/lib/1.CR3")],
                                     stall_timeout=1.0))
    assert len(results) == 6


def test_line_split_across_writes_is_reassembled(tmp_path, use_fake):
    """analyze lines carry 256 sharpness tiles + an embedding and exceed the
    pipe buffer, so they arrive in pieces. Framing per-read rather than
    per-line would yield truncated JSON."""
    big = "x" * 200_000
    use_fake(fake_helper(tmp_path, f"""
        printf '{{"path":"/lib/a.CR3","blob":"{big}"'
        sleep 0.2
        printf ',"frame":{{}}}}\\n'
    """))
    results = list(helper._run_jsonl("analyze", [Path("/lib/a.CR3")],
                                     stall_timeout=5.0))
    assert len(results) == 1
    assert results[0]["blob"] == big
    assert results[0]["frame"] == {}


def test_final_line_without_trailing_newline_is_not_dropped(tmp_path,
                                                            use_fake):
    use_fake(fake_helper(tmp_path, """
        printf '{"path":"/lib/a.CR3","frame":{}}'
    """))
    results = list(helper._run_jsonl("analyze", [Path("/lib/a.CR3")],
                                     stall_timeout=5.0))
    assert results == [{"path": "/lib/a.CR3", "frame": {}}]


def test_probe_many_keeps_partial_chunk_and_logs_the_gap(tmp_path, use_fake,
                                                         caplog):
    """A stalled chunk must not abort the scan, and must not go silent —
    ingest fills the gaps with per-file probes."""
    use_fake(fake_helper(tmp_path, """
        echo '{"path":"/lib/a.CR3","iso":100}'
        sleep 300
    """))
    monkey_timeout = 1.0
    orig = helper.PROBE_STALL_TIMEOUT_S
    helper.PROBE_STALL_TIMEOUT_S = monkey_timeout
    try:
        with caplog.at_level("WARNING"):
            out = helper.probe_many([Path("/lib/a.CR3"), Path("/lib/b.CR3")])
    finally:
        helper.PROBE_STALL_TIMEOUT_S = orig
    assert out == {"/lib/a.CR3": {"path": "/lib/a.CR3", "iso": 100}}
    assert "falling back to per-file probing" in caplog.text
