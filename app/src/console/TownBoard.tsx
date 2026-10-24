// Every town at a glance (#122): how soon fire could get there, how likely it
// is within the hour, and whether its way out is open. Sorted so the towns in
// the most danger are on top. Numbers come from the engine's situation
// message, one Monte Carlo forecast at a time.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import type { TownThreat } from "../shared/protocol";
import { aboutMinutes } from "../shared/places";
import type { Scenario } from "../shared/scenario";
import { ROUTE_COLORS } from "../render/routes";

const ROUTE_TEXT = { clear: "Clear", risky: "At risk", cut: "Cut off" } as const;
const HIGHLIGHT_MS = 8000;

function urgency(t: TownThreat): number {
  if (t.fire_inside) return -1;
  return t.soonest_min ?? t.median_min ?? 1e6 - (t.within_60?.k ?? 0);
}

export default function TownBoard({ scenario, onFocus }: { scenario: Scenario; onFocus: (x: number, y: number) => void }) {
  const { situation } = useEngine();
  const towns = [...(situation?.towns ?? [])].sort((a, b) => urgency(a) - urgency(b));
  const rerouted = useRerouted(situation?.towns);
  const where = new Map(scenario.towns.map((t) => [t.name, t]));
  if (towns.length === 0) return <p className="py-2 text-[11px] text-fg-subtle">This scenario has no towns.</p>;

  return (
    <table className="w-full table-fixed text-[11px]">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-wide text-fg-subtle">
          <th className="w-[34%] pb-1 font-medium">Town</th>
          <th className="w-[22%] pb-1 font-medium">Fire in</th>
          <th className="w-[20%] pb-1 font-medium" title="Share of simulations with fire in town within 60 minutes">
            1 h
          </th>
          <th className="pb-1 font-medium">Way out</th>
        </tr>
      </thead>
      <tbody>
        {towns.map((t) => {
          const at = where.get(t.town);
          return (
            <tr
              key={t.town}
              onClick={() => at && onFocus(at.x, at.y)}
              className={`cursor-pointer border-t border-edge/60 align-top hover:bg-surface-2 ${rerouted.has(t.town) ? "bg-amber-400/10" : ""}`}
            >
              <td className="py-1.5 pr-1">
                <div className="truncate text-fg">{t.town}</div>
                <div className="font-mono text-[10px] tabular-nums text-fg-subtle">{t.population.toLocaleString()} ppl</div>
              </td>
              <td className="py-1.5 pr-1 font-mono tabular-nums">
                <FireIn t={t} />
              </td>
              <td className="py-1.5 pr-2">
                <Chance t={t} />
              </td>
              <td className="py-1.5">
                {t.route_status ? (
                  <>
                    <div className="flex items-center gap-1.5" style={{ color: ROUTE_COLORS[t.route_status] }}>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: ROUTE_COLORS[t.route_status] }} />
                      {ROUTE_TEXT[t.route_status]}
                      {rerouted.has(t.town) && <span className="text-amber-300">· new</span>}
                    </div>
                    {t.exit && (
                      <div className="truncate text-[10px] text-fg-subtle" title={t.exit}>
                        {t.exit}
                        {t.drive_min != null && ` · ${aboutMinutes(t.drive_min)}`}
                      </div>
                    )}
                  </>
                ) : (
                  <span className="text-fg-subtle">—</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function FireIn({ t }: { t: TownThreat }) {
  if (t.fire_inside) return <span className="font-sans font-semibold text-red-400">In town</span>;
  if (t.soonest_min == null) return <span className="text-fg-subtle">&gt; 1 h</span>;
  const color = t.soonest_min <= 30 ? "text-red-300" : t.soonest_min <= 60 ? "text-amber-300" : "text-fg";
  return (
    <span className={color} title="Soonest (10th percentile) and likely (median) time until fire reaches the town">
      {Math.round(t.soonest_min)}
      {t.median_min != null && <span className="text-fg-muted">–{Math.round(t.median_min)}</span>}
      <span className="text-fg-subtle"> m</span>
    </span>
  );
}

function Chance({ t }: { t: TownThreat }) {
  const w = t.within_60;
  if (!w) return <span className="text-fg-subtle">—</span>;
  const p = w.k / Math.max(1, w.n);
  const color = p >= 0.5 ? "#ef4444" : p >= 0.2 ? "#fb923c" : "#646b75";
  return (
    <div title={`${w.k} of ${w.n} simulations (likely ${Math.round(w.lo * 100)}–${Math.round(w.hi * 100)}%)`}>
      <div className="font-mono tabular-nums text-fg-muted">
        {w.k}/{w.n}
      </div>
      <div className="relative mt-0.5 h-1 overflow-hidden rounded-full bg-surface-3">
        {/* The interval, faint, under the point estimate. */}
        <div className="absolute inset-y-0 opacity-35" style={{ left: `${w.lo * 100}%`, width: `${(w.hi - w.lo) * 100}%`, background: color }} />
        <div className="absolute inset-y-0 left-0" style={{ width: `${p * 100}%`, background: color }} />
      </div>
    </div>
  );
}

/** Towns whose way out changed in the last few seconds. */
function useRerouted(towns: TownThreat[] | undefined): Set<string> {
  const previous = useRef(new Map<string, string | null>());
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  useEffect(() => {
    const now: string[] = [];
    for (const t of towns ?? []) {
      const before = previous.current.get(t.town);
      if (before !== undefined && before !== t.exit && t.exit !== null) now.push(t.town);
      previous.current.set(t.town, t.exit);
    }
    if (now.length === 0) return;
    setChanged((s) => new Set([...s, ...now]));
    timers.current.push(
      window.setTimeout(() => setChanged((s) => new Set([...s].filter((x) => !now.includes(x)))), HIGHLIGHT_MS),
    );
  }, [towns]);
  return changed;
}
