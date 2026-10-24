// The decision queue (#122): what the operator should act on now, most urgent
// first. It's built from what the engine already works out (the town board,
// crew recommendations, units that can't get through), so every number on a
// card comes from the simulation. When the evacuation order clock (#121)
// lands, its "order by" times slot into the evacuation cards.

import type { ReactNode } from "react";
import { UNIT_STATUS, orderText } from "../shared/dispatch";
import { acceptRecommendation, useEngine } from "../shared/engine";
import type { Recommendation, Token, TownThreat } from "../shared/protocol";
import { aboutMinutes, describeLocation } from "../shared/places";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE, TOKEN_STYLE } from "../shared/tokens";
import { addToken } from "../shared/virtualTokens";
import { REC_COLOR } from "../render/routes";
import { Button } from "./ui";

type Level = "now" | "soon" | "consider" | "info";

const LEVEL: Record<Level, { label: string; color: string }> = {
  now: { label: "Act now", color: "#ef4444" },
  soon: { label: "Act soon", color: "#fb923c" },
  consider: { label: "Recommended", color: REC_COLOR },
  info: { label: "Heads up", color: "#38bdf8" },
};
const ORDER: Level[] = ["now", "soon", "consider", "info"];

interface Decision {
  key: string;
  level: Level;
  /** Sort within a level: sooner first. */
  minutes: number;
  title: string;
  body: ReactNode;
  actions: ReactNode;
}

interface Props {
  scenario: Scenario;
  onFocus: (x: number, y: number) => void;
  onTryInPlan: (rec: Recommendation) => void;
}

// A town is worth an evacuation card when at least this share of the
// simulations reach it within the hour.
const EVAC_SHARE = 0.25;

export default function Decisions({ scenario, onFocus, onTryInPlan }: Props) {
  const { situation, recommendations, tokens, units, simGrid } = useEngine();
  const burning = !!simGrid && simGrid.payload.includes(2);
  const towns = new Map(scenario.towns.map((t) => [t.name, t]));
  const decisions: Decision[] = [];

  for (const t of situation?.towns ?? []) {
    const town = towns.get(t.town);
    if (!town) continue;
    const share = t.within_60 ? t.within_60.k / Math.max(1, t.within_60.n) : 0;
    if (!t.fire_inside && share < EVAC_SHARE) continue;
    const show = (
      <Button variant="ghost" className="h-7" onClick={() => onFocus(town.x, town.y)}>
        Show
      </Button>
    );
    if (t.route_status === "cut") {
      decisions.push({
        key: `cut-${t.town}`,
        level: "now",
        minutes: t.soonest_min ?? 0,
        title: `No safe way out of ${t.town}`,
        body: (
          <>
            Every route out is cut or will burn before traffic gets through. {t.population.toLocaleString()} residents.
            Shelter in place, or send a crew to hold a road open. <Arrival t={t} />
          </>
        ),
        actions: show,
      });
      continue;
    }
    const bus = tokens.find((k) => k.token_type === "bus" && Math.hypot(k.x - town.x, k.y - town.y) <= town.radius);
    decisions.push({
      key: `evac-${t.town}`,
      level: t.fire_inside || (t.soonest_min ?? Infinity) <= 30 ? "now" : "soon",
      minutes: t.fire_inside ? 0 : (t.soonest_min ?? 60),
      title: `Evacuate ${t.town}`,
      body: (
        <>
          <Arrival t={t} />{" "}
          {t.exit ? (
            <>
              Leave by {t.exit}
              {t.drive_min != null && <>, about {aboutMinutes(t.drive_min)} drive</>}
              {t.route_status === "risky" && <span className="text-amber-300"> (route at risk)</span>}.
            </>
          ) : null}
        </>
      ),
      actions: (
        <>
          {bus ? (
            <span className="flex h-7 flex-1 items-center justify-center rounded-lg bg-emerald-500/10 text-[11px] text-emerald-300">
              Bus on scene
            </span>
          ) : (
            <Button variant="primary" className="h-7 flex-1" onClick={() => addToken("bus", town.x, town.y, scenario)}>
              Send evac bus
            </Button>
          )}
          {show}
        </>
      ),
    });
  }

  recommendations.forEach((r, i) => {
    decisions.push({
      key: r.id,
      level: "consider",
      minutes: i,
      title: `${r.action === "move" ? "Move a crew" : ORDER_STYLE[r.token_type].verb} ${describeLocation(scenario, r.x, r.y)}`,
      body: <RecBody rec={r} />,
      actions: (
        <>
          <Button
            variant="primary"
            className={`h-7 flex-1 ${r.auto ? "" : "cursor-not-allowed opacity-50"}`}
            title={r.auto ? undefined : "A physical crew on the table: move it there by hand"}
            onClick={r.auto ? () => acceptRecommendation(r.id) : undefined}
          >
            {r.action === "move" ? (r.auto ? "Move crew" : "Move by hand") : "Dispatch"}
          </Button>
          <Button className="h-7" onClick={() => onTryInPlan(r)} title="Add it to a plan and compare it with other options">
            Try in plan
          </Button>
          <Button variant="ghost" className="h-7" onClick={() => onFocus(r.x, r.y)}>
            Show
          </Button>
        </>
      ),
    });
  });

  for (const u of units) {
    if (u.status !== "blocked" && u.status !== "grounded") continue;
    const target = tokens.find((t) => t.id === u.token_id);
    decisions.push({
      key: `unit-${u.id}`,
      level: "info",
      minutes: 0,
      title: u.status === "grounded" ? `${u.station}: tankers grounded` : `${u.id} can't get through`,
      body: (
        <>
          <span style={{ color: UNIT_STATUS[u.status].color }}>{orderText(u)}</span>
          {target && <> for the {TOKEN_STYLE[target.token_type].label.toLowerCase()} order {describeLocation(scenario, target.x, target.y)}</>}.
          {u.status === "blocked" && " Cancel the order or pick a spot a road reaches."}
        </>
      ),
      actions: target ? <ShowToken token={target} onFocus={onFocus} /> : null,
    });
  }

  decisions.sort((a, b) => ORDER.indexOf(a.level) - ORDER.indexOf(b.level) || a.minutes - b.minutes);

  if (decisions.length === 0) {
    return (
      <p className="px-1 py-4 text-center text-[11px] leading-relaxed text-fg-subtle">
        {burning
          ? situation?.forecast_tick == null
            ? "Running the first forecast…"
            : "Nothing needs a decision right now. No town is likely to see fire within the hour."
          : "No active fire."}
      </p>
    );
  }

  return (
    <ol className="space-y-2">
      {decisions.map((d) => (
        <li
          key={d.key}
          className="rounded-lg border border-edge bg-surface-2 p-2.5"
          style={{ borderLeft: `3px solid ${LEVEL[d.level].color}` }}
        >
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: LEVEL[d.level].color }}>
            {LEVEL[d.level].label}
          </div>
          <div className="text-[13px] font-medium leading-snug text-fg">{d.title}</div>
          <p className="mt-1 text-[11px] leading-relaxed text-fg-muted">{d.body}</p>
          {d.actions && <div className="mt-2 flex gap-1.5">{d.actions}</div>}
        </li>
      ))}
    </ol>
  );
}

/** "Fire could reach it in as little as 18 min (likely 25 min)." */
function Arrival({ t }: { t: TownThreat }) {
  if (t.fire_inside) return <span className="text-red-300">Fire is in town now.</span>;
  const w = t.within_60;
  return (
    <>
      {t.soonest_min != null ? <>Fire could arrive in as little as {aboutMinutes(t.soonest_min)}</> : <>Fire may arrive</>}
      {t.median_min != null && <> (likely {aboutMinutes(t.median_min)})</>}
      {w && (
        <>
          ; {w.k} of {w.n} simulations reach it within the hour
        </>
      )}
      .
    </>
  );
}

function RecBody({ rec }: { rec: Recommendation }) {
  return (
    <>
      {rec.station && rec.eta_min != null && (
        <span className="text-fg">
          From {rec.station}, about {aboutMinutes(rec.eta_min)} out.{" "}
        </span>
      )}
      {rec.saves.length > 0 && (
        <>
          Keeps fire out of{" "}
          {rec.saves.map((e, i) => (
            <span key={e.town}>
              {i > 0 && ", "}
              <span className="text-emerald-300">{e.town}</span> in {e.hits} of {e.n} simulations
            </span>
          ))}
          .{" "}
        </>
      )}
      {rec.worsens.length > 0 && (
        <span className="text-red-300">
          Pushes fire toward {rec.worsens.map((e) => e.town).join(", ")} in some simulations.{" "}
        </span>
      )}
      {rec.acres_saved > 0 && <>About {Math.round(rec.acres_saved).toLocaleString()} acres kept from burning in the next hour. </>}
      {rec.confidence !== "high" && <span className="text-amber-300">Rough estimate.</span>}
    </>
  );
}

function ShowToken({ token, onFocus }: { token: Token; onFocus: (x: number, y: number) => void }) {
  return (
    <Button variant="ghost" className="h-7" onClick={() => onFocus(token.x, token.y)}>
      Show
    </Button>
  );
}
