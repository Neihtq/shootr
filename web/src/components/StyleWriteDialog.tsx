/** Write dialog for predicted develop settings (design 08 §7a, same shape as
 * the selects ExportDialog / design 11 §7).
 *
 * States the counts before writing, requires an explicit confirmation, and
 * never defaults the writing action to yes. Conflicts — sidecars that already
 * hold the user's own develop settings — get NO override control, because the
 * engine has no override parameter: they are skipped and reported, and the
 * copy says so plainly (design 08 §6, README rule 3).
 */

import { useState } from "react";
import { useStyleExportDevelop } from "../api/hooks";
import type { StyleExportResult } from "../api/types";
import { abstainCopy, paramLabel } from "../style";

export function StyleWriteDialog({
  shootId,
  family,
  processVersion,
  photoIds,
  abstainCount,
  hiddenParams,
  onClose,
}: {
  shootId: number;
  /** Resolved family from the preview — never re-derived here. */
  family: number;
  processVersion: string;
  /** Photos the engine produced a prediction for, in preview order. */
  photoIds: number[];
  abstainCount: number;
  /** Parameters hidden by the preview's display filter that the engine will
   * nevertheless write. Named explicitly rather than quietly dropped. */
  hiddenParams: string[];
  onClose: () => void;
}) {
  const write = useStyleExportDevelop(shootId);
  const [result, setResult] = useState<StyleExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = () => {
    setError(null);
    write.mutate(
      { family, photo_ids: photoIds },
      {
        onSuccess: (r) => setResult(r),
        onError: (e) => setError(e.message),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="max-h-[85vh] w-[32rem] overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">
          Write predicted develop settings to XMP
        </h2>

        {!result && (
          <>
            <ul className="mb-3 space-y-1 text-xs">
              <li>
                ✓ {photoIds.length} photo{photoIds.length === 1 ? "" : "s"} to
                write — family {family}, Process Version {processVersion}
              </li>
              {abstainCount > 0 && (
                <li className="text-neutral-400">
                  — {abstainCount} abstaining: the engine has no confident
                  prediction for {abstainCount === 1 ? "it" : "them"}, so
                  nothing at all is written for {abstainCount === 1 ? "it" : "them"}.
                  {" "}Edit {abstainCount === 1 ? "it" : "those"} by hand.
                </li>
              )}
              <li className="text-amber-300">
                ⚠ Conflicts are only known once the write runs: a sidecar that
                already holds your own develop settings is skipped and listed
                afterwards. There is no override — not a checkbox we hid, the
                engine has no such parameter.
              </li>
              <li className="text-neutral-400">
                Global sliders only. Brushes, radial and linear gradients, and
                AI subject/sky masks are never predicted and never written.
                Crop and straighten are left alone too.
              </li>
            </ul>

            {hiddenParams.length > 0 && (
              // Honesty over convenience: the toggles filter the preview, and
              // the endpoint takes no parameter list, so pretending the write
              // honours them would be a lie about the user's files.
              <div className="mb-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
                {hiddenParams.length} parameter
                {hiddenParams.length === 1 ? "" : "s"} you switched off in the
                preview{" "}
                <span className="font-mono">
                  ({hiddenParams.map(paramLabel).join(", ")})
                </span>{" "}
                WILL still be written. The engine's write endpoint applies every
                predicted parameter and takes no per-parameter switch, so the
                toggles filter what you see, not what lands on disk.
                Engine-side opt-out is still to be built (design 08 §6).
              </div>
            )}

            {error && (
              <div className="mb-3 text-xs text-red-400">Failed: {error}</div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={run}
                disabled={write.isPending || photoIds.length === 0}
                className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:opacity-50"
              >
                {write.isPending
                  ? "Writing…"
                  : `Write ${photoIds.length} sidecar${photoIds.length === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        )}

        {result && (
          <>
            <div className="mb-3">
              Wrote {result.written.length} sidecar
              {result.written.length === 1 ? "" : "s"}.
            </div>

            {result.abstained.length > 0 && (
              <div className="mb-3 text-xs text-neutral-400">
                {result.abstained.length} photo
                {result.abstained.length === 1 ? "" : "s"} abstained and were
                left without predicted settings:
                <ul className="mt-1 space-y-0.5">
                  {result.abstained.slice(0, 6).map((a) => (
                    <li key={a.photo_id}>
                      photo {a.photo_id} — {abstainCopy(a.reason)}
                    </li>
                  ))}
                  {result.abstained.length > 6 && (
                    <li>+{result.abstained.length - 6} more</li>
                  )}
                </ul>
              </div>
            )}

            {result.conflicts.length > 0 && (
              <div className="mb-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
                {result.conflicts.length} sidecar
                {result.conflicts.length === 1 ? "" : "s"} already held your own
                develop settings and were left untouched:
                <ul className="mt-1 space-y-0.5 break-all font-mono text-[10px]">
                  {result.conflicts.slice(0, 6).map((c) => (
                    <li key={c.photo_id}>{c.path}</li>
                  ))}
                  {result.conflicts.length > 6 && (
                    <li>+{result.conflicts.length - 6} more</li>
                  )}
                </ul>
                {/* Relayed verbatim rather than paraphrased. */}
                <div className="mt-1">Engine: {result.note}.</div>
              </div>
            )}

            {result.written.length > 0 && (
              <div className="text-xs text-neutral-400">
                In Lightroom: select the photos, then{" "}
                <em>Metadata → Read Metadata from Files</em>. Note: this
                overwrites catalog metadata from the files — LrC's behavior,
                not ours.
              </div>
            )}

            <div className="mt-3 flex justify-end">
              <button
                onClick={onClose}
                className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
