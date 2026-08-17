/** Compare view (design 11 §4): 2–4 frames, SYNCED pan and zoom.
 *
 * Synced zoom is the requirement, not a nicety — the judgement is "which of
 * these nearly identical frames has sharper eyes", and that's impossible
 * unless all panes are at the same magnification on the same feature.
 * Default zoom snaps to the primary face at 100%.
 *
 * One shared transform state drives every pane; there is no per-pane zoom.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { thumbUrl } from "../api/client";
import { usePhoto } from "../api/hooks";
import type { PhotoDetail } from "../api/types";

interface Transform {
  scale: number; // 1 = fit
  x: number; // pan offsets in container px
  y: number;
}

const ZOOM_100 = 4; // 2048px thumb in a ~512px pane ≈ pixel-level inspection

/** Initial pan that centers the primary face when zoomed (design 11 §4). */
function faceCenteredTransform(photo: PhotoDetail | undefined): Transform {
  const face = photo?.faces[0];
  if (!face) return { scale: ZOOM_100, x: 0, y: 0 };
  const [bx, by, bw, bh] = face.bbox;
  // Face center in image fraction; Vision origin bottom-left → flip y.
  const cx = bx + bw / 2;
  const cy = 1 - (by + bh / 2);
  // Pan so the face center lands mid-pane (offsets are fractions of pane
  // size scaled by zoom; container-relative math done in render).
  return { scale: ZOOM_100, x: 0.5 - cx, y: 0.5 - cy };
}

export function CompareView({
  photoIds,
  onClose,
  onSelect,
}: {
  photoIds: number[];
  onClose: () => void;
  onSelect: (photoId: number) => void;
}) {
  const first = usePhoto(photoIds[0] ?? null);
  const [t, setT] = useState<Transform>({ scale: 1, x: 0, y: 0 });
  const [active, setActive] = useState(0);
  const dragging = useRef<{ px: number; py: number } | null>(null);

  // Snap to the primary face at 100% once the first photo loads (§4).
  useEffect(() => {
    if (first.data) setT(faceCenteredTransform(first.data));
  }, [first.data]);

  const toggleZoom = useCallback(() => {
    setT((cur) =>
      cur.scale > 1
        ? { scale: 1, x: 0, y: 0 }
        : faceCenteredTransform(first.data),
    );
  }, [first.data]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" || ev.key === "c") onClose();
      else if (ev.key === "z") toggleZoom();
      else if (ev.key >= "1" && ev.key <= "4") {
        const i = Number(ev.key) - 1;
        if (i < photoIds.length) {
          setActive(i);
          onSelect(photoIds[i]);
        }
      } else return;
      ev.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [photoIds, onClose, onSelect, toggleZoom]);

  // Shared pan: dragging any pane moves all panes (they share `t`).
  const onPointerDown = (ev: React.PointerEvent) => {
    dragging.current = { px: ev.clientX, py: ev.clientY };
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    if (!dragging.current || t.scale <= 1) return;
    const dx = ev.clientX - dragging.current.px;
    const dy = ev.clientY - dragging.current.py;
    dragging.current = { px: ev.clientX, py: ev.clientY };
    const pane = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    setT((cur) => ({
      ...cur,
      x: cur.x + dx / (pane.width * cur.scale),
      y: cur.y + dy / (pane.height * cur.scale),
    }));
  };
  const onPointerUp = () => {
    dragging.current = null;
  };

  const cols = photoIds.length <= 2 ? photoIds.length : 2;

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-neutral-950">
      <div className="flex items-center gap-3 border-b border-neutral-800 px-3 py-1.5 text-xs text-neutral-400">
        <span>
          Compare · {photoIds.length} frames · drag to pan (synced) ·{" "}
          <kbd className="rounded bg-neutral-800 px-1">Z</kbd> 100%/fit ·{" "}
          <kbd className="rounded bg-neutral-800 px-1">1–4</kbd> pick focus ·{" "}
          <kbd className="rounded bg-neutral-800 px-1">Esc</kbd> close
        </span>
        <span className="ml-auto">{t.scale > 1 ? "100%" : "fit"}</span>
        <button
          onClick={onClose}
          className="rounded border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800"
        >
          Close
        </button>
      </div>

      <div
        className="grid min-h-0 flex-1 gap-0.5"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {photoIds.map((pid, i) => (
          <ComparePane
            key={pid}
            photoId={pid}
            index={i}
            isActive={i === active}
            transform={t}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onClick={() => {
              setActive(i);
              onSelect(pid);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function ComparePane({
  photoId,
  index,
  isActive,
  transform: t,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: {
  photoId: number;
  index: number;
  isActive: boolean;
  transform: Transform;
  onPointerDown: (ev: React.PointerEvent) => void;
  onPointerMove: (ev: React.PointerEvent) => void;
  onPointerUp: () => void;
  onClick: () => void;
}) {
  const { data: photo } = usePhoto(photoId);
  const eyes = photo?.faces[0]?.eyes;
  return (
    <div
      className={`relative min-h-0 cursor-grab overflow-hidden bg-black active:cursor-grabbing ${
        isActive ? "ring-1 ring-inset ring-neutral-400" : ""
      }`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={onClick}
    >
      <img
        src={thumbUrl(photoId, 2048)}
        alt={photo?.filename ?? `photo ${photoId}`}
        draggable={false}
        className="h-full w-full select-none object-contain"
        style={{
          // One shared transform: same magnification, same feature, every pane.
          transform: `scale(${t.scale}) translate(${t.x * 100}%, ${t.y * 100}%)`,
          transformOrigin: "center",
        }}
      />
      <div className="absolute left-1.5 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-neutral-300">
        {index + 1} · {photo?.filename}
        {photo?.selection && (
          <span className="ml-1 uppercase text-neutral-400">
            {photo.selection.state}
          </span>
        )}
      </div>
      {eyes && (
        <div className="absolute bottom-1 left-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-neutral-400">
          eyes {eyes.left.sharp_norm?.toFixed(2) ?? "—"} /{" "}
          {eyes.right.sharp_norm?.toFixed(2) ?? "—"}
        </div>
      )}
    </div>
  );
}
