// End-of-round summary: a card over the console viewport, and a large
// version the projector shows over the frozen map (#47).

import { useEffect, useState } from "react";
import { send } from "../shared/engine";
import type { Score } from "../shared/protocol";
import { END_REASON_TEXT, formatSimMinutes, headline } from "../shared/round";
import { Button } from "./ui";

/** Console card. Reappears for each new round end; can be dismissed to look at the map. */
export function RoundSummaryCard({ score }: { score: Score | null }) {
  const [dismissed, setDismissed] = useState(false);
  const ended = score?.phase === "ended";
  useEffect(() => {
    if (!ended) setDismissed(false);
  }, [ended]);
  if (!score || !ended || dismissed) return null;

  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
      <div className="w-[420px] rounded-xl border border-edge bg-surface-1 p-5 shadow-2xl shadow-black/50">
        <Title score={score} />
        <div className="mt-4 grid grid-cols-3 gap-3">
          {headline(score).map((s) => (
            <div key={s.label} className="rounded-lg border border-edge bg-surface-2 p-3">
              <div className="font-mono text-lg tabular-nums text-fg">{s.value}</div>
              <div className="text-[10px] text-fg-subtle">{s.label}</div>
              {s.pct !== null && <div className="mt-1 text-[11px] text-fg-muted">{s.pct}%</div>}
            </div>
          ))}
        </div>
        <div className="mt-5 flex gap-2">
          <Button variant="primary" className="flex-1" onClick={() => send({ type: "start_round" })}>
            New round
          </Button>
          <Button className="flex-1" onClick={() => send({ type: "reset" })}>
            Free play
          </Button>
          <Button variant="ghost" onClick={() => setDismissed(true)} title="Hide this and look at the map">
            View map
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Projector overlay: big, high-contrast text, readable from across the table. */
export function RoundSummaryProjected({ score }: { score: Score | null }) {
  if (!score || score.phase !== "ended") return null;
  return (
    // Solid black: on a projector that's no light at all, so the bright token
    // halos underneath can't glow through.
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
      <div className="rounded-2xl bg-black px-14 py-10 text-center">
        <Title score={score} large />
        <div className="mt-8 flex gap-14">
          {headline(score).map((s) => (
            <div key={s.label}>
              <div className="font-mono text-5xl tabular-nums text-white">{s.value}</div>
              <div className="mt-2 text-lg text-white/70">
                {s.label}
                {s.pct !== null && ` · ${s.pct}%`}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Title({ score, large = false }: { score: Score; large?: boolean }) {
  const reason = score.end_reason ? END_REASON_TEXT[score.end_reason] : "Round over";
  return (
    <div>
      <div className={large ? "text-4xl font-semibold text-white" : "text-base font-semibold text-fg"}>{reason}</div>
      <div className={large ? "mt-1 text-xl text-white/60" : "text-xs text-fg-subtle"}>
        after {formatSimMinutes(score.elapsed_min)} of fire
      </div>
    </div>
  );
}
