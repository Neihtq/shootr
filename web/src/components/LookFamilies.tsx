/** Screen 1 — Look families (design 08 §7a).
 *
 * A read-only list of the looks the engine DISCOVERED in the user's own edit
 * history: count, trait label, sample thumbnails, median edit. Families are
 * not editable — they are a measurement of the user's past work, not a
 * setting. Everything shown here comes straight from
 * `GET /api/style/families`; the client computes none of it (design 10 §1).
 */

import { thumbUrl } from "../api/client";
import type { StyleFamily } from "../api/types";
import { formatParam, paramLabel, paramUnit } from "../style";

export function LookFamilies({
  families,
  highlightId,
}: {
  families: StyleFamily[];
  /** The family the prediction preview is currently using, so the user can
   * see which of their looks is being applied. */
  highlightId?: number | null;
}) {
  if (!families.length) {
    return (
      <div className="text-xs text-neutral-500">
        The engine found no look families in the imported history.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {families.map((f) => {
        const median = Object.entries(f.median);
        return (
          <div
            key={f.id}
            className={`rounded border p-3 ${
              f.id === highlightId
                ? "border-sky-800 bg-sky-950/20"
                : "border-neutral-800"
            }`}
          >
            <div className="mb-2 flex items-baseline gap-2 text-xs">
              <span className="text-sm text-neutral-200">Family {f.id}</span>
              <span className="text-neutral-500">
                {f.size} edited photo{f.size === 1 ? "" : "s"}
              </span>
              {f.id === highlightId && (
                <span className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-300">
                  used by the preview below
                </span>
              )}
              <span className="ml-auto font-mono text-[11px] text-neutral-400">
                {f.traits}
              </span>
            </div>

            {f.sample_photo_ids.length > 0 ? (
              <div className="mb-2 flex gap-1.5">
                {f.sample_photo_ids.map((pid) => (
                  <img
                    key={pid}
                    src={thumbUrl(pid, 256)}
                    alt={`family ${f.id} sample, photo ${pid}`}
                    title={`photo ${pid}`}
                    className="h-16 w-24 rounded border border-neutral-800 object-cover"
                    loading="lazy"
                  />
                ))}
              </div>
            ) : (
              <div className="mb-2 text-[11px] text-neutral-500">
                No sample thumbnails — these edited photos are not in a
                scanned library.
              </div>
            )}

            <div className="text-[10px] uppercase tracking-wide text-neutral-500">
              Median edit
            </div>
            {median.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {median.map(([name, value]) => (
                  <span
                    key={name}
                    className="rounded bg-neutral-800/70 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300"
                    title={name}
                  >
                    {paramLabel(name)} {formatParam(name, value)}
                    {paramUnit(name)}
                  </span>
                ))}
              </div>
            ) : (
              // Not "no edits": the engine had no value for any parameter in
              // this family (README rule 8 — null is not zero).
              <div className="mt-1 text-[11px] text-neutral-500">
                — no median values reported for this family
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
