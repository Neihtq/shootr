/** "1/250s · f/1.8 · ISO 800 · 85mm · +0.3 EV" — the photographer's
 * shorthand. Mirrors PhotoDetail.exifLine in the native app; keep in sync. */

import type { PhotoDetail } from "./api/types";

export function exifLine(p: PhotoDetail): string {
  const parts: string[] = [];
  if (p.shutter !== null) {
    parts.push(
      p.shutter >= 1
        ? `${p.shutter.toFixed(1)}s`
        : `1/${Math.round(1 / p.shutter)}s`,
    );
  }
  if (p.aperture !== null) parts.push(`f/${p.aperture.toFixed(1)}`);
  if (p.iso !== null) parts.push(`ISO ${p.iso}`);
  if (p.focal_length !== null) parts.push(`${Math.round(p.focal_length)}mm`);
  if (p.exposure_bias !== null && p.exposure_bias !== 0) {
    const sign = p.exposure_bias > 0 ? "+" : "";
    parts.push(`${sign}${p.exposure_bias.toFixed(1)} EV`);
  }
  return parts.join(" · ");
}
