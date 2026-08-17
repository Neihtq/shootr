/** Thin fetch wrapper. Unwraps the engine's error envelope (design 10 §5)
 * so callers switch on the stable `code`. */

import type { ApiError } from "./types";

export class EngineError extends Error {
  // Explicit fields instead of constructor parameter properties:
  // `erasableSyntaxOnly` (Vite's ts default) forbids the shorthand.
  readonly api: ApiError;
  readonly status: number;

  constructor(api: ApiError, status: number) {
    super(api.message);
    this.api = api;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let api: ApiError = {
      code: "error",
      message: res.statusText,
      detail: {},
      retryable: false,
    };
    try {
      const body = await res.json();
      if (body.error) api = body.error;
    } catch {
      /* non-JSON error body */
    }
    throw new EngineError(api, res.status);
  }
  return res.json() as Promise<T>;
}

export const get = <T>(path: string) => request<T>(path);

export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const thumbUrl = (photoId: number, size: 256 | 1024 | 2048) =>
  `/api/photos/${photoId}/thumb?size=${size}`;

export const eyeCropUrl = (photoId: number, face: number, eye: "left" | "right") =>
  `/api/photos/${photoId}/eye-crop?face=${face}&eye=${eye}`;
