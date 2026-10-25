"""Drafted dispatch orders and evacuation alerts (#132)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from commander.drafts import WEA_MAX, DraftDesk, DraftRec, grounded_in, set_known_names
from protocol import DraftAction, TokenType, VirtualTokenAdd
from server import Engine


@pytest.fixture
def engine():
    e = Engine()
    e.sent = []
    import server as srv

    real = srv.broadcast
    srv.broadcast = lambda clients, msg: e.sent.append(msg)
    yield e
    srv.broadcast = real
    e.forecaster.shutdown()
    e.long_forecaster.shutdown()
    e.recommender.shutdown()


def drafts_of(e, kind=None):
    return [d for d in e.drafts.drafts if kind is None or d.kind == kind]


def run(coro):
    return asyncio.run(coro)


def test_sending_a_crew_drafts_its_order(engine):
    async def go():
        engine.fire.ignite(409.3, 118.5)
        engine.virtual.handle(VirtualTokenAdd(token_type=TokenType.CREW, x=200, y=70))
        engine.step_fire()
        await asyncio.sleep(0)
    run(go())
    [d] = drafts_of(engine, "unit_order")
    unit = next(u for u in engine.dispatcher.units if u.status == "en_route")
    assert d.subject == unit.id and d.status == "draft" and d.source == "template"
    assert d.text.startswith(unit.id) and "minutes out" in d.text and "Wind from the" in d.text
    assert grounded_in(d.text, d.facts)
    assert any(json.loads(m).get("type") == "drafts" for m in engine.sent if isinstance(m, str))


def test_evacuation_alert_is_bilingual_short_and_not_duplicated(engine):
    async def go():
        engine.order_evacuation("Paradise", True)
        engine.order_evacuation("Paradise", True)  # a second click changes nothing
        [d] = drafts_of(engine, "evac_alert")
        assert d.text.startswith("EVACUATION ORDER for Paradise") and d.text_es.startswith("ORDEN DE EVACUACIÓN para Paradise")
        assert len(d.text) <= WEA_MAX and len(d.text_es) <= WEA_MAX
        # Cancelled before it went out: the draft is dropped, and there's nothing to take back.
        engine.order_evacuation("Paradise", False)
        assert d.status == "dismissed" and len(drafts_of(engine, "evac_alert")) == 1
        await asyncio.sleep(0)

    run(go())


def test_sending_an_alert_logs_it_and_cancelling_drafts_a_lifted_notice(engine):
    async def go():
        engine.order_evacuation("Magalia", True)
        [d] = drafts_of(engine, "evac_alert")
        engine.draft_action(DraftAction(id=d.id, action="send"))
        assert d.status == "sent" and d.sent_tick == engine.fire.tick
        events = [json.loads(m) for m in engine.sent if isinstance(m, str) and '"events"' in m]
        assert any(ev["kind"] == "draft_sent" and ev["town"] == "Magalia" for m in events for ev in m["events"])
        engine.order_evacuation("Magalia", False)
        lifted = drafts_of(engine, "evac_alert")[-1]
        assert lifted.text.startswith("Evacuation order lifted for Magalia") and lifted.text_es
        await asyncio.sleep(0)

    run(go())


def test_edit_marks_the_operator_and_dismiss_removes_it_from_play(engine):
    async def go():
        d = engine.drafts.briefing(engine)
        engine.draft_action(DraftAction(id=d.id, action="edit", text="All units hold."))
        assert d.text == "All units hold." and d.source == "operator"
        engine.draft_action(DraftAction(id=d.id, action="dismiss"))
        assert d.status == "dismissed"
        engine.draft_action(DraftAction(id=d.id, action="send"))  # too late: already dismissed
        assert d.status == "dismissed"
        await asyncio.sleep(0)

    run(go())


class _Client:
    def __init__(self, text):
        self.messages = SimpleNamespace(create=self._create)
        self.text = text

    async def _create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


def _unit_draft():
    facts = {"unit": "Jarbo Gap Station 36 crew", "station": "Jarbo Gap Station 36", "location": "near Pulga",
             "eta_minutes": 17, "wind_from": "north-east", "wind_m_per_s": 12, "task": "dig in",
             "ember_spotting_likely": True, "escape_route_to": "Chico (Skyway)", "towns_with_no_safe_route": []}
    return DraftRec("d1", "unit_order", facts["unit"], "template", 0, facts)


def test_claude_rewrite_kept_only_when_grounded():
    set_known_names(["Pulga", "Paradise", "Chico (Skyway)", "Jarbo Gap Station 36"])
    desk = DraftDesk()
    good = "Jarbo Gap Station 36 crew, respond near Pulga, 17 minutes out. Wind north-east at 12 m/s; escape toward Chico (Skyway)."
    d = _unit_draft()
    assert run(desk.polish(d, _Client(good), "m")) and d.source == "llm" and d.text == good
    for bad in ("Jarbo Gap Station 36 crew, respond near Pulga, 25 minutes out.",  # invented number
                "Jarbo Gap Station 36 crew, fall back to Paradise."):  # place not in the facts
        d = _unit_draft()
        assert not run(desk.polish(d, _Client(bad), "m")) and d.text == "template"


def test_alerts_are_never_rewritten():
    d = DraftRec("d2", "evac_alert", "Paradise", "EVACUATION ORDER", 0, {"town": "Paradise"}, text_es="ORDEN")
    assert not run(DraftDesk().polish(d, _Client("Something else"), "m"))


def test_switching_scenario_clears_drafts(engine):
    async def go():
        engine.order_evacuation("Paradise", True)
        engine.switch_scenario("marshall")
        assert engine.drafts.drafts == []
        await asyncio.sleep(0)

    run(go())
