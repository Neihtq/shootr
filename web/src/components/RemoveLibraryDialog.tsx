/** Remove-library confirmation. Mirrors the native client's alert flow and
 * the export dialog's rules: state plainly what will happen, never default
 * the destructive option to yes. Removal touches only the app database —
 * nothing in this app deletes user files (design README rule 2). If the
 * engine's response notes that exported XMP selections remain on disk, that
 * is relayed verbatim rather than paraphrased. */

import { useState } from "react";
import { useDeleteLibrary } from "../api/hooks";
import type { Library } from "../api/types";

export function RemoveLibraryDialog({
  library,
  onClose,
}: {
  library: Library;
  onClose: () => void;
}) {
  const remove = useDeleteLibrary();
  // Distinguish "not yet run" from "ran, engine had no note" (note: null).
  const [result, setResult] = useState<{ note: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-[28rem] rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">Remove this library from Shootr?</h2>

        {!result && (
          <>
            <div className="mb-2 break-all text-xs text-neutral-400">
              {library.root_path}
            </div>
            <p className="mb-4 text-xs text-neutral-300">
              Scan data, analysis, and selections are removed from the app
              database. Your photo files on disk are NOT touched.
            </p>
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
                onClick={() =>
                  remove.mutate(library.id, {
                    onSuccess: (r) => setResult({ note: r.note }),
                    onError: (e) => setError(e.message),
                  })
                }
                disabled={remove.isPending}
                className="rounded border border-red-900 bg-red-950 px-3 py-1 text-red-200 hover:bg-red-900 disabled:opacity-50"
              >
                {remove.isPending ? "Removing…" : "Remove library"}
              </button>
            </div>
          </>
        )}

        {result && (
          <>
            <div className="mb-3">Library removed.</div>
            {result.note && (
              <div className="mb-3 text-xs text-neutral-400">
                Note: {result.note}.
              </div>
            )}
            <div className="flex justify-end">
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
