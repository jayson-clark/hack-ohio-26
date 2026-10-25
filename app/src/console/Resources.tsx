// What the operator has to work with (#122, #130): free units of each kind,
// and every standing order with its unit's status. An order is a token
// (#104), whether given here, accepted from a recommendation, or placed on
// the physical table.

import { orderText, unitFor } from "../shared/dispatch";
import { useEngine } from "../shared/engine";
import { describeLocation } from "../shared/places";
import type { TokenType, UnitStatus } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE } from "../shared/tokens";
import { Icon } from "./icons";
import { ORDER_COLOR, ORDER_ICON } from "./model";
import { Empty, TONE, type Tone } from "./ui";

const UNIT_TYPES: TokenType[] = ["crew", "firebreak", "water"];
const STATUS_TONE: Record<UnitStatus, Tone> = {
  available: "neutral",
  en_route: "info",
  working: "ok",
  blocked: "crit",
  grounded: "warn",
};

export default function Resources({
  scenario,
  selected,
  onSelect,
}: {
  scenario: Scenario;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { units, tokens, score } = useEngine();
  const inactive = new Set(score?.inactive_tokens ?? []);

  return (
    <div className="space-y-4">
      {units.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {UNIT_TYPES.map((t) => {
            const own = units.filter((u) => u.token_type === t);
            const free = own.filter((u) => u.status === "available").length;
            return (
              <div key={t} className="rounded-lg border border-line px-2.5 py-2">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-ink-2">
                  <Icon name={ORDER_ICON[t]} size={13} style={{ color: ORDER_COLOR[t] }} />
                  {ORDER_STYLE[t].label}
                </div>
                <div className="mt-0.5 text-[17px] font-semibold text-ink tnum">
                  {free}
                  <span className="text-xs font-normal text-ink-3"> of {own.length} free</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tokens.length === 0 ? (
        <Empty>No orders yet. Dispatch a recommendation, or pick a unit type above the map and click where it should go.</Empty>
      ) : (
        <ul className="-mx-2">
          {tokens.map((t) => {
            const u = unitFor(t, units);
            const tone: Tone = inactive.has(t.id) ? "crit" : u ? STATUS_TONE[u.status] : "neutral";
            const status = inactive.has(t.id)
              ? "Over the exercise limit"
              : u
                ? `${u.station}: ${orderText(u)}`
                : t.token_type === "bus"
                  ? "Evacuating"
                  : units.length > 0
                    ? "Waiting for a unit"
                    : "Acting now";
            return (
              <li key={t.id}>
                <button
                  onClick={() => onSelect(t.id)}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors ${t.id === selected ? "bg-accent-soft" : "hover:bg-hover"}`}
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border-2 bg-panel" style={{ borderColor: ORDER_COLOR[t.token_type], color: ORDER_COLOR[t.token_type] }}>
                    <Icon name={ORDER_ICON[t.token_type]} size={14} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-ink">
                      {ORDER_STYLE[t.token_type].label} {describeLocation(scenario, t.x, t.y)}
                    </span>
                    <span className={`block truncate text-xs ${tone === "neutral" ? "text-ink-3" : TONE[tone].text}`}>
                      {status}
                      {t.source === "vision" && " · on the table"}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
