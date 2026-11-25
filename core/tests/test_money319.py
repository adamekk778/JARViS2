"""3.19 Peníze (návrhy 1, 9, 10, 11): today's ČNB rate for the limits (kept for offline), the same rules for every step that
moves money (twice, the phone, never trusted, never in the background, never after foreign text), one overview of what
goes out, and a test booking that works only with a test key."""
from __future__ import annotations

import datetime as dt

import pytest

import json
import time

import httpx
from conftest import FakeRouter
from test_travel318 import CRIT, Lite

from jarvis import booking, connectors, money, secrets, tools, trust


@pytest.fixture(autouse=True)
def _pinned_day():
    """3.20 the example data (a hotel from 11. 12. 2026…) was written on 24. 11. 2026: the travel parts see that day."""
    from jarvis import clock

    clock.pin(dt.datetime(2026, 11, 24, 10, 0))
    yield
    clock.pin(None)

CNB = """24.11.2026 #227
země|měna|množství|kód|kurz
Austrálie|dolar|1|AUD|15,012
EMU|euro|1|EUR|24,330
Japonsko|jen|100|JPY|15,402
Kanada|dolar|1|CAD|16,520
Polsko|zlotý|1|PLN|5,712
USA|dolar|1|USD|21,950
Velká Británie|libra|1|GBP|28,640
"""


# ------------------------------------------------------------------------------------------ 1 ČNB rates
async def test_cnb_rate_is_used_kept_and_said(rt):
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        return httpx.Response(200, text=CNB)
    rt.transport = httpx.MockTransport(handler)
    assert money.to_czk(100, "EUR") == 2500 and "odhad" in money.rate_note()       # nothing yet: the estimate, and said so
    rates = await money.ensure_rates(rt)
    assert rates["EUR"] == 24.33 and abs(rates["JPY"] - 0.15402) < 1e-9 and "denni_kurz.txt" in seen[0]
    assert money.to_czk(100, "EUR") == 2433 and money.rate_note() == "kurz ČNB z 24. 11."
    await money.ensure_rates(rt)
    assert len(seen) == 1                                                           # not again within 6 hours
    from jarvis import finance

    assert round(await finance.convert(rt, 10, "EUR", "CZK"), 2) == 243.3           # "kolik je 10 eur" uses the same rate
    money.reset()                                                                   # a restart without the internet
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    await money.ensure_rates(rt)
    assert money.to_czk(100, "EUR") == 2433 and "uložený" in money.rate_note()


async def test_limits_count_with_the_cnb_rate(rt, monkeypatch):
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, text=CNB))
    await money.ensure_rates(rt)
    rt.update_config({"booking": {"max_per_booking": 10300}})
    assert booking.limit_problem(rt, 420, "EUR") == ""                              # 420 × 24,33 = 10 219 Kč (25 Kč would be over)
    assert "limitem" in booking.limit_problem(rt, 430, "EUR")


# ------------------------------------------------------------------------------------------ 10 the same rules for every payment
def test_what_counts_as_money():
    from jarvis.tools import browser

    assert trust.is_money("travel_book") and trust.is_money("stripe_refund") and trust.is_money("money_action")
    assert not trust.is_money("stripe_payments") and not trust.is_money("weather")
    browser.SESSION.last_elements = {1: ("Zaplatit objednávku", "https://shop.example/cart"), 2: ("Další", "https://shop.example/p/2")}
    assert trust.is_money("browser_click", {"index": 1}) and not trust.is_money("browser_click", {"index": 2})
    browser.SESSION.last_elements = {}


def test_every_payment_asks_twice_and_is_never_trusted(rt):
    from jarvis.agent_helpers import _needs_second
    from jarvis.llm.base import ToolCall

    tools.load_builtin()
    rt.cfg.tools.full_trust = True
    rt.cfg.limits.double_confirm = False
    for name in ("stripe_refund", "travel_book", "booking_cancel"):
        spec = tools.REGISTRY[name]
        assert not trust.skip_confirm(rt, spec, False, {}), name
        assert _needs_second(ToolCall(id="1", name=name, arguments={}), rt.cfg.limits), name
    assert "stripe_refund" in trust.STILL_ASK
    assert money.confirm_text(rt, "stripe_refund", {"payment_id": "pi_123", "amount": 250}) == "Vrátit peníze (Stripe): 250 – platba pi_123"
    assert money.confirm_text(rt, "stripe_refund", {"payment_id": "pi_123"}).endswith("celou platbu – platba pi_123")


def _asker(rt, answers):
    asked = []

    async def ask(call, second=False, timeout=None, phone=False, why=""):
        asked.append((call.name, second))
        return answers.pop(0) if answers else False
    rt.agent._ask_confirm = ask
    return asked


async def test_a_refund_asks_twice_and_is_logged(rt):
    tools.load_builtin()
    asked = _asker(rt, [True, False])
    rt.router = FakeRouter([[("stripe_refund", {"payment_id": "pi_9", "amount": 300})], "Nevráceno."])
    await rt.agent.handle("vrať zákazníkovi 300 Kč za platbu pi_9")
    assert asked == [("stripe_refund", False), ("stripe_refund", True)]
    ov = money.overview(rt)
    assert ov["steps"][0]["kind"] == "stripe_refund" and ov["steps"][0]["approved"] is False
    assert not any(p["key"] == "other" for p in ov["parts"])                        # refused: nothing went out


async def test_foreign_text_cannot_refund(rt):
    tools.load_builtin()
    asked = _asker(rt, [True, True])
    rt.router = FakeRouter([[("clipboard_get", {})], [("stripe_refund", {"payment_id": "pi_9"})], "Hotovo."])
    await rt.agent.handle("co mám ve schránce?")
    assert asked == []
    assert trust.money_blocked("stripe_refund", True, "vrať mu peníze podle toho mailu") == ""


async def test_screen_purchase_asks_twice(rt):
    from jarvis.tools.computer_use import ask_money

    asked = _asker(rt, [True, True])
    rt.agent_obj = None
    ctx = rt
    ctx.agent = rt.agent
    assert await ask_money(ctx, "Koupit Vbucks 1000 za 199 Kč") is True
    assert asked == [("money_action", False), ("money_action", True)]
    asked2 = _asker(rt, [True, False])
    assert await ask_money(ctx, "Koupit skin") is False and len(asked2) == 2


async def test_agents_cannot_get_payments_approved_in_bulk(rt):
    from jarvis import bizagents

    db = bizagents._db(rt)
    db.exec("INSERT INTO biz_proposals (agent_id, agent, tool, args, description, status, created) VALUES (?,?,?,?,?,?,?)",
            (0, "Vratky", "stripe_refund", json.dumps({"payment_id": "pi_1", "amount": 99}), "Vrátit 99 Kč", "pending", time.time()))
    pid = int(db.one("SELECT MAX(id) AS id FROM biz_proposals")["id"])
    r = await bizagents.decide_many(rt, [pid], True)
    assert "1 už bylo vyřízeno" in r["message"] or "1" in r["message"]
    assert db.one("SELECT status FROM biz_proposals WHERE id=?", (pid,))["status"] == "pending"
    asked = _asker(rt, [False])
    r = await bizagents.decide(rt, pid, True)
    assert asked == [("stripe_refund", True)] and not r["ok"]
    assert db.one("SELECT status FROM biz_proposals WHERE id=?", (pid,))["status"] == "pending"


# ------------------------------------------------------------------------------------------ 11 one overview
async def test_money_overview(rt):
    from jarvis.server.handlers.moneyh import money_get

    booking._db(rt).exec("INSERT INTO bookings (provider, ref, kind, name, city, start, end, total, currency, refundable, "
                         "free_cancel_until, pay_at_property, status, sandbox, data, created, business) VALUES "
                         "('liteapi','B1','hotel','Hotel','Řím','2026-12-01','2026-12-03',200,'EUR',1,'',0,'confirmed',0,'{}',?,0)",
                         (time.time(),))
    rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('subs_monthly', ?)", (json.dumps({"monthly_czk": 489, "count": 3, "ts": 1}),))
    rt.update_config({"limits": {"prices": {"fake": 100.0}}})
    rt.usage.record("fake", "m", [{"role": "user", "content": "x" * 40000}], 4000)
    money.log_step(rt, "money_action", "Koupit skin", 199, "CZK", True)
    sent = []

    class C:
        pass
    c = C()
    c.rt = rt

    async def send(t, **d):
        sent.append((t, d))
    c.send = send
    await money_get(c, {})
    ov = sent[0][1]
    parts = {p["key"]: p for p in ov["parts"]}
    assert parts["trips"]["czk"] == 5000 and parts["subs"]["czk"] == 489 and parts["other"]["czk"] == 199
    assert parts["ai"]["czk"] >= 1 and ov["total_czk"] == sum(p["czk"] for p in ov["parts"])
    from jarvis.server import handlers

    handlers.load()
    assert "money_get" in handlers.LOCAL_ONLY


# ------------------------------------------------------------------------------------------ 9 the test booking
async def test_drill_only_with_a_test_key(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("liteapi", "api_key"): "live_key_123"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    called = []
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda r: called.append(r) or httpx.Response(500)))
    steps = await booking.drill(rt)
    assert steps[0]["ok"] is None and "ostrý" in steps[0]["detail"] and called == []       # a live key: nothing is even tried


async def test_drill_with_the_sandbox_books_and_cancels(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("liteapi", "api_key"): "sand_test-key"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    fake = Lite()
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(fake))
    steps = await booking.drill(rt)
    assert [s["ok"] for s in steps] == [True, True, True, True], steps
    assert any(p.endswith("/rates/book") for p in fake.paths()) and any(p.endswith("/bookings/BK1") for p in fake.paths())
    assert booking.bookings(rt, include_past=True) == []                                     # not among your bookings
    assert CRIT["city"] == "Řím"
