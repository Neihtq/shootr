/** Delete-model confirmation. Same shape as RemoveLibraryDialog: state
 * plainly what happens, never default the destructive option to yes.
 *
 * Deleting a model removes a predictor and nothing else — no photo, no
 * sidecar, no edit of the user's is touched, and the history it learned from
 * stays exactly where it is. That is said out loud, because "delete" next to
 * anything learned from someone's catalog deserves to be unambiguous
 * (design README rule 2).
 */

import { useState } from "react";
import { errorCode } from "../api/client";
import { useDeleteStyleModel } from "../api/hooks";
import type { StyleModel } from "../api/types";
import { modelErrorCopy } from "../style";

export function DeleteStyleModelDialog({
  model,
  onClose,
  onDeleted,
}: {
  model: StyleModel;
  onClose: () => void;
  onDeleted: (modelId: number) => void;
}) {
  const remove = useDeleteStyleModel();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-[28rem] rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">Delete this style model?</h2>

        <div className="mb-2 text-xs text-neutral-400">
          {model.name} — {model.method}
          {model.is_active && " (currently active)"}
        </div>
        <p className="mb-2 text-xs text-neutral-300">
          Only the model is deleted: its name, its method, and what it learned.
          No photo, sidecar or edit of yours is touched, and the edit history it
          learned from is untouched — you can learn the same model again.
        </p>
        <p className="mb-4 text-xs text-neutral-400">
          Develop settings already written to XMP sidecars stay as they are on
          disk.
          {model.is_active &&
            " This model is active, so until you activate another one predictions fall back to the engine's built-in default."}
        </p>

        {error && (
          <div className="mb-3 text-xs text-red-400">{error}</div>
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
              remove.mutate(model.id, {
                onSuccess: () => {
                  onDeleted(model.id);
                  onClose();
                },
                onError: (e) =>
                  setError(modelErrorCopy(errorCode(e), e.message, "delete")),
              })
            }
            disabled={remove.isPending}
            className="rounded border border-red-900 bg-red-950 px-3 py-1 text-red-200 hover:bg-red-900 disabled:opacity-50"
          >
            {remove.isPending ? "Deleting…" : "Delete model"}
          </button>
        </div>
      </div>
    </div>
  );
}
