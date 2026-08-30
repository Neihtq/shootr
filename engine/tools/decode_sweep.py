"""Decode-path benchmark — the two remaining measurable questions of the
design 03 §7 gate that need no new sample formats:

  1. Default decode scale (0.25 / 0.5 / 1.0): does a cheaper decode rank
     photos by sharpness the same way a full decode does?
  2. CFA green plane vs scaled-decode luminance (§3.4): does gradient
     energy on the raw green plane discriminate focus better than the
     demosaiced luminance? If not, per-vendor CFA parsing never gets built.

Two measurements per question, because agreement and discrimination are
different things:

  * Ranking agreement — Spearman ρ of `sharpness_max` against the full-res
    luminance reference over real photos. A cheap path that reorders photos
    is unusable regardless of its speed.
  * Focus discrimination — a synthetic blur ladder (σ = 0 … 2 px, applied
    to the decoded surface). Reports each path's monotonicity and how
    steeply it falls at σ = 0.7, i.e. how well it separates a slight focus
    miss from a hit. Caveat stated in the output: Gaussian blur is not
    optical defocus, so this ranks paths against each other — it is not an
    absolute accuracy claim.

Usage:
  python engine/tools/decode_sweep.py --dir DIR [--n 60] [--pattern '*.CR3']
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analyzer"))

from shootr_analyzer.decode import decode_measurement, green_plane  # noqa: E402
from shootr_analyzer.sharpness import tile_map  # noqa: E402

SCALES = (0.25, 0.5, 1.0)
BLUR_SIGMAS = (0.0, 0.7, 1.5, 3.0)


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = float(pos)
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) *
           sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else float("nan")


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian, no scipy."""
    if sigma <= 0:
        return img
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    pad = np.pad(img.astype(np.float64), ((0, 0), (radius, radius)), "edge")
    out = np.apply_along_axis(lambda r: np.convolve(r, k, "valid"), 1, pad)
    pad = np.pad(out, ((radius, radius), (0, 0)), "edge")
    out = np.apply_along_axis(lambda c: np.convolve(c, k, "valid"), 0, pad)
    return np.clip(out, 0, 255).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--pattern", default="*.CR3")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--blur-n", type=int, default=10)
    args = ap.parse_args()

    files = sorted(args.dir.glob(args.pattern))
    step = max(1, len(files) // args.n)
    files = files[::step][:args.n]
    print(f"{len(files)} files from {args.dir}\n")

    sharp: dict[str, list[float]] = {f"scale{s}": [] for s in SCALES}
    sharp["cfa"] = []
    timing: dict[str, list[float]] = {k: [] for k in sharp}

    for i, f in enumerate(files, 1):
        for s in SCALES:
            t0 = time.time()
            d = decode_measurement(f, s)
            v = tile_map(d.luminance).max
            timing[f"scale{s}"].append(time.time() - t0)
            sharp[f"scale{s}"].append(v)
        t0 = time.time()
        g = green_plane(f)
        timing["cfa"].append(time.time() - t0)
        sharp["cfa"].append(tile_map(g).max if g is not None else float("nan"))
        if i % 10 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    ref = sharp["scale1.0"]
    print("\n--- ranking agreement vs full-res luminance (Spearman ρ) ---")
    print(f"{'path':>10} {'rho':>7} {'s/photo':>9} {'median value':>13}")
    for key in ("scale0.25", "scale0.5", "scale1.0", "cfa"):
        vals = sharp[key]
        ok = [(a, b) for a, b in zip(vals, ref) if not np.isnan(a)]
        rho = spearman([a for a, _ in ok], [b for _, b in ok])
        print(f"{key:>10} {rho:>7.3f} {statistics.mean(timing[key]):>9.2f} "
              f"{statistics.median([v for v in vals if not np.isnan(v)]):>13.4f}")

    print("\n--- focus discrimination: synthetic blur ladder ---")
    print("(Gaussian blur is not optical defocus — this ranks the paths "
          "against each other, it is not an absolute accuracy claim)")
    ladders: dict[str, list[list[float]]] = {"scale0.5": [], "scale1.0": [],
                                             "cfa": []}
    for f in files[:args.blur_n]:
        surfaces = {"scale0.5": decode_measurement(f, 0.5).luminance,
                    "scale1.0": decode_measurement(f, 1.0).luminance,
                    "cfa": green_plane(f)}
        for key, surf in surfaces.items():
            if surf is None:
                continue
            ladders[key].append([tile_map(gaussian_blur(surf, s)).max
                                 for s in BLUR_SIGMAS])
    print(f"{'path':>10} " + " ".join(f"σ={s:<4}" for s in BLUR_SIGMAS)
          + "  monotone  drop@0.7")
    for key, rows in ladders.items():
        if not rows:
            continue
        cols = list(zip(*rows))
        # normalize each photo's ladder by its own σ=0 value, then average
        norm = [[r[i] / r[0] if r[0] else float("nan")
                 for i in range(len(BLUR_SIGMAS))] for r in rows]
        means = [statistics.mean([r[i] for r in norm])
                 for i in range(len(BLUR_SIGMAS))]
        monotone = sum(all(r[i] > r[i + 1] for i in range(len(r) - 1))
                       for r in norm)
        print(f"{key:>10} " + " ".join(f"{m:<6.3f}" for m in means)
              + f"  {monotone}/{len(norm)}      {1 - means[1]:.3f}")
        del cols


if __name__ == "__main__":
    main()
