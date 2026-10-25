// Light or dark UI (#143). Follows the system until the operator picks one,
// then remembers it per browser. Every window shares the choice: a change in
// one reaches the others through the storage event. The projector is never
// themed; it draws for the table, not for a screen.

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "firewatch.theme";
const system = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();

function saved(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

let theme: Theme = saved() ?? (system.matches ? "dark" : "light");

function apply(next: Theme) {
  theme = next;
  document.documentElement.dataset.theme = next;
  listeners.forEach((l) => l());
}

/** Start theming this window. Call once, before the first render. */
export function initTheme() {
  apply(theme);
  system.addEventListener("change", (e) => saved() ?? apply(e.matches ? "dark" : "light"));
  window.addEventListener("storage", (e) => {
    if (e.key === STORAGE_KEY) apply(saved() ?? (system.matches ? "dark" : "light"));
  });
}

export function setTheme(next: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Private windows can refuse storage; the theme still changes this session.
  }
  apply(next);
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => theme,
  );
}
