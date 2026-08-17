/** The evidence panel — "the point" of this UI (design 11 §3).
 *
 * Renders score.components directly from the API: value, weight,
 * contribution, evidence. null components render as "—", NEVER a zero bar —
 * displaying "not measured" as "scored zero" would make every landscape
 * look broken (design 10 §3).
 */

import type { PhotoDetail, ScoreComponent } from "../api/types";
import { exifLine } from "../exif";

const METRIC_LABELS: Record<string, string> = {
  eye_focus: "eye focus",
  eyes_open: "eyes open",
  sharpness: "sharpness",
  composition: "composition",
  face_quality: "face quality",
  exposure: "exposure",
};

function Bar({ name, comp }: { name: string; comp: ScoreComponent }) {
  const label = METRIC_LABELS[name] ?? name;
  if (comp.value === null) {
    const reason = (comp.evidence?.reason as string) ?? "not applicable";
    return (
      <div className="mb-3">
        <div className="flex justify-between text-xs text-neutral-400">
          <span>{label}</span>
          <span title={reason}>—</span>
        </div>
        <div className="h-2 rounded bg-neutral-800" />
        <div className="text-[10px] text-neutral-500">{reason}</div>
      </div>
    );
  }
  return (
    <div className="mb-3">
      <div className="flex justify-between text-xs text-neutral-300">
        <span>{label}</span>
        <span>
          {comp.value.toFixed(2)}
          <span className="text-neutral-500"> ×{comp.weight.toFixed(2)}</span>
        </span>
      </div>
      <div className="h-2 rounded bg-neutral-800">
        <div
          className="h-2 rounded bg-neutral-300"
          style={{ width: `${Math.round(comp.value * 100)}%` }}
        />
      </div>
      <EvidenceLine evidence={comp.evidence} />
    </div>
  );
}

function EvidenceLine({ evidence }: { evidence: Record<string, unknown> }) {
  const parts = Object.entries(evidence)
    .filter(([k]) => k !== "per_eye" && k !== "penalties")
    .slice(0, 3)
    .map(([k, v]) => `${k}: ${typeof v === "number" ? v.toFixed(2) : String(v)}`);
  if (!parts.length) return null;
  return (
    <div className="truncate text-[10px] text-neutral-500" title={parts.join(" · ")}>
      {parts.join(" · ")}
    </div>
  );
}

export function EvidencePanel({ photo }: { photo: PhotoDetail }) {
  const score = photo.score;
  if (!score) {
    return (
      <div className="p-3 text-xs text-neutral-500">
        Not scored yet — analysis pending.
      </div>
    );
  }
  return (
    <div className="p-3">
      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-sm font-medium text-neutral-200">
          {score.total.toFixed(2)}
        </span>
        <span className="text-[10px] text-neutral-500" title={score.weights_hash}>
          {score.profile}
        </span>
      </div>
      {Object.entries(score.components).map(([name, comp]) => (
        <Bar key={name} name={name} comp={comp} />
      ))}
      {score.flags.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-neutral-400">flags</div>
          {score.flags.map((f) => (
            <span
              key={f}
              className="mr-1 inline-block rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-amber-300/80"
            >
              {f}
            </span>
          ))}
        </div>
      )}
      {photo.selection && (
        <div className="mt-3 border-t border-neutral-800 pt-2 text-[11px] text-neutral-400">
          {photo.selection.reason}
          {photo.selection.user_override && (
            <span className="ml-1 text-sky-400">(your override)</span>
          )}
        </div>
      )}
      <div className="mt-3 border-t border-neutral-800 pt-2">
        <div className="mb-1 text-[10px] uppercase text-neutral-500">
          Capture
        </div>
        <div className="font-mono text-[11px] text-neutral-400">
          {exifLine(photo)}
        </div>
        {photo.camera_model && (
          <div className="text-[10px] text-neutral-500">
            {photo.camera_model}
          </div>
        )}
        {photo.lens_model && (
          <div className="truncate text-[10px] text-neutral-500">
            {photo.lens_model}
          </div>
        )}
        {photo.captured_at && (
          <div className="text-[10px] text-neutral-500">
            {photo.captured_at.replace("T", "  ")}
          </div>
        )}
      </div>
    </div>
  );
}
