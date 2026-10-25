// Situation events (#46, #130): toasts over the map for the urgent ones, and
// the incident timeline in Review. Events are facts from the simulation; the
// commander's take on them is in its dock.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import { EVENT_STYLE } from "../shared/events";
import type { Event, EventKind } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { Icon, type IconName } from "./icons";
import { Empty, TONE, type Tone } from "./ui";

const ALERT_MS = 6000;
const RECENT_TICKS = 3;

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

/** Urgent events pop up over the map for a few seconds, newest on top. */
export function EventAlerts() {
  const { events, score } = useEngine();
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
    const urgent = fresh.filter((e) => EVENT_STYLE[e.kind].alert).map((event) => ({ key: next.current++, event }));
    if (urgent.length === 0 || over) return;
    setShown((s) => [...urgent.reverse(), ...s].slice(0, 3));
    const keys = new Set(urgent.map((u) => u.key));
    timers.current.push(window.setTimeout(() => setShown((s) => s.filter((x) => !keys.has(x.key))), ALERT_MS));
  }, [events]);

  return (
    <div className="pointer-events-none absolute inset-x-0 top-20 z-10 flex flex-col items-center gap-2">
      {shown.map(({ key, event }) => {
        const k = KIND[event.kind];
        return (
          <div key={key} className="flex w-[380px] items-start gap-3 rounded-xl border border-line bg-panel px-3.5 py-3 shadow-float">
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${TONE[k.tone].soft} ${TONE[k.tone].text}`}>
              <Icon name={k.icon} size={15} />
            </span>
            <div className="min-w-0 text-xs leading-relaxed">
              <div className="text-[13px] font-semibold text-ink">
                {EVENT_STYLE[event.kind].label}
                {event.town && <span className="font-normal text-ink-2"> · {event.town}</span>}
              </div>
              <div className="text-ink-2">{event.text}</div>
            </div>
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
