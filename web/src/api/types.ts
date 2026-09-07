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

/** The engine's allowed scoring profiles (api.py rejects anything else with
 * `invalid_profile`). Mirrored here so pickers can't offer a fifth genre. */
export const PROFILES = ["portrait", "event", "landscape", "street"] as const;
export type Profile = (typeof PROFILES)[number];

/** POST /api/libraries — add (or rescan; re-adding a known path is never a
 * duplicate) a library root. */
export interface LibraryScanResult {
  id: number;
  root_path: string;
  scan: {
    added: number;
    unchanged: number;
    errors: number;
    /** Rows healed with metadata a previous broken probe left NULL. */
    backfilled: number;
  };
}

/** DELETE /api/libraries/{id}. `note` is non-null when selections were
 * already exported: the XMP sidecars stay in the user's files. */
export interface LibraryDeleteResult {
  deleted: number;
  note: string | null;
}

/** POST /api/shoots/{id}/analyze. `chained` = everything was already
 * analyzed, so group/score/select ran inline and there is no job to watch. */
export interface AnalyzeStart {
  job_id: number;
  total: number;
  chained: boolean;
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
  skipped_embedded: string[];
  unchanged: number;
  backup_dir: string;
}

/** GET /api/style/families (design 08 §3). Discovered from the user's own
 * edits, never assumed — read-only in the UI. `median` is the family's
 * median edit as the ENGINE computed it; the client only renders it. */
export interface StyleFamily {
  id: number;
  size: number;
  /** Engine-written trait label, e.g. "+Highlights2012 −Contrast2012". */
  traits: string;
  /** Feed straight to the thumbnail endpoint — the family's face. */
  sample_photo_ids: number[];
  median: Record<string, number>;
}

/** Engine abstention reasons (api.py + style.predict). An abstention is a
 * state with a cause; it is NEVER an empty parameter list meaning "no
 * changes needed" (design 08 §7a, README rule 8). */
export type StyleAbstainReason =
  | "low_confidence"
  | "no_similar_history"
  | "family_too_small"
  | "not_analyzed";

/** One photo's entry in the predict preview. `params`, `confidence` and
 * `neighbor_photo_ids` are absent on the `not_analyzed` path and empty on
 * the other abstentions — hence optional, and hence the UI must key off
 * `abstained`, not off "params is empty". */
export interface StylePrediction {
  photo_id: number;
  abstained: boolean;
  /** null when a prediction was made. */
  reason: StyleAbstainReason | string | null;
  confidence?: number;
  params?: Record<string, number>;
  /** Guardrails that changed a predicted value, param → the engine's reason
   * (design 08 §6). Rendered, never silent: a withheld exposure push would
   * otherwise appear as an unexplained number (README rule 5). */
  damped?: Record<string, string>;
  /** Parameters the engine DID predict (the value is here) but will not
   * write, because the user excluded them (design 08 §7a). Distinct from an
   * abstention: "we had a number and you told us not to write it" is not
   * "we had nothing", so the UI must render it as neither. */
  excluded?: Record<string, number>;
  /** The history photos the blend came from — the whole reason k-NN was
   * chosen over a trained model (design 08 §4). Present on
   * `low_confidence` too: "closest we had, still not close enough". */
  neighbor_photo_ids?: number[];
}

/** POST /api/shoots/{id}/style/predict — a PREVIEW. Nothing is written. */
export interface StylePredictResult {
  /** Resolved family: the one requested, or the engine's auto-suggestion
   * when the request omitted it. */
  family: number;
  process_version: string;
  /** The user's per-parameter opt-out as the engine applied it to THIS
   * preview — not a client-side filter (design 08 §7a). */
  excluded_params: string[];
  predictions: StylePrediction[];
}

/** GET/PUT /api/style/preferences (design 08 §7a). The per-parameter opt-out
 * lives in the engine's `preference` table because it changes what lands in
 * the user's files: a client-local switch would let web and native write
 * different edits from the same click. `modelable_params` is the engine's own
 * parameter list and the PUT allowlist — a name outside it is a 400
 * `unknown_param`. */
export interface StylePreferences {
  excluded_params: string[];
  modelable_params: string[];
}

/** POST /api/shoots/{id}/style/export-develop. Conflicts are sidecars that
 * already hold the user's own develop settings: reported, skipped, and there
 * is deliberately no override parameter to send (design 08 §6). */
export interface StyleExportResult {
  written: number[];
  abstained: { photo_id: number; reason: string }[];
  conflicts: { photo_id: number; path: string }[];
  /** The opt-out the engine honoured on this write: these parameters were
   * predicted for some photos and deliberately left out of every sidecar. */
  excluded_params: string[];
  note: string;
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
