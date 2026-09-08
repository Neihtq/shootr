/** Write dialog for predicted develop settings (design 08 §7a, same shape as
 * the selects ExportDialog / design 11 §7).
 *
 * States the counts before writing, requires an explicit confirmation, and
 * never defaults the writing action to yes. Conflicts — sidecars that already
 * hold the user's own develop settings — get NO override control, because the
 * engine has no override parameter: they are skipped and reported, and the
 * copy says so plainly (design 08 §6, README rule 3).
 *
 * The per-parameter opt-out is enforced by the engine on this path, so the
 * excluded parameters are simply reported as not written — the dialog states
 * the write's real scope, it does not filter anything itself.
 *
 * The write names its source: the model the preview ran with is sent by id, so
 * what lands in the files comes from the model whose numbers the user just
 * read, and the engine echoes it back in the result (design 08 §7b).
 */

import { useState } from "react";
import { useStyleExportDevelop } from "../api/hooks";
import type { StyleExportResult, StyleModel } from "../api/types";
import { abstainCopy, methodTitle, paramLabel } from "../style";

export function StyleWriteDialog({
  shootId,
  family,
  model,
  processVersion,
  photoIds,
  abstainCount,
  excludedParams,
  withheldCount,
  onClose,
}: {
  shootId: number;
  /** Resolved family from the preview — never re-derived here. */
  family: number;
  /** The model that produced the preview, or null when the engine used its
   * built-in default (there is then no id to pin the write to). */
  model: StyleModel | null;
  processVersion: string;
  /** Photos the engine produced a prediction for, in preview order. */
  photoIds: number[];
  abstainCount: number;
  /** The engine's exclusion list as it applied to the preview: these are
   * predicted but will not be written. Named, not quietly dropped. */
  excludedParams: string[];
  /** Previewed photos where a value was actually withheld. */
  withheldCount: number;
  onClose: () => void;
}) {
  const write = useStyleExportDevelop(shootId);
  const [result, setResult] = useState<StyleExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = () => {
    setError(null);
    write.mutate(
      {
        family,
        photo_ids: photoIds,
        // Omitted when there is no model: the engine then uses the active one,
        // exactly as it did for the preview.
        ...(model === null ? {} : { model_id: model.id }),
      },
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
              <li className="text-neutral-400">
                {/* Which predictor's values are about to land in the files. */}
                {model === null ? (
                  <>
                    From the engine's built-in default (nearest edits across all
                    imported history) — no style model was chosen.
                  </>
                ) : (
                  <>
                    From your model <span className="text-neutral-200">{model.name}</span>{" "}
                    — {methodTitle(model.method)}, learned{" "}
                    {model.trained_at ?? "never"} from {model.history_n} edited
                    photo{model.history_n === 1 ? "" : "s"}.
                  </>
                )}
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

            {excludedParams.length > 0 && (
              // The engine holds this list and enforces it on the write path,
              // so this is a statement of fact about the files, not a UI hint.
              <div className="mb-3 rounded border border-neutral-700 bg-neutral-800/40 p-2 text-xs text-neutral-300">
                {excludedParams.length} parameter
                {excludedParams.length === 1 ? "" : "s"} you excluded{" "}
                <span className="font-mono">
                  ({excludedParams.map(paramLabel).join(", ")})
                </span>{" "}
                {excludedParams.length === 1 ? "is" : "are"} not written. The
                engine leaves {excludedParams.length === 1 ? "it" : "them"} out
                of every sidecar on this run
                {withheldCount > 0 && (
                  <>
                    {" "}
                    — {withheldCount} of these photos had a predicted value for{" "}
                    {excludedParams.length === 1 ? "it" : "one of them"}, shown
                    struck through in the preview
                  </>
                )}
                . Those sliders stay as they are in Lightroom, yours to set.
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
              {result.written.length === 1 ? "" : "s"}
              {/* The engine names the model it used; relayed so the record of
                  the write says where the values came from. */}
              {result.model !== null
                ? ` from ${result.model.name} (${result.model.method}).`
                : " from the engine's built-in default predictor."}
            </div>

            {result.excluded_params.length > 0 && (
              // The engine reports back which exclusions it honoured; relayed
              // so the write's scope is confirmed rather than assumed.
              <div className="mb-3 text-xs text-neutral-400">
                Left out, as you asked:{" "}
                <span className="font-mono">
                  {result.excluded_params.map(paramLabel).join(", ")}
                </span>
                . No value for {result.excluded_params.length === 1 ? "it" : "them"}{" "}
                was written to any of these files.
              </div>
            )}

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
