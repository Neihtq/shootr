/** `?` — the shortcut reference plus how the engine reaches its verdicts.
 *
 * Both were README-only before, which is the wrong place for something you
 * need while looking at a photo: an overlay the user can't name (the S
 * heatmap) is an overlay they won't trust, and a verdict whose basis is
 * undocumented is one they can't sensibly disagree with (design 06 §1).
 *
 * Content is kept identical to the native ShortcutsSheet — same keys, same
 * wording. Two frontends explaining the same behavior differently is the
 * same class of bug as two frontends scoring differently.
 */

interface Item {
  key: string;
  label: string;
  /** Longer gloss; the compact strip in the action bar shows `label` only. */
  detail?: string;
}

const NAVIGATE: Item[] = [
  { key: "← →", label: "prev / next frame", detail: "also J / K" },
  { key: "↑ ↓", label: "prev / next group", detail: "also G / ⇧G" },
  { key: "Esc", label: "close this / back to shoots" },
];

const JUDGE: Item[] = [
  { key: "P", label: "pick", detail: "recommended keeper — 3★ on export" },
  { key: "A", label: "alt", detail: "credible runner-up — 2★ on export" },
  { key: "X", label: "reject", detail: "not chosen; nothing is ever deleted" },
  { key: "Space", label: "toggle pick ↔ reject" },
];

const INSPECT: Item[] = [
  { key: "C", label: "compare", detail: "current frame vs the group's runner-ups" },
  {
    key: "S",
    label: "sharpness heatmap",
    detail: "red = sharpest tiles in THIS frame — shows where focus landed",
  },
  { key: "O", label: "composition overlay", detail: "thirds grid + face boxes" },
  { key: "B", label: "eye crops", detail: "full-res eyes of the primary face — blink check" },
  { key: "E", label: "evidence panel", detail: "per-metric scores behind the verdict" },
  { key: "?", label: "this list" },
];

/** The compact subset for the always-visible action-bar strip. */
export const STRIP: Item[] = [
  { key: "P", label: "pick" },
  { key: "A", label: "alt" },
  { key: "X", label: "reject" },
  { key: "S", label: "sharpness" },
  { key: "O", label: "faces" },
  { key: "?", label: "keys" },
];

const VERDICT_RULES: [string, string, string][] = [
  [
    "border-amber-400",
    "Exposure bracket",
    "every frame kept — brackets are never culled.",
  ],
  [
    "border-emerald-400",
    "Best few in the group",
    "ranked by score, with a penalty for looking too much like a frame " +
      "already picked, then a preference for fewest blinking subjects.",
  ],
  [
    "border-sky-500",
    "Next one down",
    "the runner-up, kept for comparison. Also where a whole group lands " +
      "when no frame clears the quality floor — the engine declines to " +
      "recommend rather than guess.",
  ],
  [
    "border-neutral-600",
    "Everything else",
    "not chosen. Nothing is deleted or moved, and rejects write nothing " +
      "on export.",
  ],
];

export function KeyCap({ children }: { children: string }) {
  return (
    <span className="rounded border border-neutral-700 bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-300">
      {children}
    </span>
  );
}

/** Always-visible hint strip; clicking it opens the full list, so the
 * shortcuts are reachable without already knowing them. */
export function KeyHints({ onShowAll }: { onShowAll: () => void }) {
  return (
    <button
      onClick={onShowAll}
      title="Show all keyboard shortcuts (?)"
      className="flex items-center gap-2.5"
    >
      {STRIP.map((item) => (
        <span key={item.key} className="flex items-center gap-1">
          <KeyCap>{item.key}</KeyCap>
          <span className="text-[10px] text-neutral-500">{item.label}</span>
        </span>
      ))}
    </button>
  );
}

export function ShortcutsDialog({
  profile,
  onClose,
}: {
  profile: string;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div
        className="max-h-full w-full max-w-3xl overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center">
          <h2 className="text-sm font-semibold text-neutral-100">Keyboard</h2>
          <button
            onClick={onClose}
            className="ml-auto rounded border border-neutral-700 px-2 py-0.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            Close
          </button>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-6">
          <Section title="Move" items={NAVIGATE} />
          <Section title="Judge" items={JUDGE} />
          <Section title="Inspect" items={INSPECT} />
        </div>

        <hr className="my-4 border-neutral-800" />

        <h3 className="text-[10px] font-medium uppercase text-neutral-500">
          How the verdicts are chosen
        </h3>
        <p className="mt-2 text-xs text-neutral-400">
          Every pick / alt / reject is proposed automatically, per group, from
          each frame’s quality score under this shoot’s genre ({profile}). Your
          changes always win and survive re-culling.
        </p>
        <ul className="mt-2 space-y-1">
          {VERDICT_RULES.map(([swatch, title, text]) => (
            <li key={title} className="flex gap-2 text-xs">
              {/* Swatch beside the words — never color carrying meaning alone. */}
              <span
                className={`mt-1 h-2 w-2 shrink-0 rounded-sm border-2 ${swatch}`}
              />
              <span className="text-neutral-400">
                {title} — <span className="text-neutral-500">{text}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[10px] text-neutral-500">
          The reason for the current frame is always in the bar below the photo;
          press E for the per-metric scores behind it.
        </p>
      </div>
    </div>
  );
}

function Section({ title, items }: { title: string; items: Item[] }) {
  return (
    <div>
      <h3 className="mb-2 text-[10px] font-medium uppercase text-neutral-500">
        {title}
      </h3>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={item.key} className="flex gap-2">
            <span className="w-12 shrink-0">
              <KeyCap>{item.key}</KeyCap>
            </span>
            <span className="min-w-0">
              <span className="block text-xs text-neutral-400">
                {item.label}
              </span>
              {item.detail && (
                <span className="block text-[10px] text-neutral-500">
                  {item.detail}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
