/** TanStack Query hooks. Server state is the source of truth (design 11
 * §8): no client-side store of scores — caching stale domain values is how
 * the client drifts from the engine. */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { get, patch, post } from "./client";
import type {
  ExportPreview,
  Group,
  JobProgress,
  Library,
  PhotoDetail,
  Selection,
  SelectionState,
  SharpnessMap,
  Shoot,
  ShootProposal,
} from "./types";

export const useLibraries = () =>
  useQuery({ queryKey: ["libraries"], queryFn: () => get<Library[]>("/api/libraries") });

export const useShoots = () =>
  useQuery({ queryKey: ["shoots"], queryFn: () => get<Shoot[]>("/api/shoots") });

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
