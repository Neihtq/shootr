"""A/B harness: Swift helper vs Python analyzer over the same files —
the design 13 §4 adoption gate, as a runnable report.

    .venv/bin/python engine/tools/ab_analyzers.py <photo-dir-or-file-list> \
        [--limit N] [--scale 0.5] [--out report.md]

Runs both analyzers batch-wise over the same photos (no DB involved — raw
JSONL side by side), then reports:
  1. sharpness ranking agreement (Spearman) + biggest disagreements
  2. face count agreement, eye-open values side by side (the labelling aid
     for the blink benchmark — hand-label these frames, design 03 §7)
  3. embedding neighborhoods: top-k cosine-neighbor Jaccard overlap
  4. grouping stability: group_shots() count/size distribution per embedding
  5. timing percentiles → 10k projection vs the "overnight on M4" bar

Adoption criteria live in the doc; this prints the numbers, honestly,
including what it could NOT measure (no labels → no blink accuracy claim).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shootr import helper  # noqa: E402
from shootr.grouping import PhotoFeatures, group_shots  # noqa: E402

RAW_SUFFIXES = {".cr2", ".cr3", ".arw", ".raf", ".dng", ".jpg", ".jpeg"}


def collect_files(target: Path, limit: int) -> list[Path]:
    if target.is_file() and target.suffix == ".json":
        files = [Path(p) for p in json.loads(target.read_text())]
    elif target.is_file():
        files = [target]
    else:
        files = sorted(p for p in target.rglob("*")
                       if p.suffix.lower() in RAW_SUFFIXES)
    return files[:limit] if limit else files


def run_analyzer(binary: Path, files: list[Path], scale: float,
                 label: str) -> tuple[dict[str, dict], list[float]]:
    """{path: result}, wall-clock seconds per emitted line."""
    import os

    os.environ["SHOOTR_HELPER"] = str(binary)
    out: dict[str, dict] = {}
    laps: list[float] = []
    t = time.monotonic()
    done = 0
    for result in helper.analyze_batch(files, scale=scale):
        now = time.monotonic()
        laps.append(now - t)
        t = now
        done += 1
        if done % 25 == 0:
            print(f"  {label}: {done}/{len(files)}", file=sys.stderr)
        if path := result.get("path"):
            out[path] = result
    return out, laps


# --- metrics -----------------------------------------------------------------


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for rank, i in enumerate(order):
            r[i] = float(rank)
        return r

    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else float("nan")


def unpack(emb_b64: str) -> list[float]:
    import struct

    raw = base64.b64decode(emb_b64)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def cosine_dist(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / (na * nb) if na and nb else 1.0


def neighbor_jaccard(embs_a: dict[str, list[float]],
                     embs_b: dict[str, list[float]], k: int = 5) -> float:
    """Mean Jaccard of each photo's top-k neighbor sets under the two
    embeddings — 'do they agree what looks similar', dimension-free."""
    shared = sorted(set(embs_a) & set(embs_b))
    if len(shared) < k + 2:
        return float("nan")

    def topk(embs: dict[str, list[float]], p: str) -> set[str]:
        dists = [(cosine_dist(embs[p], embs[q]), q)
                 for q in shared if q != p]
        return {q for _, q in sorted(dists)[:k]}

    scores = []
    for p in shared:
        na, nb = topk(embs_a, p), topk(embs_b, p)
        scores.append(len(na & nb) / len(na | nb))
    return statistics.mean(scores)


def group_stats(results: dict[str, dict], probes: dict[str, dict],
                profile: str = "event") -> str:
    feats = []
    for path, r in sorted(results.items()):
        if "error" in r or not r.get("embedding"):
            continue
        p = probes.get(path, {})
        captured = p.get("captured_at")
        if not captured:
            continue
        from datetime import datetime

        feats.append(PhotoFeatures(
            photo_id=hash(path) & 0x7FFFFFFF,
            captured_at=datetime.fromisoformat(captured),
            subsec=p.get("subsec") or 0,
            exposure_bias=p.get("exposure_bias") or 0.0,
            embedding=tuple(unpack(r["embedding"])),
            face_count=len(r.get("faces", [])),
        ))
    if len(feats) < 2:
        return "not enough grouped photos"
    groups = group_shots(feats, profile=profile)
    sizes = sorted(len(g.member_ids) for g in groups)
    singletons = sum(1 for s in sizes if s == 1)
    return (f"{len(groups)} groups, {singletons} singletons, "
            f"median size {sizes[len(sizes) // 2]}")


def pct(laps: list[float], p: float) -> float:
    if not laps:
        return float("nan")
    return sorted(laps)[min(len(laps) - 1, int(len(laps) * p))]


# --- report ------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--profile", default="event")
    ap.add_argument("--out", type=Path, default=Path("ab_report.md"))
    ap.add_argument("--swift", type=Path,
                    default=Path(__file__).resolve().parents[2]
                    / "helper/.build/debug/shootr-analyze")
    ap.add_argument("--python", type=Path,
                    default=Path(sys.executable).parent / "shootr-analyze-py")
    args = ap.parse_args()

    files = collect_files(args.target, args.limit)
    if not files:
        sys.exit("no files found")
    print(f"{len(files)} files, scale {args.scale}", file=sys.stderr)

    # Probes once (Swift — probe parity is tested separately) for capture
    # times the grouping comparison needs.
    import os

    os.environ["SHOOTR_HELPER"] = str(args.swift)
    probes = {r["path"]: r for r in helper.probe_batch(files)
              if "error" not in r}

    swift, swift_laps = run_analyzer(args.swift, files, args.scale, "swift")
    py, py_laps = run_analyzer(args.python, files, args.scale, "python")

    shared = sorted(set(swift) & set(py))
    ok = [p for p in shared
          if "error" not in swift[p] and "error" not in py[p]]

    lines = ["# Analyzer A/B — Swift (Vision/CIRAWFilter) vs Python "
             "(ONNX/libraw)", "",
             f"{len(files)} files · scale {args.scale} · "
             f"{len(ok)} analyzed by both "
             f"(swift errors: {sum(1 for p in shared if 'error' in swift[p])}, "
             f"python errors: {sum(1 for p in shared if 'error' in py[p])})",
             ""]

    # 1 — sharpness
    sm_a = [swift[p]["frame"]["sharpness_max"] for p in ok]
    sm_b = [py[p]["frame"]["sharpness_max"] for p in ok]
    lines += ["## 1. Sharpness ranking",
              f"- Spearman(sharpness_max): **{spearman(sm_a, sm_b):.3f}**"]
    ranked_a = sorted(range(len(ok)), key=lambda i: -sm_a[i])
    ranked_b = sorted(range(len(ok)), key=lambda i: -sm_b[i])
    pos_b = {i: r for r, i in enumerate(ranked_b)}
    worst = sorted(range(len(ok)),
                   key=lambda i: -abs(ranked_a.index(i) - pos_b[i]))[:5]
    lines += ["- biggest rank disagreements:"]
    for i in worst:
        lines.append(f"    - {Path(ok[i]).name}: swift #{ranked_a.index(i)}"
                     f" vs python #{pos_b[i]}")

    # 2 — faces
    fa = [len(swift[p].get("faces", [])) for p in ok]
    fb = [len(py[p].get("faces", [])) for p in ok]
    agree = sum(1 for a, b in zip(fa, fb) if a == b)
    lines += ["", "## 2. Faces",
              f"- face count agreement: **{agree}/{len(ok)}** "
              f"(swift total {sum(fa)}, python total {sum(fb)})",
              "- eye-open side by side (label these frames by hand for the "
              "blink benchmark, design 03 §7):"]
    shown = 0
    for p in ok:
        for i, (sf, pf) in enumerate(zip(swift[p].get("faces", []),
                                         py[p].get("faces", []))):
            se = sf.get("eyes", {})
            pe = pf.get("eyes", {})
            lines.append(
                f"    - {Path(p).name}[{i}] EAR l/r="
                f"{se.get('l', {}).get('open')}/{se.get('r', {}).get('open')}"
                f" · blendshapes l/r="
                f"{pe.get('l', {}).get('open')}/{pe.get('r', {}).get('open')}")
            shown += 1
            if shown >= 15:
                break
        if shown >= 15:
            break

    # 3 — embedding neighborhoods
    embs_a = {p: unpack(swift[p]["embedding"]) for p in ok
              if swift[p].get("embedding")}
    embs_b = {p: unpack(py[p]["embedding"]) for p in ok
              if py[p].get("embedding")}
    lines += ["", "## 3. Embedding neighborhoods",
              f"- top-5 neighbor Jaccard overlap: "
              f"**{neighbor_jaccard(embs_a, embs_b):.3f}** "
              "(1.0 = identical similarity structure; dims "
              f"{len(next(iter(embs_a.values()), []))} vs "
              f"{len(next(iter(embs_b.values()), []))})"]

    # 4 — grouping stability
    lines += ["", "## 4. Grouping (sequential shot clustering, "
              f"profile={args.profile})",
              f"- swift embedding:  {group_stats(swift, probes, args.profile)}",
              f"- python embedding: {group_stats(py, probes, args.profile)}",
              "- NOTE: thresholds were tuned on Vision feature prints "
              "(design 13 §4) — a python-side divergence here means "
              "re-measure thresholds, not necessarily a worse embedding."]

    # 5 — timing
    lines += ["", "## 5. Throughput"]
    for name, laps in (("swift", swift_laps), ("python", py_laps)):
        med = statistics.median(laps) if laps else float("nan")
        proj_h = med * 10_000 / 3600
        lines.append(
            f"- {name}: median {med:.2f}s p90 {pct(laps, 0.9):.2f}s "
            f"p99 {pct(laps, 0.99):.2f}s → 10k ≈ **{proj_h:.1f} h** "
            f"({'within' if proj_h <= 12 else 'OVER'} the overnight bar)")
    lines += ["", "_First-photo laps include model loading; the projection "
              "uses the median, which amortizes it. Blink accuracy is NOT "
              "claimed here — it needs the hand-labelled frames from the "
              "benchmark gate._"]

    args.out.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {args.out}", file=sys.stderr)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
