"""shootr-analyze-py — CLI contract per design 03 §4, argv-compatible with the
Swift helper so SHOOTR_HELPER can point at either binary:

  probe    --files <list.json>               → JSONL metadata
  analyze  --files <list.json> [--scale 0.5] [--sharpness luminance|cfa]
  render   --file <raw> [--size 2048] --out <path>
  version
  selftest
  verify-models                              → registry status (py-only extra)

File lists via JSON file, not argv (length limits at 10k scale). Per-photo
errors are JSONL objects; exit 2 only for malformed invocations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import ANALYZER_VERSION
from .io import emit_error, emit_line


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _arg(name: str) -> str | None:
    args = sys.argv
    if f"--{name}" in args:
        i = args.index(f"--{name}")
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _load_file_list() -> list[Path]:
    list_path = _arg("files")
    if not list_path:
        _fail("--files <list.json> required")
    try:
        with open(list_path) as fh:
            return [Path(p) for p in json.load(fh)]
    except (OSError, json.JSONDecodeError):
        _fail(f"cannot read file list: {list_path}")
    raise AssertionError  # unreachable


def engine_version() -> str:
    from .models import registry_hash

    return f"{ANALYZER_VERSION}+{registry_hash()}"


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command == "version":
        from .models import ort_providers

        emit_line({
            "engine_version": engine_version(),
            "python_analyzer": "shootr-analyze-py",
            "providers": ort_providers(),
        })

    elif command == "selftest":
        from .selftest import run

        failures = run()
        if not failures:
            emit_line({"status": "ok"})
        else:
            for f in failures:
                emit_error("selftest", f)
            sys.exit(1)

    elif command == "verify-models":
        from .models import cache_dir, verify_report

        emit_line({"cache_dir": str(cache_dir())})
        for row in verify_report():
            emit_line(row)

    elif command == "probe":
        from .probe import probe

        for path in _load_file_list():
            out = probe(path)
            if out is not None:
                emit_line(out)
            else:
                emit_error(str(path), "probe_failed")

    elif command == "analyze":
        from .analyze import analyze

        scale = float(_arg("scale") or 0.5)
        sharpness_source = _arg("sharpness") or "luminance"
        if sharpness_source not in ("luminance", "cfa"):
            _fail("--sharpness must be luminance|cfa")
        for path in _load_file_list():
            try:
                emit_line(analyze(path, scale=scale,
                                  sharpness_source=sharpness_source))
            except Exception as exc:  # noqa: BLE001 — per-photo isolation
                emit_error(str(path), f"{type(exc).__name__}: {exc}")

    elif command == "render":
        file, out = _arg("file"), _arg("out")
        if not file or not out:
            _fail("render --file <raw> --out <path> [--size 2048]")
        size = int(_arg("size") or 2048)
        from .decode import decode_display

        try:
            from PIL import Image

            rgb = decode_display(Path(file), size=size)
            Image.fromarray(rgb).save(out, "JPEG", quality=90)
            emit_line({"path": file, "out": out, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            emit_error(file, f"{type(exc).__name__}: {exc}")
            sys.exit(1)

    else:
        _fail(
            "usage: shootr-analyze-py <command>\n"
            "  probe    --files <list.json>\n"
            "  analyze  --files <list.json> [--scale 0.5] "
            "[--sharpness luminance|cfa]\n"
            "  render   --file <raw> [--size 2048] --out <path>\n"
            "  version\n"
            "  selftest\n"
            "  verify-models"
        )


if __name__ == "__main__":
    main()
