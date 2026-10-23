// All Tauri API calls live behind this module so the app also runs unchanged
// in a plain browser (see PLAN.md, "Fallback rule").

import { browserPlatform } from "./browser";
import type { Platform } from "./types";

export type { MonitorInfo, Platform } from "./types";

export const isTauri = "__TAURI_INTERNALS__" in window;

// The Tauri implementation is loaded lazily so the browser build never
// touches @tauri-apps/api.
let platformPromise: Promise<Platform> | null = null;

export function getPlatform(): Promise<Platform> {
  platformPromise ??= isTauri
    ? import("./tauri").then((m) => m.tauriPlatform)
    : Promise.resolve(browserPlatform);
  return platformPromise;
}
