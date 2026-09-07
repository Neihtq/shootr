/** Style learning screen (design 08 §7a): look families + prediction preview
 * for one shoot.
 *
 * The engine learns and predicts; this screen only renders what it says —
 * families, traits, medians, params, confidence, neighbours, abstentions
 * (design 10 §1). It also states the permanent scope boundary: local
 * adjustments are never transferred (design 08 §1).
 */

import { useState } from "react";
import { errorCode } from "../api/client";
import { useShoots, useStyleFamilies } from "../api/hooks";
import { LookFamilies } from "./LookFamilies";
import { StylePredictPanel } from "./StylePredictPanel";

export function StyleView({ shootId }: { shootId: number }) {
  const { data: families, error, isLoading } = useStyleFamilies();
  const { data: shoots } = useShoots();
  const shootName = shoots?.find((s) => s.id === shootId)?.name;
  const [usedFamily, setUsedFamily] = useState<number | null>(null);

  // 409 insufficient_history is a state of the user's data, not a failure to
  // retry: there is nothing to learn from until a catalog is imported.
  if (errorCode(error) === "insufficient_history") {
    return (
      <Frame shootName={shootName}>
        <div className="rounded border border-neutral-800 p-4 text-xs">
          <div className="mb-2 text-sm text-neutral-200">
            No edit history to learn from yet
          </div>
          <p className="mb-2 text-neutral-300">
            Style learning is built entirely from your own past edits — it never
            invents a look. Import a Lightroom Classic catalog (or a folder with
            XMP sidecars carrying develop settings) so the engine has edited
            photos to cluster and copy from.
          </p>
          <p className="mb-2 text-neutral-400">
            The imported photos also need to have been analyzed: similarity
            comes from the scene embedding, so an unanalyzed edit is invisible
            to the predictor.
          </p>
          <div className="text-neutral-500">
            Engine: {(error as Error).message}
          </div>
        </div>
      </Frame>
    );
  }

  if (error) {
    return (
      <Frame shootName={shootName}>
        <div className="rounded border border-neutral-800 p-4 text-xs">
          <div className="mb-1 text-neutral-300">
            The engine could not load look families.
          </div>
          <div className="text-neutral-500">
            Engine: {errorCode(error) ?? "error"} — {(error as Error).message}
          </div>
        </div>
      </Frame>
    );
  }

  return (
    <Frame shootName={shootName}>
      <section className="mb-6">
        <h2 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">
          Look families — discovered in your edit history
        </h2>
        {isLoading ? (
          <div className="text-xs text-neutral-500">
            Clustering your edits…
          </div>
        ) : (
          <LookFamilies families={families ?? []} highlightId={usedFamily} />
        )}
      </section>

      <section>
        <h2 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">
          Predicted develop settings for this shoot's picks
        </h2>
        {families && families.length > 0 && (
          <StylePredictPanel
            shootId={shootId}
            families={families}
            onFamilyResolved={setUsedFamily}
          />
        )}
      </section>
    </Frame>
  );
}

function Frame({
  shootName,
  children,
}: {
  shootName?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto p-6 text-sm">
      <h1 className="mb-1 text-lg font-medium text-neutral-100">
        Style{shootName ? ` — ${shootName}` : ""}
      </h1>
      {/* The boundary, stated where a user would reasonably expect brushes to
          appear (design 08 §1, §7a). */}
      <p className="mb-5 text-xs text-neutral-500">
        Global develop sliders only, learned from your own edits. Local
        adjustments — brushes, radial and linear gradients, AI subject/sky
        masks — are never transferred: they are specific to one photo's
        content, and there is no honest way to move them. Crop and straighten
        are yours alone and are never predicted.
      </p>
      {children}
    </div>
  );
}
