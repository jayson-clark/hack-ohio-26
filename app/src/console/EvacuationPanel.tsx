// The evacuation order clock (#121): for every town, how long until its
// evacuation order has to go out, from a long fire forecast against the time
// to empty the town through exit roads it shares with other ordered towns.
// Most urgent first; the countdowns tick with the sim.

import { orderEvacuation, useEngine } from "../shared/engine";
import type { EvacStatus, TownEvac } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { PinIcon } from "./icons";
import { Button, Panel } from "./ui";

const STATUS: Record<EvacStatus, { label: string; chip: string; dot: string }> = {
  late: { label: "Late", chip: "bg-red-500/20 text-red-300", dot: "#f87171" },
  trapped: { label: "Trapped", chip: "bg-red-500/20 text-red-300", dot: "#f87171" },
  order_now: { label: "Order now", chip: "bg-ember-500/20 text-ember-300", dot: "#f97316" },
  order_soon: { label: "Order soon", chip: "bg-amber-500/15 text-amber-300", dot: "#fbbf24" },
  evacuating: { label: "Evacuating", chip: "bg-sky-500/15 text-sky-300", dot: "#38bdf8" },
  watch: { label: "Watch", chip: "bg-surface-3 text-fg-muted", dot: "#64748b" },
  clear: { label: "All out", chip: "bg-emerald-500/15 text-emerald-300", dot: "#34d399" },
};
const URGENT: EvacStatus[] = ["late", "order_now", "order_soon"];

export default function EvacuationPanel({ onFocus }: { onFocus: (x: number, y: number) => void }) {
  const { evacClock, hello, simGrid, scenario, routes } = useEngine();
  if (!evacClock || evacClock.towns.length === 0) return null;
  const now = simGrid?.tick ?? scenario?.tick ?? evacClock.tick;
  const mpt = hello?.sim_minutes_per_tick ?? 1;
  const due = evacClock.towns.filter((t) => URGENT.includes(t.status) && t.ordered_tick === null).length;
  const where = new Map(routes.filter((r) => !r.bus && r.points.length).map((r) => [r.town, r.points[0]]));

  return (
    <Panel
      title="Evacuation orders"
      right={
        due > 0 ? (
          <span className="rounded bg-ember-500/20 px-1.5 py-0.5 text-[10px] font-medium text-ember-300">{due} due</span>
        ) : undefined
      }
    >
      <ul className="space-y-2">
        {evacClock.towns.map((t) => (
          <Row key={t.town} t={t} now={now} mpt={mpt} at={where.get(t.town)} onFocus={onFocus} />
        ))}
      </ul>
      <p className="mt-2.5 text-[10px] leading-relaxed text-fg-subtle">
        {evacClock.forecast_tick === null
          ? "Once a fire is burning, each town's latest safe order time shows here."
          : `Fire arrival from a ${Math.round(evacClock.horizon_min / 60)}-hour forecast that assumes the wind holds, against the time to empty each town through exit roads shared with other ordered towns.`}
      </p>
    </Panel>
  );
}

function Row({
  t,
  now,
  mpt,
  at,
  onFocus,
}: {
  t: TownEvac;
  now: number;
  mpt: number;
  at: number[] | undefined;
  onFocus: (x: number, y: number) => void;
}) {
  const s = STATUS[t.status];
  const ordered = t.ordered_tick !== null;
  const urgent = URGENT.includes(t.status);
  const need = t.clearance_min === null ? null : t.mobilize_min + t.clearance_min;
  return (
    <li className={`rounded-lg border bg-surface-2 p-2.5 ${urgent && !ordered ? "border-ember-500/40" : "border-edge"}`}>
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.dot }} />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-fg">{t.town}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${s.chip}`}>{s.label}</span>
      </div>
      <p className="mt-1 pl-4 text-[11px] text-fg">{headline(t, now, mpt)}</p>
      <div className="mt-1 space-y-0.5 pl-4 text-[10px] leading-relaxed text-fg-subtle">
        {need !== null && t.people > 0 && (
          <p>
            {t.people.toLocaleString()} people · {formatSimMinutes(need)} to get out
            {t.exits.length > 0 && ` via ${t.exits.map((x) => x.safe_zone).join(" and ")}`}
          </p>
        )}
        {t.shares_with.length > 0 && <p className="text-amber-300/90">Queues with {t.shares_with.join(", ")}</p>}
        {t.n > 0 && t.people > 0 && t.status !== "trapped" && <SafeBar t={t} />}
      </div>
      {t.status !== "clear" && (
        <div className="mt-2 flex gap-1.5 pl-4">
          {ordered ? (
            <Button className="h-7 flex-1" onClick={() => orderEvacuation(t.town, false)}>
              Cancel order
            </Button>
          ) : (
            <Button
              variant={urgent ? "primary" : "secondary"}
              className="h-7 flex-1"
              onClick={() => orderEvacuation(t.town, true)}
            >
              Order {t.town} out
            </Button>
          )}
          {at && (
            <Button variant="ghost" className="h-7" title="Fly to" onClick={() => onFocus(at[0], at[1])}>
              <PinIcon />
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

/** The one line that says what to do and by when. */
function headline(t: TownEvac, now: number, mpt: number): string {
  switch (t.status) {
    case "clear":
      return "Everyone is out.";
    case "trapped":
      return "No open way out. Shelter in place or at a refuge.";
    case "evacuating": {
      const out = t.last_car_out_tick === null ? null : (t.last_car_out_tick - now) * mpt;
      return `${t.people.toLocaleString()} still in town${out !== null ? ` · last car out in ${formatSimMinutes(out)}` : ""}`;
    }
  }
  if (t.order_by_tick === null) return "Waiting for the long forecast.";
  const left = (t.order_by_tick - now) * mpt;
  if (t.order_by_bound) return `Order within ${formatSimMinutes(Math.max(0, left))} or more (fire not yet in the forecast)`;
  if (left > 0) return `Order within ${formatSimMinutes(left)}`;
  return `${formatSimMinutes(-left)} past the latest safe order time`;
}

/** In how many simulations the last car gets out before the fire, with its 90% range. */
function SafeBar({ t }: { t: TownEvac }) {
  const pct = Math.round(t.p_safe * 100);
  const color = t.p_safe >= 0.9 ? "#34d399" : t.p_safe >= 0.5 ? "#fbbf24" : "#f87171";
  return (
    <div
      className="pt-0.5"
      title={`${t.ordered_tick === null ? "If ordered now, the" : "The"} last car gets out before the fire in ${
        t.p_safe_bound ? "at most " : ""
      }${Math.round(t.p_safe * t.n)} of ${t.n} simulations (likely ${Math.round(t.p_safe_lo * 100)}–${Math.round(
        t.p_safe_hi * 100,
      )}%)`}
    >
      <div className="flex justify-between">
        <span>{t.ordered_tick === null ? "If ordered now, last car out first" : "Last car out before the fire"}</span>
        <span className="font-mono tabular-nums" style={{ color }}>
          {t.p_safe_bound ? "≤" : ""}
          {pct}%
        </span>
      </div>
      <div className="relative mt-0.5 h-1 overflow-hidden rounded-full bg-surface-3">
        <div
          className="absolute inset-y-0 rounded-full opacity-35"
          style={{ left: `${t.p_safe_lo * 100}%`, width: `${(t.p_safe_hi - t.p_safe_lo) * 100}%`, background: color }}
        />
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}
