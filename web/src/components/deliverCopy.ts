/** Wording and dry-run protocol shared by the two file-delivery actions
 * (design 07 §3.2b).
 *
 * §3.2b is deliberately TWO doors over ONE engine code path:
 *
 * - **Deliver files…** — `hardlink` (default) or `copy`. The originals stay
 *   exactly where they are; nothing about the library changes.
 * - **Move keepers…** — `move`, and nothing else. The originals leave their
 *   folder.
 *
 * What lives here is what must not diverge between the two: the plan-first
 * protocol, the strings describing a plan, and the byte formatter. What
 * deliberately does NOT live here is the *choice* — there is no mode picker
 * spanning both actions, because burying a move as the third radio button is
 * exactly the mis-click the two-door split exists to prevent. Each dialog
 * passes its own fixed mode(s) in.
 *
 * The strings are also the native client's (`DeliverCopy` in
 * native/Sources/ShootrApp/DeliverViews.swift). Two clients describing the
 * same action in different words is the same class of bug as scoring in the
 * client: if a sentence reads badly, change it in both.
 */

import { useState } from "react";
import { EngineError, errorCode } from "../api/client";
import { useDeliverSelects } from "../api/hooks";
import type {
  DeliveryMode,
  DeliveryPreview,
  DeliveryResult,
} from "../api/types";

export const plural = (n: number, word: string, plural?: string) =>
  n === 1 ? `${n} ${word}` : `${n} ${plural ?? word + "s"}`;

/** Bytes the engine measured, in units a person reads. Display formatting
 * only — the space verdict itself is the engine's `enough_space`. */
export const size = (bytes: number) =>
  bytes >= 1e9
    ? `${(bytes / 1e9).toFixed(1)} GB`
    : `${Math.max(1, Math.round(bytes / 1e6))} MB`;

/** The destination, the scope, and everything a plan can say. Identical for
 * both actions: a plan reads the same whatever mode produced it. */
export const PLAN_COPY = {
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
};

/** Why a plan cannot be confirmed — the engine's verdicts only (`count`,
 * `enough_space`), never a comparison this client makes. */
export const planBlocked = (plan: DeliveryPreview) =>
  plan.count === 0 || !plan.enough_space;

/** What the engine refused, kept so a dialog can offer a way out it actually
 * has (the cross-volume hardlink → copy case). */
export interface Refusal {
  code: string | null;
  /** Modes the engine says it has, when it said so. */
  modes: string[] | null;
  /** The mode that was refused. */
  mode: DeliveryMode;
}

/** The plan-first protocol, once, for both actions.
 *
 * `M` is the set of modes the calling dialog is allowed to send, and it is
 * never widened here: the flow sends what it is given, so a dialog typed to
 * `"hardlink" | "copy"` has no expressible path to `move`. The confirm
 * re-sends the *planned* request rather than whatever the form says now — a
 * confirmation has to mean the plan the user read.
 */
export function useDeliveryFlow<M extends DeliveryMode>(
  selectionId: number,
  initialMode: M,
) {
  const deliver = useDeliverSelects(selectionId);

  const [destDir, setDestDir] = useState("");
  const [mode, setMode] = useState<M>(initialMode);
  const [includeAlt, setIncludeAlt] = useState(false);

  /** The engine echoes back the mode it was sent (api.py `preview`), so the
   * plan on screen is a plan for one of this dialog's own modes. */
  const [plan, setPlan] = useState<(DeliveryPreview & { mode: M }) | null>(null);
  /** The scope the plan on screen was computed for. */
  const [plannedAlt, setPlannedAlt] = useState(false);
  const [result, setResult] = useState<DeliveryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  const clearPlan = () => {
    setPlan(null);
    setError(null);
    setRefusal(null);
  };

  const fail = (e: Error, attempted: M) => {
    setError(PLAN_COPY.errorCopy(errorCode(e), e.message));
    const detail = e instanceof EngineError ? e.api.detail : {};
    setRefusal({
      code: errorCode(e),
      modes: Array.isArray(detail.modes)
        ? (detail.modes as unknown[]).map(String)
        : null,
      mode: attempted,
    });
  };

  /** The dry run. Writes nothing; re-run on any change of folder, mode or
   * scope, so the plan on screen always belongs to the settings on screen. */
  const check = (next?: { mode?: M; includeAlt?: boolean }) => {
    const m = next?.mode ?? mode;
    const alt = next?.includeAlt ?? includeAlt;
    clearPlan();
    const dest = destDir.trim();
    if (!dest) return;
    deliver.mutate(
      { dest_dir: dest, mode: m, include_alt: alt, confirm: false },
      {
        onSuccess: (r) => {
          if (r.dry_run) {
            setPlan(r as DeliveryPreview & { mode: M });
            setPlannedAlt(alt);
          }
        },
        onError: (e) => fail(e, m),
      },
    );
  };

  /** Reachable only with a plan on screen: this is the only call that writes. */
  const run = () => {
    if (!plan) return;
    setError(null);
    setRefusal(null);
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

  return {
    destDir,
    changeDest: (v: string) => {
      setDestDir(v);
      clearPlan();
    },
    mode,
    /** Only the two-mode Deliver dialog uses this, and only within its own
     * `M` — there is no path from here to a mode the dialog isn't typed for. */
    changeMode: (m: M) => {
      setMode(m);
      check({ mode: m });
    },
    includeAlt,
    changeIncludeAlt: (v: boolean) => {
      setIncludeAlt(v);
      check({ includeAlt: v });
    },
    plan,
    result,
    error,
    refusal,
    isPending: deliver.isPending,
    check,
    run,
  };
}
