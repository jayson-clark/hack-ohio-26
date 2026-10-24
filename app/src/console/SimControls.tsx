// Pause, single-step and speed for the fire (#76; engine side in #71). Lives
// in the header so it's reachable mid-demo, with Space as the shortcut.

import { useEffect, useRef } from "react";
import { send } from "../shared/engine";
import type { ScenarioState } from "../shared/protocol";
import { PauseIcon, PlayIcon, StepIcon } from "./icons";

const SPEEDS = [0.5, 1, 2, 4];

export default function SimControls({ state }: { state: ScenarioState | null }) {
  // Space toggles pause. Read the latest state through a ref so the listener
  // is registered once.
  const paused = useRef(false);
  paused.current = state?.paused ?? false;
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.code !== "Space" || e.repeat) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.target instanceof HTMLButtonElement) return; // Space already clicks a focused button
      e.preventDefault();
      send({ type: "set_running", running: paused.current });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!state) return null;
  const { paused: isPaused, speed } = state;
  return (
    <div className="flex items-center gap-1 rounded-lg border border-edge bg-surface-1 p-0.5">
      <button
        title={isPaused ? "Resume (Space)" : "Pause (Space)"}
        onClick={() => send({ type: "set_running", running: isPaused })}
        className={`flex h-6 w-7 items-center justify-center rounded-md transition-colors ${
          isPaused ? "bg-ember-500 text-black hover:bg-ember-400" : "text-fg hover:bg-surface-3"
        }`}
      >
        {isPaused ? <PlayIcon /> : <PauseIcon />}
      </button>
      <button
        title="Step one sim-minute"
        disabled={!isPaused}
        onClick={() => send({ type: "step_once" })}
        className="flex h-6 w-7 items-center justify-center rounded-md text-fg transition-colors hover:bg-surface-3 disabled:text-fg-subtle disabled:hover:bg-transparent"
      >
        <StepIcon />
      </button>
      <div className="mx-0.5 h-4 w-px bg-edge" />
      {SPEEDS.map((s) => (
        <button
          key={s}
          onClick={() => send({ type: "set_speed", speed: s })}
          className={`h-6 rounded-md px-1.5 font-mono text-[11px] tabular-nums transition-colors ${
            speed === s ? "bg-surface-3 text-fg" : "text-fg-subtle hover:text-fg"
          }`}
        >
          {s}×
        </button>
      ))}
      {isPaused && <span className="px-1.5 text-[11px] font-medium text-ember-300">Paused</span>}
    </div>
  );
}
