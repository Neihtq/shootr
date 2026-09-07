/** Screen 2 — Predict for a shoot (design 08 §7a).
 *
 * A PREVIEW, and presented as one: nothing is written until the user opens the
 * write dialog and confirms. Per photo it renders the engine's predicted
 * parameters, its confidence, and the neighbour photos the blend came from —
 * "edited like these five" is the explanation that made k-NN worth choosing
 * over a trained model (design 08 §4). Abstentions are first-class states with
 * the engine's reason, never an empty parameter list (design 08 §7a).
 *
 * No arithmetic on predictions happens here (design 10 §1): the family is the
 * engine's, the confidence is the engine's, the abstain/predict verdict is the
 * engine's. The per-parameter opt-out is the engine's too — it is stored
 * server-side and it changes what is written, so the checkboxes below are a
 * view of `GET /api/style/preferences`, not a local display filter.
 */

import { useEffect, useMemo, useState } from "react";
import { errorCode, thumbUrl } from "../api/client";
import {
  useSetStylePreferences,
  useStylePrediction,
  useStylePreferences,
} from "../api/hooks";
import type { StyleFamily, StylePrediction } from "../api/types";
import {
  abstainCopy,
  formatParam,
  paramLabel,
  paramUnit,
  prefErrorCopy,
  SUGGESTED_EXCLUSIONS,
} from "../style";
import { StyleWriteDialog } from "./StyleWriteDialog";

/** How many preview rows to mount at once — a wedding's picks run into the
 * hundreds and each row carries up to nine thumbnails. */
const PAGE = 25;

/** Stable empty fallback: a fresh `[]` per render would re-run the memo (and
 * defeat TanStack's stable `data` identity) on every keystroke elsewhere. */
const NO_PREDICTIONS: StylePrediction[] = [];

const PREDICT_ERROR_COPY: Record<string, string> = {
  no_selection:
    "This shoot has no cull selection yet. Run Analyze & cull first — the preview covers the selection's picks.",
  not_analyzed:
    "These photos have no scene embeddings yet. Analyze the shoot first; similarity is what the prediction is built on.",
  insufficient_history:
    "Not enough imported edit history to predict from — import a Lightroom catalog with your edits.",
};

export function StylePredictPanel({
  shootId,
  families,
  onFamilyResolved,
}: {
  shootId: number;
  families: StyleFamily[];
  /** Lets the families list above highlight the look actually in use. */
  onFamilyResolved?: (family: number) => void;
}) {
  // null = omit `family` from the request so the ENGINE suggests one (§3).
  const [family, setFamily] = useState<number | null>(null);
  const { data, error, isFetching } = useStylePrediction(shootId, family);
  const { data: prefs } = useStylePreferences();
  const setPrefs = useSetStylePreferences();
  const [prefError, setPrefError] = useState<string | null>(null);
  const [writeOpen, setWriteOpen] = useState(false);
  const [shown, setShown] = useState(PAGE);

  // Report the family the engine settled on upward, so the families list can
  // mark it. Callers pass a stable setter.
  const resolved = data?.family ?? null;
  useEffect(() => {
    if (resolved !== null) onFamilyResolved?.(resolved);
  }, [resolved, onFamilyResolved]);

  const predictions = data?.predictions ?? NO_PREDICTIONS;
  const predicted = predictions.filter((p) => !p.abstained);
  const abstained = predictions.filter((p) => p.abstained);

  // The engine's own exclusion list. Never a local copy: it decides what is
  // written, and `data.excluded_params` is what THIS preview was built with.
  const excluded = prefs?.excluded_params ?? data?.excluded_params ?? [];

  // Parameter set the engine actually returned (predicted or withheld), in its
  // own order. Never a hardcoded list: if the engine starts predicting another
  // slider it shows up here instead of being silently dropped.
  const returnedNames = useMemo(() => {
    const seen: string[] = [];
    for (const p of predictions) {
      for (const name of [
        ...Object.keys(p.params ?? {}),
        ...Object.keys(p.excluded ?? {}),
      ]) {
        if (!seen.includes(name)) seen.push(name);
      }
    }
    return seen;
  }, [predictions]);

  // The engine's modelable list is the PUT allowlist, so it is the set of
  // togglable rows; anything it returned that is somehow outside that list is
  // still shown (read-only) rather than quietly missing from the panel.
  const modelable = prefs?.modelable_params ?? [];
  const paramNames = [
    ...modelable,
    ...returnedNames.filter((n) => !modelable.includes(n)),
  ];

  const setExcluded = (next: string[]) => {
    setPrefError(null);
    setPrefs.mutate(next, {
      onError: (e) => setPrefError(prefErrorCopy(errorCode(e), e.message)),
    });
  };
  const toggle = (name: string) =>
    setExcluded(
      excluded.includes(name)
        ? excluded.filter((n) => n !== name)
        : [...excluded, name],
    );

  // Measured suggestions the user hasn't taken up yet. One click applies them;
  // the client never applies one on its own (design 08 §7a).
  const suggested = Object.keys(SUGGESTED_EXCLUSIONS).filter(
    (n) => modelable.includes(n) && !excluded.includes(n),
  );

  // How many previewed photos actually had a value withheld — "you opted out
  // of a parameter" and "it affected these photos" are different facts.
  const withheldCount = predictions.filter(
    (p) => Object.keys(p.excluded ?? {}).length > 0,
  ).length;

  if (error) {
    const code = errorCode(error);
    return (
      <div className="rounded border border-neutral-800 p-3 text-xs">
        <div className="mb-1 text-neutral-300">
          {PREDICT_ERROR_COPY[code ?? ""] ?? "The engine could not build a preview."}
        </div>
        <div className="text-neutral-500">
          Engine: {code ?? "error"} — {(error as Error).message}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Unmistakably a preview. */}
      <div className="mb-3 rounded border border-sky-900 bg-sky-950/30 p-2 text-xs text-sky-200">
        Preview only — nothing has been written to your files. These are
        suggested starting points blended from your own past edits; the write
        dialog states the counts before anything touches disk.
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5 text-neutral-400">
          Look family
          <select
            value={family === null ? "auto" : String(family)}
            onChange={(e) => {
              const v = e.target.value;
              setFamily(v === "auto" ? null : Number(v));
              setShown(PAGE);
            }}
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
          >
            <option value="auto">Auto — let the engine suggest</option>
            {families.map((f) => (
              <option key={f.id} value={f.id}>
                Family {f.id} ({f.size}) — {f.traits}
              </option>
            ))}
          </select>
        </label>

        {resolved !== null && (
          <span className="text-neutral-400">
            using family {resolved}
            {family === null && (
              <span className="text-neutral-500"> (engine's suggestion)</span>
            )}
            {data && (
              <span className="text-neutral-500">
                {" · "}Process Version {data.process_version}
              </span>
            )}
          </span>
        )}

        {isFetching && <span className="text-neutral-500">predicting…</span>}

        <span className="ml-auto" />

        {data && (
          <span className="text-neutral-400">
            {predicted.length} predicted · {abstained.length} abstaining ·{" "}
            {predictions.length} previewed
            {excluded.length > 0 && (
              <span className="text-neutral-500">
                {" · "}
                {excluded.length} parameter{excluded.length === 1 ? "" : "s"} you
                excluded
              </span>
            )}
          </span>
        )}

        <button
          onClick={() => setWriteOpen(true)}
          disabled={!data || predicted.length === 0}
          title={
            predicted.length === 0
              ? "Nothing to write — the engine abstained on every photo"
              : "Review the counts, then confirm"
          }
          className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Write to XMP…
        </button>
      </div>

      {/* Waits for the engine's list rather than guessing one: the togglable
          set IS `modelable_params`, and a toggle here writes to the user's
          files. */}
      {prefs && paramNames.length > 0 && (
        <div className="mb-3 rounded border border-neutral-800 p-2">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">
            Parameters — which ones Shootr is allowed to write
          </div>
          <div className="mb-2 text-[11px] text-neutral-400">
            Unchecked parameters are never written to your files. The engine
            stores this choice and applies it everywhere — this preview, the
            write, and the native client alike. Values it predicted for an
            excluded parameter are still shown below, struck through, so you can
            see what you turned down rather than losing sight of it.
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {paramNames.map((name) => {
              const off = excluded.includes(name);
              const togglable = modelable.includes(name);
              return (
                <label
                  key={name}
                  className={`flex items-center gap-1.5 text-[11px] ${
                    off ? "text-neutral-500" : "text-neutral-300"
                  } ${togglable ? "" : "opacity-60"}`}
                  title={
                    togglable
                      ? name
                      : `${name} — the engine returned this but does not list it as modelable, so it cannot be excluded`
                  }
                >
                  <input
                    type="checkbox"
                    checked={!off}
                    disabled={!togglable || setPrefs.isPending}
                    onChange={() => toggle(name)}
                  />
                  <span className={off ? "line-through" : ""}>
                    {paramLabel(name)}
                  </span>
                  {off && (
                    <span className="text-[10px] text-neutral-500">
                      not written
                    </span>
                  )}
                </label>
              );
            })}
          </div>

          {setPrefs.isPending && (
            <div className="mt-2 text-[11px] text-neutral-500">
              Saving to the engine and re-predicting…
            </div>
          )}

          {prefError && (
            <div className="mt-2 rounded border border-red-900 bg-red-950/40 p-2 text-[11px] text-red-300">
              {prefError}
            </div>
          )}

          {suggested.map((name) => (
            // A suggestion, not an action taken for them: excluding a parameter
            // changes the user's files, so the reason is stated and the click
            // is theirs (design 08 §7a).
            <div
              key={name}
              className="mt-2 rounded border border-sky-900 bg-sky-950/30 p-2 text-[11px] text-sky-200"
            >
              <div className="mb-1">
                <span className="font-medium">
                  Suggested: don't write {paramLabel(name)}.
                </span>{" "}
                {SUGGESTED_EXCLUSIONS[name]}
              </div>
              <div className="text-sky-300/70">
                Nothing has been changed — this parameter is currently being
                written.
              </div>
              <button
                onClick={() => setExcluded([...excluded, name])}
                disabled={setPrefs.isPending}
                className="mt-1.5 rounded border border-sky-700 px-2 py-0.5 hover:bg-sky-900/50 disabled:opacity-50"
              >
                Exclude {paramLabel(name)}
              </button>
            </div>
          ))}
        </div>
      )}

      {data && predictions.length === 0 && (
        <div className="text-xs text-neutral-500">
          The selection's picks contain no photos to predict for.
        </div>
      )}

      <div className="space-y-2">
        {predictions.slice(0, shown).map((p) => (
          <PredictionRow key={p.photo_id} pred={p} />
        ))}
      </div>

      {predictions.length > shown && (
        <button
          onClick={() => setShown((n) => n + PAGE)}
          className="mt-3 rounded border border-neutral-700 px-3 py-1 text-xs hover:bg-neutral-800"
        >
          Show more — {shown} of {predictions.length} shown
        </button>
      )}

      {writeOpen && data && (
        <StyleWriteDialog
          shootId={shootId}
          family={data.family}
          processVersion={data.process_version}
          photoIds={predicted.map((p) => p.photo_id)}
          abstainCount={abstained.length}
          excludedParams={data.excluded_params ?? excluded}
          withheldCount={withheldCount}
          onClose={() => setWriteOpen(false)}
        />
      )}
    </div>
  );
}

function PredictionRow({ pred }: { pred: StylePrediction }) {
  const params = Object.entries(pred.params ?? {});
  // Predicted, then withheld because the user said so. Rendered — not dropped,
  // and not dressed up as an abstention: the engine reports the number on
  // purpose so the user can see what they turned down (design 08 §7a).
  const excluded = Object.entries(pred.excluded ?? {});
  const neighbors = pred.neighbor_photo_ids ?? [];

  return (
    <div
      className={`flex gap-3 rounded border p-2 ${
        pred.abstained
          ? "border-amber-900/70 bg-amber-950/10"
          : "border-neutral-800"
      }`}
    >
      <img
        src={thumbUrl(pred.photo_id, 256)}
        alt={`photo ${pred.photo_id}`}
        className="h-20 w-28 shrink-0 rounded border border-neutral-800 object-cover"
        loading="lazy"
      />

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2 text-[11px]">
          <span className="text-neutral-500">photo {pred.photo_id}</span>
          {pred.abstained ? (
            <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
              no confident prediction — needs manual edit
            </span>
          ) : (
            <span className="text-neutral-400">
              confidence{" "}
              <span className="font-mono text-neutral-300">
                {pred.confidence?.toFixed(2) ?? "—"}
              </span>
            </span>
          )}
        </div>

        {pred.abstained ? (
          // Never a blank parameter list: an abstention is stated, with its
          // cause, and with what will happen (nothing).
          <div className="text-[11px] text-amber-200/90">
            {abstainCopy(pred.reason)}{" "}
            <span className="text-neutral-400">
              Nothing will be written for this photo.
            </span>
            {pred.confidence !== undefined && (
              <span className="text-neutral-500">
                {" "}
                (engine confidence {pred.confidence.toFixed(2)}, below its gate)
              </span>
            )}
          </div>
        ) : params.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {params.map(([name, value]) => (
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
          // Predicted, but every value belongs to a parameter the user
          // excluded — say so, rather than showing an empty row that reads as
          // "no edit needed".
          <div className="text-[11px] text-neutral-500">
            {excluded.length} predicted parameter
            {excluded.length === 1 ? "" : "s"}, all of them ones you excluded —
            nothing from this prediction will be written.
          </div>
        )}

        {excluded.length > 0 && (
          // Deliberately NOT amber: an abstention is the engine having nothing
          // to say, this is the user's own decision being honoured.
          <div className="mt-1 flex flex-wrap items-baseline gap-1">
            <span className="text-[10px] uppercase tracking-wide text-neutral-500">
              excluded by you — predicted, not written:
            </span>
            {excluded.map(([name, value]) => (
              <span
                key={name}
                className="rounded border border-neutral-700 px-1.5 py-0.5 font-mono text-[10px] text-neutral-500 line-through"
                title={`${name} — you excluded this parameter; the engine predicted ${formatParam(name, value)}${paramUnit(name)} and will not write it`}
              >
                {paramLabel(name)} {formatParam(name, value)}
                {paramUnit(name)}
              </span>
            ))}
          </div>
        )}

        {Object.keys(pred.damped ?? {}).length > 0 && (
          // A guardrail fired (08 §6). The engine's sentence carries the
          // number and the cause; showing the damped value alone would be an
          // unexplained number.
          <div className="mt-1 space-y-0.5">
            {Object.entries(pred.damped ?? {}).map(([name, why]) => (
              <div key={name} className="text-[10px] text-amber-200/90">
                {paramLabel(name)}: {why}
              </div>
            ))}
          </div>
        )}

      </div>

      {neighbors.length > 0 && (
        <div className="shrink-0">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">
            {pred.abstained
              ? `Closest ${neighbors.length} in your history — not close enough to copy`
              : `Edited like these ${neighbors.length}`}
          </div>
          <div className="flex gap-1">
            {neighbors.map((pid) => (
              <img
                key={pid}
                src={thumbUrl(pid, 256)}
                alt={`neighbour photo ${pid}`}
                title={`history photo ${pid}`}
                className="h-12 w-16 rounded border border-neutral-800 object-cover"
                loading="lazy"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
