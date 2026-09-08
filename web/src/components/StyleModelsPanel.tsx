/** Style models — list and manager (design 08 §7b).
 *
 * A model is a user-created object: a name, a method, the libraries its
 * history came from, and the metrics the engine's harness measured for it. The
 * four operations live here — learn (create), relearn, compare, choose
 * (activate) — plus delete.
 *
 * Everything shown is engine state, including which model is active: the
 * active model decides what the native client predicts with too, so a local
 * copy of that choice would let the two clients write different edits from the
 * same click (design 10 §1). No metric is computed here and no model is
 * recommended — §7b is explicit that the harness reports and the user decides.
 */

import { useState } from "react";
import { errorCode } from "../api/client";
import {
  useActivateStyleModel,
  useLibraries,
  useStyleModels,
  useTrainStyleModel,
} from "../api/hooks";
import type { StyleModel } from "../api/types";
import {
  formatModelParams,
  heldOutCopy,
  methodExplainsCopy,
  methodTitle,
  modelErrorCopy,
  scopeLabel,
} from "../style";
import { CreateStyleModelForm } from "./CreateStyleModelForm";
import { DeleteStyleModelDialog } from "./DeleteStyleModelDialog";
import { StyleModelCompare } from "./StyleModelCompare";

export function StyleModelsPanel({
  usedModelId,
  onModelDeleted,
}: {
  /** The model the preview below actually ran with, straight from the predict
   * response — null when the engine used its built-in default. */
  usedModelId?: number | null;
  onModelDeleted: (modelId: number) => void;
}) {
  const { data: models, error, isLoading } = useStyleModels();
  const { data: libraries } = useLibraries();
  const [creating, setCreating] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [deleting, setDeleting] = useState<StyleModel | null>(null);

  if (error) {
    return (
      <div className="rounded border border-neutral-800 p-3 text-xs">
        <div className="mb-1 text-neutral-300">
          The engine could not list your style models.
        </div>
        <div className="text-neutral-500">
          Engine: {errorCode(error) ?? "error"} — {(error as Error).message}
        </div>
      </div>
    );
  }

  const list = models ?? [];

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <p className="text-neutral-400">
          A model is yours: you name it, choose how it learns, and choose which
          libraries it learns from. Nothing is learned when you import a
          catalog, and no method is picked for you.
        </p>
        <span className="ml-auto" />
        {list.length > 1 && (
          <button
            onClick={() => setComparing((c) => !c)}
            className="shrink-0 rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800"
          >
            {comparing ? "Hide comparison" : "Compare"}
          </button>
        )}
        <button
          onClick={() => setCreating((c) => !c)}
          className="shrink-0 rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800"
        >
          {creating ? "Cancel" : "Learn a model…"}
        </button>
      </div>

      {creating && (
        <div className="mb-3">
          <CreateStyleModelForm onDone={() => setCreating(false)} />
        </div>
      )}

      {isLoading && (
        <div className="text-xs text-neutral-500">Loading models…</div>
      )}

      {!isLoading && list.length === 0 && (
        // Not an empty list dressed up as a problem: the feature works without
        // a model, and the engine says exactly what it falls back to.
        <div className="rounded border border-neutral-800 p-3 text-xs">
          <div className="mb-1 text-neutral-200">No style models yet</div>
          <p className="text-neutral-400">
            Predictions still work: with no model, the engine uses its built-in
            default — nearest edits across all your imported history. Creating a
            model turns that into a choice you made, on the libraries you
            picked, with metrics measured for it so it can be compared against
            another.
          </p>
        </div>
      )}

      {comparing && list.length > 0 && (
        <div className="mb-3">
          <StyleModelCompare models={list} libraries={libraries} />
        </div>
      )}

      <div className="space-y-2">
        {list.map((m) => (
          <ModelRow
            key={m.id}
            model={m}
            libraryLabel={scopeLabel(m.library_ids, libraries)}
            isUsedByPreview={usedModelId === m.id}
            onDelete={() => setDeleting(m)}
          />
        ))}
      </div>

      {deleting && (
        <DeleteStyleModelDialog
          model={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={onModelDeleted}
        />
      )}
    </div>
  );
}

function ModelRow({
  model,
  libraryLabel,
  isUsedByPreview,
  onDelete,
}: {
  model: StyleModel;
  libraryLabel: string;
  isUsedByPreview: boolean;
  onDelete: () => void;
}) {
  const activate = useActivateStyleModel();
  const relearn = useTrainStyleModel();
  const [error, setError] = useState<string | null>(null);

  const metrics = model.metrics;

  return (
    <div
      className={`rounded border p-3 text-xs ${
        model.is_active
          ? "border-sky-800 bg-sky-950/20"
          : "border-neutral-800"
      }`}
    >
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <span className="text-sm text-neutral-200">{model.name}</span>
        {model.is_active && (
          <span className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-300">
            active — predicts unless you choose another
          </span>
        )}
        {isUsedByPreview && (
          <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-300">
            used by the preview below
          </span>
        )}
        {!model.trained && (
          // Created but never learned. Distinct from "learned and bad".
          <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] text-amber-300">
            not learned yet
          </span>
        )}
        <span className="ml-auto text-neutral-400">
          {methodTitle(model.method)}
        </span>
      </div>

      <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-0.5 text-[11px]">
        <dt className="text-neutral-500">Learns from</dt>
        <dd className="break-all text-neutral-300">{libraryLabel}</dd>

        <dt className="text-neutral-500">Edit history used</dt>
        <dd className="text-neutral-300">
          {model.trained
            ? `${model.history_n} edited photo${model.history_n === 1 ? "" : "s"}`
            : "— nothing learned yet"}
        </dd>

        <dt className="text-neutral-500">Process version</dt>
        <dd className="text-neutral-300">
          {model.process_version ?? "—"}
          {model.process_version && (
            <span className="text-neutral-500">
              {" "}
              — the single version its history was narrowed to
            </span>
          )}
        </dd>

        <dt className="text-neutral-500">Learned</dt>
        <dd className="text-neutral-300">
          {/* The engine's own timestamp, rendered as given. */}
          {model.trained_at ?? "never"}
        </dd>

        {Object.keys(model.params).length > 0 && (
          <>
            <dt className="text-neutral-500">Knobs</dt>
            <dd className="font-mono text-neutral-400">
              {formatModelParams(model.params)}
            </dd>
          </>
        )}

        {metrics.params_scored !== undefined && (
          <>
            <dt className="text-neutral-500">Measured</dt>
            <dd className="text-neutral-300">
              beat the family median on {metrics.beats_median_on ?? 0} of{" "}
              {metrics.params_scored} parameters
              {metrics.coverage !== undefined && (
                <span className="text-neutral-500">
                  {" · "}predicted for {(metrics.coverage * 100).toFixed(0)}% of
                  held-out photos
                </span>
              )}
            </dd>
          </>
        )}
      </dl>

      <div className="mt-1.5 text-[11px] text-neutral-400">
        {methodExplainsCopy(model.explains_by_neighbours)}
      </div>

      {metrics.held_out_by !== undefined && (
        <div className="mt-1 text-[11px] text-neutral-500">
          {heldOutCopy(metrics.held_out_by)}
        </div>
      )}

      {error && (
        <div className="mt-2 rounded border border-red-900 bg-red-950/40 p-2 text-[11px] text-red-300">
          {error}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          onClick={() => {
            setError(null);
            activate.mutate(model.id, {
              onError: (e) =>
                setError(modelErrorCopy(errorCode(e), e.message, "activate")),
            });
          }}
          disabled={model.is_active || !model.trained || activate.isPending}
          title={
            !model.trained
              ? "Learn this model first — an unlearned model cannot predict"
              : "Make this the model that predicts by default, in both clients"
          }
          className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {activate.isPending ? "Activating…" : "Activate"}
        </button>

        <button
          onClick={() => {
            setError(null);
            relearn.mutate(model.id, {
              onError: (e) =>
                setError(modelErrorCopy(errorCode(e), e.message, "relearn")),
            });
          }}
          disabled={relearn.isPending}
          title="Re-run this model against your history as it stands now"
          className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800 disabled:opacity-40"
        >
          {relearn.isPending
            ? "Learning…"
            : model.trained
              ? "Relearn"
              : "Learn now"}
        </button>

        <button
          onClick={onDelete}
          className="rounded border border-neutral-800 px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
        >
          Delete…
        </button>

        <span className="ml-auto self-center text-[11px] text-neutral-500">
          Relearn is how new shoots take effect — the engine never retrains on
          its own.
        </span>
      </div>
    </div>
  );
}
