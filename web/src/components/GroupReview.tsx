/** Group Review — the screen that matters (design 11 §2).
 *
 * Groups are the primary navigation, not a flat grid: the cull unit is the
 * group (design 05). Bracket groups are visually distinct (⚑ HDR) and have
 * no cull controls — the §04.6 guard made visible.
 */

import { useEffect, useMemo, useState } from "react";
import {
  useGroups,
  useOverrideEntry,
  usePhoto,
  useSelection,
  useShoots,
} from "../api/hooks";
import { thumbUrl } from "../api/client";
import type { Group, Selection, SelectionState } from "../api/types";
import { exifLine } from "../exif";
import { CompareView } from "./CompareView";
import { CompositionOverlay } from "./CompositionOverlay";
import { EvidencePanel } from "./EvidencePanel";
import { EyeCrops, EyeOverlay } from "./EyeCrops";
import { SharpnessOverlay } from "./SharpnessOverlay";
import { KeyHints, ShortcutsDialog } from "./ShortcutsDialog";
import { useKeyboard } from "../keyboard";

const STATE_STYLES: Record<SelectionState, string> = {
  pick: "border-emerald-400 text-emerald-300",
  alt: "border-sky-500 text-sky-300",
  reject: "border-neutral-700 text-neutral-500 opacity-60",
};

export function GroupReview({
  shootId,
  selectionId,
  onOpenExport,
}: {
  shootId: number;
  selectionId: number | null;
  onOpenExport: () => void;
}) {
  const { data: groups } = useGroups(shootId);
  const { data: selection } = useSelection(selectionId);
  const override = useOverrideEntry(selectionId);

  const [groupIdx, setGroupIdx] = useState(0);
  const [frameIdx, setFrameIdx] = useState(0);
  const [showSharpness, setShowSharpness] = useState(false);
  const [showComposition, setShowComposition] = useState(false);
  const [showEyes, setShowEyes] = useState(false);
  const [showEvidence, setShowEvidence] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);

  // The shortcut dialog names the genre the verdicts were computed under —
  // "pick" means something different for street than for portrait.
  const { data: shoots } = useShoots();
  const profile =
    shoots?.find((s) => s.id === shootId)?.profile ?? "this shoot's genre";

  const entryByPhoto = useMemo(() => {
    const m = new Map<number, Selection["entries"][number]>();
    selection?.entries.forEach((e) => m.set(e.photo_id, e));
    return m;
  }, [selection]);

  const group: Group | undefined = groups?.[groupIdx];
  const photoId = group?.photo_ids[frameIdx] ?? null;
  const { data: photo } = usePhoto(photoId);

  // Thumbnail prefetch ±5 (design 11 §9): J/K scrubbing must not wait on
  // decode round-trips. The browser cache does the storing; we just warm it.
  // Adjacent groups' FIRST frames too: ↑/↓ skimming always lands there.
  useEffect(() => {
    if (!group) return;
    for (let d = -5; d <= 5; d++) {
      const pid = group.photo_ids[frameIdx + d];
      if (pid !== undefined && d !== 0) {
        new Image().src = thumbUrl(pid, 2048);
      }
    }
    for (const gi of [groupIdx + 1, groupIdx - 1]) {
      const pid = groups?.[gi]?.photo_ids[0];
      if (pid !== undefined) {
        new Image().src = thumbUrl(pid, 2048);
      }
    }
  }, [group, frameIdx, groups, groupIdx]);

  const clampFrame = (g: Group | undefined, i: number) =>
    g ? Math.max(0, Math.min(g.photo_ids.length - 1, i)) : 0;

  const setState = (state: SelectionState) => {
    // Brackets have no cull controls — the guard is visible, not implicit.
    if (photoId === null || !selectionId || group?.is_bracket) return;
    override.mutate({ photoId, state });
  };

  useKeyboard({
    onPrevFrame: () => setFrameIdx((i) => clampFrame(group, i - 1)),
    onNextFrame: () => setFrameIdx((i) => clampFrame(group, i + 1)),
    onPrevGroup: () => {
      setGroupIdx((i) => Math.max(0, i - 1));
      setFrameIdx(0);
    },
    onNextGroup: () => {
      setGroupIdx((i) => Math.min((groups?.length ?? 1) - 1, i + 1));
      setFrameIdx(0);
    },
    onPick: () => setState("pick"),
    onReject: () => setState("reject"),
    onAlt: () => setState("alt"),
    onToggleEvidence: () => setShowEvidence((v) => !v),
    onToggleSharpness: () => setShowSharpness((v) => !v),
    onToggleCompare: () => setComparing((v) => !v),
    onToggleComposition: () => setShowComposition((v) => !v),
    onToggleEyes: () => setShowEyes((v) => !v),
    onShowShortcuts: () => setShowShortcuts(true),
    onTogglePick: () => {
      const current = photoId !== null
        ? entryByPhoto.get(photoId)?.state : undefined;
      setState(current === "pick" ? "reject" : "pick");
    },
    // CompareView and the shortcut dialog own the keyboard while open.
    enabled: !comparing && !showShortcuts,
  });

  // Esc closes the dialog — it's modal, so the review bindings are inert.
  useEffect(() => {
    if (!showShortcuts) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setShowShortcuts(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showShortcuts]);

  // Compare the current frame against the group's other top-ranked frames:
  // the pick-vs-alt judgement is what compare exists for (design 11 §4).
  const compareIds = useMemo(() => {
    if (!group || photoId === null) return [];
    const ranked = group.photo_ids
      .filter((pid) => pid !== photoId)
      .sort((a, b) => {
        const ra = entryByPhoto.get(a)?.rank ?? 99;
        const rb = entryByPhoto.get(b)?.rank ?? 99;
        return ra - rb;
      });
    return [photoId, ...ranked.slice(0, 3)];
  }, [group, photoId, entryByPhoto]);

  if (!groups?.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        No groups yet — run grouping from the shoot header.
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Group list */}
      <nav className="w-44 shrink-0 overflow-y-auto border-r border-neutral-800">
        {groups.map((g, i) => (
          <button
            key={g.id}
            onClick={() => {
              setGroupIdx(i);
              setFrameIdx(0);
            }}
            className={`block w-full px-3 py-1.5 text-left text-xs ${
              i === groupIdx
                ? "bg-neutral-800 text-neutral-100"
                : "text-neutral-400 hover:bg-neutral-900"
            }`}
          >
            {g.is_bracket ? "⚑ " : "▸ "}
            {g.id}
            <span className="ml-1 text-neutral-500">({g.photo_ids.length})</span>
            {g.is_bracket && (
              <span className="ml-1 text-[10px] text-amber-400">HDR</span>
            )}
          </button>
        ))}
      </nav>

      {/* Main area */}
      <main className="flex min-w-0 flex-1 flex-col">
        {group && (
          <>
            <div className="flex items-center gap-2 border-b border-neutral-800 px-3 py-1.5 text-xs text-neutral-400">
              Group {group.id} · {group.photo_ids.length} frames
              {group.is_bracket && (
                <span className="rounded bg-amber-950 px-1.5 py-0.5 text-amber-300">
                  exposure bracket — all frames kept, no culling
                </span>
              )}
              <span className="ml-auto" />
              <button
                onClick={onOpenExport}
                className="rounded border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800"
              >
                Export…
              </button>
            </div>

            {/* Frame strip */}
            <div className="flex gap-1.5 overflow-x-auto border-b border-neutral-800 p-2">
              {group.photo_ids.map((pid, i) => {
                const entry = entryByPhoto.get(pid);
                const stateClass = entry
                  ? STATE_STYLES[entry.state]
                  : "border-neutral-800 text-neutral-500";
                return (
                  <button
                    key={pid}
                    onClick={() => setFrameIdx(i)}
                    className={`relative shrink-0 rounded border-2 ${stateClass} ${
                      i === frameIdx ? "ring-2 ring-neutral-300" : ""
                    }`}
                  >
                    <img
                      src={thumbUrl(pid, 256)}
                      alt={`frame ${i + 1}`}
                      className="h-20 w-28 rounded object-cover"
                      loading="lazy"
                    />
                    {entry && !group.is_bracket && (
                      <span className="absolute left-1 top-0.5 text-[10px] font-bold uppercase">
                        {entry.state}
                        {entry.user_override ? "*" : ""}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Selected frame */}
            <div className="relative min-h-0 flex-1 bg-black">
              {photoId !== null && (
                <>
                  <img
                    src={thumbUrl(photoId, 2048)}
                    alt={photo?.filename ?? `photo ${photoId}`}
                    className="h-full w-full object-contain"
                  />
                  <SharpnessOverlay photoId={photoId} visible={showSharpness} />
                  {photo && (
                    <CompositionOverlay
                      photo={photo}
                      visible={showComposition}
                    />
                  )}
                  {photo && photo.id === photoId && (
                    <EyeOverlay photo={photo} visible={showEyes} />
                  )}
                </>
              )}
            </div>

            {/* Action bar */}
            {!group.is_bracket && photo?.selection && (
              <div className="flex items-center gap-2 border-t border-neutral-800 px-3 py-1.5 text-xs">
                <span className="truncate text-neutral-400">
                  “{photo.selection.reason}”
                </span>
                <span className="ml-auto" />
                <span className="whitespace-nowrap font-mono text-[11px] text-neutral-400">
                  {exifLine(photo)}
                </span>
                <Key label="P pick" onClick={() => setState("pick")} />
                <Key label="A alt" onClick={() => setState("alt")} />
                <Key label="X reject" onClick={() => setState("reject")} />
                <Key
                  label={showSharpness ? "S map ✓" : "S map"}
                  onClick={() => setShowSharpness((v) => !v)}
                />
                <Key label="?" onClick={() => setShowShortcuts(true)} />
              </div>
            )}

            {/* Always visible, including on bracket groups where the action
                bar above is suppressed — that's exactly when a user needs to
                be told why there are no cull controls. */}
            <div className="flex items-center border-t border-neutral-800 px-3 py-1">
              <KeyHints onShowAll={() => setShowShortcuts(true)} />
            </div>
          </>
        )}
      </main>

      {/* Evidence panel */}
      {showEvidence && photo && (
        <aside className="w-64 shrink-0 overflow-y-auto border-l border-neutral-800">
          <EvidencePanel photo={photo} />
          <EyeCrops photo={photo} />
        </aside>
      )}

      {showShortcuts && (
        <ShortcutsDialog
          profile={profile}
          onClose={() => setShowShortcuts(false)}
        />
      )}

      {comparing && compareIds.length >= 2 && (
        <CompareView
          photoIds={compareIds}
          onClose={() => setComparing(false)}
          onSelect={(pid) => {
            const i = group?.photo_ids.indexOf(pid) ?? -1;
            if (i >= 0) setFrameIdx(i);
          }}
        />
      )}
    </div>
  );
}

function Key({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300 hover:bg-neutral-800"
    >
      {label}
    </button>
  );
}
