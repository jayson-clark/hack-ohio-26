export interface MonitorInfo {
  id: string;
  name: string;
  width: number; // physical pixels
  height: number;
  primary: boolean;
}

export interface Platform {
  kind: "tauri" | "browser";
  listMonitors(): Promise<MonitorInfo[]>;
  /** Open (or move) the projector window, fullscreen on the given monitor. */
  openProjector(monitorId: string): Promise<void>;
  closeProjector(): Promise<void>;
}
