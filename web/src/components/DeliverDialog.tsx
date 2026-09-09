/** Deliver the selects as FILES into a folder the user chooses (design 07
 * §3.2b) — the workflow with no Lightroom in it at all.
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
 * - **A move says what a move is.** `moves_originals` gets its own bordered
 *   block: the originals leave their current folder, and nothing is deleted.
 *   This is the only destructive-feeling action in the app and must read as
 *   one, without pretending it deletes.
 * - **Rejects are never in scope.** `include_alt` widens picks to picks+alts;
 *   there is deliberately no control that could include a reject.
 * - The engine's `note` about the library's paths is relayed verbatim.
 *
 * The user-visible strings are deliberately the SAME as the native client's
 * `DeliverCopy` (native/Sources/ShootrApp/DeliverViews.swift). Two clients
 * describing the same action in different words is the same class of bug as
 * scoring in the client: if a sentence reads badly, change it in both.
 */

import { useState } from "react";
import { EngineError, errorCode } from "../api/client";
import { useDeliverSelects } from "../api/hooks";
import {
  DELIVERY_MODES,
  type DeliveryMode,
  type DeliveryPreview,
  type DeliveryResult,
} from "../api/types";

const plural = (n: number, word: string, plural?: string) =>
  n === 1 ? `${n} ${word}` : `${n} ${plural ?? word + "s"}`;

/** Bytes the engine measured, in units a person reads. Display formatting
 * only — the space verdict itself is the engine's `enough_space`. */
const size = (bytes: number) =>
  bytes >= 1e9
    ? `${(bytes / 1e9).toFixed(1)} GB`
    : `${Math.max(1, Math.round(bytes / 1e6))} MB`;

const COPY = {
  title: "Deliver selects as files",
  intro:
    "Puts the keepers in a folder you choose, so you can hand them over " +
    "without Lightroom. Rejected frames are never delivered, in any mode.",

  destLabel: "Destination folder",
  /** Web-only: a browser cannot open a native picker for an arbitrary
   * absolute path, so the path is typed or pasted. The native client has a
   * real folder picker and no equivalent line. */
  destHelp:
    "Full path to the folder. Paste it from Finder: select the folder, ⌥⌘C.",
  destPlaceholder: "/Volumes/Shoots2026/Selects",

  includeAltLabel: "Also deliver the runners-up (alt)",
  includeAltHelp:
    "Off by default: picks only. Rejects are never included either way.",

  modeLabel: { hardlink: "Hardlink", copy: "Copy", move: "Move" } as Record<
    DeliveryMode,
    string
  >,

  /** One plain line per mode, in the order that decides it: what it costs on
   * disk, what becomes of the originals, and any restriction. All three are
   * shown at once — the trade-off is the choice. */
  modeExplainer: {
    hardlink:
      "Hardlink — costs no extra disk space, and your originals stay " +
      "exactly where they are. Same drive only.",
    copy:
      "Copy — writes every file again at full size, and your originals stay " +
      "exactly where they are.",
    move:
      "Move — relocates your originals into that folder. Nothing is deleted.",
  } as Record<DeliveryMode, string>,

  planning: "Checking what would happen…",
  dryRunBanner: "Nothing has been written yet — this is what would happen.",
  chooseFolderFirst:
    "Choose a folder to see what would happen. Nothing is written until you " +
    "confirm the plan.",
  checkButton: "Check what would happen",
  checkAgainButton: "Check again",

  countLine: (n: number, dest: string) => `${plural(n, "photo")} → ${dest}`,
  nothingToDeliver:
    "Nothing to deliver — this selection has no picks in scope.",
  companionsLine: (n: number) =>
    plural(n, "sidecar or JPEG sibling", "sidecars and JPEG siblings") +
    " travel with them, so ratings aren't orphaned and RAW+JPEG pairs aren't " +
    "split.",
  renamedLine: (n: number) =>
    plural(n, "name collision") +
    " — those get a numbered suffix. Nothing already in that folder is ever " +
    "overwritten.",
  alreadyPresentLine: (n: number) =>
    plural(n, "file") + " already in that folder as the same file — skipped.",
  missingSourceLine: (n: number) =>
    plural(n, "source file") +
    " could not be found and will be skipped — the drive holding " +
    (n === 1 ? "it" : "them") +
    " may be offline.",
  /** Only stated for `move`: across drives the engine copies, verifies, and
   * unlinks only then, and that is worth knowing before starting. */
  crossVolumeMove:
    "That folder is on a different drive, so each file is copied, verified, " +
    "and only then removed from its old location.",
  spaceLine: (needed: number, free: number | null) =>
    `Needs ${size(needed)}; ` +
    (free !== null
      ? `${size(free)} free at the destination.`
      : "free space at the destination could not be read."),
  notEnoughSpace:
    "Not enough free space at the destination, so this would fail partway " +
    "through. Choose another folder, or use hardlink if the folder is on the " +
    "same drive as the photos.",

  moveWarningHeading: "This moves your originals",
  moveWarning:
    "The files leave their current folder and afterwards exist only in the " +
    "destination. Nothing is deleted: each file is either moved intact or " +
    "left exactly where it was, and Shootr updates its own record of where " +
    "every photo lives.",

  confirmButton: (mode: DeliveryMode, count: number) =>
    mode === "move"
      ? `Move ${plural(count, "photo")} out of their folder`
      : `${COPY.modeLabel[mode]} ${plural(count, "photo")}`,
  running: "Delivering…",

  deliveredLine: (n: number, dest: string) =>
    `Delivered ${plural(n, "file")} to ${dest}.`,
  failedHeading: (n: number) => `${plural(n, "file")} could not be delivered:`,

  /** The engine's own sentence wherever it has one — `delivery_impossible`
   * already says why the mode cannot work here and what to use instead. */
  errorCopy: (code: string | null, message: string) =>
    code === "no_selection"
      ? "This shoot has no cull selection yet. Run Analyze & cull first — " +
        "delivery hands over the selection's picks."
      : message,
  useCopyInstead: "Use copy instead",
};

/** Names, capped so 900 collisions don't push the buttons off screen. */
function NameList({ names }: { names: string[] }) {
  return (
    <ul className="mt-0.5 ml-4 space-y-0.5 break-all font-mono text-[10px] text-neutral-500">
      {names.slice(0, 6).map((n) => (
        <li key={n}>{n}</li>
      ))}
      {names.length > 6 && <li>+{names.length - 6} more</li>}
    </ul>
  );
}

function Line({
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

export function DeliverDialog({
  selectionId,
  onClose,
}: {
  selectionId: number;
  onClose: () => void;
}) {
  const deliver = useDeliverSelects(selectionId);

  const [destDir, setDestDir] = useState("");
  /** Hardlink is the engine's default too (§3.2b) — the cheapest mode that
   * leaves the originals alone. */
  const [mode, setMode] = useState<DeliveryMode>("hardlink");
  const [includeAlt, setIncludeAlt] = useState(false);

  const [plan, setPlan] = useState<DeliveryPreview | null>(null);
  /** The scope the plan on screen was computed for. The confirm re-sends the
   * planned request, not whatever the form says now — a confirmation has to
   * mean the plan the user actually read. */
  const [plannedAlt, setPlannedAlt] = useState(false);
  const [result, setResult] = useState<DeliveryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Set when the engine refused a mode and names copy as one it has — the
   * cross-volume hardlink case, one click from being fixed. */
  const [offerCopy, setOfferCopy] = useState(false);

  const clearPlan = () => {
    setPlan(null);
    setError(null);
    setOfferCopy(false);
  };

  const fail = (e: Error, attempted: DeliveryMode) => {
    const code = errorCode(e);
    setError(COPY.errorCopy(code, e.message));
    const detail = e instanceof EngineError ? e.api.detail : {};
    const modes = Array.isArray(detail.modes)
      ? (detail.modes as unknown[]).map(String)
      : null;
    setOfferCopy(
      code === "delivery_impossible" &&
        attempted !== "copy" &&
        (modes === null || modes.includes("copy")),
    );
  };

  /** The dry run. Writes nothing; re-run on any change of folder, mode or
   * scope, so the plan on screen always belongs to the settings on screen. */
  const check = (next?: { mode?: DeliveryMode; includeAlt?: boolean }) => {
    const m = next?.mode ?? mode;
    const alt = next?.includeAlt ?? includeAlt;
    const dest = destDir.trim();
    if (!dest) return;
    clearPlan();
    deliver.mutate(
      { dest_dir: dest, mode: m, include_alt: alt, confirm: false },
      {
        onSuccess: (r) => {
          if (r.dry_run) {
            setPlan(r);
            setPlannedAlt(alt);
          }
        },
        onError: (e) => fail(e, m),
      },
    );
  };

  const run = () => {
    if (!plan) return;
    setError(null);
    setOfferCopy(false);
    deliver.mutate(
      {
        dest_dir: plan.dest_dir,
        mode: plan.mode,
        include_alt: plannedAlt,
        confirm: true,
      },
      {
        onSuccess: (r) => {
          if (!r.dry_run) setResult(r);
        },
        onError: (e) => fail(e, plan.mode),
      },
    );
  };

  const blocked =
    !plan || plan.count === 0 || (plan.mode === "copy" && !plan.enough_space);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="max-h-[85vh] w-[32rem] overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm text-neutral-200">
        <h2 className="mb-3 font-medium">{COPY.title}</h2>

        {!result && (
          <>
            <p className="mb-3 text-xs text-neutral-400">{COPY.intro}</p>

            <label
              htmlFor="deliver-dest"
              className="mb-1 block text-xs text-neutral-400"
            >
              {COPY.destLabel}
            </label>
            <input
              id="deliver-dest"
              value={destDir}
              onChange={(e) => {
                setDestDir(e.target.value);
                clearPlan();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") check();
              }}
              placeholder={COPY.destPlaceholder}
              className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
            />
            <div className="mt-1 text-xs text-neutral-500">
              {COPY.destHelp}
            </div>

            {/* All three trade-offs on screen, the selected one lit: choosing
                between them is the point, so they are not hidden behind it. */}
            <div className="mt-3 space-y-1">
              {DELIVERY_MODES.map((m) => (
                <label
                  key={m}
                  className="flex cursor-pointer items-start gap-2 rounded px-1 py-0.5 hover:bg-neutral-800/60"
                >
                  <input
                    type="radio"
                    name="deliver-mode"
                    checked={mode === m}
                    onChange={() => {
                      setMode(m);
                      clearPlan();
                      check({ mode: m });
                    }}
                    className="mt-0.5"
                  />
                  <span
                    className={`text-xs ${
                      mode === m
                        ? m === "move"
                          ? "text-red-300"
                          : "text-neutral-200"
                        : "text-neutral-500"
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
                checked={includeAlt}
                onChange={(e) => {
                  setIncludeAlt(e.target.checked);
                  clearPlan();
                  check({ includeAlt: e.target.checked });
                }}
              />
              {COPY.includeAltLabel}
            </label>
            <div className="mt-0.5 ml-6 text-xs text-neutral-500">
              {COPY.includeAltHelp}
            </div>

            {deliver.isPending && (
              <div className="mt-3 text-xs text-neutral-400">
                {plan === null ? COPY.planning : COPY.running}
              </div>
            )}

            {error && (
              <div className="mt-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
                {error}
                {offerCopy && (
                  <div className="mt-2">
                    <button
                      onClick={() => {
                        setMode("copy");
                        check({ mode: "copy" });
                      }}
                      disabled={deliver.isPending}
                      className="rounded border border-amber-700 px-2 py-0.5 text-amber-100 hover:bg-amber-900 disabled:opacity-50"
                    >
                      {COPY.useCopyInstead}
                    </button>
                  </div>
                )}
              </div>
            )}

            {!plan && !error && !deliver.isPending && (
              <div className="mt-3 text-xs text-neutral-500">
                {COPY.chooseFolderFirst}
              </div>
            )}

            {plan && !deliver.isPending && (
              <div className="mt-3 rounded border border-neutral-700 bg-neutral-800/40 p-2">
                <div className="mb-1 text-[11px] text-neutral-500">
                  {COPY.dryRunBanner}
                </div>
                <ul className="space-y-1 text-xs">
                  {plan.count === 0 ? (
                    <Line icon="⊖" tone="text-amber-300">
                      {COPY.nothingToDeliver}
                    </Line>
                  ) : (
                    <Line icon="→">
                      {COPY.countLine(plan.count, plan.dest_dir)}
                    </Line>
                  )}
                  {plan.companions > 0 && (
                    <Line icon="⧉" tone="text-neutral-400">
                      {COPY.companionsLine(plan.companions)}
                    </Line>
                  )}
                  {plan.renamed.length > 0 && (
                    <Line icon="✎">
                      {COPY.renamedLine(plan.renamed.length)}
                      <NameList names={plan.renamed} />
                    </Line>
                  )}
                  {plan.already_present.length > 0 && (
                    <Line icon="=" tone="text-neutral-400">
                      {COPY.alreadyPresentLine(plan.already_present.length)}
                      <NameList names={plan.already_present} />
                    </Line>
                  )}
                  {plan.missing_source.length > 0 && (
                    <Line icon="⚠" tone="text-amber-300">
                      {COPY.missingSourceLine(plan.missing_source.length)}
                      <NameList names={plan.missing_source} />
                    </Line>
                  )}
                  {plan.mode === "copy" && (
                    <>
                      <Line
                        icon="▤"
                        tone={
                          plan.enough_space
                            ? "text-neutral-400"
                            : "text-amber-300"
                        }
                      >
                        {COPY.spaceLine(plan.bytes_needed, plan.free_bytes)}
                      </Line>
                      {!plan.enough_space && (
                        <Line icon="⚠" tone="text-amber-300">
                          {COPY.notEnoughSpace}
                        </Line>
                      )}
                    </>
                  )}
                  {plan.moves_originals && plan.cross_volume && (
                    <Line icon="ⓘ" tone="text-neutral-400">
                      {COPY.crossVolumeMove}
                    </Line>
                  )}
                </ul>

                {/* The confirm step for a move says plainly what leaves the
                    folder and what is not deleted, and it does not look like
                    the other two modes. */}
                {plan.moves_originals && (
                  <div className="mt-2 rounded border border-red-800 bg-red-950/50 p-2 text-xs">
                    <div className="font-medium text-red-200">
                      ⚠ {COPY.moveWarningHeading}
                    </div>
                    <div className="mt-1 text-red-200/90">
                      {COPY.moveWarning}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                onClick={() => check()}
                disabled={!destDir.trim() || deliver.isPending}
                className="rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:opacity-50"
              >
                {plan ? COPY.checkAgainButton : COPY.checkButton}
              </button>
              {/* Reachable only after a dry run, and never the default action:
                  there is no Enter-key path into moving or duplicating the
                  user's photographs. */}
              {plan && (
                <button
                  onClick={run}
                  disabled={blocked || deliver.isPending}
                  className={
                    plan.moves_originals
                      ? "rounded border border-red-800 bg-red-950 px-3 py-1 text-red-200 hover:bg-red-900 disabled:opacity-50"
                      : "rounded border border-neutral-600 bg-neutral-800 px-3 py-1 hover:bg-neutral-700 disabled:opacity-50"
                  }
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
              {COPY.deliveredLine(result.delivered, result.dest_dir)}
            </div>

            {result.failed.length > 0 && (
              <div className="mb-3 rounded border border-amber-900 bg-amber-950/40 p-2 text-xs text-amber-200">
                {COPY.failedHeading(result.failed.length)}
                {/* The engine's reason, verbatim — a failure with no stated
                    cause is not something the user can act on. */}
                <ul className="mt-1 space-y-0.5 break-all">
                  {result.failed.slice(0, 6).map((f) => (
                    <li key={f.file}>
                      <span className="font-mono text-[10px]">{f.file}</span> —{" "}
                      {f.error}
                    </li>
                  ))}
                  {result.failed.length > 6 && (
                    <li>+{result.failed.length - 6} more</li>
                  )}
                </ul>
              </div>
            )}

            {/* Relayed as the engine wrote it, not paraphrased: it is the
                record of what became of the originals. */}
            <div className="mb-3 text-xs text-neutral-400">
              Engine: {result.note}.
            </div>

            {error && (
              <div className="mb-3 text-xs text-red-400">{error}</div>
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
