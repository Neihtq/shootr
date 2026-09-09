/** Deliver the selects as FILES into a folder the user chooses (design 07
 * §3.2b) — the workflow with no Lightroom in it at all.
 *
 * **This dialog is non-destructive by construction.** It offers `hardlink`
 * (default) and `copy` only: after either one, every original is still exactly
 * where it was. Moving is a different kind of act and lives behind its own
 * button and its own dialog (`MoveKeepersDialog`, `move` only) — §3.2b's
 * two-door split. There is no mode here that relocates anything, so there is
 * nothing in this file about moving.
 *
 * The safety properties of §3.2b are the feature, so the dialog is shaped
 * around them rather than around the three-line form:
 *
 * - **Dry run first, always.** The plan comes from the engine and is on screen
 *   before anything can be confirmed. The client never decides whether a mode
 *   is possible, whether there is room, or what collides (design 10 §1) — it
 *   asks, and renders the answer.
 * - **Never a default-yes confirm.** The proceed button exists only once a plan
 *   is shown, it names the action and the count, and it is not focused or
 *   styled as the obvious next click (design 11 §7, as in ExportDialog /
 *   RemoveLibraryDialog).
 * - **Rejects are never in scope.** `include_alt` widens picks to picks+alts;
 *   there is deliberately no control that could include a reject.
 * - The engine's `note` about the library's paths is relayed verbatim.
 *
 * The user-visible strings are deliberately the SAME as the native client's
 * `DeliverCopy` (native/Sources/ShootrApp/DeliverViews.swift). Two clients
 * describing the same action in different words is the same class of bug as
 * scoring in the client: if a sentence reads badly, change it in both.
 */

import { NON_DESTRUCTIVE_DELIVERY_MODES } from "../api/types";
import {
  DeliverModal,
  EngineNote,
  FailedFiles,
  PlanBox,
} from "./DeliverPlan";
import { PLAN_COPY, planBlocked, plural, useDeliveryFlow } from "./deliverCopy";

/** The two modes this dialog can send. Narrower than `DeliveryMode` on
 * purpose: nothing here can name `move`. */
type SafeMode = (typeof NON_DESTRUCTIVE_DELIVERY_MODES)[number];

const COPY = {
  title: "Deliver selects as files",
  intro:
    "Puts the keepers in a folder you choose, so you can hand them over " +
    "without Lightroom. Rejected frames are never delivered, in any mode.",

  modeLabel: { hardlink: "Hardlink", copy: "Copy" } as Record<
    SafeMode,
    string
  >,

  /** One plain line per mode, in the order that decides it: what it costs on
   * disk, what becomes of the originals, and any restriction. Both are shown
   * at once — the trade-off is the choice. */
  modeExplainer: {
    hardlink:
      "Hardlink — costs no extra disk space, and your originals stay " +
      "exactly where they are. Same drive only.",
    copy:
      "Copy — writes every file again at full size, and your originals stay " +
      "exactly where they are.",
  } as Record<SafeMode, string>,

  confirmButton: (mode: SafeMode, count: number) =>
    `${COPY.modeLabel[mode]} ${plural(count, "photo")}`,
  running: "Delivering…",

  useCopyInstead: "Use copy instead",
};

export function DeliverDialog({
  selectionId,
  onClose,
}: {
  selectionId: number;
  onClose: () => void;
}) {
  /** Hardlink is the engine's default too (§3.2b) — the cheapest mode that
   * leaves the originals alone. The flow is typed to the two safe modes, so
   * `move` is not merely absent from the form: it is unrepresentable here. */
  const flow = useDeliveryFlow<SafeMode>(selectionId, "hardlink");
  const { plan, mode, result, error, refusal, isPending } = flow;

  /** The engine refused a mode and names copy as one it has — the
   * cross-volume hardlink case, one click from being fixed. */
  const offerCopy =
    refusal !== null &&
    refusal.code === "delivery_impossible" &&
    refusal.mode !== "copy" &&
    (refusal.modes === null || refusal.modes.includes("copy"));

  return (
    <DeliverModal title={COPY.title}>
      {!result && (
        <>
          <p className="mb-3 text-xs text-neutral-400">{COPY.intro}</p>

          <label
            htmlFor="deliver-dest"
            className="mb-1 block text-xs text-neutral-400"
          >
            {PLAN_COPY.destLabel}
          </label>
          <input
            id="deliver-dest"
            value={flow.destDir}
            onChange={(e) => flow.changeDest(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") flow.check();
            }}
            placeholder={PLAN_COPY.destPlaceholder}
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
          />
          <div className="mt-1 text-xs text-neutral-500">
            {PLAN_COPY.destHelp}
          </div>

          {/* Both trade-offs on screen, the selected one lit: choosing between
              them is the point, so they are not hidden behind it. Moving is
              not among them — it is its own action, not a third radio. */}
          <div className="mt-3 space-y-1">
            {NON_DESTRUCTIVE_DELIVERY_MODES.map((m) => (
              <label
                key={m}
                className="flex cursor-pointer items-start gap-2 rounded px-1 py-0.5 hover:bg-neutral-800/60"
              >
                <input
                  type="radio"
                  name="deliver-mode"
                  checked={mode === m}
                  onChange={() => flow.changeMode(m)}
                  className="mt-0.5"
                />
                <span
                  className={`text-xs ${
                    mode === m ? "text-neutral-200" : "text-neutral-500"
                  }`}
                >
                  {COPY.modeExplainer[m]}
                </span>
              </label>
            ))}
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
              {offerCopy && (
                <div className="mt-2">
                  <button
                    onClick={() => flow.changeMode("copy")}
                    disabled={isPending}
                    className="rounded border border-amber-700 px-2 py-0.5 text-amber-100 hover:bg-amber-900 disabled:opacity-50"
                  >
                    {COPY.useCopyInstead}
                  </button>
                </div>
              )}
            </div>
          )}

          {!plan && !error && !isPending && (
            <div className="mt-3 text-xs text-neutral-500">
              {PLAN_COPY.chooseFolderFirst}
            </div>
          )}

          {plan && !isPending && <PlanBox plan={plan} />}

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
            {/* Reachable only after a dry run, and never the default action:
                there is no Enter-key path into duplicating the user's
                photographs. */}
            {plan && (
              <button
                onClick={flow.run}
                disabled={planBlocked(plan) || isPending}
                className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:opacity-50"
              >
                {COPY.confirmButton(plan.mode, plan.count)}
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
