/** Move the keepers OUT of their folder and into one the user chooses
 * (design 07 §3.2b) — mode `move`, and nothing else.
 *
 * Its own door on purpose. Moving someone's originals is a different kind of
 * act from producing a second view of them, and as the third radio button in
 * the deliver dialog it was the most consequential choice and the easiest to
 * mis-click. So: a separate button, a separate dialog, one mode, no picker —
 * there is no state in this file in which it does anything but move.
 *
 * What it still shares with `DeliverDialog` is everything that must not
 * diverge: the mandatory dry run, the plan rendering, the byte formatter and
 * the wording (`deliverCopy.ts`, `DeliverPlan.tsx`).
 *
 * The protections, and why each one is here:
 *
 * - **Dry run first, always.** The plan (counts, companions, collisions,
 *   skips, cross-volume) comes from the engine before anything is written.
 * - **The warning is not a footnote.** `moves_originals` gets its own bordered
 *   block saying what leaves the folder and what is not deleted. Rule 2 is
 *   about the engine never removing a photo on its own judgement; a user
 *   pointing at a folder is a different act, and it still must read as the
 *   serious one it is without pretending it deletes.
 * - **Never a default-yes confirm.** The confirm appears only once a plan is
 *   on screen, names the count, is styled unlike every other primary button,
 *   and is not focused — there is no Enter-key path into moving photographs.
 * - **Rejects are never in scope.** `include_alt` widens picks to picks+alts;
 *   nothing here can include a reject.
 * - **What became of the library is reported.** `relinked` / `marked_missing`
 *   plus the engine's own `note`, verbatim: after a move, where the library
 *   thinks the photos live is the thing the user most needs to be told.
 *
 * `moveWarningHeading` / `moveWarning` / the confirm label are character-for-
 * character the native client's `DeliverCopy` strings
 * (native/Sources/ShootrApp/DeliverViews.swift). If a sentence reads badly,
 * change it in both.
 */

import {
  DeliverModal,
  EngineNote,
  FailedFiles,
  Line,
  PlanBox,
} from "./DeliverPlan";
import { PLAN_COPY, planBlocked, plural, useDeliveryFlow } from "./deliverCopy";

const COPY = {
  title: "Move keepers out of their folder",
  intro:
    "Move — relocates your originals into that folder. Nothing is deleted. " +
    "Rejected frames are never moved.",

  moveWarningHeading: "This moves your originals",
  moveWarning:
    "The files leave their current folder and afterwards exist only in the " +
    "destination. Nothing is deleted: each file is either moved intact or " +
    "left exactly where it was, and Shootr updates its own record of where " +
    "every photo lives.",

  confirmButton: (count: number) =>
    `Move ${plural(count, "photo")} out of their folder`,
  running: "Moving…",

  /** The library's own record afterwards — the part a move changes that the
   * destination folder cannot show. */
  relinkedLine: (n: number) =>
    plural(n, "photo") +
    " relinked inside your library — Shootr now points at the new location, " +
    "and the scores and analysis are unchanged.",
  markedMissingLine: (n: number) =>
    plural(n, "photo") +
    " now outside your library and marked missing — nothing was deleted and " +
    "no analysis was discarded; Shootr simply no longer looks there.",
};

export function MoveKeepersDialog({
  selectionId,
  onClose,
}: {
  selectionId: number;
  onClose: () => void;
}) {
  /** One mode, fixed at the type level: `changeMode` here accepts nothing but
   * "move", and is never called. */
  const flow = useDeliveryFlow(selectionId, "move");
  const { plan, result, error, isPending } = flow;

  return (
    <DeliverModal title={COPY.title}>
      {!result && (
        <>
          <p className="mb-3 text-xs text-neutral-400">{COPY.intro}</p>

          <label
            htmlFor="move-dest"
            className="mb-1 block text-xs text-neutral-400"
          >
            {PLAN_COPY.destLabel}
          </label>
          <input
            id="move-dest"
            value={flow.destDir}
            onChange={(e) => flow.changeDest(e.target.value)}
            onKeyDown={(e) => {
              // Enter runs the DRY RUN only — the same key never confirms.
              if (e.key === "Enter") flow.check();
            }}
            placeholder={PLAN_COPY.destPlaceholder}
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
          />
          <div className="mt-1 text-xs text-neutral-500">
            {PLAN_COPY.destHelp}
          </div>

          <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-neutral-300">
            <input
              type="checkbox"
              checked={flow.includeAlt}
              onChange={(e) => flow.changeIncludeAlt(e.target.checked)}
            />
            {PLAN_COPY.includeAltLabel}
          </label>
          <div className="mt-0.5 ml-6 text-xs text-neutral-500">
            {PLAN_COPY.includeAltHelp}
          </div>

          {isPending && (
            <div className="mt-3 text-xs text-neutral-400">
              {plan === null ? PLAN_COPY.planning : COPY.running}
            </div>
          )}

          {error && (
            <div className="mt-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
              {error}
            </div>
          )}

          {!plan && !error && !isPending && (
            <div className="mt-3 text-xs text-neutral-500">
              {PLAN_COPY.chooseFolderFirst}
            </div>
          )}

          {plan && !isPending && <PlanBox plan={plan} />}

          {/* Always on screen — before any plan exists, so the user knows what
              this door is on opening it, and immediately above the confirm,
              which is the last thing read before clicking it. */}
          <div className="mt-3 rounded border border-red-800 bg-red-950/50 p-2 text-xs">
            <div className="font-medium text-red-200">
              ⚠ {COPY.moveWarningHeading}
            </div>
            <div className="mt-1 text-red-200/90">{COPY.moveWarning}</div>
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
            >
              Cancel
            </button>
            <button
              onClick={() => flow.check()}
              disabled={!flow.destDir.trim() || isPending}
              className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:opacity-50"
            >
              {plan ? PLAN_COPY.checkAgainButton : PLAN_COPY.checkButton}
            </button>
            {/* Reachable only after a dry run, visually unlike any other
                confirm in the app, and never the focused/default action. */}
            {plan && (
              <button
                onClick={flow.run}
                disabled={planBlocked(plan) || isPending}
                className="rounded border border-red-800 bg-red-950 px-3 py-1 text-red-200 hover:bg-red-900 disabled:opacity-50"
              >
                {COPY.confirmButton(plan.count)}
              </button>
            )}
          </div>
        </>
      )}

      {result && (
        <>
          <div className="mb-3 break-all">
            {PLAN_COPY.deliveredLine(result.delivered, result.dest_dir)}
          </div>

          <FailedFiles failed={result.failed} />

          {/* What happened to the library's own record of these photos. */}
          {(result.relinked > 0 || result.marked_missing > 0) && (
            <ul className="mb-3 space-y-1 text-xs">
              {result.relinked > 0 && (
                <Line icon="↻" tone="text-neutral-400">
                  {COPY.relinkedLine(result.relinked)}
                </Line>
              )}
              {result.marked_missing > 0 && (
                <Line icon="⚠" tone="text-amber-300">
                  {COPY.markedMissingLine(result.marked_missing)}
                </Line>
              )}
            </ul>
          )}

          <EngineNote note={result.note} />

          {error && <div className="mb-3 text-xs text-red-400">{error}</div>}

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
    </DeliverModal>
  );
}
