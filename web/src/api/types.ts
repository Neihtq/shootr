/** TypeScript mirrors of the engine payloads (design 10 §3).
 *
 * Contract rule 1: the client NEVER computes domain values. These types
 * carry the engine's verdicts and evidence; any arithmetic on scores in
 * this codebase is a design bug (design 10 §1).
 *
 * `value: number | null` is semantically load-bearing: null means
 * not-applicable or detector-abstained and must render as "—", never as a
 * zero bar (design 10 §3).
 */

export interface ScoreComponent {
  value: number | null;
  weight: number;
  contrib: number | null;
  evidence: Record<string, unknown>;
}

export interface Score {
  profile: string;
  total: number;
  components: Record<string, ScoreComponent>;
  flags: string[];
  weights_hash: string;
}

export interface Eye {
  sharp_norm: number | null;
  open: number | null;
}

export interface Face {
  idx: number;
  bbox: [number, number, number, number];
  yaw: number | null;
  capture_quality: number | null;
  eyes: { left: Eye; right: Eye };
  eye_source: string;
}

export interface PhotoDetail {
  id: number;
  filename: string;
  raw_format: string | null;
  captured_at: string | null;
  camera_model: string | null;
  lens_model: string | null;
  iso: number | null;
  shutter: number | null;
  aperture: number | null;
  focal_length: number | null;
  exposure_bias: number | null;
  missing: boolean;
  analysis: {
    decode_mode: string;
    engine_version: string;
    frame: Record<string, number | null>;
  } | null;
  faces: Face[];
  score: Score | null;
  group: { shot_id: number; size: number; is_bracket: boolean } | null;
  selection: {
    state: SelectionState;
    rank: number | null;
    reason: string;
    user_override: boolean;
  } | null;
}

export type SelectionState = "pick" | "alt" | "reject";

export interface SelectionEntry {
  photo_id: number;
  group_id: number | null;
  state: SelectionState;
  rank: number | null;
  reason: string;
  user_override: number;
}

export interface Selection {
  id: number;
  shoot_id: number;
  created_at: string;
  exported_at: string | null;
  params: Record<string, unknown>;
  entries: SelectionEntry[];
}

export interface Group {
  id: number;
  level: string;
  is_bracket: boolean;
  photo_ids: number[];
}

export interface Shoot {
  id: number;
  name: string;
  profile: string;
  photo_count: number;
  analyzed_count: number;
  latest_selection_id: number | null;
  /** Non-null while analysis/culling is in flight. Server-derived, so it
   * survives a reload and agrees with the native app. */
  busy_job_id: number | null;
  /** Why a stopped analyze job stopped (`volume_offline`, `helper_failed`,
   * `interrupted_restart`). Non-null means partial work is checkpointed and
   * re-running resumes it — never presented as "not culled yet". */
  stopped_reason: string | null;
}

export interface Library {
  id: number;
  root_path: string;
  online: boolean;
}

export interface ShootProposal {
  photo_ids: number[];
  start: string | null; // null when no photo in the folder has EXIF dates
  end: string | null;
  directories: string[];
}

export interface JobProgress {
  job_id: number;
  kind: string;
  state: "pending" | "running" | "done" | "failed" | "cancelled";
  total: number;
  completed: number;
  failed: number;
}

export interface ExportPreview {
  new_sidecars: number;
  updates: number;
  conflicts: {
    path: string;
    old_rating: number | null;
    new_rating: number | null;
    has_develop_settings: boolean;
  }[];
  skipped_dng: string[];
  unchanged: number;
  backup_dir: string;
}

export interface ApiError {
  code: string;
  message: string;
  detail: Record<string, unknown>;
  retryable: boolean;
}

export interface SharpnessMap {
  tiles: number[][] | null;
  max: number | null;
  mean: number | null;
}
