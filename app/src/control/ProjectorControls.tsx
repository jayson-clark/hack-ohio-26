import { useEffect, useState } from "react";
import { getPlatform, type MonitorInfo, type Platform } from "../platform";
import { RefreshIcon } from "../console/icons";
import { Button } from "../console/ui";

export default function ProjectorControls() {
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [monitors, setMonitors] = useState<MonitorInfo[]>([]);
  const [monitorId, setMonitorId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function refresh(p: Platform) {
    const list = await p.listMonitors();
    setMonitors(list);
    // Default to a non-primary monitor: that's almost always the projector.
    setMonitorId((current) =>
      list.some((m) => m.id === current) ? current : (list.find((m) => !m.primary) ?? list[0])?.id ?? "",
    );
  }

  useEffect(() => {
    getPlatform().then((p) => {
      setPlatform(p);
      refresh(p);
    });
  }, []);

  if (!platform) return null;

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="space-y-2 text-xs">
      {platform.kind === "tauri" && (
        <div className="flex gap-1.5">
          <select
            value={monitorId}
            onChange={(e) => setMonitorId(e.target.value)}
            className="h-8 min-w-0 flex-1 rounded-lg border border-edge bg-surface-2 px-2 text-xs text-fg outline-none focus:border-edge-strong"
          >
            {monitors.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.width}×{m.height}){m.primary ? " · primary" : ""}
              </option>
            ))}
          </select>
          <Button variant="secondary" title="Refresh monitors" onClick={() => run(() => refresh(platform))}>
            <RefreshIcon />
          </Button>
        </div>
      )}
      <div className="flex gap-1.5">
        <Button variant="primary" className="flex-1" onClick={() => run(() => platform.openProjector(monitorId))}>
          Open projector
        </Button>
        <Button variant="secondary" onClick={() => run(() => platform.closeProjector())}>
          Close
        </Button>
      </div>
      {platform.kind === "browser" && (
        <p className="text-[11px] leading-relaxed text-fg-subtle">
          Browser mode: drag the popup to the projector screen and press F for fullscreen.
        </p>
      )}
      {error && <p className="text-red-400">{error}</p>}
    </div>
  );
}
