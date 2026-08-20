"""Blink labelling aid — turn an hour of keystrokes into the validation the
blink metric requires (design 03 §5, 13 §4: a dominant metric may not drive
culling until checked against hand labels).

Three subcommands, run in order:

  prepare <photo-dir> [--limit 40] [--workdir blink_labels]
      Runs BOTH analyzers over the sample, matches faces between them by
      bbox IoU, renders a viewing crop per face, writes manifest.jsonl.

  serve [--workdir blink_labels] [--port 8899]
      Local page (127.0.0.1 only): one face at a time, one keystroke each —
      O open · C closed · U unclear · ← back. Labels append to labels.jsonl,
      resumable, last write wins.

  report [--workdir blink_labels]
      Joins labels with each source's eye-open values (EAR from the Swift
      helper, blendshapes from the Python analyzer), sweeps thresholds, and
      reports per-source accuracy + false-reject rate — including at the 0.4
      cutoff culling currently uses. Writes blink_report.md.

The metric consumes min(left, right) per face (scoring.py `_eyes_open`), so
labels are per FACE, not per eye. Faces under 48 px are skipped — if a human
can't judge the crop, it can't be ground truth.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import statistics
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import helper  # noqa: E402

RAW_SUFFIXES = {".cr2", ".cr3", ".arw", ".raf", ".dng", ".jpg", ".jpeg"}
MIN_FACE_PX = 48
MATCH_IOU = 0.3
CURRENT_CULLING_THRESHOLD = 0.4  # culling's "eyes closed" cutoff today


# --- shared math (unit-tested) ------------------------------------------------


def face_score(face: dict) -> float | None:
    """What the scorer consumes: min of the two eyes; None if both absent."""
    eyes = face.get("eyes", {})
    vals = [eyes.get(s, {}).get("open") for s in ("l", "r")]
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def iou(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1 = min(a[0] + a[2], b[0] + b[2])
    iy1 = min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def evaluate(open_scores: list[float], closed_scores: list[float],
             threshold: float) -> dict:
    """below threshold = flagged closed. False reject = an OPEN eye flagged
    closed — the asymmetric failure (a good photo rejected for a stated,
    wrong reason)."""
    fr = sum(1 for s in open_scores if s < threshold)
    fa = sum(1 for s in closed_scores if s >= threshold)
    n_open, n_closed = len(open_scores), len(closed_scores)
    tpr = 1 - fr / n_open if n_open else float("nan")
    tnr = 1 - fa / n_closed if n_closed else float("nan")
    return {
        "threshold": threshold,
        "false_reject_rate": fr / n_open if n_open else float("nan"),
        "false_accept_rate": fa / n_closed if n_closed else float("nan"),
        "balanced_accuracy": (tpr + tnr) / 2,
    }


def best_threshold(open_scores: list[float],
                   closed_scores: list[float]) -> dict:
    """Sweep 0..1, maximize balanced accuracy; ties → lower threshold (favor
    fewer false rejects, the asymmetric cost)."""
    best = None
    for i in range(101):
        t = i / 100
        e = evaluate(open_scores, closed_scores, t)
        if best is None or e["balanced_accuracy"] > best["balanced_accuracy"]:
            best = e
    return best


# --- prepare -------------------------------------------------------------------


def collect_files(target: Path, limit: int) -> list[Path]:
    files = sorted(p for p in target.rglob("*")
                   if p.suffix.lower() in RAW_SUFFIXES)
    return files[:limit] if limit else files


def run_analyzer(binary: Path, files: list[Path]) -> dict[str, dict]:
    os.environ["SHOOTR_HELPER"] = str(binary)
    out: dict[str, dict] = {}
    for i, result in enumerate(helper.analyze_batch(files, scale=0.5), 1):
        if i % 10 == 0:
            print(f"  {binary.name}: {i}/{len(files)}", file=sys.stderr)
        if path := result.get("path"):
            out[path] = result
    return out


def prepare(args: argparse.Namespace) -> None:
    from PIL import Image

    swift_bin = args.swift
    py_bin = args.python
    work = args.workdir
    (work / "crops").mkdir(parents=True, exist_ok=True)

    files = collect_files(args.target, args.limit)
    if not files:
        sys.exit("no files found")
    print(f"{len(files)} files → {work}", file=sys.stderr)

    swift = run_analyzer(swift_bin, files) if swift_bin.exists() else {}
    py = run_analyzer(py_bin, files)

    entries = []
    render_bin = swift_bin if swift_bin.exists() else py_bin
    for path in sorted(set(swift) | set(py)):
        s_faces = swift.get(path, {}).get("faces", [])
        p_faces = py.get(path, {}).get("faces", [])
        if not s_faces and not p_faces:
            continue

        # One display render per photo, crops cut from it.
        rendered = work / "crops" / (Path(path).stem + "_full.jpg")
        if not rendered.exists():
            subprocess.run(
                [str(render_bin), "render", "--file", path,
                 "--size", "2048", "--out", str(rendered)],
                check=True, capture_output=True)
        img = Image.open(rendered)
        iw, ih = img.size

        # Union of faces: python's are primary (blendshapes live there);
        # unmatched Swift-only faces still get labelled (EAR-only data).
        used_swift: set[int] = set()
        for pi, pf in enumerate(p_faces):
            match = None
            for si, sf in enumerate(s_faces):
                if si not in used_swift and iou(pf["bbox"], sf["bbox"]) >= MATCH_IOU:
                    match = si
                    used_swift.add(si)
                    break
            entries.append(_entry(path, pf, pi,
                                  s_faces[match] if match is not None else None))
        for si, sf in enumerate(s_faces):
            if si not in used_swift:
                entries.append(_entry(path, None, None, sf, swift_idx=si))

        # Cut the crops.
        for e in entries:
            if e["photo"] != path or "crop" in e:
                continue
            bbox = e["bbox"]
            # Vision bottom-left normalized → PIL top-left pixels, 40% pad.
            w, h = bbox[2] * iw, bbox[3] * ih
            if min(w, h) < MIN_FACE_PX:
                e["crop"] = None  # too small to judge — excluded below
                continue
            x0 = max(0, bbox[0] * iw - w * 0.4)
            y1 = ih - bbox[1] * ih  # bottom edge
            y0 = max(0, y1 - h - h * 0.4)
            crop = img.crop((int(x0), int(y0),
                             int(min(iw, x0 + w * 1.8)),
                             int(min(ih, y0 + h * 1.8))))
            if crop.width < 320:  # upscale small faces for viewing only
                ratio = 320 / crop.width
                crop = crop.resize((320, int(crop.height * ratio)))
            name = f"{Path(path).stem}_f{e['key']}.jpg"
            crop.save(work / "crops" / name, "JPEG", quality=90)
            e["crop"] = name
        img.close()
        rendered.unlink()  # full renders are big; only crops are needed

    entries = [e for e in entries if e.get("crop")]
    with open(work / "manifest.jsonl", "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    print(f"{len(entries)} faces to label "
          f"(skipped small/cropless ones). Next:\n"
          f"  .venv/bin/python engine/tools/label_blinks.py serve "
          f"--workdir {work}", file=sys.stderr)


def _entry(path: str, pf: dict | None, pi: int | None,
           sf: dict | None, swift_idx: int | None = None) -> dict:
    key = f"p{pi}" if pi is not None else f"s{swift_idx}"
    return {
        "photo": path,
        "key": key,
        "bbox": (pf or sf)["bbox"],
        "blend": face_score(pf) if pf else None,
        "ear": face_score(sf) if sf else None,
    }


# --- serve ---------------------------------------------------------------------

_PAGE = """<!doctype html><meta charset="utf-8"><title>blink labels</title>
<style>
 body{background:#111113;color:#e8e8ea;font:14px system-ui;display:flex;
      flex-direction:column;align-items:center;gap:14px;padding-top:30px}
 img{max-height:60vh;border-radius:6px}
 .keys{color:#9a9aa2} kbd{background:#232327;padding:2px 7px;border-radius:4px}
 .done{font-size:18px;color:#4cc38a}
</style>
<div id="progress"></div><img id="crop" hidden><div id="done" hidden
 class="done">All labelled — run the report:<br>
 <code>.venv/bin/python engine/tools/label_blinks.py report</code></div>
<div class="keys"><kbd>O</kbd> eyes open · <kbd>C</kbd> closed (any eye) ·
 <kbd>U</kbd> unclear · <kbd>←</kbd> back</div>
<script>
let faces=[], labels={}, i=0;
async function load(){
  const s = await (await fetch('/state')).json();
  faces = s.faces; labels = s.labels;
  i = faces.findIndex(f => !(f.crop in labels));
  if (i < 0) i = faces.length;
  show();
}
function show(){
  const done = i >= faces.length;
  document.getElementById('crop').hidden = done;
  document.getElementById('done').hidden = !done;
  document.getElementById('progress').textContent =
    Object.keys(labels).length + ' / ' + faces.length;
  if (!done) document.getElementById('crop').src = '/crops/' + faces[i].crop;
}
async function label(v){
  if (i >= faces.length) return;
  labels[faces[i].crop] = v;
  await fetch('/label', {method:'POST',
    body: JSON.stringify({crop: faces[i].crop, label: v})});
  i++; show();
}
addEventListener('keydown', e => {
  if (e.key==='o') label('open');
  else if (e.key==='c') label('closed');
  else if (e.key==='u') label('unclear');
  else if (e.key==='ArrowLeft' && i>0){ i--; show(); }
});
load();
</script>"""


def serve(args: argparse.Namespace) -> None:
    work = args.workdir
    manifest = [json.loads(line)
                for line in open(work / "manifest.jsonl")]
    labels_path = work / "labels.jsonl"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(_PAGE.encode(), "text/html")
            elif self.path == "/state":
                labels = _read_labels(labels_path)
                self._send(json.dumps(
                    {"faces": manifest, "labels": labels}).encode(),
                    "application/json")
            elif self.path.startswith("/crops/"):
                p = work / "crops" / Path(self.path).name
                if p.is_file():
                    self._send(p.read_bytes(), "image/jpeg")
                else:
                    self.send_error(404)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/label":
                self.send_error(404)
                return
            n = int(self.headers.get("Content-Length", 0))
            entry = json.loads(self.rfile.read(n))
            with open(labels_path, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._send(b"{}", "application/json")

    addr = ("127.0.0.1", args.port)
    url = f"http://{addr[0]}:{addr[1]}/"
    print(f"labelling at {url} — Ctrl-C when done", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    # Threading: browsers hold keep-alive connections open, and a
    # single-threaded HTTPServer serializes on them — the page then hangs.
    http.server.ThreadingHTTPServer(addr, Handler).serve_forever()


def _read_labels(path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    if path.exists():
        for line in open(path):
            e = json.loads(line)
            labels[e["crop"]] = e["label"]  # last write wins
    return labels


# --- report --------------------------------------------------------------------


def report(args: argparse.Namespace) -> None:
    work = args.workdir
    manifest = [json.loads(line) for line in open(work / "manifest.jsonl")]
    labels = _read_labels(work / "labels.jsonl")

    lines = ["# Blink validation — hand labels vs both detectors", ""]
    n_labelled = sum(1 for e in manifest if labels.get(e["crop"]) in
                     ("open", "closed"))
    n_unclear = sum(1 for e in manifest
                    if labels.get(e["crop"]) == "unclear")
    lines.append(f"{len(manifest)} faces · {n_labelled} labelled open/closed"
                 f" · {n_unclear} unclear (excluded)")

    for source, field in (("EAR (Swift landmarks)", "ear"),
                          ("blendshapes (MediaPipe)", "blend")):
        open_s, closed_s = [], []
        for e in manifest:
            v = e.get(field)
            lab = labels.get(e["crop"])
            if v is None or lab not in ("open", "closed"):
                continue
            (open_s if lab == "open" else closed_s).append(v)
        lines += ["", f"## {source}",
                  f"- coverage: {len(open_s) + len(closed_s)}/{n_labelled} "
                  "labelled faces have a value"]
        if not open_s or not closed_s:
            lines.append("- **not enough labelled data in one class — "
                         "label more closed-eye frames**")
            continue
        lines.append(
            f"- score distribution: open μ={statistics.mean(open_s):.2f} "
            f"(n={len(open_s)}), closed μ={statistics.mean(closed_s):.2f} "
            f"(n={len(closed_s)})")
        best = best_threshold(open_s, closed_s)
        cur = evaluate(open_s, closed_s, CURRENT_CULLING_THRESHOLD)
        lines += [
            f"- best threshold **{best['threshold']:.2f}**: balanced acc "
            f"{best['balanced_accuracy']:.1%}, false-reject "
            f"{best['false_reject_rate']:.1%}, false-accept "
            f"{best['false_accept_rate']:.1%}",
            f"- at culling's current {CURRENT_CULLING_THRESHOLD}: "
            f"balanced acc {cur['balanced_accuracy']:.1%}, "
            f"**false-reject {cur['false_reject_rate']:.1%}** "
            "(open eyes flagged closed — the asymmetric failure)",
        ]

    lines += ["", "_False-reject is the number that matters: it is the rate "
              "at which good photos would be rejected with the stated reason "
              "'eyes closed'. Whichever source wins, culling's threshold "
              "should move to that source's best value (design 06 §6)._"]
    out = work / "blink_report.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}", file=sys.stderr)


# --- main ----------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    root = Path(__file__).resolve().parents[2]

    p = sub.add_parser("prepare")
    p.add_argument("target", type=Path)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--workdir", type=Path, default=Path("blink_labels"))
    p.add_argument("--swift", type=Path,
                   default=root / "helper/.build/debug/shootr-analyze")
    p.add_argument("--python", type=Path,
                   default=Path(sys.executable).parent / "shootr-analyze-py")

    s = sub.add_parser("serve")
    s.add_argument("--workdir", type=Path, default=Path("blink_labels"))
    s.add_argument("--port", type=int, default=8899)
    s.add_argument("--no-browser", action="store_true")

    r = sub.add_parser("report")
    r.add_argument("--workdir", type=Path, default=Path("blink_labels"))

    args = ap.parse_args()
    {"prepare": prepare, "serve": serve, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
