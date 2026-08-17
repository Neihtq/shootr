/** Full-res eye crops side by side (design 11 §3): "is the eye actually
 * sharp?" — the verification view behind the eye_focus number. */

import { eyeCropUrl } from "../api/client";
import type { PhotoDetail } from "../api/types";

export function EyeCrops({ photo }: { photo: PhotoDetail }) {
  const primary = photo.faces[0];
  if (!primary) return null;
  return (
    <div className="flex gap-2 p-2">
      {(["left", "right"] as const).map((eye) => {
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
