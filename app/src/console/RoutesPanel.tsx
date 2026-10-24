// Every town's evacuation route as a list (#26): where it leads, how long the
// drive is, and how risky. A town whose exit just changed is highlighted for
// a few seconds, so a reroute is hard to miss even though #59 keeps routes
// steady between forecasts.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import type { RouteInfo } from "../shared/protocol";
import { ROUTE_COLORS } from "../render/routes";
import { Panel } from "./ui";

const HIGHLIGHT_MS = 8000;
const STATUS_TEXT = { clear: "Clear", risky: "At risk", cut: "Cut off" } as const;

export default function RoutesPanel({ onFocus }: { onFocus: (x: number, y: number) => void }) {
  const { routes } = useEngine();
  const towns = routes.filter((r) => !r.bus);
  const changed = useRerouted(towns);
  if (towns.length === 0) return null;

  const cut = towns.filter((r) => r.status === "cut").length;
  return (
    <Panel
      title="Evacuation routes"
      right={
        cut > 0 ? (
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-300">{cut} cut off</span>
        ) : undefined
      }
    >
      <ul className="-mx-1.5 space-y-0.5">
        {towns.map((r) => (
          <li key={r.town}>
            <button
              onClick={() => r.points.length && onFocus(r.points[0][0], r.points[0][1])}
              title="Fly to"
              className={`flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left transition-colors ${
                changed.has(r.town) ? "bg-amber-400/15" : "hover:bg-surface-2"
              }`}
            >
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: ROUTE_COLORS[r.status] }} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-fg">{r.town}</span>
                <span className="block truncate text-[10px] text-fg-subtle">
                  {r.safe_zone ? `→ ${r.safe_zone}` : "No safe way out"}
                  {changed.has(r.town) && <span className="text-amber-300"> · rerouted</span>}
                </span>
              </span>
              <span className="shrink-0 text-right font-mono text-[10px] tabular-nums">
                <span className="block text-fg-muted">{r.safe_zone ? `${Math.round(r.eta_min)} min` : "—"}</span>
                <span className="block" style={{ color: ROUTE_COLORS[r.status] }}>
                  {/* Risk only says something for a route that's still open. */}
                  {r.status === "risky" ? `${STATUS_TEXT.risky} ${Math.round(r.risk * 100)}%` : STATUS_TEXT[r.status]}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Towns whose exit changed in the last few seconds. */
function useRerouted(routes: RouteInfo[]): Set<string> {
  const previous = useRef(new Map<string, string | null>());
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  useEffect(() => {
    const now: string[] = [];
    for (const r of routes) {
      const before = previous.current.get(r.town);
      // Only a change of exit counts, not the first plan or a reset back to none.
      if (before !== undefined && before !== r.safe_zone && r.safe_zone !== null) now.push(r.town);
      previous.current.set(r.town, r.safe_zone);
    }
    if (now.length === 0) return;
    setChanged((s) => new Set([...s, ...now]));
    timers.current.push(
      window.setTimeout(() => setChanged((s) => new Set([...s].filter((t) => !now.includes(t)))), HIGHLIGHT_MS),
    );
  }, [routes]);
  return changed;
}
