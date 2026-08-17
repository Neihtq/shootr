/** Export dialog (design 11 §7): wraps the §07 safety protocol. Calls
 * export/preview first, shows the engine-computed diff, and never defaults
 * the destructive option to yes. The client only renders the diff — it
 * never decides what counts as a conflict (design 10 §2). */

import { useEffect, useState } from "react";
import { useExport, useExportPreview } from "../api/hooks";
import type { ExportPreview } from "../api/types";

export function ExportDialog({
  selectionId,
  onClose,
}: {
  selectionId: number;
  onClose: () => void;
}) {
  const preview = useExportPreview(selectionId);
  const doExport = useExport(selectionId);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    preview.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionId]);

  const p: ExportPreview | undefined = preview.data;

  const run = (confirmOverwrite: boolean) =>
    doExport.mutate(confirmOverwrite, {
      onSuccess: (r) => setResult(`Wrote ${r.written} sidecars.`),
      onError: (e) => setResult(`Failed: ${e.message}`),
    });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-[28rem] rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">Export selects to XMP</h2>

        {!p && <div className="text-neutral-400">Computing diff…</div>}

        {p && !result && (
          <>
            <ul className="mb-4 space-y-1 text-xs">
              <li>✓ {p.new_sidecars} new sidecars</li>
              {p.updates > 0 && <li>✎ {p.updates} sidecars updated (no develop settings)</li>}
              {p.conflicts.length > 0 && (
                <li className="text-amber-300">
                  ⚠ {p.conflicts.length} existing sidecars WITH develop settings
                  — requires explicit confirmation
                </li>
              )}
              {p.skipped_dng.length > 0 && (
                <li className="text-neutral-400">
                  ⓘ {p.skipped_dng.length} DNG files will be skipped (sidecar
                  writeback unsupported)
                </li>
              )}
              {p.unchanged > 0 && <li className="text-neutral-500">{p.unchanged} unchanged</li>}
              <li className="pt-1 text-neutral-500">Backups → {p.backup_dir}</li>
            </ul>

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={() => run(false)}
                className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700"
              >
                {p.conflicts.length > 0 ? "Skip conflicts" : "Write"}
              </button>
              {p.conflicts.length > 0 && (
                <button
                  onClick={() => run(true)}
                  className="rounded border border-amber-700 bg-amber-950 px-3 py-1 text-amber-200 hover:bg-amber-900"
                >
                  Overwrite {p.conflicts.length} (backed up)
                </button>
              )}
            </div>
          </>
        )}

        {result && (
          <>
            <div className="mb-3">{result}</div>
            <div className="text-xs text-neutral-400">
              In Lightroom: select the photos, then{" "}
              <em>Metadata → Read Metadata from Files</em>. Note: this
              overwrites catalog metadata from the files — LrC's behavior,
              not ours.
            </div>
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
