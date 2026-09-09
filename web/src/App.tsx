/** App shell. Dark neutral chrome by default (design 11 §8): colored chrome
 * around photos biases color judgement. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { DeliverDialog } from "./components/DeliverDialog";
import { ExportDialog } from "./components/ExportDialog";
import { GroupReview } from "./components/GroupReview";
import { JobHeader } from "./components/JobHeader";
import { MoveKeepersDialog } from "./components/MoveKeepersDialog";
import { ShootList } from "./components/ShootList";
import { StyleView } from "./components/StyleView";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 1 },
  },
});

interface View {
  shootId: number | null;
  selectionId: number | null;
  /** Which screen an open shoot shows: culling, or style prediction (design
   * 08 §7a). */
  screen: "review" | "style";
}

function Shell() {
  const [view, setView] = useState<View>({
    shootId: null,
    selectionId: null,
    screen: "review",
  });
  const [exportOpen, setExportOpen] = useState(false);
  const [deliverOpen, setDeliverOpen] = useState(false);
  /** Separate from `deliverOpen`, like the two actions themselves (design 07
   * §3.2b): moving the originals is its own door, not a mode of delivery. */
  const [moveOpen, setMoveOpen] = useState(false);

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-200">
      <JobHeader />
      {view.shootId === null ? (
        <ShootList
          onOpenShoot={(shootId, selectionId) =>
            setView({ shootId, selectionId, screen: "review" })
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-2 border-b border-neutral-800 px-3 py-1 text-xs text-neutral-400">
            <button
              onClick={() =>
                setView({ shootId: null, selectionId: null, screen: "review" })
              }
              className="hover:text-neutral-200"
            >
              ← shoots
            </button>
            <span className="text-neutral-700">|</span>
            {(["review", "style"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setView((v) => ({ ...v, screen: s }))}
                className={
                  view.screen === s
                    ? "text-neutral-100"
                    : "hover:text-neutral-200"
                }
              >
                {s === "review" ? "cull review" : "style"}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {view.screen === "review" ? (
              <GroupReview
                shootId={view.shootId}
                selectionId={view.selectionId}
                onOpenExport={() => setExportOpen(true)}
                onOpenDeliver={() => setDeliverOpen(true)}
                onOpenMove={() => setMoveOpen(true)}
                onOpenStyle={() => setView((v) => ({ ...v, screen: "style" }))}
                dialogOpen={exportOpen || deliverOpen || moveOpen}
              />
            ) : (
              <StyleView shootId={view.shootId} />
            )}
          </div>
        </>
      )}
      {exportOpen && view.selectionId !== null && (
        <ExportDialog
          selectionId={view.selectionId}
          onClose={() => setExportOpen(false)}
        />
      )}
      {deliverOpen && view.selectionId !== null && (
        <DeliverDialog
          selectionId={view.selectionId}
          onClose={() => setDeliverOpen(false)}
        />
      )}
      {moveOpen && view.selectionId !== null && (
        <MoveKeepersDialog
          selectionId={view.selectionId}
          onClose={() => setMoveOpen(false)}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  );
}
