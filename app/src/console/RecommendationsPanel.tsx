// Crew placement recommendations (#45): the engine's top picks from paired
// counterfactual rollouts (#62), numbered to match the rings drawn on the
// map. Accept places a virtual crew there.

import { acceptRecommendation, useEngine } from "../shared/engine";
import type { Recommendation, TownEffect } from "../shared/protocol";
import { REC_COLOR } from "../render/routes";
import { PinIcon } from "./icons";
import { Button, Panel } from "./ui";

export default function RecommendationsPanel({ onFocus }: { onFocus: (x: number, y: number) => void }) {
  const { recommendations, simGrid } = useEngine();
  const burning = !!simGrid && simGrid.payload.includes(2);
  return (
    <Panel
      title="Recommended"
      right={<span className="font-mono text-[11px] tabular-nums text-fg-subtle">{recommendations.length}</span>}
    >
      {recommendations.length === 0 ? (
        <p className="py-1 text-[11px] leading-relaxed text-fg-subtle">
          {burning
            ? "Weighing crew placements against the forecast…"
            : "Once a fire is burning, the best places for a crew show here and as numbered rings on the map."}
        </p>
      ) : (
        <ol className="space-y-2">
          {recommendations.map((r, i) => (
            <Card key={r.id} rank={i + 1} rec={r} onFocus={onFocus} />
          ))}
        </ol>
      )}
    </Panel>
  );
}

function Card({ rank, rec, onFocus }: { rank: number; rec: Recommendation; onFocus: (x: number, y: number) => void }) {
  return (
    <li className="rounded-lg border border-edge bg-surface-2 p-2.5">
      <div className="flex items-start gap-2">
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-black"
          style={{ background: REC_COLOR }}
        >
          {rank}
        </span>
        <p className="flex-1 text-xs leading-relaxed text-fg">{rec.text}</p>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1 pl-7">
        {rec.saves.map((e) => (
          <Effect key={`s${e.town}`} effect={e} good />
        ))}
        {rec.worsens.map((e) => (
          <Effect key={`w${e.town}`} effect={e} good={false} />
        ))}
        {rec.confidence !== "high" && (
          <span
            title="Helps even at the low end of its range, but the range is wide: few simulations agree on how much"
            className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300"
          >
            rough estimate
          </span>
        )}
        {rec.acres_saved > 0 && (
          <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] text-fg-muted">
            ~{Math.round(rec.acres_saved).toLocaleString()} ac kept
          </span>
        )}
      </div>
      <div className="mt-2 flex gap-1.5 pl-7">
        <Button
          variant="primary"
          className={`h-7 flex-1 ${rec.auto ? "" : "cursor-not-allowed opacity-50"}`}
          title={rec.auto ? undefined : "A physical crew on the table: move it there by hand"}
          onClick={rec.auto ? () => acceptRecommendation(rec.id) : undefined}
        >
          {rec.action === "move" ? (rec.auto ? "Move crew" : "Move it by hand") : "Place crew"}
        </Button>
        <Button variant="ghost" className="h-7" title="Fly to" onClick={() => onFocus(rec.x, rec.y)}>
          <PinIcon />
        </Button>
      </div>
    </li>
  );
}

/** "Paradise 24/32": in how many of the rollouts the crew changes whether fire reaches the town. */
function Effect({ effect, good }: { effect: TownEffect; good: boolean }) {
  return (
    <span
      title={`${good ? "Keeps fire out of" : "Pushes fire into"} ${effect.town} in ${effect.hits} of ${effect.n} simulations (likely ${Math.round(effect.lo * 100)}–${Math.round(effect.hi * 100)}%)`}
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${
        good ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
      }`}
    >
      {good ? "" : "⚠ "}
      {effect.town} {effect.hits}/{effect.n}
    </span>
  );
}
