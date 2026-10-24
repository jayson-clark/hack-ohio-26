// Situation events (#46; engine side in #38/#66): a log in the sidebar and
// short-lived alerts over the map for the urgent ones. Events are facts from
// the simulation; the commander's take on them is in its own panel.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import { EVENT_STYLE } from "../shared/events";
import type { Event } from "../shared/protocol";
import { Panel } from "./ui";

const ALERT_MS = 6000;

export function EventLogPanel() {
  const { events, hello } = useEngine();
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const newestFirst = [...events].reverse();
  return (
    <Panel title="Events" right={<span className="font-mono text-[11px] tabular-nums text-fg-subtle">{events.length}</span>}>
      {events.length === 0 ? (
        <p className="py-1 text-[11px] text-fg-subtle">Road cuts, reroutes and threatened towns show up here.</p>
      ) : (
        <ul className="-mx-1 max-h-56 space-y-1 overflow-y-auto px-1">
          {newestFirst.map((e, i) => {
            const style = EVENT_STYLE[e.kind];
            return (
              <li key={events.length - i} className="flex gap-2 text-[11px]">
                <span className="w-12 shrink-0 font-mono tabular-nums text-fg-subtle">
                  T+{Math.round(e.tick * perTick)}m
                </span>
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: style.color }} />
                <span className="leading-relaxed text-fg">
                  <span className="font-medium" style={{ color: style.color }}>
                    {style.label}
                  </span>{" "}
                  {e.text}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/** Urgent events pop up over the map for a few seconds, newest on top. */
export function EventAlerts() {
  const { events } = useEngine();
  const [shown, setShown] = useState<{ key: number; event: Event }[]>([]);
  // The store keeps only the last 50 events, so its length stops growing:
  // find new ones by the last event already seen instead.
  const lastSeen = useRef<Event | undefined>(events[events.length - 1]);
  const next = useRef(0);
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  useEffect(() => {
    const idx = lastSeen.current ? events.lastIndexOf(lastSeen.current) : -1;
    // Not found: the store was cleared (reconnect) or rolled past it. Only the
    // newest few are worth an alert then.
    const fresh = idx >= 0 ? events.slice(idx + 1) : events.slice(-3);
    lastSeen.current = events[events.length - 1];
    const urgent = fresh.filter((e) => EVENT_STYLE[e.kind].alert).map((event) => ({ key: next.current++, event }));
    if (urgent.length === 0) return;
    setShown((s) => [...urgent.reverse(), ...s].slice(0, 3));
    const keys = new Set(urgent.map((u) => u.key));
    timers.current.push(window.setTimeout(() => setShown((s) => s.filter((x) => !keys.has(x.key))), ALERT_MS));
  }, [events]);

  return (
    <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex flex-col items-center gap-2">
      {shown.map(({ key, event }) => {
        const style = EVENT_STYLE[event.kind];
        return (
          <div
            key={key}
            className="flex max-w-md items-start gap-2.5 rounded-lg border bg-surface-1/95 px-3 py-2 shadow-xl shadow-black/40 backdrop-blur"
            style={{ borderColor: `${style.color}66` }}
          >
            <span className="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full" style={{ background: style.color }} />
            <div className="text-xs">
              <div className="font-semibold" style={{ color: style.color }}>
                {style.label}
                {event.town && <span className="text-fg"> · {event.town}</span>}
              </div>
              <div className="text-fg-muted">{event.text}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
