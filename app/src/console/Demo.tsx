// Demo mode (#158), for recording the video and showing judges: a bar over
// the map with the fire's clock (pause, step, speed) so a presenter never has
// to leave the console, and an autopilot that takes the top decision after a
// short countdown shown on its card. Hidden unless the console is opened with
// ?demo=1 or Shift+D is pressed; a real operator doesn't control the clock.
//
// Keys while it's showing: [ and ] slow down and speed up, . pauses, A
// toggles the autopilot.

import { useEffect, useRef, useState } from "react";
import { send, useEngine } from "../shared/engine";
import { Icon } from "./icons";
import { Floating } from "./ui";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8]; // the engine's set_speed range
const DELAYS = [2, 4, 8]; // seconds the autopilot waits before acting

export interface AutoItem {
  key: string;
  /** What the autopilot does for this card; cards without one are skipped. */
  auto?: () => void;
}

export interface AutopilotState {
  on: boolean;
  delayS: number;
  /** The card about to be acted on, and when (performance.now() ms). */
  pending: { key: string; at: number } | null;
}

function remembered(): boolean {
  if (new URLSearchParams(location.search).get("demo") === "1") return true;
  try {
    return localStorage.getItem("fireline.demo") === "1";
  } catch {
    return false;
  }
}

/** Whether the demo bar shows, toggled with Shift+D and remembered per browser. */
export function useDemoMode(): boolean {
  const [on, setOn] = useState(remembered);
  useEffect(() => {
    function down(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.shiftKey && e.code === "KeyD") {
        setOn((v) => {
          try {
            localStorage.setItem("fireline.demo", v ? "0" : "1");
          } catch {
            // private window: it just won't be remembered
          }
          return !v;
        });
      }
    }
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
  }, []);
  return on;
}

/** Take the first card that has an action, `delayS` after it comes up. One at
 * a time, each card at most once, and nothing while the fire is paused. */
export function useAutopilot(items: AutoItem[], enabled: boolean): [AutopilotState, (s: Partial<Pick<AutopilotState, "on" | "delayS">>) => void] {
  const { scenario } = useEngine();
  const [on, setOn] = useState(false);
  const [delayS, setDelayS] = useState(4);
  const [pending, setPending] = useState<AutopilotState["pending"]>(null);
  const done = useRef(new Set<string>());
  const latest = useRef(items);
  latest.current = items;

  const active = enabled && on && !!scenario && !scenario.paused;
  const next = active ? items.find((i) => i.auto && !done.current.has(i.key)) : undefined;
  const nextKey = next?.key ?? null;

  // Line up the next card, keeping the countdown if it's still the same one.
  useEffect(() => {
    setPending((p) => (nextKey === null ? null : p?.key === nextKey ? p : { key: nextKey, at: performance.now() + delayS * 1000 }));
  }, [nextKey, delayS]);

  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => {
      done.current.add(pending.key);
      latest.current.find((i) => i.key === pending.key)?.auto?.();
      setPending(null);
    }, Math.max(0, pending.at - performance.now()));
    return () => clearTimeout(t);
  }, [pending]);

  const set = (s: Partial<Pick<AutopilotState, "on" | "delayS">>) => {
    if (s.on !== undefined) setOn(s.on);
    if (s.delayS !== undefined) setDelayS(s.delayS);
  };
  return [{ on, delayS, pending: active ? pending : null }, set];
}

/** A bar draining over the countdown, for the card the autopilot is about to take. */
export function AutopilotCountdown({ at, delayS }: { at: number; delayS: number }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      setNow(performance.now());
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const left = Math.max(0, at - now);
  return (
    <div className="mt-2.5">
      <div className="flex items-center justify-between text-[11px] font-medium text-accent">
        <span className="flex items-center gap-1">
          <Icon name="bolt" size={12} />
          Autopilot
        </span>
        <span className="tnum">in {Math.ceil(left / 1000)} s</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunken">
        <div className="h-full rounded-full bg-accent" style={{ width: `${(left / (delayS * 1000)) * 100}%` }} />
      </div>
    </div>
  );
}

export function DemoBar({ autopilot, onAutopilot }: { autopilot: AutopilotState; onAutopilot: (s: Partial<Pick<AutopilotState, "on" | "delayS">>) => void }) {
  const { scenario } = useEngine();
  const paused = scenario?.paused ?? false;
  const speed = scenario?.speed ?? 1;

  // Read the latest through refs so the listener is registered once.
  const live = useRef({ paused, speed, autopilot: autopilot.on });
  live.current = { paused, speed, autopilot: autopilot.on };
  useEffect(() => {
    function down(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.metaKey || e.ctrlKey) return;
      const i = SPEEDS.indexOf(live.current.speed);
      if (e.key === "[" && i > 0) send({ type: "set_speed", speed: SPEEDS[i - 1] });
      else if (e.key === "]" && i < SPEEDS.length - 1) send({ type: "set_speed", speed: SPEEDS[i < 0 ? 2 : i + 1] });
      else if (e.key === ".") send({ type: "set_running", running: live.current.paused });
      else if (e.key.toLowerCase() === "a" && !e.shiftKey) onAutopilot({ on: !live.current.autopilot });
    }
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
    // onAutopilot only calls state setters, so the first one is fine.
  }, []);

  if (!scenario) return null;
  const seg = (active: boolean) =>
    `h-7 rounded-md px-2 text-xs font-medium tnum transition-colors ${active ? "bg-panel text-ink shadow-card ring-1 ring-line" : "text-ink-3 hover:text-ink"}`;
  return (
    <Floating className="pointer-events-auto flex items-center gap-1.5 p-1">
      <span className="px-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Demo</span>
      <button
        title={paused ? "Resume (.)" : "Pause (.)"}
        onClick={() => send({ type: "set_running", running: paused })}
        className={`flex h-7 w-8 items-center justify-center rounded-md transition-colors ${paused ? "bg-accent text-white hover:bg-accent-hover" : "text-ink hover:bg-hover"}`}
      >
        <Icon name={paused ? "play" : "pause"} size={13} />
      </button>
      <button
        title="Step one tick"
        disabled={!paused}
        onClick={() => send({ type: "step_once" })}
        className="flex h-7 w-7 items-center justify-center rounded-md text-ink transition-colors hover:bg-hover disabled:text-ink-3 disabled:hover:bg-transparent"
      >
        <Icon name="chevronRight" size={14} />
      </button>
      <div className="flex rounded-lg bg-sunken p-0.5" title="Sim speed ([ and ])">
        {SPEEDS.map((s) => (
          <button key={s} onClick={() => send({ type: "set_speed", speed: s })} className={seg(speed === s)}>
            {s < 1 ? `${s}`.replace(/^0/, "") : s}×
          </button>
        ))}
      </div>
      <div className="mx-0.5 h-5 w-px bg-line" />
      <button
        title="Autopilot: take the top decision after a countdown (A)"
        aria-pressed={autopilot.on}
        onClick={() => onAutopilot({ on: !autopilot.on })}
        className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
          autopilot.on ? "bg-accent text-white hover:bg-accent-hover" : "text-ink-2 hover:bg-hover hover:text-ink"
        }`}
      >
        <Icon name="bolt" size={13} />
        Autopilot
      </button>
      {autopilot.on && (
        <div className="flex rounded-lg bg-sunken p-0.5" title="How long the autopilot waits">
          {DELAYS.map((d) => (
            <button key={d} onClick={() => onAutopilot({ delayS: d })} className={seg(autopilot.delayS === d)}>
              {d}s
            </button>
          ))}
        </div>
      )}
    </Floating>
  );
}
