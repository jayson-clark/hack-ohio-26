import type { Token, TokenType } from "../shared/protocol";
import { elevationAt, type Scenario } from "../shared/scenario";
import { TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import { removeToken } from "../shared/virtualTokens";
import { CloseIcon, PinIcon } from "./icons";
import ProjectorControls from "./ProjectorControls";
import { Kbd, Panel } from "./ui";

interface Props {
  scenario: Scenario | null;
  tokens: Token[];
  placeType: TokenType;
  onPlaceType: (t: TokenType) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onFocusPlace: (x: number, y: number) => void;
}

export default function Sidebar(props: Props) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto pb-3">
      <DeployPanel {...props} />
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

function DeployPanel({ tokens, placeType, onPlaceType }: Props) {
  return (
    <Panel title="Deploy">
      <div className="grid grid-cols-2 gap-2">
        {TOKEN_TYPES.map((t, i) => {
          const active = placeType === t;
          const count = tokens.filter((tk) => tk.token_type === t).length;
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
                <div className="text-[11px] text-fg-subtle">{count === 0 ? "None placed" : `${count} on table`}</div>
              </div>
            </button>
          );
        })}
      </div>
      <p className="mt-2.5 text-[11px] leading-relaxed text-fg-subtle">{TOKEN_STYLE[placeType].hint}.</p>
    </Panel>
  );
}

function TokensPanel({ scenario, tokens, selectedId, onSelect }: Props) {
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
