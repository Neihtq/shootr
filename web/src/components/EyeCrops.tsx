/** Full-res eye crops side by side (design 11 §3): "is the eye actually
 * sharp / is the subject blinking?" — the verification view behind the
 * eye_focus and eyes_open numbers. Two placements: the evidence panel
 * (always) and a loupe overlay toggled with B. */

import { eyeCropUrl } from "../api/client";
import type { PhotoDetail } from "../api/types";

// Image-left first: a camera-facing subject's RIGHT eye is on image left.
const EYE_ORDER = ["right", "left"] as const;

export function EyeCrops({ photo }: { photo: PhotoDetail }) {
  const primary = photo.faces[0];
  if (!primary) return null;
  return (
    <div className="flex gap-2 p-2">
      {EYE_ORDER.map((eye) => {
        const data = primary.eyes[eye];
        return (
          <figure key={eye} className="flex-1">
            <div className="aspect-square overflow-hidden rounded bg-neutral-900">
              <img
                src={eyeCropUrl(photo.id, primary.idx, eye)}
                alt={`${eye} eye at full resolution`}
                className="h-full w-full object-cover"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-1 text-center text-[10px] text-neutral-400">
              {eye}
              {" · sharp "}
              {data.sharp_norm === null ? "—" : data.sharp_norm.toFixed(2)}
              {" · open "}
              {data.open === null ? "—" : data.open.toFixed(2)}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}

/** B — the blink check floated over the loupe: a blink is invisible at fit
 * zoom, and this answers it without opening 100% or the evidence panel. */
export function EyeOverlay({
  photo,
  visible,
}: {
  photo: PhotoDetail;
  visible: boolean;
}) {
  if (!visible) return null;
  const primary = photo.faces[0];
  return (
    <div className="pointer-events-none absolute bottom-3 right-3 rounded-lg bg-black/70 p-2">
      {primary ? (
        <div className="flex gap-2">
          {EYE_ORDER.map((eye) => {
            const data = primary.eyes[eye];
            return (
              <figure key={eye}>
                <img
                  src={eyeCropUrl(photo.id, primary.idx, eye)}
                  alt={`${eye} eye`}
                  className="h-24 w-36 rounded object-cover"
                />
                <figcaption className="mt-0.5 text-center text-[10px] text-neutral-300">
                  {eye} · open{" "}
                  {data.open === null ? "—" : data.open.toFixed(2)}
                </figcaption>
              </figure>
            );
          })}
        </div>
      ) : (
        <span className="text-[10px] text-neutral-400">no face detected</span>
      )}
    </div>
  );
}
