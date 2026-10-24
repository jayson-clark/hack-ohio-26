// Review mode: how the incident has gone so far, town by town. Exercises
// (rounds) are scored by the engine's game layer; the after-action comparison
// against doing nothing is #124.

import { useEngine } from "../shared/engine";
import { END_REASON_TEXT, formatSimMinutes, headline, pct } from "../shared/round";

export default function ReviewPanel() {
  const { score } = useEngine();
  if (!score) return null;
  const phase =
    score.phase === "sandbox"
      ? "Free play: not a timed exercise. Start one from Exercise control to score it."
      : score.phase === "running"
        ? `Exercise running, ${formatSimMinutes(score.duration_min - score.elapsed_min)} left.`
        : `${score.end_reason ? END_REASON_TEXT[score.end_reason] : "Exercise over"} after ${formatSimMinutes(score.elapsed_min)}.`;

  return (
    <div className="space-y-3">
      <p className="text-[11px] leading-relaxed text-fg-subtle">{phase}</p>
      <div className="grid grid-cols-3 gap-2">
        {headline(score).map((s) => (
          <div key={s.label} className="rounded-lg border border-edge bg-surface-2 p-2">
            <div className="font-mono text-sm tabular-nums text-fg">{s.value}</div>
            <div className="text-[10px] leading-tight text-fg-subtle">{s.label}</div>
            {s.pct !== null && <div className="text-[10px] text-fg-muted">{s.pct}%</div>}
          </div>
        ))}
      </div>
      {score.towns.length > 0 && (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-fg-subtle">
              <th className="pb-1 font-medium">Town</th>
              <th className="pb-1 text-right font-medium">Evacuated</th>
              <th className="pb-1 text-right font-medium">Structures lost</th>
            </tr>
          </thead>
          <tbody>
            {score.towns.map((t) => (
              <tr key={t.name} className="border-t border-edge/60">
                <td className="py-1 text-fg">{t.name}</td>
                <td className="py-1 text-right font-mono tabular-nums text-fg-muted">
                  {t.evacuated.toLocaleString()}
                  <span className="text-fg-subtle">/{t.population.toLocaleString()}</span>
                </td>
                <td className={`py-1 text-right font-mono tabular-nums ${t.structures_lost ? "text-red-300" : "text-fg-muted"}`}>
                  {t.structures_lost.toLocaleString()}
                  <span className="text-fg-subtle"> · {pct(t.structures_lost, t.structures)}%</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
