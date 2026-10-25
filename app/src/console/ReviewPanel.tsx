// Review mode (#130): how the incident has gone so far, then the timeline.
// The comparison against doing nothing is #124.

import { useEngine } from "../shared/engine";
import { END_REASON_TEXT, formatSimMinutes, headline, pct } from "../shared/round";
import { Timeline } from "./EventLog";
import { Section, Stat } from "./ui";

export default function ReviewPanel() {
  const { score, events } = useEngine();
  if (!score) return null;
  const phase =
    score.phase === "sandbox"
      ? "Free play, not a timed exercise. Start one from Exercise control to score it."
      : score.phase === "running"
        ? `Exercise running, ${formatSimMinutes(score.duration_min - score.elapsed_min)} left.`
        : `${score.end_reason ? END_REASON_TEXT[score.end_reason] : "Exercise over"} after ${formatSimMinutes(score.elapsed_min)}.`;
  const [evacuated, saved, acres] = headline(score);

  return (
    <>
      <Section title="Outcome so far">
        <p className="mb-3 text-xs text-ink-2">{phase}</p>
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Evacuated" value={evacuated.value} sub={`${evacuated.pct}% of residents`} tone="ok" />
          <Stat label="Structures saved" value={saved.value} sub={`${saved.pct}%`} />
          <Stat label="Acres burned" value={acres.value} tone="crit" />
        </div>
        {score.towns.length > 0 && (
          <div className="mt-4">
            <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 pb-1 text-[11px] font-medium text-ink-3">
              <span>Town</span>
              <span className="text-right">Evacuated</span>
              <span className="w-20 text-right">Structures lost</span>
            </div>
            {score.towns.map((t) => (
              <div key={t.name} className="grid grid-cols-[1fr_auto_auto] gap-x-4 border-t border-line py-1.5 text-xs">
                <span className="text-ink">{t.name}</span>
                <span className="text-right text-ink-2 tnum">
                  {t.evacuated.toLocaleString()}
                  <span className="text-ink-3">/{t.population.toLocaleString()}</span>
                </span>
                <span className={`w-20 text-right tnum ${t.structures_lost ? "font-medium text-crit" : "text-ink-3"}`}>
                  {t.structures_lost.toLocaleString()} · {pct(t.structures_lost, t.structures)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Timeline" count={events.length}>
        <Timeline />
      </Section>
    </>
  );
}
