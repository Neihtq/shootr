/** App shell. Dark neutral chrome by default (design 11 §8): colored chrome
 * around photos biases color judgement. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ExportDialog } from "./components/ExportDialog";
import { GroupReview } from "./components/GroupReview";
import { JobHeader } from "./components/JobHeader";
import { ShootList } from "./components/ShootList";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 1 },
  },
});

interface View {
  shootId: number | null;
  selectionId: number | null;
}

function Shell() {
  const [view, setView] = useState<View>({ shootId: null, selectionId: null });
  const [exportOpen, setExportOpen] = useState(false);

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-200">
      <JobHeader />
      {view.shootId === null ? (
        <ShootList
          onOpenShoot={(shootId, selectionId) =>
            setView({ shootId, selectionId })
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-2 border-b border-neutral-800 px-3 py-1 text-xs text-neutral-400">
            <button
              onClick={() => setView({ shootId: null, selectionId: null })}
              className="hover:text-neutral-200"
            >
              ← shoots
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <GroupReview
              shootId={view.shootId}
              selectionId={view.selectionId}
              onOpenExport={() => setExportOpen(true)}
            />
          </div>
        </>
      )}
      {exportOpen && view.selectionId !== null && (
        <ExportDialog
          selectionId={view.selectionId}
          onClose={() => setExportOpen(false)}
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
