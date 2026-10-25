// Tauri implementation. The only file allowed to import @tauri-apps/*.

import { LogicalPosition } from "@tauri-apps/api/dpi";
import { availableMonitors, primaryMonitor, type Monitor } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import type { MonitorInfo, Platform } from "./types";

const PROJECTOR_LABEL = "projector";
const CONTROL_LABEL = "control";

// Monitors have no stable id in Tauri, so key them by name plus position.
function monitorId(m: Monitor) {
  return `${m.name ?? "monitor"}@${m.position.x},${m.position.y}`;
}

async function closeProjector() {
  const existing = await WebviewWindow.getByLabel(PROJECTOR_LABEL);
  if (!existing) return;
  const closed = new Promise<void>((resolve) => existing.once("tauri://destroyed", () => resolve()));
  await existing.destroy();
  await closed;
}

export const tauriPlatform: Platform = {
  kind: "tauri",

  async listMonitors(): Promise<MonitorInfo[]> {
    const [monitors, primary] = await Promise.all([availableMonitors(), primaryMonitor()]);
    const primaryId = primary ? monitorId(primary) : null;
    return monitors.map((m) => ({
      id: monitorId(m),
      name: m.name ?? "Unknown monitor",
      width: m.size.width,
      height: m.size.height,
      primary: monitorId(m) === primaryId,
    }));
  },

  async openProjector(id) {
    const monitor = (await availableMonitors()).find((m) => monitorId(m) === id);
    if (!monitor) throw new Error(`Monitor ${id} not found`);
    await closeProjector();

    // Window options are in logical pixels; monitor geometry is physical.
    const scale = monitor.scaleFactor;
    const win = new WebviewWindow(PROJECTOR_LABEL, {
      url: "/?view=projector",
      title: "Fireline Projector",
      x: monitor.position.x / scale,
      y: monitor.position.y / scale,
      width: monitor.size.width / scale,
      height: monitor.size.height / scale,
      decorations: false,
      focus: false,
    });
    await new Promise<void>((resolve, reject) => {
      win.once("tauri://created", () => resolve());
      win.once("tauri://error", (e) => reject(new Error(String(e.payload))));
    });
    await win.setFullscreen(true);
  },

  closeProjector,

  async openControl() {
    const existing = await WebviewWindow.getByLabel(CONTROL_LABEL);
    if (existing) {
      await existing.setFocus();
      return;
    }
    const win = new WebviewWindow(CONTROL_LABEL, {
      url: "/?view=control",
      title: "Fireline Exercise Control",
      width: 1400,
      height: 900,
      // The traffic lights sit in the header row, as in the console.
      titleBarStyle: "overlay",
      hiddenTitle: true,
      trafficLightPosition: new LogicalPosition(16, 18),
    });
    await new Promise<void>((resolve, reject) => {
      win.once("tauri://created", () => resolve());
      win.once("tauri://error", (e) => reject(new Error(String(e.payload))));
    });
  },
};
