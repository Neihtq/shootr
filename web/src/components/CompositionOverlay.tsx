/** Composition overlay (design 11 §3): face boxes + thirds grid, so the
 * user can judge whether a composition flag is fair. Pure rendering of
 * engine data — the client computes nothing. */

import type { PhotoDetail } from "../api/types";

export function CompositionOverlay({
  photo,
  visible,
}: {
  photo: PhotoDetail;
  visible: boolean;
}) {
  if (!visible) return null;
  return (
    <div className="pointer-events-none absolute inset-0">
      {/* Rule-of-thirds grid */}
      {[1, 2].map((i) => (
        <div key={`v${i}`}>
          <div
            className="absolute h-full w-px bg-white/25"
            style={{ left: `${(i * 100) / 3}%` }}
          />
          <div
            className="absolute w-full border-t border-white/25"
            style={{ top: `${(i * 100) / 3}%` }}
          />
        </div>
      ))}
      {/* Face boxes — Vision origin is bottom-left; CSS top-left */}
      {photo.faces.map((f) => {
        const [x, y, w, h] = f.bbox;
        return (
          <div
            key={f.idx}
            className="absolute border border-amber-300/70"
            style={{
              left: `${x * 100}%`,
              bottom: `${y * 100}%`,
              width: `${w * 100}%`,
              height: `${h * 100}%`,
            }}
          >
            <span className="absolute -top-4 left-0 text-[9px] text-amber-300/90">
              face {f.idx}
            </span>
          </div>
        );
      })}
    </div>
  );
}
