/** Scaffolding screens (design 11 §2): library list and shoot picker with
 * the pipeline actions. Everything here is one level above Group Review. */

import { useState } from "react";
import { del, post } from "../api/client";
import { useLibraries, useShoots } from "../api/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { ProposalList } from "./ProposalList";

export function ShootList({
  onOpenShoot,
}: {
  onOpenShoot: (shootId: number, selectionId: number | null) => void;
}) {
  const { data: libraries } = useLibraries();
  const { data: shoots } = useShoots();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [newRoot, setNewRoot] = useState("");

  const addLibrary = async () => {
    if (!newRoot) return;
    setBusy("scanning…");
    try {
      await post("/api/libraries", { root_path: newRoot });
      setNewRoot("");
      qc.invalidateQueries();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const runPipeline = async (shootId: number) => {
    // One action: analyze runs in the background; the engine chains
    // group → score → select when it finishes. Firing those steps from
    // here while analysis runs was a race (empty scores on first run).
    setBusy("starting analysis…");
    try {
      const r = await post<{ job_id: number; total: number; chained: boolean }>(
        `/api/shoots/${shootId}/analyze`,
      );
      qc.invalidateQueries();
      if (r.total > 0) {
        alert(
          `Analyzing ${r.total} photos in the background — watch the ` +
            "progress bar. The shoot opens with results when it finishes; " +
            "reopen it if you got there early.",
        );
      }
      onOpenShoot(shootId, null);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-2xl p-6 text-sm">
      <h1 className="mb-4 text-lg font-medium text-neutral-100">Shootr</h1>

      <section className="mb-6">
        <h2 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">
          Libraries
        </h2>
        {libraries?.map((lib) => (
          <div key={lib.id} className="flex items-center gap-2 py-1 text-neutral-300">
            <span className={lib.online ? "text-emerald-400" : "text-red-400"}>
              ●
            </span>
            <span className="truncate">{lib.root_path}</span>
            {!lib.online && (
              <span className="text-xs text-neutral-500">(offline — showing last known contents)</span>
            )}
            <button
              onClick={async () => {
                if (
                  !window.confirm(
                    `Remove this library from Shootr?\n\n${lib.root_path}\n\n` +
                      "Scan data, analysis, and selections are removed from " +
                      "the app. Your photo files are NOT touched.",
                  )
                )
                  return;
                await del(`/api/libraries/${lib.id}`);
                qc.invalidateQueries();
              }}
              className="ml-auto rounded border border-neutral-800 px-2 py-0.5 text-xs text-neutral-500 hover:border-red-900 hover:text-red-400"
            >
              Remove
            </button>
          </div>
        ))}
        <div className="mt-2 flex gap-2">
          <input
            value={newRoot}
            onChange={(e) => setNewRoot(e.target.value)}
            placeholder="/Volumes/Shoots2026/…"
            className="flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-200"
          />
          <button
            onClick={addLibrary}
            disabled={!!busy}
            className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800 disabled:opacity-50"
          >
            Add & scan
          </button>
        </div>
      </section>

      {libraries?.map((lib) => (
        <ProposalList key={lib.id} libraryId={lib.id} />
      ))}

      <section>
        <h2 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">
          Shoots
        </h2>
        {shoots?.map((s) => (
          <div
            key={s.id}
            className="flex items-center gap-3 border-b border-neutral-800 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="text-neutral-200">{s.name}</div>
              <div className="text-xs text-neutral-500">
                {s.profile} · {s.photo_count} photos
                {s.analyzed_count < s.photo_count &&
                  ` · ${s.analyzed_count} analyzed`}
                {s.latest_selection_id !== null && " · culled"}
              </div>
            </div>
            <button
              onClick={() => runPipeline(s.id)}
              disabled={!!busy}
              className="rounded border border-neutral-700 px-2 py-1 text-xs hover:bg-neutral-800 disabled:opacity-50"
            >
              Analyze & cull
            </button>
            <button
              onClick={() => onOpenShoot(s.id, s.latest_selection_id)}
              className="rounded border border-neutral-700 px-2 py-1 text-xs hover:bg-neutral-800"
            >
              Open
            </button>
          </div>
        ))}
        {busy && <div className="mt-2 text-xs text-neutral-400">{busy}</div>}
      </section>
    </div>
  );
}
