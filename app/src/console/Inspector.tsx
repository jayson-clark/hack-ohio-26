// Details for whatever is selected (#130): a town (fire arrival, evacuation
// clock, way out), a recommendation (what it buys, with ranges), or an order
// (its unit and status). Opens beside the map; the actions live here too.

import type { ReactNode } from "react";
import { orderText, recButton, recVerb, unitFor } from "../shared/dispatch";
import { acceptRecommendation, orderEvacuation, relieveOrder, useEngine } from "../shared/engine";
import { aboutMinutes, describeLocation } from "../shared/places";
import type { KofN, Recommendation, Token, TownEffect } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE } from "../shared/tokens";
import { addToken, removeToken } from "../shared/virtualTokens";
import { Icon } from "./icons";
import { EVAC, findRec, minutesUntil, ORDER_COLOR, ORDER_ICON, type Selection, type TownView } from "./model";
import { Badge, Button, IconButton, Label, Meter, TONE, type Tone } from "./ui";

interface Props {
  scenario: Scenario;
  towns: TownView[];
  selection: NonNullable<Selection>;
  onClose: () => void;
  onFocus: (x: number, y: number) => void;
  onTryInPlan: (rec: Recommendation) => void;
}

export default function Inspector(props: Props) {
  const { recommendations, tokens } = useEngine();
  const s = props.selection;
  let body: ReactNode = null;
  if (s.kind === "town") {
    const t = props.towns.find((x) => x.name === s.name);
    if (t) body = <TownDetail town={t} scenario={props.scenario} onClose={props.onClose} onFocus={props.onFocus} />;
  } else if (s.kind === "rec") {
    const r = findRec(recommendations, s);
    const rank = r ? recommendations.indexOf(r) + 1 : 0;
    if (r) body = <RecDetail rec={r} rank={rank} {...props} />;
  } else {
    const t = tokens.find((x) => x.id === s.id);
    if (t) body = <OrderDetail token={t} {...props} />;
  }
  if (!body) body = <Gone onClose={props.onClose} />;
  return <aside className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-line bg-panel">{body}</aside>;
}

function Header({ eyebrow, title, badge, onClose, onFocus }: { eyebrow: string; title: string; badge?: ReactNode; onClose: () => void; onFocus?: () => void }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-panel px-4 pb-3 pt-3.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-medium text-ink-3">{eyebrow}</div>
          <h2 className="mt-0.5 text-[17px] font-semibold leading-snug text-ink">{title}</h2>
        </div>
        {onFocus && <IconButton icon="target" title="Center on map" onClick={onFocus} />}
        <IconButton icon="close" title="Close" onClick={onClose} />
      </div>
      {badge && <div className="mt-2 flex flex-wrap gap-1.5">{badge}</div>}
    </header>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-4 py-4 last:border-b-0">
      <h3 className="mb-2.5 text-xs font-semibold text-ink">{title}</h3>
      {children}
    </section>
  );
}

function Fact({ label, value, tone }: { label: string; value: ReactNode; tone?: Tone }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className={`mt-0.5 text-[15px] font-semibold tnum ${tone ? TONE[tone].text : "text-ink"}`}>{value}</div>
    </div>
  );
}

function Chance({ label, c, tone }: { label: string; c: KofN; tone: Tone }) {
  const p = c.k / Math.max(1, c.n);
  return (
    <div title={`${c.k} of ${c.n} simulations; likely ${Math.round(c.lo * 100)}–${Math.round(c.hi * 100)}%`}>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink-2">{label}</span>
        <span className="font-medium text-ink tnum">
          {Math.round(p * 100)}% <span className="font-normal text-ink-3">({c.k}/{c.n})</span>
        </span>
      </div>
      <Meter value={p} lo={c.lo} hi={c.hi} tone={tone} />
    </div>
  );
}

function TownDetail({ town: t, scenario, onClose, onFocus }: { town: TownView; scenario: Scenario; onClose: () => void; onFocus: (x: number, y: number) => void }) {
  const { hello, score, tokens } = useEngine();
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const now = score?.tick ?? 0;
  const th = t.threat;
  const e = t.evac;
  const meterTone: Tone = t.tone === "neutral" || t.tone === "ok" ? "warn" : t.tone;
  const bus = tokens.find((k) => k.token_type === "bus" && Math.hypot(k.x - t.x, k.y - t.y) <= t.radius);

  return (
    <>
      <Header eyebrow="Town" title={t.name} badge={<Badge tone={t.tone} dot>{t.status}</Badge>} onClose={onClose} onFocus={() => onFocus(t.x, t.y)} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-line px-4 py-4">
        <Fact label="Residents" value={t.population.toLocaleString()} />
        <Fact label="Structures" value={t.structures.toLocaleString()} />
        <Fact
          label="Fire could arrive"
          tone={t.tone === "neutral" ? undefined : t.tone}
          value={
            th?.fire_inside
              ? "In town now"
              : th?.eta_lo_min != null && th.eta_hi_min != null
                ? `${aboutMinutes(th.eta_lo_min)}–${aboutMinutes(th.eta_hi_min)} (90%)`
                : th?.soonest_min != null
                  ? `${aboutMinutes(th.soonest_min)}`
                  : "Not within 1 h"
          }
        />
        <Fact label="Likely arrival" value={th?.median_min != null ? aboutMinutes(th.median_min) : "—"} />
      </div>

      {th?.within_30 && th.within_60 && (
        <Block title="Chance fire reaches it">
          <div className="space-y-3">
            <Chance label="Within 30 minutes" c={th.within_30} tone={meterTone} />
            <Chance label="Within 1 hour" c={th.within_60} tone={meterTone} />
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-ink-3">Share of the forecast's simulations; the faint band is the 90% range.</p>
        </Block>
      )}

      {e && (
        <Block title="Evacuation">
          <EvacSummary t={t} now={now} perTick={perTick} />
          <div className="mt-3 flex gap-2">
            {e.status === "clear" ? null : e.ordered_tick === null ? (
              <Button variant={EVAC[e.status].tone === "crit" ? "primary" : "secondary"} className="flex-1" icon="users" onClick={() => orderEvacuation(t.name, true)}>
                Order evacuation
              </Button>
            ) : (
              <Button className="flex-1" onClick={() => orderEvacuation(t.name, false)}>
                Cancel evacuation order
              </Button>
            )}
          </div>
        </Block>
      )}

      <Block title="Way out">
        {th?.route_status ? (
          <div className="flex items-start gap-3">
            <span className={`mt-0.5 flex h-7 w-7 items-center justify-center rounded-full ${TONE[th.route_status === "clear" ? "ok" : th.route_status === "risky" ? "warn" : "crit"].soft}`}>
              <Icon name="route" size={15} className={TONE[th.route_status === "clear" ? "ok" : th.route_status === "risky" ? "warn" : "crit"].text} />
            </span>
            <div className="text-xs leading-relaxed text-ink-2">
              <div className="text-[13px] font-medium text-ink">
                {th.exit ?? "No safe exit"}
                {th.drive_min != null && <span className="font-normal text-ink-2"> · {aboutMinutes(th.drive_min)} drive</span>}
              </div>
              {th.route_status === "clear" && "Open and expected to stay open."}
              {th.route_status === "risky" && "Open now, but the fire may reach it before traffic clears."}
              {th.route_status === "cut" && "Cut. No exit is expected to stay open long enough."}
            </div>
          </div>
        ) : (
          <p className="text-xs text-ink-3">No road data for this scenario.</p>
        )}
        {!e && th?.route_status && th.route_status !== "cut" && (
          <div className="mt-3">
            {bus ? (
              <Badge tone="ok">Evacuation bus on scene</Badge>
            ) : (
              <Button className="w-full" icon="bus" onClick={() => addToken("bus", t.x, t.y, scenario)}>
                Send an evacuation bus
              </Button>
            )}
          </div>
        )}
      </Block>
    </>
  );
}

function EvacSummary({ t, now, perTick }: { t: TownView; now: number; perTick: number }) {
  const e = t.evac!;
  const left = minutesUntil(e.order_by_tick, now, perTick);
  const out = minutesUntil(e.last_car_out_tick, now, perTick);
  const need = e.clearance_min === null ? null : e.mobilize_min + e.clearance_min;
  let headline: string;
  if (e.status === "clear") headline = "Everyone is out.";
  else if (e.status === "trapped") headline = "No open way out. Shelter in place or at a refuge.";
  else if (e.ordered_tick !== null) headline = `Ordered. ${e.people.toLocaleString()} still in town${out !== null ? `, last car out in ${aboutMinutes(out)}` : ""}.`;
  else if (left === null) headline = "Waiting for the long forecast.";
  else if (left > 0) headline = `Order within ${aboutMinutes(left)}${e.order_by_bound ? " or more" : ""}.`;
  else headline = `${aboutMinutes(-left)} past the latest safe order time.`;
  const pTone: Tone = e.p_safe >= 0.9 ? "ok" : e.p_safe >= 0.5 ? "warn" : "crit";
  return (
    <div className="space-y-3">
      <p className={`text-[13px] font-medium ${TONE[EVAC[e.status].tone === "neutral" ? "neutral" : EVAC[e.status].tone].text}`}>{headline}</p>
      <div className="grid grid-cols-2 gap-3">
        <Fact label="People to move" value={e.people.toLocaleString()} />
        <Fact label="Time to get out" value={need !== null ? aboutMinutes(need) : "—"} />
      </div>
      {e.n > 0 && e.people > 0 && e.status !== "trapped" && (
        <div title={`Likely ${Math.round(e.p_safe_lo * 100)}–${Math.round(e.p_safe_hi * 100)}%`}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-ink-2">{e.ordered_tick === null ? "If ordered now, last car out before fire" : "Last car out before fire"}</span>
            <span className={`font-medium tnum ${TONE[pTone].text}`}>
              {e.p_safe_bound ? "≤" : ""}
              {Math.round(e.p_safe * 100)}%
            </span>
          </div>
          <Meter value={e.p_safe} lo={e.p_safe_lo} hi={e.p_safe_hi} tone={pTone} />
        </div>
      )}
      {e.exits.length > 0 && (
        <ul className="space-y-1 text-xs text-ink-2">
          {e.exits.map((x) => (
            <li key={x.safe_zone} className="flex justify-between">
              <span>{x.safe_zone}</span>
              <span className="text-ink-3 tnum">
                {Math.round(x.share * 100)}% of traffic · {aboutMinutes(x.drive_min)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {e.shares_with.length > 0 && <p className="text-xs text-warn">Shares exit roads with {e.shares_with.join(", ")}, so ordering them slows this town.</p>}
    </div>
  );
}

function RecDetail({ rec, rank, scenario, onClose, onFocus, onTryInPlan }: Props & { rec: Recommendation; rank: number }) {
  return (
    <>
      <Header
        eyebrow={`Recommendation ${rank}`}
        title={`${recVerb(rec)} ${describeLocation(scenario, rec.x, rec.y)}`}
        badge={
          <>
            <Badge tone="info">{rec.confidence === "high" ? "High confidence" : "Rough estimate"}</Badge>
            {rec.station && <Badge>{rec.station}</Badge>}
          </>
        }
        onClose={onClose}
        onFocus={() => onFocus(rec.x, rec.y)}
      />
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-line px-4 py-4">
        <Fact label="Arrives in" value={rec.eta_min != null ? aboutMinutes(rec.eta_min) : "Now"} />
        <Fact label="Acres kept (1 h)" value={Math.round(rec.acres_saved).toLocaleString()} tone="ok" />
      </div>
      <Block title="What it buys">
        {rec.saves.length === 0 && rec.worsens.length === 0 ? (
          <p className="text-xs leading-relaxed text-ink-2">It slows the fire overall without changing which towns it reaches in the next hour.</p>
        ) : (
          <div className="space-y-3">
            {rec.saves.map((e) => (
              <Effect key={`s${e.town}`} e={e} good />
            ))}
            {rec.worsens.map((e) => (
              <Effect key={`w${e.town}`} e={e} good={false} />
            ))}
          </div>
        )}
        <p className="mt-3 text-[11px] leading-relaxed text-ink-3">
          From paired simulations with and without the crew. Shown only when it helps even at the low end of its range.
        </p>
      </Block>
      <div className="flex gap-2 px-4 py-4">
        <Button variant="primary" className="flex-1" disabled={!rec.auto} onClick={() => { acceptRecommendation(rec.id); onClose(); }}>
          {recButton(rec)}
        </Button>
        <Button onClick={() => onTryInPlan(rec)}>Try in plan</Button>
      </div>
    </>
  );
}

function Effect({ e, good }: { e: TownEffect; good: boolean }) {
  const tone: Tone = good ? "ok" : "crit";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink">{good ? `Keeps fire out of ${e.town}` : `Pushes fire into ${e.town}`}</span>
        <span className="text-ink-3 tnum">
          {e.hits}/{e.n} sims
        </span>
      </div>
      <Meter value={e.hits / Math.max(1, e.n)} lo={e.lo} hi={e.hi} tone={tone} />
    </div>
  );
}

function OrderDetail({ token: t, scenario, onClose, onFocus }: Props & { token: Token }) {
  const { units } = useEngine();
  const u = unitFor(t, units);
  return (
    <>
      <Header
        eyebrow="Order"
        title={`${ORDER_STYLE[t.token_type].label} ${describeLocation(scenario, t.x, t.y)}`}
        badge={t.source === "vision" ? <Badge>Placed on the table</Badge> : undefined}
        onClose={onClose}
        onFocus={() => onFocus(t.x, t.y)}
      />
      <Block title="Unit">
        <div className="flex items-start gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-md border-2" style={{ borderColor: ORDER_COLOR[t.token_type], color: ORDER_COLOR[t.token_type] }}>
            <Icon name={ORDER_ICON[t.token_type]} size={15} />
          </span>
          <div className="text-xs leading-relaxed text-ink-2">
            {u ? (
              <>
                <div className="text-[13px] font-medium text-ink">{u.id}</div>
                {orderText(u)}
                {u.status === "working" && u.token_type === "crew" && (
                  <div className="mt-2">
                    <Meter value={1 - u.fatigue} tone={u.fatigue > 0 ? "warn" : "ok"} />
                    <div className="mt-1 text-[11px] text-ink-3">
                      {u.fatigue > 0 ? "Past its shift: send a fresh crew to take over the line." : "Fresh: full strength for its first 4 h on the line."}
                    </div>
                  </div>
                )}
              </>
            ) : t.token_type === "bus" ? (
              "Picking up residents."
            ) : units.length ? (
              "Waiting for a free unit (units are assigned while the fire runs)."
            ) : (
              "Acting now."
            )}
          </div>
        </div>
      </Block>
      {u?.status === "working" && t.token_type === "crew" && (
        <div className="px-4 pt-4">
          <Button
            className="w-full"
            disabled={!units.some((x) => x.token_type === "crew" && x.status === "available")}
            title="The tired crew keeps working until the fresh one arrives, then rests"
            onClick={() => relieveOrder(t.id)}
          >
            Relieve crew
          </Button>
        </div>
      )}
      {t.source === "virtual" && (
        <div className="px-4 py-4">
          <Button variant="danger" className="w-full" onClick={() => { removeToken(t.id); onClose(); }}>
            Cancel order
          </Button>
        </div>
      )}
    </>
  );
}

function Gone({ onClose }: { onClose: () => void }) {
  return (
    <>
      <Header eyebrow="" title="No longer available" onClose={onClose} />
      <p className="px-4 py-4 text-xs text-ink-3">This item was replaced by newer information.</p>
    </>
  );
}
