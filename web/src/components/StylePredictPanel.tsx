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
 * engine's.
 */

import { useEffect, useMemo, useState } from "react";
import { errorCode, thumbUrl } from "../api/client";
import { useStylePrediction } from "../api/hooks";
import type { StyleFamily, StylePrediction } from "../api/types";
import {
  abstainCopy,
  formatParam,
  paramLabel,
  paramUnit,
  useHiddenParams,
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
  const { hidden, toggle } = useHiddenParams();
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

  // Parameter set the engine actually returned, in its own order. Never a
  // hardcoded list: if the engine starts predicting another slider, it shows
  // up here instead of being silently dropped from the preview.
  const paramNames = useMemo(() => {
    const seen: string[] = [];
    for (const p of predictions) {
      for (const name of Object.keys(p.params ?? {})) {
        if (!seen.includes(name)) seen.push(name);
      }
    }
    return seen;
  }, [predictions]);

  const hiddenPresent = paramNames.filter((n) => hidden.includes(n));

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

      {paramNames.length > 0 && (
        <div className="mb-3 rounded border border-neutral-800 p-2">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">
            Parameters — display filter for this preview only
          </div>
          <div className="mb-2 text-[11px] text-amber-300/90">
            These toggles change what you see here. They do NOT change what gets
            written: the engine's write endpoint applies every predicted
            parameter and has no per-parameter switch yet (design 08 §6). The
            write dialog repeats this and names anything you switched off.
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {paramNames.map((name) => (
              <label
                key={name}
                className="flex items-center gap-1.5 text-[11px] text-neutral-300"
                title={name}
              >
                <input
                  type="checkbox"
                  checked={!hidden.includes(name)}
                  onChange={() => toggle(name)}
                />
                {paramLabel(name)}
              </label>
            ))}
          </div>
        </div>
      )}

      {data && predictions.length === 0 && (
        <div className="text-xs text-neutral-500">
          The selection's picks contain no photos to predict for.
        </div>
      )}

      <div className="space-y-2">
        {predictions.slice(0, shown).map((p) => (
          <PredictionRow key={p.photo_id} pred={p} hidden={hidden} />
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
          hiddenParams={hiddenPresent}
          onClose={() => setWriteOpen(false)}
        />
      )}
    </div>
  );
}

function PredictionRow({
  pred,
  hidden,
}: {
  pred: StylePrediction;
  hidden: string[];
}) {
  const params = Object.entries(pred.params ?? {});
  const shownParams = params.filter(([name]) => !hidden.includes(name));
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
        ) : shownParams.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {shownParams.map(([name, value]) => (
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
          // Predicted, but every parameter is hidden by the display filter —
          // say so, rather than showing an empty row that reads as "no edit".
          <div className="text-[11px] text-neutral-500">
            {params.length} predicted parameter{params.length === 1 ? "" : "s"},
            all hidden by your display filter above.
          </div>
        )}

        {params.length > shownParams.length && shownParams.length > 0 && (
          <div className="mt-1 text-[10px] text-neutral-500">
            {params.length - shownParams.length} more predicted parameter
            {params.length - shownParams.length === 1 ? "" : "s"} hidden by the
            display filter (still written).
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
