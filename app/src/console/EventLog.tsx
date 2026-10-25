// Situation events (#46, #130): toasts over the map for the urgent ones, and
// the incident timeline in Review. Events are facts from the simulation; the
// commander's take on them is in its dock.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import { EVENT_STYLE } from "../shared/events";
import type { Event, EventKind } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { Icon, type IconName } from "./icons";
import type { Selection } from "./model";
import { Empty, TONE, type Tone } from "./ui";

const ALERT_MS = 6000;
const RECENT_TICKS = 3;
// The same events also reach the decision queue and the commander's dock. The
// queue is the source of truth, so events it already has a card for don't pop
// up too; a toast is only for news with no card that the operator still needs
// at once (a road cut, a unit that can't get through, tankers grounded). One
// line, one at a time, in the map's empty corner: three full cards across the
// middle of the map used to cover the very towns they were about.
const QUEUED: ReadonlySet<EventKind> = new Set(["town_threatened", "no_safe_route", "evacuate_now"]);
const MAX_ALERTS = 1;

const KIND: Record<EventKind, { tone: Tone; icon: IconName }> = {
  town_threatened: { tone: "warn", icon: "alert" },
  no_safe_route: { tone: "crit", icon: "alert" },
  road_cut: { tone: "crit", icon: "route" },
  route_changed: { tone: "warn", icon: "route" },
  forecast_shift: { tone: "info", icon: "activity" },
  town_safe: { tone: "ok", icon: "check" },
  round_ended: { tone: "neutral", icon: "check" },
  unit_arrived: { tone: "ok", icon: "crew" },
  unit_blocked: { tone: "crit", icon: "route" },
  tankers_grounded: { tone: "warn", icon: "air" },
  evacuate_now: { tone: "crit", icon: "users" },
};

/** Urgent events without a decision card pop up over the map for a few
 * seconds. Clicking one opens its town, or the stuck unit's order, in the
 * inspector. */
export function EventAlerts({ onSelect }: { onSelect?: (s: Selection) => void }) {
  const { events, score, units, tokens } = useEngine();
  const [shown, setShown] = useState<{ key: number; event: Event }[]>([]);
  // The store keeps only the last 50 events, so its length stops growing:
  // find new ones by the last event already seen instead.
  const lastSeen = useRef<Event | undefined>(events[events.length - 1]);
  const next = useRef(0);
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  // The end of an exercise outranks whatever was urgent a moment before (#128).
  const over = score?.phase === "ended";
  useEffect(() => {
    if (over) setShown([]);
  }, [over]);

  useEffect(() => {
    // Not found: the store was cleared (a reconnect) and refilled with the
    // engine's recent log. That's history, not news, so only pop up events
    // from the last few ticks.
    const idx = lastSeen.current ? events.lastIndexOf(lastSeen.current) : -1;
    const now = score?.tick ?? 0;
    const fresh = idx >= 0 ? events.slice(idx + 1) : events.filter((e) => e.tick >= now - RECENT_TICKS);
    lastSeen.current = events[events.length - 1];
    const urgent = fresh
      .filter((e) => EVENT_STYLE[e.kind].alert && !QUEUED.has(e.kind))
      .map((event) => ({ key: next.current++, event }));
    if (urgent.length === 0 || over) return;
    // A repeat for the same town and kind replaces its toast instead of stacking.
    const same = (a: Event, b: Event) => a.kind === b.kind && a.town === b.town;
    setShown((s) =>
      [...urgent.reverse(), ...s]
        .filter((x, i, all) => all.findIndex((y) => same(y.event, x.event)) === i)
        .slice(0, MAX_ALERTS),
    );
    const keys = new Set(urgent.map((u) => u.key));
    timers.current.push(window.setTimeout(() => setShown((s) => s.filter((x) => !keys.has(x.key))), ALERT_MS));
  }, [events]);

  const dismiss = (key: number) => setShown((s) => s.filter((x) => x.key !== key));
  // What a toast opens: its town, or for unit news the stuck unit's order.
  function target(e: Event): Selection {
    if (e.town) return { kind: "town", name: e.town };
    const status = e.kind === "tankers_grounded" ? "grounded" : e.kind === "unit_blocked" ? "blocked" : null;
    const u = status && units.find((x) => x.status === status && tokens.some((t) => t.id === x.token_id));
    return u ? { kind: "order", id: u.token_id! } : null;
  }
  return (
    <div className="pointer-events-none absolute left-4 top-[72px] z-10 flex w-[300px] flex-col gap-1.5">
      {shown.map(({ key, event }) => {
        const k = KIND[event.kind];
        const town = event.town;
        const open = onSelect && target(event);
        return (
          <div
            key={key}
            title={event.text}
            onClick={open ? () => onSelect(open) : undefined}
            className={`pointer-events-auto flex items-center gap-2 rounded-lg border border-line bg-panel/95 py-1.5 pl-2 pr-1 shadow-float backdrop-blur ${
              open ? "cursor-pointer hover:border-line-strong" : ""
            }`}
          >
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${TONE[k.tone].soft} ${TONE[k.tone].text}`}>
              <Icon name={k.icon} size={12} />
            </span>
            <span className="min-w-0 flex-1 truncate text-xs">
              <span className="font-semibold text-ink">{EVENT_STYLE[event.kind].label}</span>
              {town && <span className="text-ink-2"> · {town}</span>}
            </span>
            <button
              aria-label="Dismiss"
              onClick={(e) => {
                e.stopPropagation();
                dismiss(key);
              }}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 hover:bg-sunken hover:text-ink"
            >
              <Icon name="close" size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/** Every event so far, newest first, on a vertical timeline. */
export function Timeline() {
  const { events, hello } = useEngine();
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  if (events.length === 0) return <Empty>Road cuts, reroutes, arrivals and threatened towns are logged here.</Empty>;
  return (
    <ol className="relative ml-1.5 border-l border-line">
      {[...events].reverse().map((e, i) => {
        const k = KIND[e.kind];
        return (
          <li key={events.length - i} className="relative pb-3.5 pl-5 last:pb-0">
            <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-panel ${TONE[k.tone].solid}`} />
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-medium text-ink">{EVENT_STYLE[e.kind].label}</span>
              <span className="text-[11px] text-ink-3 tnum">T+{formatSimMinutes(e.tick * perTick)}</span>
            </div>
            <p className="text-xs leading-relaxed text-ink-2">{e.text}</p>
          </li>
        );
      })}
    </ol>
  );
}
