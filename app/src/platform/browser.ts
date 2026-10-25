// Plain-browser fallback. The projector is a popup the user drags to the
// projector screen and fullscreens with the F key.

import type { MonitorInfo, Platform } from "./types";

const PROJECTOR_NAME = "fireline-projector";
const CONTROL_NAME = "fireline-control";
let projector: Window | null = null;

export const browserPlatform: Platform = {
  kind: "browser",

  async listMonitors(): Promise<MonitorInfo[]> {
    return [
      {
        id: "browser",
        name: "Browser popup",
        width: window.screen.width,
        height: window.screen.height,
        primary: true,
      },
    ];
  },

  async openProjector() {
    projector = window.open("/?view=projector", PROJECTOR_NAME, "popup,width=900,height=900");
    projector?.focus();
  },

  async closeProjector() {
    projector?.close();
    projector = null;
  },

  async openControl() {
    window.open("/?view=control", CONTROL_NAME, "popup,width=1400,height=900")?.focus();
  },
};
