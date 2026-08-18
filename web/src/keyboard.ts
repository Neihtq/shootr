/** Keyboard-first culling (design 11 §5). Modeled on LrC's own bindings
 * (P/X, J/K) so it doesn't fight existing muscle memory. */

import { useEffect } from "react";

export interface KeyboardHandlers {
  onPrevFrame: () => void;
  onNextFrame: () => void;
  onPrevGroup: () => void;
  onNextGroup: () => void;
  onPick: () => void;
  onReject: () => void;
  onAlt: () => void;
  onToggleEvidence: () => void;
  onToggleSharpness: () => void;
  onToggleCompare?: () => void;
  onTogglePick?: () => void;
  onToggleComposition?: () => void;
  /** Disable while a modal (compare view) owns the keyboard. */
  enabled?: boolean;
}

export function useKeyboard(h: KeyboardHandlers) {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (h.enabled === false) return;
      if (ev.target instanceof HTMLInputElement) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      switch (ev.key) {
        case "j":
        case "ArrowLeft":
          h.onPrevFrame();
          break;
        case "k":
        case "ArrowRight":
          h.onNextFrame();
          break;
        case "g":
          h.onNextGroup();
          break;
        case "G": // shift+g
          h.onPrevGroup();
          break;
        case "p":
          h.onPick();
          break;
        case "x":
          h.onReject();
          break;
        case "a":
          h.onAlt();
          break;
        case "e":
          h.onToggleEvidence();
          break;
        case "s":
          h.onToggleSharpness();
          break;
        case "o":
          h.onToggleComposition?.();
          break;
        case "c":
          h.onToggleCompare?.();
          break;
        case " ":
          h.onTogglePick?.();
          break;
        case "ArrowUp":
          h.onPrevGroup();
          break;
        case "ArrowDown":
          h.onNextGroup();
          break;
        default:
          return;
      }
      ev.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [h]);
}
