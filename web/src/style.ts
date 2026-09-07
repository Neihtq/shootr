/** Display helpers for the style-learning screens (design 08 §7a).
 *
 * Presentation only. Nothing here computes a prediction, a confidence, or an
 * abstention — those arrive from the engine and are rendered as given
 * (design 08 §7a, design 10 §1). The one number formatted here is a `crs:`
 * value's sign and decimals, which is typography, not arithmetic.
 */

import { useCallback, useState } from "react";

/** `crs:` slider names → the label Lightroom shows the user. Unknown keys
 * fall through as themselves: the engine's parameter list can grow without
 * this file silently hiding a parameter that is about to be written. */
const PARAM_LABELS: Record<string, string> = {
  Exposure2012: "Exposure",
  Contrast2012: "Contrast",
  Highlights2012: "Highlights",
  Shadows2012: "Shadows",
  Whites2012: "Whites",
  Blacks2012: "Blacks",
  Texture: "Texture",
  Clarity2012: "Clarity",
  Dehaze: "Dehaze",
  Vibrance: "Vibrance",
  Saturation: "Saturation",
  ColorGradeMidtoneHue: "Color grade · midtone hue",
  ColorGradeMidtoneSat: "Color grade · midtone saturation",
};

export const paramLabel = (name: string) => PARAM_LABELS[name] ?? name;

/** Exposure is in EV and moves in tenths; the rest are Lightroom's ±100
 * slider units. Signed, because the direction is the interesting part. */
export function formatParam(name: string, value: number): string {
  const digits = name === "Exposure2012" ? 2 : 1;
  const s = value.toFixed(digits);
  return value > 0 ? `+${s}` : s;
}

export const paramUnit = (name: string) =>
  name === "Exposure2012" ? " EV" : "";

/** Engine abstention reason → human copy. A photo below the confidence gate
 * must read as "no confident prediction", never as an empty parameter list
 * that could pass for "no changes needed" (design 08 §7a). Unknown reasons
 * are surfaced verbatim rather than swallowed. */
const ABSTAIN_COPY: Record<string, string> = {
  low_confidence:
    "The nearest edits in your history disagree too much, or aren't similar enough — below the engine's confidence gate.",
  no_similar_history:
    "Nothing in this look family looks like this photo, so there is nothing honest to copy from.",
  family_too_small:
    "This look family has too few edited photos to predict from.",
  not_analyzed:
    "This photo has no scene embedding yet — analyze the shoot before predicting.",
};

export const abstainCopy = (reason: string | null | undefined): string =>
  ABSTAIN_COPY[reason ?? ""] ??
  `The engine abstained (reason: ${reason ?? "unspecified"}).`;

/** Parameters hidden from this preview by default.
 *
 * Measured, not guessed: k-NN beats the family median on 11 of 12 parameters
 * but loses on ColorGradeMidtoneHue
 * (`docs/benchmarks/2026-08-30-style-knn-eval.md`), so it ships hidden.
 */
export const DEFAULT_HIDDEN_PARAMS = ["ColorGradeMidtoneHue"];

/** localStorage, deliberately: the engine has no user-preference store, so
 * there is nowhere on the server to persist this. Consequence, stated in the
 * UI rather than hidden: this is a per-browser DISPLAY filter and the write
 * endpoint has no per-parameter switch, so hiding a parameter here does not
 * stop it being written (design 08 §6 — engine-side opt-out is still to do).
 */
const STORAGE_KEY = "shootr.style.hiddenParams";

function loadHidden(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return DEFAULT_HIDDEN_PARAMS;
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : [];
  } catch {
    // Private mode / quota / corrupt value: fall back to the measured default.
    return DEFAULT_HIDDEN_PARAMS;
  }
}

export function useHiddenParams() {
  const [hidden, setHidden] = useState<string[]>(loadHidden);

  const toggle = useCallback((name: string) => {
    setHidden((prev) => {
      const next = prev.includes(name)
        ? prev.filter((n) => n !== name)
        : [...prev, name];
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Non-persistent this session; the toggle still works in-memory.
      }
      return next;
    });
  }, []);

  return { hidden, toggle };
}
