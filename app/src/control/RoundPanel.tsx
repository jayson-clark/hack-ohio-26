// Round controls and the live scoreboard (game layer, #47). Outside a round
// the engine runs free play with no limits or timer; a round resets the map,
// lights the scenario's fire and counts down.

import { send } from "../shared/engine";
import type { Score } from "../shared/protocol";
import { END_REASON_TEXT, formatSimMinutes, headline, pct } from "../shared/round";
import { TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import { Button, Panel } from "../console/ui";

export default function RoundPanel({ score }: { score: Score | null }) {
  if (!score) return null;
  return (
    <Panel title="Exercise" right={<PhaseBadge score={score} />}>
      {score.phase === "sandbox" && <FreePlay score={score} />}
      {score.phase === "running" && <Running score={score} />}
      {score.phase === "ended" && <Ended score={score} />}
      {/* Free play isn't scored against anything, so keep the panel short there. */}
      {score.phase !== "sandbox" && (
        <>
          <Stats score={score} />
          <Towns score={score} />
        </>
      )}
    </Panel>
  );
}

function PhaseBadge({ score }: { score: Score }) {
  const style = {
    sandbox: "bg-surface-3 text-fg-muted",
    running: "bg-ember-500/15 text-ember-300",
    ended: "bg-sky-500/15 text-sky-300",
  }[score.phase];
  const label = { sandbox: "Free play", running: "Live", ended: "Final" }[score.phase];
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${style}`}>{label}</span>;
}

function FreePlay({ score }: { score: Score }) {
  return (
    <div className="space-y-2">
      <p className="text-[11px] leading-relaxed text-fg-subtle">
        Free play: no limits or timer. An exercise resets the map, starts the scenario's fire and runs for{" "}
        {formatSimMinutes(score.duration_min)} with limited units.
      </p>
      <Button variant="primary" className="w-full" onClick={() => send({ type: "start_round" })}>
        Start exercise
      </Button>
    </div>
  );
}

function Running({ score }: { score: Score }) {
  const left = score.duration_min - score.elapsed_min;
  const done = Math.min(1, score.elapsed_min / Math.max(1, score.duration_min));
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-baseline justify-between text-[11px]">
          <span className="text-fg-subtle">Time left</span>
          <span className="font-mono text-sm tabular-nums text-fg">{formatSimMinutes(left)}</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
          <div
            className={`h-full rounded-full ${left < score.duration_min * 0.15 ? "bg-red-400" : "bg-ember-500"}`}
            style={{ width: `${done * 100}%` }}
          />
        </div>
      </div>
      <Resources score={score} />
      <Button className="w-full" onClick={() => send({ type: "end_round" })}>
        End exercise
      </Button>
    </div>
  );
}

function Ended({ score }: { score: Score }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-fg">
        {score.end_reason ? END_REASON_TEXT[score.end_reason] : "Exercise over"}
        <span className="text-fg-subtle"> after {formatSimMinutes(score.elapsed_min)}</span>
      </p>
      <div className="grid grid-cols-2 gap-2">
        <Button variant="primary" onClick={() => send({ type: "start_round" })}>
          New exercise
        </Button>
        <Button onClick={() => send({ type: "reset" })}>Free play</Button>
      </div>
    </div>
  );
}

/** One pip per token of each type the round allows: filled when placed. */
function Resources({ score }: { score: Score }) {
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
      {TOKEN_TYPES.map((t) => {
        const r = score.resources.find((x) => x.token_type === t);
        if (!r || r.limit === null) return null;
        const { color, label } = TOKEN_STYLE[t];
        return (
          <div key={t} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="truncate text-fg-subtle">{label}</span>
            <span className="flex gap-1" title={`${r.used} of ${r.limit} deployed`}>
              {Array.from({ length: r.limit }, (_, i) => (
                <span
                  key={i}
                  className="h-2 w-2 rounded-full"
                  style={i < r.used ? { background: color } : { boxShadow: `inset 0 0 0 1px ${color}88` }}
                />
              ))}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Stats({ score }: { score: Score }) {
  return (
    <div className="mt-3 grid grid-cols-3 gap-2 border-t border-edge pt-3">
      {headline(score).map((s) => (
        <div key={s.label} className="min-w-0">
          <div className="font-mono text-sm tabular-nums text-fg">{s.value}</div>
          <div className="text-[10px] leading-tight text-fg-subtle" title={`${s.label} ${s.of}`}>
            {s.short}
            {s.pct !== null && <div className="text-fg-muted">{s.pct}%</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

function Towns({ score }: { score: Score }) {
  if (score.towns.length === 0) return null;
  return (
    <ul className="mt-3 space-y-1.5">
      {score.towns.map((t) => {
        const out = pct(t.evacuated, t.population);
        // A few structures out of thousands rounds to 0%, which reads as none.
        const lost = t.structures_lost / Math.max(1, t.structures) < 0.01 ? "<1" : pct(t.structures_lost, t.structures);
        return (
          <li key={t.name} className="text-[11px]">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-fg">{t.name}</span>
              <span className="shrink-0 font-mono tabular-nums text-fg-subtle">
                {t.evacuated.toLocaleString()}/{t.population.toLocaleString()} out
                {t.structures_lost > 0 && <span className="text-red-400"> · {lost}% lost</span>}
              </span>
            </div>
            <div className="mt-0.5 flex h-1 overflow-hidden rounded-full bg-surface-3">
              <div className="h-full bg-emerald-400" style={{ width: `${out}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
