// What the operator has to work with (#122): free units of each kind, and
// every standing order with what its unit is doing. An order is a token
// (#104), whether it was given here, accepted from a recommendation, or
// placed on the physical table.

import { orderText, unitFor, UNIT_STATUS } from "../shared/dispatch";
import { useEngine } from "../shared/engine";
import { describeLocation } from "../shared/places";
import type { TokenType } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE, TOKEN_STYLE } from "../shared/tokens";
import { removeToken } from "../shared/virtualTokens";
import { CloseIcon } from "./icons";
import StationsPanel from "./StationsPanel";

const UNIT_TYPES: TokenType[] = ["crew", "firebreak", "water"];

export default function Resources({ scenario, onFocus }: { scenario: Scenario; onFocus: (x: number, y: number) => void }) {
  const { units, tokens, score } = useEngine();
  const inactive = new Set(score?.inactive_tokens ?? []);

  return (
    <div className="space-y-3">
      {units.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5">
          {UNIT_TYPES.map((t) => {
            const own = units.filter((u) => u.token_type === t);
            const free = own.filter((u) => u.status === "available").length;
            return (
              <div key={t} className="rounded-lg border border-edge bg-surface-2 px-2 py-1.5">
                <div className="flex items-center gap-1.5 text-[10px] text-fg-subtle">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: TOKEN_STYLE[t].color }} />
                  {ORDER_STYLE[t].label}
                </div>
                <div className="font-mono text-sm tabular-nums text-fg">
                  {free}
                  <span className="text-[11px] text-fg-subtle">/{own.length} free</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">Orders</div>
        {tokens.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-fg-subtle">
            None yet. Dispatch a recommendation, or pick an order type on the map and click where it should go.
          </p>
        ) : (
          <ul className="-mx-1.5 space-y-0.5">
            {tokens.map((t) => {
              const u = unitFor(t, units);
              return (
                <li key={t.id}>
                  <div
                    onClick={() => onFocus(t.x, t.y)}
                    className="group flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 hover:bg-surface-2"
                  >
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TOKEN_STYLE[t.token_type].color }} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-fg">
                        {ORDER_STYLE[t.token_type].label} {describeLocation(scenario, t.x, t.y)}
                      </div>
                      <div className="truncate text-[10px] text-fg-subtle">
                        {inactive.has(t.id) ? (
                          <span className="text-red-400">over the exercise's limit, no effect</span>
                        ) : u ? (
                          <span style={{ color: UNIT_STATUS[u.status].color }}>
                            {u.station}: {orderText(u)}
                          </span>
                        ) : t.token_type === "bus" ? (
                          "evacuating"
                        ) : units.length > 0 ? (
                          // Dispatch assigns units as the fire steps, so a paused fire leaves orders waiting.
                          "waiting for a unit"
                        ) : (
                          "acting now"
                        )}
                        {t.source === "vision" && " · on the table"}
                      </div>
                    </div>
                    {t.source === "virtual" && (
                      <button
                        title="Cancel this order"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeToken(t.id);
                        }}
                        className="rounded p-1 text-fg-subtle opacity-0 hover:bg-surface-3 hover:text-fg group-hover:opacity-100"
                      >
                        <CloseIcon />
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {units.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-[10px] font-semibold uppercase tracking-wide text-fg-subtle hover:text-fg-muted">
            <span className="inline-block transition-transform group-open:rotate-90">›</span> By station
          </summary>
          <div className="mt-2">
            <StationsPanel onFocus={onFocus} bare />
          </div>
        </details>
      )}
    </div>
  );
}
