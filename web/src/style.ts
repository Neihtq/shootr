/** Display helpers for the style-learning screens (design 08 §7a).
 *
 * Presentation only. Nothing here computes a prediction, a confidence, or an
 * abstention — those arrive from the engine and are rendered as given
 * (design 08 §7a, design 10 §1). The one number formatted here is a `crs:`
 * value's sign and decimals, which is typography, not arithmetic.
 */

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

/** Parameters we have a MEASURED reason to recommend excluding, with that
 * reason in the user's own terms. Surfaced as a suggestion, never applied for
 * them: the exclusion list lives on the server and changes what is written to
 * their files, so the client proposing it silently would be the client making
 * the decision (design 08 §7a, design 10 §1).
 *
 * k-NN beats the family median on 11 of 12 parameters and loses on this one
 * (`docs/benchmarks/2026-08-30-style-knn-eval.md`: MAE 0.336 vs 0.283 under
 * leave-one-shot-group-out).
 */
export const SUGGESTED_EXCLUSIONS: Record<string, string> = {
  ColorGradeMidtoneHue:
    "Measured on your own edits: the family's median hue beats the per-photo prediction here (MAE 0.283 vs 0.336) — the only parameter of 12 where it does. Excluding it means Shootr leaves midtone hue to you.",
};

/** Engine error codes from the preferences endpoint → human copy. */
const PREF_ERROR_COPY: Record<string, string> = {
  unknown_param:
    "The engine does not model that parameter, so it cannot be excluded. Nothing was changed — reload the screen to pick up the engine's current parameter list.",
};

export const prefErrorCopy = (
  code: string | null,
  message: string,
): string =>
  PREF_ERROR_COPY[code ?? ""] ??
  `The engine rejected the change (${code ?? "error"}): ${message}. Nothing was changed.`;
