import { useState } from "react";
import { send, useEngine } from "../shared/engine";
import MapView from "../shared/MapView";
import type { TokenType } from "../shared/protocol";
import { TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import ProjectorControls from "./ProjectorControls";

export default function Console() {
  const { status, scenario, tokens } = useEngine();
  const [placeType, setPlaceType] = useState<TokenType>("crew");

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-2">
        <h1 className="text-sm font-semibold tracking-wide">FIREWATCH</h1>
        <div className="flex items-center gap-4 text-xs text-neutral-400">
          {scenario && <span>tick {scenario.tick}</span>}
          <ConnectionBadge status={status} />
        </div>
      </header>

      <main className="flex min-h-0 flex-1 gap-4 p-4">
        <section className="flex min-w-0 flex-1 items-center justify-center">
          <MapView
            placeType={placeType}
            showGrid
            className="aspect-square max-h-full max-w-full rounded border border-neutral-800"
          />
        </section>

        <aside className="flex w-64 shrink-0 flex-col gap-6 text-sm">
          <Panel title="Place token">
            <TokenPicker value={placeType} onChange={setPlaceType} />
            <p className="mt-2 text-xs text-neutral-500">
              Click the map to place. Drag to move, right-click to remove.
            </p>
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

function TokenPicker({ value, onChange }: { value: TokenType; onChange: (t: TokenType) => void }) {
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
