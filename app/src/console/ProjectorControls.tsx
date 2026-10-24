import { useEffect, useState } from "react";
import { getPlatform, type MonitorInfo, type Platform } from "../platform";

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
        <div className="flex gap-1">
          <select
            value={monitorId}
            onChange={(e) => setMonitorId(e.target.value)}
            className="min-w-0 flex-1 rounded bg-neutral-900 px-2 py-1"
          >
            {monitors.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.width}×{m.height}){m.primary ? " · primary" : ""}
              </option>
            ))}
          </select>
          <button className="rounded bg-neutral-900 px-2 hover:bg-neutral-800" onClick={() => run(() => refresh(platform))}>
            ↻
          </button>
        </div>
      )}
      <div className="flex gap-1">
        <button
          className="flex-1 rounded bg-neutral-700 px-2 py-1 hover:bg-neutral-600"
          onClick={() => run(() => platform.openProjector(monitorId))}
        >
          Open projector
        </button>
        <button
          className="rounded bg-neutral-900 px-2 py-1 hover:bg-neutral-800"
          onClick={() => run(() => platform.closeProjector())}
        >
          Close
        </button>
      </div>
      {platform.kind === "browser" && (
        <p className="text-neutral-500">Browser mode: drag the popup to the projector and press F.</p>
      )}
      {error && <p className="text-red-400">{error}</p>}
    </div>
  );
}
