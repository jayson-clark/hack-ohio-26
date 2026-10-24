// Station roster (#109): every station's units and what each is doing, so
// it's clear what's still free and how long help takes to arrive. Dispatch is
// off for a scenario without stations.json, and the panel hides itself.

import { useEngine } from "../shared/engine";
import { orderText, UNIT_STATUS } from "../shared/dispatch";
import type { UnitInfo } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { TOKEN_STYLE } from "../shared/tokens";
import { Panel } from "./ui";

export default function StationsPanel({ onFocus, bare = false }: { onFocus: (x: number, y: number) => void; bare?: boolean }) {
  const { hello, units } = useEngine();
  const stations = hello?.stations ?? [];
  if (stations.length === 0) return null;

  const free = units.filter((u) => u.status === "available").length;
  const list = (
      <ul className="-mx-1.5 space-y-1">
        {stations.map((st) => {
          const own = units.filter((u) => u.station === st.name);
          return (
            <li key={st.name}>
              <button
                onClick={() => onFocus(st.x, st.y)}
                title={st.kind === "air" ? "Air base (may be off the map)" : "Fly to"}
                className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-surface-2"
              >
                <span className="w-4 shrink-0 text-center text-[11px] text-fg-subtle">{st.kind === "air" ? "✈" : "⌂"}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-fg">{st.name}</span>
              </button>
              <ul className="ml-7 space-y-0.5">
                {own.map((u) => (
                  <UnitRow key={u.id} unit={u} />
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
  );
  if (bare) return list;
  return (
    <Panel
      title="Stations"
      right={
        <span className="font-mono text-[11px] tabular-nums text-fg-subtle">
          {free}/{units.length} free
        </span>
      }
    >
      {list}
    </Panel>
  );
}

function UnitRow({ unit }: { unit: UnitInfo }) {
  const style = UNIT_STATUS[unit.status];
  return (
    <li className="flex items-center gap-2 text-[11px]">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TOKEN_STYLE[unit.token_type].color }} />
      <span className="flex-1 truncate text-fg-muted">{TOKEN_STYLE[unit.token_type].label}</span>
      <span className="font-mono tabular-nums" style={{ color: style.color }}>
        {style.label}
        {unit.status === "en_route" && unit.eta_min != null && ` · ${formatSimMinutes(unit.eta_min)}`}
      </span>
    </li>
  );
}

/** Floating list over the map of units still on their way (or stuck), so
 * arrival times show in every view, including the 3D table. */
export function DispatchChip() {
  const { units } = useEngine();
  const pending = units
    .filter((u) => u.status === "en_route" || u.status === "blocked" || u.status === "grounded")
    .sort((a, b) => (a.eta_min ?? Infinity) - (b.eta_min ?? Infinity));
  if (pending.length === 0) return null;
  return (
    <div className="pointer-events-none absolute left-3 top-14 z-[5] max-w-xs rounded-lg border border-edge bg-surface-1/85 px-2.5 py-1.5 text-[11px] shadow-lg shadow-black/30 backdrop-blur">
      <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">On the way</div>
      <ul className="space-y-0.5">
        {pending.slice(0, 5).map((u) => (
          <li key={u.id} className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TOKEN_STYLE[u.token_type].color }} />
            <span className="truncate text-fg-muted">{TOKEN_STYLE[u.token_type].label}</span>
            <span className="shrink-0" style={{ color: UNIT_STATUS[u.status].color }}>
              {orderText(u)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
