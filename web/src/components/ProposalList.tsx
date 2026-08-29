/** Shoot confirmation with profile picker (design 02 §4, 11 §2).
 *
 * Ingest proposes; it never finalizes — only the user knows the genre, and
 * the genre sets the scoring profile. A one-day two-part wedding shouldn't
 * silently become two shoots, nor a week of travel one, so proposals are
 * editable before confirming.
 */

import { useState } from "react";
import {
  useAnalyzeShoot,
  useCreateShoot,
  useShootProposals,
} from "../api/hooks";
import type { Profile, ShootProposal } from "../api/types";
import { PROFILES } from "../api/types";

function proposalLabel(p: ShootProposal): string {
  const day = p.start?.slice(0, 10) ?? "undated";
  const dir = p.directories[p.directories.length - 1] ?? "";
  return dir && dir !== "." ? `${dir} (${day})` : day;
}

export function ProposalList({ libraryId }: { libraryId: number }) {
  const { data: proposals, isLoading } = useShootProposals(libraryId);
  const createShoot = useCreateShoot();
  const analyze = useAnalyzeShoot();
  const [busy, setBusy] = useState(false);
  // Per-proposal edits, keyed by index.
  const [names, setNames] = useState<Record<number, string>>({});
  const [profiles, setProfiles] = useState<Record<number, Profile>>({});
  // Checked proposals for combining ("morning ceremony + evening reception
  // is ONE wedding" — design 02 §4's two-part-wedding case).
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const confirm = async (i: number, p: ShootProposal, andAnalyze: boolean) => {
    setBusy(true);
    try {
      const shoot = await createShoot.mutateAsync({
        library_id: libraryId,
        name: names[i] || proposalLabel(p),
        profile: profiles[i] || "event",
        photo_ids: p.photo_ids,
      });
      // "Create & analyze" mirrors the native proposal card: one gesture
      // from proposal to running pipeline. Progress shows in the SSE job
      // header; the shoot row unlocks itself when the engine finishes.
      if (andAnalyze) await analyze.mutateAsync(shoot.id);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const combineChecked = async () => {
    if (!proposals || checked.size < 2) return;
    const indices = [...checked].sort((a, b) => a - b);
    const parts = indices.map((i) => proposals[i]);
    setBusy(true);
    try {
      await createShoot.mutateAsync({
        library_id: libraryId,
        name: names[indices[0]] || proposalLabel(parts[0]),
        profile: profiles[indices[0]] || "event",
        photo_ids: parts.flatMap((p) => p.photo_ids),
      });
      setChecked(new Set());
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return null;
  if (!proposals?.length) return null;

  return (
    <section className="mb-6">
      <div className="mb-2 flex items-baseline gap-3">
        <h2 className="text-xs uppercase tracking-wide text-neutral-500">
          Proposed shoots — confirm genre to enable scoring
        </h2>
        {checked.size >= 2 && (
          <button
            onClick={combineChecked}
            disabled={busy}
            className="rounded border border-sky-800 bg-sky-950 px-2 py-0.5 text-xs text-sky-200 hover:bg-sky-900 disabled:opacity-50"
          >
            Combine {checked.size} into one shoot
          </button>
        )}
      </div>
      {proposals.map((p, i) => (
        <div
          key={`${p.start}-${i}`}
          className="mb-2 rounded border border-neutral-800 p-3"
        >
          <div className="mb-2 flex items-baseline gap-2 text-xs text-neutral-400">
            <label className="flex items-center gap-1.5 text-neutral-500">
              <input
                type="checkbox"
                checked={checked.has(i)}
                onChange={(e) =>
                  setChecked((s) => {
                    const next = new Set(s);
                    if (e.target.checked) next.add(i);
                    else next.delete(i);
                    return next;
                  })
                }
              />
            </label>
            <span className="text-neutral-200">
              {p.photo_ids.length} photos
            </span>
            <span>
              {p.start
                ? `${p.start.replace("T", " ")} → ${p.end?.replace("T", " ")}`
                : "no capture dates"}
            </span>
            <span className="truncate">{p.directories.join(", ")}</span>
          </div>
          <div className="flex gap-2">
            <input
              value={names[i] ?? proposalLabel(p)}
              onChange={(e) =>
                setNames((n) => ({ ...n, [i]: e.target.value }))
              }
              className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
            />
            <select
              value={profiles[i] ?? "event"}
              onChange={(e) =>
                setProfiles((pr) => ({ ...pr, [i]: e.target.value as Profile }))
              }
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
            >
              {PROFILES.map((prof) => (
                <option key={prof} value={prof}>
                  {prof}
                </option>
              ))}
            </select>
            <button
              onClick={() => confirm(i, p, false)}
              disabled={busy}
              className="rounded border border-neutral-700 px-3 py-1 text-sm hover:bg-neutral-800 disabled:opacity-50"
            >
              Create shoot
            </button>
            <button
              onClick={() => confirm(i, p, true)}
              disabled={busy}
              title="Create the shoot and start analysis now — progress shows in the header"
              className="rounded border border-emerald-800 bg-emerald-950 px-3 py-1 text-sm text-emerald-200 hover:bg-emerald-900 disabled:opacity-50"
            >
              Create & analyze
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
