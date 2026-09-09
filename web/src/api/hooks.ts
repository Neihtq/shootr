/** TanStack Query hooks. Server state is the source of truth (design 11
 * §8): no client-side store of scores — caching stale domain values is how
 * the client drifts from the engine. */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { del, get, patch, post, put } from "./client";
import type {
  AnalyzeStart,
  DeliveryMode,
  DeliveryResponse,
  ExportPreview,
  Group,
  JobProgress,
  Library,
  LibraryDeleteResult,
  LibraryScanResult,
  PhotoDetail,
  Profile,
  Selection,
  SelectionState,
  SharpnessMap,
  Shoot,
  ShootProposal,
  StyleExportResult,
  StyleFamily,
  StyleMethod,
  StyleModel,
  StylePredictResult,
  StylePreferences,
} from "./types";

export const useLibraries = () =>
  useQuery({ queryKey: ["libraries"], queryFn: () => get<Library[]>("/api/libraries") });

/** Add (or rescan) a library root. The scan is synchronous in the engine and
 * can take seconds on a large folder — callers show a pending state. */
export const useAddLibrary = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rootPath: string) =>
      post<LibraryScanResult>("/api/libraries", { root_path: rootPath }),
    // New photos change libraries, proposals, and shoot counts alike.
    onSuccess: () => qc.invalidateQueries(),
  });
};

/** Removes the library's rows from the app database only — the engine never
 * touches files on disk (design README rule 2). Callers must confirm first. */
export const useDeleteLibrary = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (libraryId: number) =>
      del<LibraryDeleteResult>(`/api/libraries/${libraryId}`),
    onSuccess: () => qc.invalidateQueries(),
  });
};

export const useCreateShoot = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      library_id: number;
      name: string;
      profile: Profile;
      photo_ids: number[];
    }) => post<{ id: number }>("/api/shoots", body),
    onSuccess: () => qc.invalidateQueries(),
  });
};

/** Start (or resume — the engine reuses a stopped job) analysis. Progress
 * surfaces through the SSE job stream (JobHeader); nothing to poll here. */
export const useAnalyzeShoot = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shootId: number) =>
      post<AnalyzeStart>(`/api/shoots/${shootId}/analyze`),
    onSuccess: () => qc.invalidateQueries(),
  });
};

export const useShoots = () =>
  useQuery({
    queryKey: ["shoots"],
    queryFn: () => get<Shoot[]>("/api/shoots"),
    // While any shoot is busy, keep the list fresh so its card unlocks on
    // its own — including a job this tab didn't start. Idle: no polling.
    refetchInterval: (q) =>
      q.state.data?.some((s) => s.busy_job_id !== null) ? 2000 : false,
  });

export const useShootProposals = (libraryId: number | null) =>
  useQuery({
    queryKey: ["proposals", libraryId],
    queryFn: () => get<ShootProposal[]>(`/api/libraries/${libraryId}/shoot-proposals`),
    enabled: libraryId !== null,
  });

export const useGroups = (shootId: number | null) =>
  useQuery({
    queryKey: ["groups", shootId],
    queryFn: () => get<Group[]>(`/api/shoots/${shootId}/groups`),
    enabled: shootId !== null,
  });

export const usePhoto = (photoId: number | null) =>
  useQuery({
    queryKey: ["photo", photoId],
    queryFn: () => get<PhotoDetail>(`/api/photos/${photoId}`),
    enabled: photoId !== null,
  });

export const useSharpnessMap = (photoId: number | null, enabled: boolean) =>
  useQuery({
    queryKey: ["sharpness", photoId],
    queryFn: () => get<SharpnessMap>(`/api/photos/${photoId}/sharpness-map`),
    enabled: enabled && photoId !== null,
  });

export const useSelection = (selectionId: number | null) =>
  useQuery({
    queryKey: ["selection", selectionId],
    queryFn: () => get<Selection>(`/api/selections/${selectionId}`),
    enabled: selectionId !== null,
  });

/** Optimistic override (design 11 §5): at culling speed, waiting a round
 * trip per keystroke is unusable. Rolls back on error. */
export const useOverrideEntry = (selectionId: number | null) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ photoId, state }: { photoId: number; state: SelectionState }) =>
      patch(`/api/selections/${selectionId}/entries/${photoId}`, { state }),
    onMutate: async ({ photoId, state }) => {
      await qc.cancelQueries({ queryKey: ["selection", selectionId] });
      const prev = qc.getQueryData<Selection>(["selection", selectionId]);
      if (prev) {
        qc.setQueryData<Selection>(["selection", selectionId], {
          ...prev,
          entries: prev.entries.map((e) =>
            e.photo_id === photoId
              ? { ...e, state, user_override: 1, reason: "user override" }
              : e,
          ),
        });
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["selection", selectionId], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["selection", selectionId] });
      qc.invalidateQueries({ queryKey: ["photo"] });
    },
  });
};

export const useRunSelect = (shootId: number | null) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      post<{ selection_id: number }>(`/api/shoots/${shootId}/select`, {}),
    onSuccess: () => qc.invalidateQueries(),
  });
};

export const useExportPreview = (selectionId: number | null) =>
  useMutation({
    mutationFn: () =>
      post<ExportPreview>(`/api/selections/${selectionId}/export/preview`),
  });

export const useExport = (selectionId: number | null) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (confirmOverwrite: boolean) =>
      post<{ written: number }>(`/api/selections/${selectionId}/export`, {
        confirm_overwrite: confirmOverwrite,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["selection", selectionId] }),
  });
};

/** Deliver the selects as files (design 07 §3.2b).
 *
 * One endpoint for both steps: without `confirm` it is a dry run that writes
 * nothing and returns the plan, with `confirm` it runs that plan. The client
 * always asks for the plan first — it does not decide whether a mode is
 * possible, whether there is room, or what collides (design 10 §1).
 *
 * `include_alt` widens the scope from picks to picks + alts. There is no value
 * that includes rejects. */
export const useDeliverSelects = (selectionId: number | null) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      dest_dir: string;
      mode: DeliveryMode;
      include_alt: boolean;
      confirm: boolean;
    }) => post<DeliveryResponse>(`/api/selections/${selectionId}/deliver`, body),
    onSuccess: (r) => {
      // A confirmed move relocates originals: the engine rewrites photo paths
      // or marks them missing, so anything the client shows about those photos
      // is stale. A dry run wrote nothing — nothing to refresh.
      if (!r.dry_run) qc.invalidateQueries();
    },
  });
};

/** -- style learning (design 08 §7a) ---------------------------------------
 *
 * Every value on these screens — families, traits, medians, predicted
 * params, confidence, neighbours, abstentions — is computed by the engine.
 * The client renders it (design 10 §1); there is deliberately no local
 * blending, no confidence maths, no re-derived abstention rule here.
 */

/** Look families, spanning all imported history: looks belong to the user,
 * not to a shoot. 409 `insufficient_history` is a legitimate state, not a
 * transient failure, so retries are off — the screen renders the state. */
export const useStyleFamilies = () =>
  useQuery({
    queryKey: ["style", "families"],
    queryFn: () => get<StyleFamily[]>("/api/style/families"),
    retry: false,
  });

/** -- style models (design 08 §7b) -----------------------------------------
 *
 * A model is a user-created object with four explicit operations: learn
 * (create), relearn (train), compare (read `metrics`), choose (activate).
 * Nothing here decides anything: the metrics are the engine's harness output
 * and the active model is engine state, so both clients read the same answer.
 */

/** The method registry. Static for a given engine build, so it is fetched
 * once and kept — it carries the fits / explains-by-neighbours facts the
 * create form has to state. */
export const useStyleMethods = () =>
  useQuery({
    queryKey: ["style", "methods"],
    queryFn: () => get<StyleMethod[]>("/api/style/methods"),
    staleTime: Infinity,
  });

export const useStyleModels = () =>
  useQuery({
    queryKey: ["style", "models"],
    queryFn: () => get<StyleModel[]>("/api/style/models"),
  });

/** Create AND learn, in one explicit action (the engine does both).
 *
 * Invalidated on settle, not on success: a 409 `insufficient_history` still
 * leaves the model row behind (the engine keeps it, and its `detail.model_id`
 * says which), so the list has changed even though the call failed. */
export const useCreateStyleModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      method: string;
      library_ids: number[];
      params?: Record<string, number | null>;
    }) => post<StyleModel>("/api/style/models", { params: {}, ...body }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["style"] }),
  });
};

/** Relearn: same model, current history. The user decides when their style
 * has moved — the engine never retrains on import. */
export const useTrainStyleModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelId: number) =>
      post<StyleModel>(`/api/style/models/${modelId}/train`),
    // Relearning changes what a prediction would be, so previews go too.
    onSettled: () => qc.invalidateQueries({ queryKey: ["style"] }),
  });
};

/** Choose which model predicts by default. Engine state: activating here
 * changes what the native client predicts with too. */
export const useActivateStyleModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelId: number) =>
      post<StyleModel>(`/api/style/models/${modelId}/activate`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["style"] }),
  });
};

/** Deletes the model row only. No photo, sidecar or edit is touched — a
 * model is a predictor, not the user's work (README rule 2). Callers confirm
 * first and say so. */
export const useDeleteStyleModel = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (modelId: number) =>
      del<{ deleted: number }>(`/api/style/models/${modelId}`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["style"] }),
  });
};

/** The per-parameter opt-out (design 08 §6, §7a). Server state, not a
 * browser setting: it decides what gets written into the user's files, so
 * both clients must read the same answer. */
export const useStylePreferences = () =>
  useQuery({
    queryKey: ["style", "preferences"],
    queryFn: () => get<StylePreferences>("/api/style/preferences"),
  });

/** Sets the whole exclusion list (the endpoint is a PUT, not a patch — the
 * body is the new list). Excluding a parameter changes what the engine
 * predicts *and* returns, so the prediction preview is invalidated: leaving a
 * stale preview on screen would show values that are no longer what a write
 * would produce. A name outside `modelable_params` comes back as a 400
 * `unknown_param`; callers render it. */
export const useSetStylePreferences = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (excludedParams: string[]) =>
      put<{ excluded_params: string[] }>("/api/style/preferences", {
        excluded_params: excludedParams,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["style", "preferences"] });
      qc.invalidateQueries({ queryKey: ["style", "predict"] });
    },
  });
};

/** Prediction PREVIEW for a shoot. POST because the engine needs a body,
 * but it is read-only and writes nothing — modelled as a query so switching
 * family re-reads instead of accumulating mutation state.
 *
 * `family: null` lets the engine auto-suggest (design 08 §3); the resolved
 * family comes back in the response. `photo_ids` is omitted so the engine
 * uses the shoot's latest selection picks — the client does not decide the
 * scope of a cull.
 *
 * `modelId: null` omits `model_id` entirely so the engine uses the ACTIVE
 * model (design 08 §7b) — sending a guessed id would be the client choosing
 * the predictor. The model that actually ran comes back in `model`. */
export const useStylePrediction = (
  shootId: number | null,
  family: number | null,
  modelId: number | null,
) =>
  useQuery({
    queryKey: ["style", "predict", shootId, family, modelId],
    queryFn: () =>
      post<StylePredictResult>(`/api/shoots/${shootId}/style/predict`, {
        family,
        ...(modelId === null ? {} : { model_id: modelId }),
      }),
    enabled: shootId !== null,
    retry: false,
  });

/** Writes predicted `crs:` values to XMP sidecars via the §07 Rule-2
 * protocol. Abstentions write nothing; conflicting sidecars are skipped and
 * reported — the endpoint takes no override flag, by design.
 *
 * `model_id` must be the one the preview ran with, so what is written comes
 * from the model whose numbers the user just read; omitted means the active
 * model, exactly as in the preview. */
export const useStyleExportDevelop = (shootId: number | null) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      family: number;
      photo_ids: number[];
      model_id?: number;
    }) =>
      post<StyleExportResult>(
        `/api/shoots/${shootId}/style/export-develop`,
        body,
      ),
    // A write changes what a re-preview would find (sidecars now conflict).
    onSuccess: () => qc.invalidateQueries({ queryKey: ["style", "predict"] }),
  });
};

/** SSE job progress (design 09 §5, 11 §6). Invalidates queries when a job
 * finishes so the grid fills in as analysis completes. */
export const useJobStream = (onProgress?: (p: JobProgress) => void) => {
  const qc = useQueryClient();
  useEffect(() => {
    const es = new EventSource("/api/jobs/stream");
    es.onmessage = (ev) => {
      const p = JSON.parse(ev.data) as JobProgress;
      onProgress?.(p);
      if (p.state === "done" || p.state === "failed") {
        qc.invalidateQueries();
      }
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qc]);
};
