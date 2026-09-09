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

/** POST /api/selections/{id}/deliver (design 07 §3.2b) — put the keepers in a
 * folder as FILES, for the workflow with no Lightroom in it.
 *
 * The engine's own mode list; mirrored so a picker cannot offer a fourth. */
export const DELIVERY_MODES = ["hardlink", "copy", "move"] as const;
export type DeliveryMode = (typeof DELIVERY_MODES)[number];

/** The plan the engine computed. Present on the dry run AND echoed on the
 * confirmed run, so the result is read against the plan it came from. */
interface DeliveryPlan {
  mode: DeliveryMode;
  dest_dir: string;
  /** Photos in scope: picks, plus alts only when `include_alt` was sent.
   * Rejects are never in scope, whatever the client asks for. */
  count: number;
  /** Sidecars and JPEG siblings that travel with the RAWs. */
  companions: number;
  /** Destination names a collision forced a numbered suffix on. Nothing is
   * ever overwritten, so a collision renames rather than replaces. */
  renamed: string[];
  /** Sources already hardlinked into the destination — skipped, not redone. */
  already_present: string[];
  /** In the selection but not on disk right now (offline drive, moved file). */
  missing_source: string[];
  /** Destination is on a different volume than the photos. Fatal for
   * hardlink; for move it means the verified copy-then-unlink path. */
  cross_volume: boolean;
  bytes_needed: number;
  free_bytes: number | null;
  /** The engine's verdict, not a comparison the client makes. Always true for
   * modes that consume no space. */
  enough_space: boolean;
  /** True for `move`: the user's originals leave their current folder. The
   * client must be able to say so before it happens. */
  moves_originals: boolean;
}

/** Dry run: nothing was written. This is what the user confirms against. */
export interface DeliveryPreview extends DeliveryPlan {
  dry_run: true;
}

export interface DeliveryResult extends DeliveryPlan {
  dry_run: false;
  delivered: number;
  /** Per-file failures, collected rather than fatal — one unreadable photo
   * does not abandon the rest. */
  failed: { file: string; error: string }[];
  /** Moved photos whose library path was updated in place (still inside the
   * library root; identity is content-based, so analysis survives). */
  relinked: number;
  /** Moved out of the library root and marked missing — honest, and nothing
   * was deleted. */
  marked_missing: number;
  /** The engine's plain sentence about what happened to the library's paths.
   * Relayed verbatim, never paraphrased. */
  note: string;
}

/** One endpoint, discriminated by `dry_run`. */
export type DeliveryResponse = DeliveryPreview | DeliveryResult;

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

/** GET /api/style/methods — the method registry (design 08 §7b).
 *
 * The two booleans are the whole trade-off and the client must state it, not
 * hide it: `fits` = the method has a fitting step, so new history only counts
 * after a relearn; `explains_by_neighbours` = a prediction can name the
 * photos it was copied from. No method is privileged and none is
 * auto-selected — the engine measures, the user chooses. */
export interface StyleMethod {
  method: string;
  /** The engine's knobs for this method. `null` for a knob the engine picks
   * while learning (ridge's λ is chosen by cross-validation). */
  default_params: Record<string, number | null>;
  fits: boolean;
  explains_by_neighbours: boolean;
}

/** One parameter's row in a model's evaluation (`metrics.per_param`).
 *
 * `mae` is the model's error and `baseline_mae` the family-median baseline's,
 * both in the parameter's own units, both measured by the engine's harness.
 * The client renders the pair; it never combines them into a score of its own
 * (design 10 §1) — the engine already publishes its own tally in
 * `beats_median_on`. `baseline_mae: null` = the baseline had nothing to
 * compare on, which is not the same as a tie. */
export interface StyleParamMetric {
  mae: number;
  baseline_mae: number | null;
  n: number;
}

/** A model's evaluation as the §7 harness measured it FOR THAT MODEL, which
 * is what makes two models comparable at all.
 *
 * Every field is optional because an untrained model carries `{}` — a model
 * that exists but was never learned (the engine keeps the row when a create
 * hits `insufficient_history`) has no metrics, and inventing zeros for it
 * would read as "measured, and bad" (README rule 8). */
export interface StyleModelMetrics {
  history_n?: number;
  families?: number;
  /** Fraction of held-out photos the method produced a prediction for. */
  coverage?: number;
  /** The engine's own count of parameters where it beat the family median —
   * the engine's tally, not one the client recomputes. */
  beats_median_on?: number;
  params_scored?: number;
  held_out?: boolean;
  /** `shot_group` = whole bursts were held out together; `photo` = split
   * photo by photo, which lets burst siblings straddle the split and flatters
   * retrieval (design 08 §7b). Rendered, because it changes what the numbers
   * below mean. */
  held_out_by?: "shot_group" | "photo" | string;
  /** The ridge λ actually used (chosen by cross-validation when not pinned);
   * null for methods that have none. */
  lambda?: number | null;
  per_param?: Record<string, StyleParamMetric>;
}

/** A style model: the user's named, persisted choice of predictor (design 08
 * §7b). Created explicitly — nothing is learned on import. */
export interface StyleModel {
  id: number;
  name: string;
  method: string;
  /** Scope: which libraries the edit history comes from. Empty = all of
   * them, which is a real answer and not "unset". */
  library_ids: number[];
  params: Record<string, number | null>;
  metrics: StyleModelMetrics;
  history_n: number;
  /** The single process version the history was narrowed to before learning
   * (design 08 §6). */
  process_version: string | null;
  /** Engine timestamp, or null when the model was created but never learned. */
  trained_at: string | null;
  trained: boolean;
  is_active: boolean;
  /** Whether predictions from this model can name neighbour photos. False for
   * a fitted method: it reports how much history it was fitted from instead,
   * and the UI must render that rather than an empty thumbnail strip. */
  explains_by_neighbours: boolean;
}

/** Engine abstention reasons (api.py + style.predict). An abstention is a
 * state with a cause; it is NEVER an empty parameter list meaning "no
 * changes needed" (design 08 §7a, README rule 8). */
export type StyleAbstainReason =
  | "low_confidence"
  | "no_similar_history"
  | "family_too_small"
  | "not_analyzed"
  /** A fitted model produced no value at all for this photo. */
  | "model_abstained";

/** One photo's entry in the predict preview. `params`, `confidence` and
 * `neighbor_photo_ids` are absent on the `not_analyzed` path and empty on
 * the other abstentions — hence optional, and hence the UI must key off
 * `abstained`, not off "params is empty". */
export interface StylePrediction {
  photo_id: number;
  abstained: boolean;
  /** null when a prediction was made. */
  reason: StyleAbstainReason | string | null;
  /** Explicitly `null` from a fitted method — it has no retrieval confidence
   * to report. Null must read as absent, never as the text "null" or as a
   * zero-confidence prediction. */
  confidence?: number | null;
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
  /** Present only on predictions from a FITTED method, where the list above
   * is empty by construction. This is that method's whole answer to "where
   * did this come from" (design 08 §7b), so its presence — not the model's
   * method string — is what tells a row to render fitted provenance instead
   * of a neighbour strip. */
  fitted_from_history_n?: number;
}

/** POST /api/shoots/{id}/style/predict — a PREVIEW. Nothing is written. */
export interface StylePredictResult {
  /** Resolved family: the one requested, or the engine's auto-suggestion
   * when the request omitted it. */
  family: number;
  process_version: string;
  /** The model these predictions came from, or null meaning no model was
   * involved: the engine fell back to its built-in k-NN over all imported
   * history. Null is rendered as exactly that, since "the default happened to
   * run" is not the same statement as "you chose this model". */
  model: StyleModel | null;
  /** The user's per-parameter opt-out as the engine applied it to THIS
   * preview — not a client-side filter (design 08 §7a). */
  excluded_params: string[];
  /** What the engine actually learned from for this preview. Both trailing
   * fields are COUNTS of history photos the process-version filter set aside,
   * not flags (verified against the engine's payload). */
  history?: {
    used: number;
    excluded_other_process_version: number;
    process_version_unverified: number;
  };
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
  /** The model that produced what was written, or null for the engine's
   * built-in default. Reported back so the record of a write names its
   * source. */
  model: StyleModel | null;
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
