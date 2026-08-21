"""Face-recall spot-check — who is right when the detectors disagree?

SCRFD found 77 faces where Vision found 56 on the A/B sample. More recall is
only better if the extras are real faces; a detector that invents faces
feeds phantom blink/quality metrics into scoring. This renders one review
crop per DISPUTED detection (found by exactly one detector) so a human can
judge: real face, or false positive.

    prepare <photo-dir> [--limit 60]   → workdir with crops + manifest
    serve   [--port 8894]              → keystroke labelling (R real / F not
                                          a face / U unclear / ← back)
    report                             → precision of each detector's
                                          disputed detections

Reuses the matching (bbox IoU) and serving pattern from label_blinks.py.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import helper  # noqa: E402

RAW_SUFFIXES = {".cr2", ".cr3", ".arw", ".raf", ".dng", ".jpg", ".jpeg"}
MATCH_IOU = 0.3
MIN_FACE_PX = 32  # smaller than blink's 48: tiny faces are exactly the
                  # disputed population; judging "is it a face" needs less
                  # resolution than judging a blink


def iou(a: list[float], b: list[float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1 = min(a[0] + a[2], b[0] + b[2])
    iy1 = min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def collect_files(target: Path, limit: int) -> list[Path]:
    files = sorted(p for p in target.rglob("*")
                   if p.suffix.lower() in RAW_SUFFIXES)
    return files[:limit] if limit else files


def run_analyzer(binary: Path, files: list[Path]) -> dict[str, list[dict]]:
    os.environ["SHOOTR_HELPER"] = str(binary)
    out: dict[str, list[dict]] = {}
    for i, r in enumerate(helper.analyze_batch(files, scale=0.5), 1):
        if i % 10 == 0:
            print(f"  {binary.name}: {i}/{len(files)}", file=sys.stderr)
        if p := r.get("path"):
            out[p] = r.get("faces", [])
    return out


def prepare(args: argparse.Namespace) -> None:
    from PIL import Image

    work = args.workdir
    (work / "crops").mkdir(parents=True, exist_ok=True)
    files = collect_files(args.target, args.limit)
    print(f"{len(files)} files", file=sys.stderr)

    swift = run_analyzer(args.swift, files)
    py = run_analyzer(args.python, files)

    entries = []
    for path in sorted(set(swift) & set(py)):
        s_faces, p_faces = swift[path], py[path]
        matched_p: set[int] = set()
        disputed: list[tuple[str, dict]] = []
        for sf in s_faces:
            hit = None
            for pi, pf in enumerate(p_faces):
                if pi not in matched_p and iou(sf["bbox"], pf["bbox"]) >= MATCH_IOU:
                    hit = pi
                    matched_p.add(pi)
                    break
            if hit is None:
                disputed.append(("swift_only", sf))
        disputed += [("python_only", pf) for pi, pf in enumerate(p_faces)
                     if pi not in matched_p]
        if not disputed:
            continue

        rendered = work / "crops" / (Path(path).stem + "_full.jpg")
        subprocess.run(
            [str(args.swift), "render", "--file", path,
             "--size", "2048", "--out", str(rendered)],
            check=True, capture_output=True)
        img = Image.open(rendered)
        iw, ih = img.size
        for i, (who, f) in enumerate(disputed):
            bx, by, bw, bh = f["bbox"]
            w, h = bw * iw, bh * ih
            if min(w, h) < MIN_FACE_PX:
                continue
            # Vision bottom-left normalized → PIL top-left px, 60% pad for
            # context (a face is easier to judge with shoulders visible).
            x0 = max(0, bx * iw - w * 0.6)
            y1 = ih - by * ih
            y0 = max(0, y1 - h - h * 0.6)
            crop = img.crop((int(x0), int(y0),
                             int(min(iw, x0 + w * 2.2)),
                             int(min(ih, y0 + h * 2.2))))
            if crop.width < 280:
                crop = crop.resize((280, int(crop.height * 280 / crop.width)))
            name = f"{Path(path).stem}_{who}_{i}.jpg"
            crop.save(work / "crops" / name, "JPEG", quality=90)
            entries.append({
                "photo": path, "who": who, "crop": name,
                "score": f.get("capture_quality"),
                "bbox": f["bbox"],
            })
        img.close()
        rendered.unlink()

    with open(work / "manifest.jsonl", "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    by_who = {}
    for e in entries:
        by_who[e["who"]] = by_who.get(e["who"], 0) + 1
    print(f"{len(entries)} disputed detections to judge ({by_who}). Next:\n"
          f"  .venv/bin/python engine/tools/face_recall_check.py serve "
          f"--workdir {work}", file=sys.stderr)


_PAGE = """<!doctype html><meta charset="utf-8"><title>face check</title>
<style>
 body{background:#111113;color:#e8e8ea;font:14px system-ui;display:flex;
      flex-direction:column;align-items:center;gap:12px;padding-top:28px}
 img{max-height:55vh;border-radius:6px}
 .who{color:#9a9aa2;font-size:12px}
 .keys{color:#9a9aa2} kbd{background:#232327;padding:2px 7px;border-radius:4px}
 .done{font-size:18px;color:#4cc38a}
</style>
<div id="progress"></div><div id="who" class="who"></div>
<img id="crop" hidden><div id="done" hidden class="done">All judged — run:
<br><code>.venv/bin/python engine/tools/face_recall_check.py report</code></div>
<div class="keys"><kbd>R</kbd> real face · <kbd>F</kbd> not a face ·
 <kbd>U</kbd> unclear · <kbd>←</kbd> back</div>
<script>
let items=[], labels={}, i=0;
async function load(){
  const s = await (await fetch('/state')).json();
  items = s.items; labels = s.labels;
  i = items.findIndex(x => !(x.crop in labels));
  if (i < 0) i = items.length;
  show();
}
function show(){
  const done = i >= items.length;
  document.getElementById('crop').hidden = done;
  document.getElementById('done').hidden = !done;
  document.getElementById('progress').textContent =
    Object.keys(labels).length + ' / ' + items.length;
  if (!done){
    document.getElementById('crop').src = '/crops/' + items[i].crop;
    document.getElementById('who').textContent =
      'found only by: ' + (items[i].who === 'python_only'
        ? 'SCRFD (python)' : 'Vision (swift)');
  }
}
async function label(v){
  if (i >= items.length) return;
  labels[items[i].crop] = v;
  await fetch('/label', {method:'POST',
    body: JSON.stringify({crop: items[i].crop, label: v})});
  i++; show();
}
addEventListener('keydown', e => {
  if (e.key==='r') label('real');
  else if (e.key==='f') label('not_face');
  else if (e.key==='u') label('unclear');
  else if (e.key==='ArrowLeft' && i>0){ i--; show(); }
});
load();
</script>"""


def serve(args: argparse.Namespace) -> None:
    work = args.workdir
    manifest = [json.loads(line) for line in open(work / "manifest.jsonl")]
    labels_path = work / "labels.jsonl"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
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
                self._send(json.dumps(
                    {"items": manifest,
                     "labels": _read_labels(labels_path)}).encode(),
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
            n = int(self.headers.get("Content-Length", 0))
            entry = json.loads(self.rfile.read(n))
            with open(labels_path, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._send(b"{}", "application/json")

    addr = ("127.0.0.1", args.port)
    print(f"judging at http://{addr[0]}:{addr[1]}/ — Ctrl-C when done",
          file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(f"http://{addr[0]}:{addr[1]}/")
    http.server.ThreadingHTTPServer(addr, Handler).serve_forever()


def _read_labels(path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    if path.exists():
        for line in open(path):
            e = json.loads(line)
            labels[e["crop"]] = e["label"]
    return labels


def report(args: argparse.Namespace) -> None:
    work = args.workdir
    manifest = [json.loads(line) for line in open(work / "manifest.jsonl")]
    labels = _read_labels(work / "labels.jsonl")

    lines = ["# Face-recall check — disputed detections, human-judged", ""]
    for who, name in (("python_only", "SCRFD-only (python's extra faces)"),
                      ("swift_only", "Vision-only (swift's extra faces)")):
        counts = {"real": 0, "not_face": 0, "unclear": 0, "unlabelled": 0}
        for e in manifest:
            if e["who"] != who:
                continue
            counts[labels.get(e["crop"], "unlabelled")] += 1
        judged = counts["real"] + counts["not_face"]
        lines += [f"## {name}",
                  f"- {sum(counts.values())} disputed: "
                  f"{counts['real']} real, {counts['not_face']} not faces, "
                  f"{counts['unclear']} unclear, "
                  f"{counts['unlabelled']} unlabelled"]
        if judged:
            lines.append(f"- **precision of the extras: "
                         f"{counts['real'] / judged:.0%}**")
        lines.append("")
    lines += ["_Extras that are REAL faces = recall the other detector "
              "missed (good). Extras that are NOT faces = phantom subjects "
              "feeding blink/quality metrics (bad). This decides whether "
              "SCRFD's 77-vs-56 count is an edge or a liability "
              "(design 13 §4)._"]
    out = work / "face_recall_report.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    root = Path(__file__).resolve().parents[2]

    p = sub.add_parser("prepare")
    p.add_argument("target", type=Path)
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--workdir", type=Path, default=Path("face_check"))
    p.add_argument("--swift", type=Path,
                   default=root / "helper/.build/debug/shootr-analyze")
    p.add_argument("--python", type=Path,
                   default=Path(sys.executable).parent / "shootr-analyze-py")

    s = sub.add_parser("serve")
    s.add_argument("--workdir", type=Path, default=Path("face_check"))
    s.add_argument("--port", type=int, default=8894)
    s.add_argument("--no-browser", action="store_true")

    r = sub.add_parser("report")
    r.add_argument("--workdir", type=Path, default=Path("face_check"))

    args = ap.parse_args()
    {"prepare": prepare, "serve": serve, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
