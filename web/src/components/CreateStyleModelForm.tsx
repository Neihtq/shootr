/** Learn a new style model (design 08 §7b, operation 1).
 *
 * Name, method, and the libraries to learn from. Creating IS learning here —
 * that is one engine call, and it is always an explicit action: nothing is
 * learned on import.
 *
 * The method list comes from `GET /api/style/methods` and each option states
 * the two facts that decide the choice: whether it fits (so new edits need a
 * relearn) and whether a prediction can name the photos behind it. That
 * trade-off is the point of having a choice, so it is stated, not hidden —
 * and no method is preselected as "the good one", because the engine does not
 * privilege one either.
 */

import { useState } from "react";
import { errorCode } from "../api/client";
import { useCreateStyleModel, useLibraries, useStyleMethods } from "../api/hooks";
import {
  formatModelParams,
  METHOD_TRADEOFF,
  methodExplainsCopy,
  methodFitsCopy,
  methodTitle,
  modelErrorCopy,
} from "../style";

export function CreateStyleModelForm({ onDone }: { onDone: () => void }) {
  const { data: methods, error: methodsError } = useStyleMethods();
  const { data: libraries } = useLibraries();
  const create = useCreateStyleModel();

  const [name, setName] = useState("");
  const [method, setMethod] = useState<string | null>(null);
  const [libraryIds, setLibraryIds] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);

  const chosen = methods?.find((m) => m.method === method) ?? null;

  const submit = () => {
    if (!name.trim() || method === null) return;
    setError(null);
    create.mutate(
      // `params` omitted → the engine applies its own defaults for the
      // method. The client does not invent knob values.
      { name: name.trim(), method, library_ids: libraryIds },
      {
        onSuccess: onDone,
        onError: (e) =>
          setError(modelErrorCopy(errorCode(e), e.message, "create")),
      },
    );
  };

  return (
    <div className="rounded border border-neutral-800 p-3 text-xs">
      <div className="mb-2 text-sm text-neutral-200">Learn a style model</div>

      {methodsError && (
        <div className="mb-2 text-neutral-400">
          The engine could not list its methods:{" "}
          {errorCode(methodsError) ?? "error"} —{" "}
          {(methodsError as Error).message}
        </div>
      )}

      <label className="mb-3 block">
        <div className="mb-1 text-neutral-400">Name</div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Weddings 2024–26"
          className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
        />
        <div className="mt-1 text-[11px] text-neutral-500">
          Yours to label. Style drifts over years and genres, so a model is
          worth naming for the work it came from.
        </div>
      </label>

      <div className="mb-3">
        <div className="mb-1 text-neutral-400">Method</div>
        <p className="mb-2 text-[11px] text-neutral-400">{METHOD_TRADEOFF}</p>
        <div className="space-y-1.5">
          {(methods ?? []).map((m) => (
            <label
              key={m.method}
              className={`block cursor-pointer rounded border p-2 ${
                method === m.method
                  ? "border-sky-800 bg-sky-950/20"
                  : "border-neutral-800 hover:border-neutral-700"
              }`}
            >
              <div className="flex items-baseline gap-2">
                <input
                  type="radio"
                  name="style-method"
                  checked={method === m.method}
                  onChange={() => setMethod(m.method)}
                />
                <span className="text-neutral-200">
                  {methodTitle(m.method)}
                </span>
                <span className="font-mono text-[10px] text-neutral-500">
                  {m.method}
                </span>
              </div>
              <ul className="mt-1 ml-5 space-y-0.5 text-[11px] text-neutral-400">
                <li>{methodFitsCopy(m.fits)}</li>
                <li
                  className={
                    m.explains_by_neighbours
                      ? "text-neutral-400"
                      : "text-amber-200/90"
                  }
                >
                  {methodExplainsCopy(m.explains_by_neighbours)}
                </li>
                {Object.keys(m.default_params).length > 0 && (
                  <li className="font-mono text-[10px] text-neutral-500">
                    engine defaults: {formatModelParams(m.default_params)}
                  </li>
                )}
              </ul>
            </label>
          ))}
        </div>
      </div>

      <div className="mb-3">
        <div className="mb-1 text-neutral-400">Learn from</div>
        <p className="mb-1.5 text-[11px] text-neutral-500">
          Which libraries the edit history comes from. Leave everything
          unchecked to use all of them. Whatever the scope, the engine narrows
          the history to a single Lightroom process version before learning and
          records which — the same slider renders differently across versions,
          so mixing them would describe neither.
        </p>
        {libraries === undefined ? (
          <div className="text-neutral-500">Loading libraries…</div>
        ) : libraries.length === 0 ? (
          <div className="text-neutral-500">
            No libraries yet. A model can still be created with "all libraries"
            as its scope, but there is nothing to learn from until one is added
            and analyzed.
          </div>
        ) : (
          <div className="space-y-1">
            {libraries.map((l) => (
              <label
                key={l.id}
                className="flex items-baseline gap-1.5 text-[11px] text-neutral-300"
              >
                <input
                  type="checkbox"
                  checked={libraryIds.includes(l.id)}
                  onChange={() =>
                    setLibraryIds((prev) =>
                      prev.includes(l.id)
                        ? prev.filter((i) => i !== l.id)
                        : [...prev, l.id],
                    )
                  }
                />
                <span className="break-all">{l.root_path}</span>
                {!l.online && (
                  <span className="text-neutral-500">(offline)</span>
                )}
              </label>
            ))}
            <div className="text-[11px] text-neutral-500">
              {libraryIds.length === 0
                ? "Scope: all libraries."
                : `Scope: ${libraryIds.length} of ${libraries.length} libraries.`}
            </div>
          </div>
        )}
      </div>

      {chosen && !chosen.explains_by_neighbours && (
        // Stated before the model exists, not discovered later in the preview.
        <div className="mb-3 rounded border border-amber-900 bg-amber-950/20 p-2 text-[11px] text-amber-200">
          {methodTitle(chosen.method)} gives up the neighbour explanation.
          Predictions from it will say they were fitted, and from how many
          edited photos, but not which photos a value came from. The guardrails
          are unchanged — values are still clamped to the range seen in your
          history, and nothing overwrites your own develop settings.
        </div>
      )}

      {error && (
        <div className="mb-3 rounded border border-red-900 bg-red-950/40 p-2 text-[11px] text-red-300">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button
          onClick={onDone}
          className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={create.isPending || !name.trim() || method === null}
          title={
            method === null
              ? "Pick a method — the engine does not choose one for you"
              : "Creates the model and learns it now"
          }
          className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {create.isPending ? "Learning…" : "Create and learn"}
        </button>
      </div>
    </div>
  );
}
