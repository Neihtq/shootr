/** 16×16 tile heatmap over the frame (design 11 §3): makes "focus missed —
 * it hit the shoulder" legible in one glance instead of a claim taken on
 * faith. Pure rendering of engine data. */

import { useSharpnessMap } from "../api/hooks";

export function SharpnessOverlay({
  photoId,
  visible,
}: {
  photoId: number;
  visible: boolean;
}) {
  const { data } = useSharpnessMap(photoId, visible);
  if (!visible || !data?.tiles || !data.max) return null;
  return (
    <div className="pointer-events-none absolute inset-0 grid grid-cols-16 grid-rows-16">
      {data.tiles.flatMap((row, y) =>
        row.map((v, x) => (
          <div
            key={`${x}-${y}`}
            style={{
              // Vision origin is bottom-left; CSS grid is top-down.
              gridRow: 16 - y,
              gridColumn: x + 1,
              backgroundColor: `rgba(255, 80, 40, ${
                data.max ? Math.min(0.65, (v / data.max) * 0.65) : 0
              })`,
            }}
          />
        )),
      )}
    </div>
  );
}
