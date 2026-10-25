"""Draft dispatch orders and evacuation alerts from the operator's decisions (#132).

When the operator sends a unit or orders a town out, the engine writes the
message that would go to the people acting on it. The operator approves,
edits or dismisses each one. Nothing is delivered anywhere: "send" only marks
it sent and logs it (an Event the decision log picks up).

- unit_order: a radio-style order for a dispatched crew, dozer or tanker:
  where, how soon, the job, the wind and embers, and the way out.
- evac_alert: a public evacuation alert in English and Spanish, short enough
  for a Wireless Emergency Alert (360 characters). Cancelling the order
  dismisses an unsent alert, or drafts a notice that it was lifted.
- briefing: on request, a short situation summary for incoming crews.

Every draft starts as a template filled from engine facts, so it works with
no API key. Unit orders and briefings may then be rewritten by Claude from
the same facts, and the rewrite is kept only if every number in it comes
from those facts and it names no place the facts don't (the grounding
guard). Evacuation alerts stay templated: their wording is a public
instruction and the Spanish must match the English exactly.
"""

import asyncio
import json
import logging
import math
from dataclasses import dataclass, field

from commander.guard import allowed_numbers, ungrounded
from protocol import Draft, Drafts, TokenType
from sim.fire import SIM_MINUTES_PER_TICK, SPOT_MIN_WIND

log = logging.getLogger("drafts")

WEA_MAX = 360  # characters, Wireless Emergency Alert long form
POLISH_TIMEOUT_S = 8.0
TASKS = {
    TokenType.CREW: "dig in and hold the fire's flank there",
    TokenType.FIREBREAK: "cut a dozer line there",
    TokenType.WATER: "drop on the fire there",
}
_COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]

POLISH_SYSTEM = """You turn facts about a wildfire dispatch into a short radio-style order for the crew.
Use only the facts given: every number and every place name must appear in them. Do not add advice, \
estimates or places of your own. Leave out facts that are false, null or empty (say nothing about \
embers if spotting isn't likely). Two or three plain sentences, no lists or markdown. Start with the unit's name."""


def compass(from_deg: float) -> str:
    return _COMPASS[int(((from_deg % 360) + 22.5) // 45) % 8]


@dataclass
class DraftRec:
    id: str
    kind: str  # unit_order | evac_alert | briefing
    subject: str  # unit id or town
    text: str
    tick: int
    facts: dict
    text_es: str | None = None
    status: str = "draft"  # draft | sent | dismissed
    source: str = "template"  # template | llm | operator
    grounded: bool = True
    sent_tick: int | None = None

    def model(self) -> Draft:
        return Draft(id=self.id, kind=self.kind, subject=self.subject, status=self.status, text=self.text,
                     text_es=self.text_es, source=self.source, grounded=self.grounded, tick=self.tick,
                     sent_tick=self.sent_tick)


@dataclass
class DraftDesk:
    drafts: list[DraftRec] = field(default_factory=list)
    _n: int = 0

    def _add(self, d: DraftRec) -> DraftRec:
        self.drafts.append(d)
        self.drafts = self.drafts[-30:]  # keep the panel short
        return d

    def _id(self) -> str:
        self._n += 1
        return f"d{self._n}"

    def clear(self) -> None:
        self.drafts.clear()

    def message(self, tick: int) -> str:
        return Drafts(tick=tick, drafts=[d.model() for d in self.drafts]).model_dump_json()

    # --- triggers -----------------------------------------------------------------

    def unit_order(self, engine, unit) -> DraftRec:
        """A unit was just sent (or redirected). Replaces its unsent order."""
        facts = unit_facts(engine, unit)
        for d in self.drafts:
            if d.kind == "unit_order" and d.subject == unit.id and d.status == "draft":
                d.status = "dismissed"  # superseded by the new trip
        return self._add(DraftRec(self._id(), "unit_order", unit.id, unit_template(facts), engine.fire.tick, facts))

    def evacuation(self, engine, town: str, ordered: bool) -> DraftRec | None:
        """A town was ordered out, or the order was taken back."""
        if ordered:
            facts = evac_facts(engine, town)
            en, es = evac_templates(facts)
            return self._add(DraftRec(self._id(), "evac_alert", town, en, engine.fire.tick, facts, text_es=es))
        sent_before = False
        for d in self.drafts:
            if d.kind == "evac_alert" and d.subject == town:
                if d.status == "draft":
                    d.status = "dismissed"  # never went out; nothing to take back
                elif d.status == "sent":
                    sent_before = True
        if not sent_before:
            return None
        en = f"Evacuation order lifted for {town}. Follow official instructions before returning."
        es = f"Se levanta la orden de evacuación para {town}. Siga las instrucciones oficiales antes de regresar."
        return self._add(DraftRec(self._id(), "evac_alert", town, en, engine.fire.tick, {"town": town}, text_es=es))

    def briefing(self, engine) -> DraftRec:
        facts = briefing_facts(engine)
        return self._add(DraftRec(self._id(), "briefing", "situation", briefing_template(facts), engine.fire.tick, facts))

    # --- operator actions ---------------------------------------------------------

    def act(self, draft_id: str, action: str, text: str | None, tick: int) -> DraftRec | None:
        """Apply send / dismiss / edit. Returns the draft if it was just sent."""
        d = next((d for d in self.drafts if d.id == draft_id), None)
        if d is None or d.status != "draft":
            return None
        if action == "edit" and text and text.strip():
            d.text, d.source = text.strip()[: 4 * WEA_MAX], "operator"
            if d.kind == "evac_alert":
                d.text_es = None  # the Spanish no longer matches; the operator writes their own
        elif action == "dismiss":
            d.status = "dismissed"
        elif action == "send":
            d.status, d.sent_tick = "sent", tick
            return d
        return None

    # --- Claude rewrite -----------------------------------------------------------

    async def polish(self, d: DraftRec, client, model: str) -> bool:
        """Rewrite a unit order or briefing with Claude from its facts. Keeps
        the template unless the rewrite is grounded. Returns True if kept."""
        if client is None or d.kind == "evac_alert" or d.status != "draft" or d.source != "template":
            return False
        try:
            msg = await asyncio.wait_for(client.messages.create(
                model=model, max_tokens=1000, system=POLISH_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(d.facts)}],
                output_config={"effort": "low"},
            ), POLISH_TIMEOUT_S)
            if getattr(msg, "stop_reason", "end_turn") != "end_turn":
                return False  # cut off (out of tokens) or refused: half an order is worse than the template
            text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "text") == "text").strip()
        except Exception as e:  # no network, timeout, refusal: the template stands
            log.info("draft polish failed: %r", e)
            return False
        if not text or not grounded_in(text, d.facts) or d.status != "draft" or d.source != "template":
            return False
        d.text, d.source = text, "llm"
        return True


# --- facts and templates ------------------------------------------------------------


def describe_xy(engine, x: float, y: float) -> str:
    """'near Pulga' within ~4.7 km of a named place, else 'in the north-east
    of the map'. Reads after a verb: 'respond near Pulga'."""
    named = list(engine.tools.places.values())
    if named:
        px, py, name = min(named, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        if (px - x) ** 2 + (py - y) ** 2 <= 50**2:
            return f"near {name}"
    w, h = engine.scenario.width, engine.scenario.height
    ns = "north" if y < h / 3 else "south" if y > 2 * h / 3 else ""
    ew = "west" if x < w / 3 else "east" if x > 2 * w / 3 else ""
    return f"in the {ns}-{ew} of the map" if ns and ew else f"in the {ns or ew or 'middle'} of the map"


def _nearest_town(engine, x: float, y: float) -> str | None:
    if not engine.towns:
        return None
    return min(engine.towns, key=lambda t: (t.x - x) ** 2 + (t.y - y) ** 2).name


def _route_for(engine, town: str | None):
    return next((r for r in engine.routes if r.town == town and r.bus is None), None)


def unit_facts(engine, unit) -> dict:
    x, y = unit.target
    w = engine.fire.wind
    eta = max(0.0, (unit.arrive_tick - engine.fire.tick) * SIM_MINUTES_PER_TICK)
    town = _nearest_town(engine, x, y)
    route = _route_for(engine, town)
    cut = sorted({r.town for r in engine.routes if r.status == "cut" and r.bus is None})
    return {
        "unit": unit.id,
        "station": unit.station.name,
        "task": TASKS.get(unit.token_type, "respond"),
        "location": describe_xy(engine, x, y),
        "eta_minutes": int(math.ceil(eta)),
        "wind_from": compass(w.from_deg),
        "wind_m_per_s": round(w.speed_ms),
        "ember_spotting_likely": w.speed_ms >= SPOT_MIN_WIND,
        "escape_route_to": None if route is None or route.status == "cut" else route.safe_zone,
        "towns_with_no_safe_route": cut,
    }


def unit_template(f: dict) -> str:
    parts = [f"{f['unit']}: respond {f['location']}, about {f['eta_minutes']} minutes out. Task: {f['task']}."]
    wind = f"Wind from the {f['wind_from']} at {f['wind_m_per_s']} m/s"
    parts.append(wind + (", ember spotting likely ahead of the front." if f["ember_spotting_likely"] else "."))
    if f["escape_route_to"]:
        parts.append(f"Escape route: toward {f['escape_route_to']}.")
    if f["towns_with_no_safe_route"]:
        parts.append(f"No safe route out of {', '.join(f['towns_with_no_safe_route'])}.")
    return " ".join(parts)


def evac_facts(engine, town: str) -> dict:
    route = _route_for(engine, town)
    threat = next((t for t in engine.tools.town_threats() if t.town == town), None)
    return {
        "town": town,
        "safe_zone": None if route is None or route.status == "cut" else route.safe_zone,
        "fire_in_town": bool(threat and threat.fire_inside),
        "eta_lo_min": None if threat is None else threat.eta_lo_min,
        "eta_hi_min": None if threat is None else threat.eta_hi_min,
    }


def _split_zone(zone: str) -> tuple[str, str | None]:
    """'Chico (Skyway)' -> ('Chico', 'Skyway')."""
    if zone.endswith(")") and "(" in zone:
        name, road = zone[:-1].split("(", 1)
        return name.strip(), road.strip()
    return zone, None


def evac_templates(f: dict) -> tuple[str, str]:
    town = f["town"]
    if f["safe_zone"]:
        place, road = _split_zone(f["safe_zone"])
        go_en = f"Leave now{f' by {road}' if road else ''} toward {place}."
        go_es = f"Salga ahora{f' por {road}' if road else ''} hacia {place}."
    else:
        go_en = "Leave now by the safest open road. Follow officers' directions."
        go_es = "Salga ahora por la vía abierta más segura. Siga las indicaciones de los oficiales."
    if f["fire_in_town"]:
        when_en, when_es = "Fire is in the area.", "Hay fuego en la zona."
    elif f["eta_lo_min"] is not None:
        lo = int(f["eta_lo_min"])
        when_en, when_es = f"Fire could arrive within {lo} minutes.", f"El fuego podría llegar en {lo} minutos."
    else:
        when_en = when_es = ""
    en = f"EVACUATION ORDER for {town}: wildfire. {go_en} {when_en} Do not wait.".replace("  ", " ").strip()
    es = f"ORDEN DE EVACUACIÓN para {town}: incendio forestal. {go_es} {when_es} No espere.".replace("  ", " ").strip()
    return en[:WEA_MAX], es[:WEA_MAX]


def briefing_facts(engine) -> dict:
    burning, burned = engine.fire.counts()
    acres_per_cell = engine.tools.acres_per_cell
    threats = []
    for t in engine.tools.town_threats():
        if t.fire_inside:
            threats.append({"town": t.town, "fire_in_town": True})
        elif t.eta_lo_min is not None or t.soonest_min is not None:
            threats.append({"town": t.town, "fire_could_arrive_in_min": round(t.eta_lo_min if t.eta_lo_min is not None else t.soonest_min)})
    units = [{"unit": u.id, "status": u.status} for u in engine.dispatcher.units if u.status in ("en_route", "working")]
    w = engine.fire.wind
    return {
        "minutes_since_start": int(engine.fire.tick * SIM_MINUTES_PER_TICK),
        "acres_burned": round((burning + burned) * acres_per_cell),
        "wind_from": compass(w.from_deg),
        "wind_m_per_s": round(w.speed_ms),
        "threatened_towns": threats[:4],
        "units_committed": units[:6],
        "towns_ordered_out": sorted(engine.evac_orders),
    }


def briefing_template(f: dict) -> str:
    parts = [f"Situation at {f['minutes_since_start']} minutes: about {f['acres_burned']} acres burned, "
             f"wind from the {f['wind_from']} at {f['wind_m_per_s']} m/s."]
    for t in f["threatened_towns"]:
        if t.get("fire_in_town"):
            parts.append(f"Fire is in {t['town']}.")
        else:
            parts.append(f"{t['town']}: fire could arrive in {t['fire_could_arrive_in_min']} minutes.")
    if f["units_committed"]:
        parts.append(f"{len(f['units_committed'])} units committed.")
    if f["towns_ordered_out"]:
        parts.append(f"Ordered out: {', '.join(f['towns_ordered_out'])}.")
    return " ".join(parts)


def grounded_in(text: str, facts: dict) -> bool:
    """Every number in `text` comes from `facts`, and it mentions no known
    place, town or station that the facts don't."""
    if ungrounded(text, allowed_numbers([facts])):
        return False
    blob = json.dumps(facts)
    return all(name in blob for name in _known_names() if name in text)


_NAMES: list[str] = []


def set_known_names(names: list[str]) -> None:
    """Place, town and station names for the rewrite check (set per scenario)."""
    _NAMES[:] = sorted({n for n in names if n}, key=len, reverse=True)


def _known_names() -> list[str]:
    return _NAMES
