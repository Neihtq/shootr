"""Is `sharpness_max` comparable across cameras and exposures? (design 03 §3.1)

Found by public Fuji samples (2026-08-30): a visibly sharp X-E5 cityscape
measures 0.00065 — below `MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS` (0.005) — so
the scorer calls it `motion_blur_or_shake` and scores its sharpness 0.
Absolute Tenengrad on a linear-gamma decode scales with the scene's own
contrast and level, and every threshold in scoring.py was calibrated on one
bright Canon shoot.

This measures candidate surfaces against four requirements at once:

  1. **Cross-source comparability** — the spread of "known sharp" photos
     across vendors must shrink (that is the bug).
  2. **Within-shoot ranking preserved** — Spearman vs the current metric on
     one shoot's files. A candidate that reorders a shoot invalidates the
     existing calibration for no benefit.
  3. **Focus discrimination kept** — the synthetic blur ladder must still
     fall steeply (a contrast-normalized metric can flatten it).
  4. **Floor clearance** — the Fuji reproducer must land above a
     recalibrated floor while its blurred copy stays below.

Candidates:
  current   tenengrad(luminance)                     (absolute)
  ranged    tenengrad(luminance rescaled p99.5→235)  (level-normalized)
  varnorm   Σ|∇I|² / Σ(I−Ī)² per tile                (contrast-normalized)

Usage:
  python engine/tools/sharpness_norm_probe.py --cross DIR --shoot DIR
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analyzer"))

from shootr_analyzer.decode import decode_measurement  # noqa: E402
from shootr_analyzer.sharpness import TILE_GRID, tenengrad, tile_map  # noqa: E402

BLUR_SIGMAS = (0.0, 0.7, 1.5)


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return img
    r = max(1, int(3 * sigma))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    pad = np.pad(img.astype(np.float64), ((0, 0), (r, r)), "edge")
    out = np.apply_along_axis(lambda row: np.convolve(row, k, "valid"), 1, pad)
    pad = np.pad(out, ((r, r), (0, 0)), "edge")
    out = np.apply_along_axis(lambda col: np.convolve(col, k, "valid"), 0, pad)
    return np.clip(out, 0, 255).astype(np.uint8)


def _rescale(lum: np.ndarray) -> np.ndarray:
    """Level-normalize: map the photo's own p99.5 to 235."""
    hi = float(np.percentile(lum, 99.5))
    if hi <= 1:
        return lum
    return np.clip(lum.astype(np.float64) * (235.0 / hi), 0, 255).astype(
        np.uint8)


def _varnorm_tile(tile: np.ndarray) -> float:
    """Gradient energy over intensity variance — invariant to both gain and
    offset, so a dim flat-contrast scene is judged on structure alone."""
    p = tile.astype(np.float64)
    if p.shape[0] <= 2 or p.shape[1] <= 2:
        return 0.0
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - \
         (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - \
         (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    energy = float(np.sum(gx * gx + gy * gy)) / (16.0 * p[1:-1, 1:-1].size)
    var = float(np.var(p))
    return energy / var if var > 1e-6 else 0.0


def _tile_max(lum: np.ndarray, fn) -> float:
    h, w = lum.shape
    th, tw = h // TILE_GRID, w // TILE_GRID
    if th <= 2 or tw <= 2:
        return 0.0
    return max(fn(lum[r * th:(r + 1) * th, c * tw:(c + 1) * tw])
               for r in range(TILE_GRID) for c in range(TILE_GRID))


def measures(lum: np.ndarray) -> dict[str, float]:
    return {
        "current": tile_map(lum).max,
        "ranged": tile_map(_rescale(lum)).max,
        "varnorm": _tile_max(lum, _varnorm_tile),
    }


def spearman(a, b) -> float:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cross", type=Path, required=True,
                    help="dir of mixed-vendor sharp samples")
    ap.add_argument("--shoot", type=Path, required=True,
                    help="dir of one shoot's RAWs (ranking check)")
    ap.add_argument("--shoot-pattern", default="*.CR3")
    ap.add_argument("--shoot-n", type=int, default=24)
    args = ap.parse_args()

    print("--- 1/4 cross-source comparability (all judged sharp) ---")
    cross = sorted(p for p in args.cross.iterdir()
                   if p.suffix.lower() in (".arw", ".raf", ".cr3", ".cr2"))
    rows = {}
    for f in cross:
        lum = decode_measurement(f, 0.5).luminance
        rows[f.name] = measures(lum)
        m = rows[f.name]
        print(f"  {f.name[:38]:38} current={m['current']:.5f} "
              f"ranged={m['ranged']:.5f} varnorm={m['varnorm']:.5f}")
    print(f"\n  {'metric':>8} {'min':>10} {'max':>10} {'spread×':>9}")
    for key in ("current", "ranged", "varnorm"):
        vals = [m[key] for m in rows.values()]
        lo, hi = min(vals), max(vals)
        print(f"  {key:>8} {lo:>10.5f} {hi:>10.5f} "
              f"{hi / lo if lo else float('inf'):>9.1f}")

    print("\n--- 2/4 within-shoot ranking vs current (Spearman) ---")
    files = sorted(args.shoot.glob(args.shoot_pattern))
    step = max(1, len(files) // args.shoot_n)
    files = files[::step][:args.shoot_n]
    shoot_rows = []
    for f in files:
        shoot_rows.append(measures(decode_measurement(f, 0.5).luminance))
    for key in ("ranged", "varnorm"):
        rho = spearman([r[key] for r in shoot_rows],
                       [r["current"] for r in shoot_rows])
        print(f"  {key:>8} ρ={rho:.3f} over {len(shoot_rows)} files")

    print("\n--- 3/4 focus discrimination (blur ladder, normalized to σ=0) ---")
    ladder: dict[str, list[list[float]]] = {k: [] for k in
                                            ("current", "ranged", "varnorm")}
    for f in files[:6]:
        lum = decode_measurement(f, 0.5).luminance
        per_sigma = [measures(gaussian_blur(lum, s)) for s in BLUR_SIGMAS]
        for key in ladder:
            base = per_sigma[0][key] or float("nan")
            ladder[key].append([p[key] / base for p in per_sigma])
    print(f"  {'metric':>8} " + " ".join(f"σ={s:<5}" for s in BLUR_SIGMAS))
    for key, rowset in ladder.items():
        means = [statistics.mean([r[i] for r in rowset])
                 for i in range(len(BLUR_SIGMAS))]
        print(f"  {key:>8} " + " ".join(f"{m:<7.3f}" for m in means))

    print("\n--- 4/4 floor clearance on the reproducer ---")
    repro = next((p for p in cross if p.name.startswith("DSCF0202")), None)
    if repro:
        lum = decode_measurement(repro, 0.5).luminance
        sharp = measures(lum)
        blurred = measures(gaussian_blur(lum, 3.0))
        for key in ("current", "ranged", "varnorm"):
            others = [m[key] for n, m in rows.items()
                      if not n.startswith("DSCF0202")]
            print(f"  {key:>8} sharp={sharp[key]:.5f} blurred={blurred[key]:.5f} "
                  f"ratio={sharp[key] / blurred[key] if blurred[key] else float('inf'):.1f}× "
                  f"(other sharp files min {min(others):.5f})")


if __name__ == "__main__":
    main()
