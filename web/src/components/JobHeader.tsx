/** Progressive-analysis header (design 11 §6): the UI must be useful DURING
 * the 20–30 min analyze run. Failed count is always visible — a run that
 * silently skipped 300 corrupt files would misrepresent coverage. */

import { useState } from "react";
import { useJobStream } from "../api/hooks";
import type { JobProgress } from "../api/types";

export function JobHeader() {
  const [job, setJob] = useState<JobProgress | null>(null);
  useJobStream(setJob);

  if (!job || job.state === "done" || job.state === "cancelled") return null;

  const pct = job.total ? Math.round((job.completed / job.total) * 100) : 0;
  return (
    <div className="flex items-center gap-3 border-b border-neutral-800 bg-neutral-900 px-3 py-1 text-xs text-neutral-300">
      <span>
        {job.kind} {job.completed.toLocaleString()}/{job.total.toLocaleString()}
      </span>
      <div className="h-1.5 w-40 rounded bg-neutral-800">
        <div
          className="h-1.5 rounded bg-neutral-400 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      {job.failed > 0 && (
        <span className="text-amber-400">{job.failed} failed</span>
      )}
      {job.state === "failed" && (
        <span className="text-red-400">job failed — some items exhausted retries</span>
      )}
    </div>
  );
}
