import { useEffect, useState } from "react";
import { send, useEngine } from "../shared/engine";
import MapView, { type PlaceType } from "../shared/MapView";
import type { WindState } from "../shared/protocol";
import { TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import ProjectorControls from "./ProjectorControls";

export default function Console() {
  const { status, scenario, tokens } = useEngine();
  const [placeType, setPlaceType] = useState<PlaceType>("crew");

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-2">
        <h1 className="text-sm font-semibold tracking-wide">FIREWATCH</h1>
        <div className="flex items-center gap-4 text-xs text-neutral-400">
          {scenario && (
            <span className="tabular-nums">
              {scenario.burning_cells} burning · {scenario.burned_cells} burned
            </span>
          )}
          {scenario && <span>tick {scenario.tick}</span>}
          <ConnectionBadge status={status} />
        </div>
      </header>

      <main className="flex min-h-0 flex-1 gap-4 p-4">
        <section className="flex min-w-0 flex-1 items-center justify-center">
          <MapView
            placeType={placeType}
            showGrid
            className="max-h-full max-w-full rounded border border-neutral-800"
          />
        </section>

        <aside className="flex w-64 shrink-0 flex-col gap-6 text-sm">
          <Panel title="Place token">
            <TokenPicker value={placeType} onChange={setPlaceType} />
            <p className="mt-2 text-xs text-neutral-500">
              Click the map to place. Drag to move, right-click to remove.
            </p>
          </Panel>

          <Panel title="Fire">
            <div className="flex gap-1">
              <button
                onClick={() => setPlaceType("ignite")}
                className={`flex-1 rounded px-2 py-1 text-xs ${
                  placeType === "ignite" ? "bg-orange-700" : "bg-neutral-900 hover:bg-neutral-800"
                }`}
              >
                Ignite
              </button>
              <button
                onClick={() => send({ type: "reset" })}
                className="flex-1 rounded bg-neutral-900 px-2 py-1 text-xs hover:bg-neutral-800"
              >
                Reset
              </button>
            </div>
            {scenario && <WindControl wind={scenario.wind} />}
          </Panel>

          <Panel title={`Tokens (${tokens.length})`}>
            <ul className="space-y-1">
              {tokens.map((t) => (
                <li key={t.id} className="flex items-center gap-2 text-xs">
                  <span className="h-2 w-2 rounded-full" style={{ background: TOKEN_STYLE[t.token_type].color }} />
                  <span className="flex-1">{TOKEN_STYLE[t.token_type].label}</span>
                  <span className="tabular-nums text-neutral-500">
                    {t.x.toFixed(0)}, {t.y.toFixed(0)}
                  </span>
                  {t.source === "virtual" && (
                    <button
                      className="text-neutral-500 hover:text-neutral-200"
                      onClick={() => send({ type: "virtual_token_remove", id: t.id })}
                    >
                      ×
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Projector">
            <ProjectorControls />
          </Panel>
        </aside>
      </main>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-neutral-500">{title}</h2>
      {children}
    </div>
  );
}

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

// Local state while dragging, so the 1 Hz scenario_state echo doesn't fight
// the slider; it resyncs whenever the engine reports a different wind.
function WindControl({ wind }: { wind: WindState }) {
  const [speed, setSpeed] = useState(wind.speed_ms);
  const [dir, setDir] = useState(wind.from_deg);
  useEffect(() => {
    setSpeed(wind.speed_ms);
    setDir(wind.from_deg);
  }, [wind.speed_ms, wind.from_deg]);

  function update(speed_ms: number, from_deg: number) {
    setSpeed(speed_ms);
    setDir(from_deg);
    send({ type: "set_wind", speed_ms, from_deg });
  }

  return (
    <div className="mt-3 space-y-2 text-xs">
      <label className="block">
        <span className="flex justify-between text-neutral-400">
          <span>Wind speed</span>
          <span className="tabular-nums">{speed.toFixed(0)} m/s</span>
        </span>
        <input
          type="range"
          min={0}
          max={20}
          step={1}
          value={speed}
          onChange={(e) => update(Number(e.target.value), dir)}
          className="w-full"
        />
      </label>
      <label className="block">
        <span className="flex justify-between text-neutral-400">
          <span>From</span>
          <span className="tabular-nums">
            {COMPASS[Math.round(dir / 45) % 8]} {dir.toFixed(0)}°
          </span>
        </span>
        <input
          type="range"
          min={0}
          max={355}
          step={5}
          value={dir}
          onChange={(e) => update(speed, Number(e.target.value))}
          className="w-full"
        />
      </label>
    </div>
  );
}

function TokenPicker({ value, onChange }: { value: PlaceType; onChange: (t: PlaceType) => void }) {
  return (
    <div className="grid grid-cols-2 gap-1">
      {TOKEN_TYPES.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`flex items-center gap-2 rounded px-2 py-1 text-left text-xs ${
            value === t ? "bg-neutral-700" : "bg-neutral-900 hover:bg-neutral-800"
          }`}
        >
          <span className="h-2 w-2 rounded-full" style={{ background: TOKEN_STYLE[t].color }} />
          {TOKEN_STYLE[t].label}
        </button>
      ))}
    </div>
  );
}

function ConnectionBadge({ status }: { status: string }) {
  const color = status === "open" ? "bg-green-500" : status === "connecting" ? "bg-yellow-500" : "bg-red-500";
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      engine {status === "open" ? "connected" : status}
    </span>
  );
}
