/** Compare style models (design 08 §7b, operation 3).
 *
 * Models side by side on the metrics the SAME harness measured for each of
 * them: per-parameter MAE against the family-median baseline, plus how the
 * numbers were produced.
 *
 * This screen deliberately computes nothing (design 10 §1, README rule 6). No
 * aggregate score, no ranking, no "best model" badge, not even a per-parameter
 * winner mark — those would be the client inventing a verdict on top of the
 * engine's measurements, and it is exactly how two frontends start disagreeing
 * about which model is better. The only tally shown is `beats_median_on`,
 * which the engine itself counted. The judgement is the user's.
 */

import type { Library, StyleModel } from "../api/types";
import {
  formatError,
  heldOutCopy,
  methodTitle,
  paramLabel,
  paramUnit,
  scopeLabel,
} from "../style";

export function StyleModelCompare({
  models,
  libraries,
}: {
  models: StyleModel[];
  libraries: Library[] | undefined;
}) {
  const measured = models.filter(
    (m) => Object.keys(m.metrics.per_param ?? {}).length > 0,
  );
  const unmeasured = models.filter(
    (m) => Object.keys(m.metrics.per_param ?? {}).length === 0,
  );

  // Parameter rows: every parameter any model was scored on, in the order the
  // engine listed them. A parameter one model was scored on and another was
  // not shows an explicit gap rather than being dropped from both.
  const paramNames: string[] = [];
  for (const m of measured) {
    for (const name of Object.keys(m.metrics.per_param ?? {})) {
      if (!paramNames.includes(name)) paramNames.push(name);
    }
  }

  if (measured.length === 0) {
    return (
      <div className="rounded border border-neutral-800 p-3 text-xs text-neutral-400">
        No learned model has metrics to compare yet. Learn a model — the engine
        measures it against your own edits as part of learning it.
      </div>
    );
  }

  // Splits differ → the columns are not measured the same way. Said out loud,
  // because comparing across splits is the mistake §7b was written to prevent.
  const splits = new Set(measured.map((m) => m.metrics.held_out_by ?? "?"));

  return (
    <div className="rounded border border-neutral-800 p-3">
      <p className="mb-2 text-[11px] text-neutral-400">
        Each column is what the engine's evaluation harness measured for that
        model, on your own edits. Mean absolute error, in each parameter's own
        units — lower is closer to what you actually did. Shootr shows the
        engine's numbers and its own count of parameters where the model beat
        the family median; it does not add a score of its own or name a winner.
      </p>

      {splits.size > 1 && (
        <div className="mb-2 rounded border border-amber-900 bg-amber-950/30 p-2 text-[11px] text-amber-200">
          These models were not held out the same way (
          {[...splits].join(", ")}), so their errors are not directly
          comparable. Relearn them so both use the same split before reading
          one against the other.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-[11px]">
          <thead>
            <tr>
              <th className="w-40 border-b border-neutral-800 p-1.5 text-left font-normal text-neutral-500">
                Parameter
              </th>
              {measured.map((m) => (
                <th
                  key={m.id}
                  className="border-b border-neutral-800 p-1.5 text-left align-bottom font-normal"
                >
                  <div className="text-neutral-200">
                    {m.name}
                    {m.is_active && (
                      <span className="ml-1 rounded bg-sky-950 px-1 py-0.5 text-[9px] text-sky-300">
                        active
                      </span>
                    )}
                  </div>
                  <div className="text-neutral-500">{methodTitle(m.method)}</div>
                  <div className="text-neutral-500">
                    {scopeLabel(m.library_ids, libraries)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {/* How each column was produced, before any of its numbers. */}
            <ProvenanceRow
              label="Edited photos measured on"
              models={measured}
              cell={(m) => m.metrics.history_n ?? m.history_n}
            />
            <ProvenanceRow
              label="Look families"
              models={measured}
              cell={(m) => m.metrics.families ?? "—"}
            />
            <ProvenanceRow
              label="Coverage (predicted, not abstained)"
              models={measured}
              // The engine's fraction, shown as a percentage — the same number
              // in different units, not a derived one.
              cell={(m) =>
                m.metrics.coverage === undefined
                  ? "—"
                  : `${(m.metrics.coverage * 100).toFixed(0)}% (${m.metrics.coverage})`
              }
            />
            <ProvenanceRow
              label="Beat the family median on"
              models={measured}
              cell={(m) =>
                m.metrics.beats_median_on === undefined
                  ? "—"
                  : `${m.metrics.beats_median_on} of ${m.metrics.params_scored ?? "?"} parameters`
              }
            />
            <ProvenanceRow
              label="Held out by"
              models={measured}
              cell={(m) => m.metrics.held_out_by ?? "not reported"}
            />
            <ProvenanceRow
              label="λ used"
              models={measured}
              // Only ridge has one; "—" is "this method has no λ", which is
              // not the same as a λ of zero.
              cell={(m) =>
                m.metrics.lambda === undefined || m.metrics.lambda === null
                  ? "—"
                  : String(m.metrics.lambda)
              }
            />

            <tr>
              <td
                colSpan={measured.length + 1}
                className="border-b border-neutral-800 pt-3 pb-1 text-[10px] uppercase tracking-wide text-neutral-500"
              >
                Per parameter — model error vs. family-median baseline
              </td>
            </tr>

            {paramNames.map((name) => (
              <tr key={name} className="align-top">
                <td className="border-b border-neutral-900 p-1.5 text-neutral-300">
                  {paramLabel(name)}
                  <span className="text-neutral-600">{paramUnit(name)}</span>
                </td>
                {measured.map((m) => {
                  const row = m.metrics.per_param?.[name];
                  return (
                    <td
                      key={m.id}
                      className="border-b border-neutral-900 p-1.5 font-mono text-neutral-300"
                    >
                      {row === undefined ? (
                        // Not scored for this model — a gap in the
                        // measurement, not a zero error (README rule 8).
                        <span className="text-neutral-600">
                          not scored for this model
                        </span>
                      ) : (
                        <>
                          <div title={`${name}: model MAE ${row.mae}`}>
                            {formatError(name, row.mae)}
                          </div>
                          <div
                            className="text-neutral-500"
                            title={
                              row.baseline_mae === null
                                ? "the family median had no value to score here"
                                : `family median MAE ${row.baseline_mae}`
                            }
                          >
                            median{" "}
                            {row.baseline_mae === null
                              ? "—"
                              : formatError(name, row.baseline_mae)}
                          </div>
                          <div className="text-neutral-600">n {row.n}</div>
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2 space-y-1 text-[11px] text-neutral-400">
        {measured.map((m) => (
          <div key={m.id}>
            <span className="text-neutral-300">{m.name}:</span>{" "}
            {heldOutCopy(m.metrics.held_out_by)}
          </div>
        ))}
      </div>

      {unmeasured.length > 0 && (
        <div className="mt-2 text-[11px] text-neutral-500">
          Not in this comparison, because the engine has no metrics for{" "}
          {unmeasured.length === 1 ? "it" : "them"}:{" "}
          {unmeasured.map((m) => m.name).join(", ")}. Relearn to measure.
        </div>
      )}
    </div>
  );
}

function ProvenanceRow({
  label,
  models,
  cell,
}: {
  label: string;
  models: StyleModel[];
  cell: (m: StyleModel) => string | number;
}) {
  return (
    <tr>
      <td className="border-b border-neutral-900 p-1.5 text-neutral-500">
        {label}
      </td>
      {models.map((m) => (
        <td
          key={m.id}
          className="border-b border-neutral-900 p-1.5 text-neutral-300"
        >
          {cell(m)}
        </td>
      ))}
    </tr>
  );
}
