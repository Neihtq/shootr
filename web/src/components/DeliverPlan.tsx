/** Rendering shared by both file-delivery actions (design 07 §3.2b): the
 * modal chrome, the dry-run plan, and the per-file failure list.
 *
 * The plan is the engine's answer, rendered — the client never decides whether
 * a mode is possible, whether there is room, or what collides (design 10 §1).
 * Only components are exported from here so the copy and the dry-run protocol
 * stay in `deliverCopy.ts`, one place each.
 */

import { PLAN_COPY } from "./deliverCopy";
import type { DeliveryPreview, DeliveryResult } from "../api/types";

/** Names, capped so 900 collisions don't push the buttons off screen. */
export function NameList({ names }: { names: string[] }) {
  return (
    <ul className="mt-0.5 ml-4 space-y-0.5 break-all font-mono text-[10px] text-neutral-500">
      {names.slice(0, 6).map((n) => (
        <li key={n}>{n}</li>
      ))}
      {names.length > 6 && <li>+{names.length - 6} more</li>}
    </ul>
  );
}

export function Line({
  icon,
  tone = "text-neutral-300",
  children,
}: {
  icon: string;
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <li className={`flex gap-1.5 ${tone}`}>
      <span aria-hidden className="shrink-0">
        {icon}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** The modal frame both dialogs sit in, so they cannot drift apart visually
 * while describing two halves of one engine operation. */
export function DeliverModal({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="max-h-[85vh] w-[32rem] overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** The dry run on screen: counts, companions, collisions, skips, and the
 * space verdict. Identical in both dialogs — a plan reads the same whichever
 * action produced it, and the per-action warnings sit outside this box. */
export function PlanBox({ plan }: { plan: DeliveryPreview }) {
  return (
    <div className="mt-3 rounded border border-neutral-700 bg-neutral-800/40 p-2">
      <div className="mb-1 text-[11px] text-neutral-500">
        {PLAN_COPY.dryRunBanner}
      </div>
      <ul className="space-y-1 text-xs">
        {plan.count === 0 ? (
          <Line icon="⊖" tone="text-amber-300">
            {PLAN_COPY.nothingToDeliver}
          </Line>
        ) : (
          <Line icon="→">{PLAN_COPY.countLine(plan.count, plan.dest_dir)}</Line>
        )}
        {plan.companions > 0 && (
          <Line icon="⧉" tone="text-neutral-400">
            {PLAN_COPY.companionsLine(plan.companions)}
          </Line>
        )}
        {plan.renamed.length > 0 && (
          <Line icon="✎">
            {PLAN_COPY.renamedLine(plan.renamed.length)}
            <NameList names={plan.renamed} />
          </Line>
        )}
        {plan.already_present.length > 0 && (
          <Line icon="=" tone="text-neutral-400">
            {PLAN_COPY.alreadyPresentLine(plan.already_present.length)}
            <NameList names={plan.already_present} />
          </Line>
        )}
        {plan.missing_source.length > 0 && (
          <Line icon="⚠" tone="text-amber-300">
            {PLAN_COPY.missingSourceLine(plan.missing_source.length)}
            <NameList names={plan.missing_source} />
          </Line>
        )}
        {/* The engine measures bytes and free space for `copy` only — the
            other modes consume none, and `enough_space` is true for them. */}
        {plan.mode === "copy" && (
          <>
            <Line
              icon="▤"
              tone={plan.enough_space ? "text-neutral-400" : "text-amber-300"}
            >
              {PLAN_COPY.spaceLine(plan.bytes_needed, plan.free_bytes)}
            </Line>
            {!plan.enough_space && (
              <Line icon="⚠" tone="text-amber-300">
                {PLAN_COPY.notEnoughSpace}
              </Line>
            )}
          </>
        )}
        {plan.moves_originals && plan.cross_volume && (
          <Line icon="ⓘ" tone="text-neutral-400">
            {PLAN_COPY.crossVolumeMove}
          </Line>
        )}
      </ul>
    </div>
  );
}

/** Per-file failures with the engine's reason, verbatim — a failure with no
 * stated cause is not something the user can act on. */
export function FailedFiles({ failed }: { failed: DeliveryResult["failed"] }) {
  if (failed.length === 0) return null;
  return (
    <div className="mb-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
      {PLAN_COPY.failedHeading(failed.length)}
      <ul className="mt-1 space-y-0.5 break-all">
        {failed.slice(0, 6).map((f) => (
          <li key={f.file}>
            <span className="font-mono text-[10px]">{f.file}</span> — {f.error}
          </li>
        ))}
        {failed.length > 6 && <li>+{failed.length - 6} more</li>}
      </ul>
    </div>
  );
}

/** The engine's own sentence about what became of the originals, relayed as
 * it wrote it rather than paraphrased. */
export function EngineNote({ note }: { note: string }) {
  return <div className="mb-3 text-xs text-neutral-400">Engine: {note}.</div>;
}
