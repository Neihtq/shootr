/** Display helpers for the style-learning screens (design 08 §7a).
 *
 * Presentation only. Nothing here computes a prediction, a confidence, or an
 * abstention — those arrive from the engine and are rendered as given
 * (design 08 §7a, design 10 §1). The one number formatted here is a `crs:`
 * value's sign and decimals, which is typography, not arithmetic.
 */

import type { Library } from "./api/types";

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

/** A measured ERROR (mean absolute error), so unsigned: it is a distance, and
 * a "+" in front of it would suggest a direction it does not have. Formatting
 * only — the number itself is the engine's. */
export function formatError(name: string, value: number): string {
  return value.toFixed(name === "Exposure2012" ? 3 : 2);
}

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
  model_abstained:
    "The model returned no value for this photo. Nothing will be written for it.",
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

/** -- style models (design 08 §7b) ------------------------------------------
 *
 * Copy only. The method registry, the metrics and the active model all come
 * from the engine; nothing here ranks a method, scores a model or picks a
 * winner (design 10 §1, README rule 6).
 */

/** Method id → the name to show. Unknown methods fall through as themselves,
 * so a method the engine gains (design 08 §7b lists `gbt` as a candidate)
 * appears rather than vanishing from the picker. */
const METHOD_TITLES: Record<string, string> = {
  knn: "k-NN — nearest edits in your history",
  ridge: "Ridge regression — fitted to your history",
  gbt: "Gradient-boosted trees — fitted to your history",
};

export const methodTitle = (method: string) =>
  METHOD_TITLES[method] ?? method;

/** A model's scope in the user's terms: the library root paths its history
 * came from. An empty list means every library, which is a deliberate answer
 * and is worded as one rather than as "none". A library that has since been
 * removed from Shootr is named as missing instead of being dropped — the
 * model was learned from it either way. */
export const scopeLabel = (
  libraryIds: number[],
  libraries: Library[] | undefined,
): string => {
  if (libraryIds.length === 0) return "all libraries";
  return libraryIds
    .map(
      (id) =>
        libraries?.find((l) => l.id === id)?.root_path ??
        `library ${id} (no longer in Shootr)`,
    )
    .join(", ");
};

/** Method knob → display. `null` is the engine choosing the value while it
 * learns (ridge's λ by cross-validation), which is not the same as "unset". */
export const formatModelParams = (
  params: Record<string, number | null>,
): string =>
  Object.entries(params)
    .map(([k, v]) => `${k} ${v === null ? "chosen while learning" : v}`)
    .join(" · ");

/** The trade-off between methods, stated rather than hidden: it is the reason
 * there is a choice here at all. Kept as one string so the web and native
 * clients say the same thing. */
export const METHOD_TRADEOFF =
  "The trade-off, plainly: a method that retrieves can show you the photos a prediction came from; a method that fits cannot — it can only say how much history it was fitted from. Which one is more accurate on your own edits is measured, not assumed — learn both and compare them.";

/** `fits` → what that means for the user, in facts about behaviour. */
export const methodFitsCopy = (fits: boolean): string =>
  fits
    ? "Fits coefficients to your history when you learn the model. Newly imported edits do not change its predictions until you relearn it."
    : "Fits nothing in advance: each prediction is blended from the nearest edits in your history at the moment it is made, so newly imported edits count without a relearn. The recorded metrics still date from the last learn.";

/** `explains_by_neighbours` → what a prediction from it can tell you.
 * §7a's inspectability requirement is not waived by accuracy, so a fitted
 * method's limit is named up front, before the model is created. */
export const methodExplainsCopy = (explains: boolean): string =>
  explains
    ? "Every prediction names the photos it was copied from — “edited like these five”, with thumbnails."
    : "Predictions cannot name the photos behind a value. Each one reports only that it was fitted, and from how many edited photos.";

/** How the engine produced the comparison numbers. Not a footnote: it changes
 * what they mean (design 08 §7b). */
export const heldOutCopy = (heldOutBy: string | undefined): string => {
  if (heldOutBy === "shot_group") {
    return "Measured on your own edits, held out by shot group: whole bursts were kept out of the history the model learned from, so a near-duplicate sibling could not hand it the answer.";
  }
  if (heldOutBy === "photo") {
    return "Measured on your own edits, held out photo by photo: burst siblings can land on both sides of the split, and a near-duplicate sibling in the history flatters retrieval — read these numbers as optimistic.";
  }
  return `Measured on your own edits, held out by ${heldOutBy ?? "an unreported split"}.`;
};

/** Engine error codes from the model endpoints → human copy. `relearn` and
 * `create` differ in one fact worth stating: a failed create still leaves the
 * model row behind, so the user's choice is not silently discarded. */
export const modelErrorCopy = (
  code: string | null,
  message: string,
  op: "create" | "relearn" | "activate" | "delete",
): string => {
  if (code === "unknown_method") {
    return `The engine does not offer that method (${message}). Nothing was created — reload to pick up the engine's current method list.`;
  }
  if (code === "insufficient_history") {
    const tail =
      op === "create"
        ? "The model was created anyway and is listed as not learned, so your choice is not lost: import or analyze those edits, then Relearn it."
        : "The model is unchanged and keeps whatever it last learned, if anything. Import or analyze those edits, then Relearn.";
    return `Not enough learnable history in the chosen libraries. The engine needs edited photos that are both imported (a Lightroom Classic catalog, or XMP sidecars carrying develop settings) and analyzed — similarity comes from the scene embedding, so an unanalyzed edit is invisible to it. ${tail} Engine: ${message}`;
  }
  return `The engine rejected this (${code ?? "error"}): ${message}.`;
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
