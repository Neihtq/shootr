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

/** B — who is blinking? A marker on EVERY face's eye region with that
 * face's eyes-open value, in place: a group shot answers it at a glance.
 * Color + number, never color alone: green ≥ open, amber = partial blink,
 * red < the calibrated "eyes closed" boundary (design 04 §2.2); gray "—" =
 * detector abstained (abstained ≠ bad). */
export function EyeOverlay({
  photo,
  visible,
}: {
  photo: PhotoDetail;
  visible: boolean;
}) {
  if (!visible) return null;
  if (!photo.faces.length) {
    return (
      <div className="pointer-events-none absolute bottom-3 right-3 rounded-full bg-black/70 px-2 py-1 text-[10px] text-neutral-400">
        no face detected
      </div>
    );
  }
  return (
    <div className="pointer-events-none absolute inset-0">
      {photo.faces.map((f) => {
        const opens = EYE_ORDER.map((e) => f.eyes[e]?.open).filter(
          (v): v is number => v !== null && v !== undefined,
        );
        // min of the two eyes — one closed eye is a blink (design 04 §2.2).
        const open = opens.length ? Math.min(...opens) : null;
        const color =
          open === null
            ? "border-neutral-500 text-neutral-400"
            : open < 0.42
              ? "border-red-500 text-red-300"
              : open < 0.65
                ? "border-amber-400 text-amber-300"
                : "border-emerald-400 text-emerald-300";
        // Eye band = upper part of the face box (55–100% of its height —
        // same heuristic as the eye-crop endpoint; landmarks aren't
        // persisted in M1). Vision bbox is bottom-left normalized.
        const left = f.bbox[0] * 100;
        const width = f.bbox[2] * 100;
        const bandH = f.bbox[3] * 0.45 * 100;
        const top = (1 - f.bbox[1] - f.bbox[3]) * 100;
        return (
          <div key={f.idx}>
            <div
              className={`absolute rounded border-2 ${color}`}
              style={{
                left: `${left}%`,
                top: `${top}%`,
                width: `${width}%`,
                height: `${bandH}%`,
              }}
            />
            <span
              className={`absolute -translate-x-1/2 -translate-y-full rounded-full bg-black/70 px-1.5 text-[10px] ${color}`}
              style={{ left: `${left + width / 2}%`, top: `${top}%` }}
            >
              {open === null ? "—" : open.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
