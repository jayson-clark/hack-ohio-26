import { useEffect, useState } from "react";
import { send } from "../shared/engine";
import type { Score, Token, TokenType, WindState } from "../shared/protocol";
import { formatSimMinutes, limitFor } from "../shared/round";
import { elevationAt, type Scenario } from "../shared/scenario";
import { TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import { removeToken, type PlaceType } from "../shared/virtualTokens";
import { CloseIcon, PinIcon } from "./icons";
import ProjectorControls from "./ProjectorControls";
import RoundPanel from "./RoundPanel";
import { Kbd, Panel } from "./ui";

interface Props {
  scenario: Scenario | null;
  wind: WindState | null;
  score: Score | null;
  tokens: Token[];
  placeType: PlaceType;
  onPlaceType: (t: PlaceType) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onFocusPlace: (x: number, y: number) => void;
}

export default function Sidebar(props: Props) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto pb-3">
      <RoundPanel score={props.score} />
      <DeployPanel {...props} />
      <FirePanel {...props} />
      <TokensPanel {...props} />
      {props.scenario && <PlacesPanel scenario={props.scenario} onFocus={props.onFocusPlace} />}
      <Panel title="Projector">
        <ProjectorControls />
      </Panel>
    </aside>
  );
}

function TokenBadge({ type, size = 28 }: { type: TokenType; size?: number }) {
  const { color, letter } = TOKEN_STYLE[type];
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full font-bold text-black"
      style={{ width: size, height: size, background: color, fontSize: size * 0.42, boxShadow: `0 0 0 3px ${color}22` }}
    >
      {letter}
    </span>
  );
}

function DeployPanel({ tokens, score, placeType, onPlaceType }: Props) {
  return (
    <Panel title="Deploy">
      <div className="grid grid-cols-2 gap-2">
        {TOKEN_TYPES.map((t, i) => {
          const active = placeType === t;
          const count = tokens.filter((tk) => tk.token_type === t).length;
          const limit = limitFor(score, t);
          const full = limit !== null && count >= limit;
          return (
            <button
              key={t}
              onClick={() => onPlaceType(t)}
              className={`group relative flex flex-col items-start gap-2 rounded-lg border p-2.5 text-left transition-colors ${
                active ? "border-ember-500/70 bg-ember-500/10" : "border-edge bg-surface-2 hover:border-edge-strong"
              }`}
            >
              <div className="flex w-full items-center justify-between">
                <TokenBadge type={t} size={24} />
                <Kbd>{i + 1}</Kbd>
              </div>
              <div>
                <div className="text-xs font-medium text-fg">{TOKEN_STYLE[t].label}</div>
                <div className={`text-[11px] ${limit !== null && count > limit ? "text-red-400" : "text-fg-subtle"}`}>
                  {limit !== null
                    ? `${count} of ${limit}${full ? (count > limit ? " · over limit" : " · all out") : ""}`
                    : count === 0
                      ? "None placed"
                      : `${count} on table`}
                </div>
              </div>
            </button>
          );
        })}
      </div>
      {placeType !== "ignite" && (
        <p className="mt-2.5 text-[11px] leading-relaxed text-fg-subtle">{TOKEN_STYLE[placeType].hint}.</p>
      )}
    </Panel>
  );
}

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

function FirePanel({ wind, placeType, onPlaceType }: Props) {
  const igniting = placeType === "ignite";
  return (
    <Panel title="Fire">
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => onPlaceType("ignite")}
          className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
            igniting
              ? "border-ember-500/70 bg-ember-500/10 text-ember-300"
              : "border-edge bg-surface-2 text-fg hover:border-edge-strong"
          }`}
        >
          Ignite
        </button>
        <button
          onClick={() => send({ type: "reset" })}
          className="rounded-lg border border-edge bg-surface-2 px-2.5 py-1.5 text-xs font-medium text-fg hover:border-edge-strong"
        >
          Reset
        </button>
      </div>
      {igniting && <p className="mt-2.5 text-[11px] leading-relaxed text-fg-subtle">Click the map to start a fire.</p>}
      {wind && <WindControl wind={wind} />}
    </Panel>
  );
}

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
    <div className="mt-3 space-y-2 text-[11px]">
      <label className="block">
        <span className="flex justify-between text-fg-subtle">
          <span>Wind speed</span>
          <span className="font-mono tabular-nums text-fg">{speed.toFixed(0)} m/s</span>
        </span>
        <input
          type="range"
          min={0}
          max={20}
          step={1}
          value={speed}
          onChange={(e) => update(Number(e.target.value), dir)}
          className="w-full accent-ember-500"
        />
      </label>
      <label className="block">
        <span className="flex justify-between text-fg-subtle">
          <span>From</span>
          <span className="font-mono tabular-nums text-fg">
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
          className="w-full accent-ember-500"
        />
      </label>
    </div>
  );
}

function TokensPanel({ scenario, score, tokens, selectedId, onSelect }: Props) {
  // Over a round's limit these do nothing; water drops show their cooldown.
  const inactive = new Set(score?.inactive_tokens ?? []);
  const cooldown = new Map((score?.water_cooldowns ?? []).map((c) => [c.id, c.ready_in_min]));
  return (
    <Panel
      title="On the table"
      right={<span className="font-mono text-[11px] tabular-nums text-fg-subtle">{tokens.length}</span>}
    >
      {tokens.length === 0 ? (
        <p className="py-3 text-center text-xs text-fg-subtle">
          No tokens yet. Click the map to place one, or put a real token on the table.
        </p>
      ) : (
        <ul className="-mx-1.5 max-h-56 space-y-0.5 overflow-y-auto">
          {tokens.map((t) => {
            const selected = t.id === selectedId;
            return (
              <li key={t.id}>
                <div
                  onClick={() => onSelect(selected ? null : t.id)}
                  className={`group flex cursor-default items-center gap-2.5 rounded-md px-1.5 py-1.5 ${
                    selected ? "bg-surface-3" : "hover:bg-surface-2"
                  }`}
                >
                  <TokenBadge type={t.token_type} size={20} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-fg">{TOKEN_STYLE[t.token_type].label}</div>
                    <div className="font-mono text-[10px] tabular-nums text-fg-subtle">
                      {t.x.toFixed(0)}, {t.y.toFixed(0)}
                      {scenario && ` · ${Math.round(elevationAt(scenario, t.x, t.y))} m`}
                      {inactive.has(t.id) && <span className="text-red-400"> · over limit, no effect</span>}
                      {!inactive.has(t.id) && (cooldown.get(t.id) ?? 0) > 0 && (
                        <span className="text-sky-300"> · refills in {formatSimMinutes(cooldown.get(t.id)!)}</span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                      t.source === "vision" ? "bg-sky-500/15 text-sky-300" : "bg-surface-3 text-fg-muted"
                    }`}
                  >
                    {t.source === "vision" ? "camera" : "virtual"}
                  </span>
                  {t.source === "virtual" && (
                    <button
                      title="Remove"
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
    </Panel>
  );
}

function PlacesPanel({ scenario, onFocus }: { scenario: Scenario; onFocus: (x: number, y: number) => void }) {
  return (
    <Panel title="Places">
      <ul className="-mx-1.5 space-y-0.5">
        {scenario.info.places.map((p) => {
          const [x, y] = p.map;
          const origin = /origin/i.test(p.name);
          return (
            <li key={p.name}>
              <button
                onClick={() => onFocus(x, y)}
                title="Fly to"
                className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left hover:bg-surface-2"
              >
                <span className={origin ? "text-ember-400" : "text-fg-muted"}>
                  <PinIcon />
                </span>
                <span className="flex-1 truncate text-xs text-fg">{p.name}</span>
                <span className="font-mono text-[10px] tabular-nums text-fg-subtle">
                  {Math.round(elevationAt(scenario, x, y))} m
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
