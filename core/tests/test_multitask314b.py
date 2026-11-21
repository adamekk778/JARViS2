"""3.14 Multitasking 2: zkušební obchodování, a watcher's chart, messages to working agents, ready-made teams, the AI
use (and slowing down at a limit), the results file, money approved from the phone, agents on a schedule, the monitor
test, the morning news by your interests."""
import asyncio
import io
import json
from pathlib import Path

import pytest
from conftest import FakeRouter, drain

from jarvis import multitask, papertrade, tools
from jarvis.multitask import Multitask

TWO = [{"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
       {"index": 2, "left": -1280, "top": 0, "width": 1280, "height": 1024, "primary": False}]


def two_monitors(rt, monkeypatch):
    monkeypatch.setattr(rt.platform, "monitors", lambda: [dict(m) for m in TWO], raising=False)


async def wait_done(s, limit=10.0):
    for _ in range(int(limit / 0.02)):
        if s.state != "running":
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"still running: {[w.state for w in s.workers]}")


# ---------------------------------------------------------------- the play wallet
def test_the_play_wallet_buys_sells_and_counts_profit(rt):
    pt = papertrade.of(rt)
    pt.reset(10000)
    t = pt.trade("buy", "btc", "2 000 000 Kč", czk=1000)
    assert t["symbol"] == "BTC" and abs(t["qty"] - 0.0005) < 1e-9 and pt.summary()["cash"] == 9000
    pt.mark("BTC", 2_200_000)                                   # the price went up 10 %
    s = pt.summary()
    assert s["value"] == 10100 and s["pl"] == 100 and s["pl_pct"] == 1.0 and s["positions"][0]["pl"] == 100
    pt.trade("prodat", "BTC", 2_200_000)                       # sell everything
    s = pt.summary()
    assert s["cash"] == 10100 and not s["positions"] and s["count"] == 2 and "+100 Kč" in pt.describe()
    with pytest.raises(ValueError, match="nestačí"):
        pt.trade("buy", "BTC", 1000, czk=50000)
    with pytest.raises(ValueError, match="nemáš"):
        pt.trade("sell", "ETH", 1000)
    with pytest.raises(ValueError, match="cena"):
        pt.trade("buy", "BTC", 0, czk=10)
    assert papertrade._num("1 234,5") == 1234.5 and papertrade._num("2,012,400") == 2012400


async def test_in_the_trial_mode_the_driver_writes_trades_and_never_clicks_buy(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    papertrade.of(rt).reset(10000)
    rt.router = FakeRouter(['{"action":"click","x":10,"y":10,"why":"kliknu na Koupit"}',
                            '{"action":"paper","side":"buy","symbol":"BTC","czk":2000,"price":2000000}',
                            '{"action":"done","summary":"nakoupeno zkušebně"}', "s"])
    seen = []
    q = rt.bus.subscribe()
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Obchodník", "kind": "screen", "task": "kup BTC", "monitor": 1}], paper=True)
    await wait_done(s)
    seen = [e for e in drain(q) if e["type"] == "confirm_request"]
    assert not seen                                              # nothing to approve: no real money
    assert not [c for c in rt.platform.calls if c[0] == "click"]
    sm = papertrade.of(rt).summary()
    assert sm["cash"] == 8000 and sm["positions"][0]["symbol"] == "BTC"
    assert any("zkušební obchod" in t for _ts, _w, t in s.notes)
    assert "ZKUŠEBNÍ REŽIM" in rt.router.calls[0]["messages"][0]["content"]


async def test_the_watcher_draws_its_values_and_values_the_wallet(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    monkeypatch.setattr(multitask, "WATCH_MIN_S", 0.01)
    rt.cfg.multitask.watch_every_s = 0
    papertrade.of(rt).reset(10000)
    papertrade.of(rt).trade("buy", "BTC", 2_000_000, czk=1000)
    looks = [json.dumps({"values": f"BTC {p}", "verdict": v, "number": p, "symbol": "BTC", "alert": False})
             for p, v in ((2_000_000, "počkat"), (2_100_000, "vyplatí se"), (2_200_000, "vyplatí se"))]
    rt.router = FakeRouter(looks + [looks[-1]] * 40)
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Analytik", "kind": "watch", "task": "sleduj BTC", "monitor": 2, "minutes": 5}], paper=True)
    for _ in range(300):
        if len(s.workers[0].series) >= 3:
            break
        await asyncio.sleep(0.01)
    mt.stop(s.id)
    await wait_done(s)
    sr = s.workers[0].series
    assert [p[1] for p in sr[:3]] == [2_000_000, 2_100_000, 2_200_000] and sr[1][2] == "vyplatí se"
    assert papertrade.of(rt).summary()["positions"][0]["price"] == 2_200_000      # valued at what the analyst saw
    st = mt.state()
    assert st["paper"]["pl"] == 100 and st["sessions"][0]["workers"][0]["series"]


# ---------------------------------------------------------------- talking to a working agent
async def test_a_working_agent_gets_your_message(rt):
    gate = asyncio.Event()

    class Router:
        last_used = ("fake", "fake")

        def __init__(self):
            self.calls = []

        async def stream(self, messages, tools=None, **kw):
            from jarvis.llm.base import Chunk, ToolCall

            self.calls.append(json.loads(json.dumps(messages, default=str)))
            if len(self.calls) == 1:
                await gate.wait()
                yield Chunk(tool_calls=[ToolCall(id="c1", name="get_time", arguments={})], done=True)
            else:
                yield Chunk(text="Sleduji i ETH.")
                yield Chunk(done=True)

        async def complete(self, messages, **kw):
            return "shrnutí"
    rt.router = Router()
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Analytik", "task": "sleduj BTC"}])
    await asyncio.sleep(0.05)
    w = mt.tell("", "analytik", "sleduj i ETH")
    assert w is not None and w.orders == ["sleduj i ETH"] and any("→ Analytik: sleduj i ETH" in t for _a, _b, t in s.notes)
    gate.set()
    await wait_done(s)
    assert any("Uživatel ti teď napsal: sleduj i ETH" in str(m.get("content")) for m in rt.router.calls[1])
    assert mt.tell("", "analytik", "už nic") is None                 # it has finished


async def test_the_driver_reads_your_orders(rt, monkeypatch):
    from jarvis.tools.computer_use import run_computer_task

    rt.router = FakeRouter(['{"action":"done","summary":"ok"}'])
    await run_computer_task(rt, "obchoduj", orders=lambda: ["kupuj jen pod 2 miliony"])
    text = rt.router.calls[0]["messages"][1]["content"][0]["text"]
    assert "Uživatel ti během práce napsal" in text and "kupuj jen pod 2 miliony" in text


# ---------------------------------------------------------------- ready-made teams
async def test_the_trading_desk_team(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    rt.router = FakeRouter(['{"action":"wait","seconds":0.01}'] * 3 + ["x"] * 20)
    mt = Multitask(rt)
    s = await mt.start_preset("obchodni_stul", "BTC na Binance")
    try:
        kinds = [(w.name, w.kind, w.monitor) for w in s.workers]
        assert kinds == [("Obchodník", "screen", 1), ("Analytik", "watch", 2), ("Zprávy", "work", 0)]
        assert s.paper and s.preset == "obchodni_stul" and "BTC na Binance" in s.workers[0].task
    finally:
        mt.stop(s.id)
        await wait_done(s)
    with pytest.raises(ValueError, match="potřebuje"):
        await mt.start_preset("vyzkum", "")
    with pytest.raises(ValueError, match="Neznámá"):
        await mt.start_preset("nic", "x")


async def test_the_research_team_is_split_by_the_coordinator(rt):
    plan = [{"name": f"Otázka {i}", "kind": "work", "task": f"zjisti {i}"} for i in range(20)]
    rt.router = FakeRouter([json.dumps(plan, ensure_ascii=False)] + ["hotovo"] * 30)
    mt = Multitask(rt)
    s = await mt.start_preset("vyzkum", "elektroauta")
    assert len(s.workers) == 20 and "nejvýš 20 agentů" in rt.router.calls[0]["messages"][0]["content"]
    await wait_done(s)


# ---------------------------------------------------------------- the AI use, slowing down at a limit
async def test_the_ai_use_is_counted_and_a_limit_slows_down(rt):
    class Router:
        last_used = ("openrouter", "gpt-5-mini")

        def __init__(self):
            self.n = 0

        async def stream(self, messages, tools=None, **kw):
            from jarvis.llm.base import Chunk

            self.n += 1
            if self.n == 1:
                raise RuntimeError("429 Too Many Requests – rate limit")
            yield Chunk(text="výsledek " * 50)
            yield Chunk(done=True)

        async def complete(self, messages, **kw):
            return "shrnutí"
    rt.router = Router()
    mt = Multitask(rt)
    mt.retry_scale = 0.001
    s = await mt.start("x", [{"name": "A", "task": "a" * 4000}])
    await wait_done(s)
    assert s.workers[0].state == "done" and mt.slowed()
    u = s.usage
    assert u["calls"] >= 1 and u["tin"] >= 300 and u["czk"] > 0
    assert mt.state()["slowed"] is True


# ---------------------------------------------------------------- the results file
async def test_the_results_are_saved_and_open_only_from_the_reports_folder(rt, tmp_path):
    rt.router = FakeRouter(["Výsledek A: 42", "Výsledek B: 7", "Shrnutí: 42 a 7."])
    mt = Multitask(rt)
    q = rt.bus.subscribe()
    s = await mt.start("Spočítej věci", [{"name": "A", "task": "a"}, {"name": "B", "task": "b"}])
    await wait_done(s)
    p = Path(s.report)
    text = p.read_text(encoding="utf-8")
    assert p.parent == multitask.reports_dir() and "# Spočítej věci" in text and "### A" in text and "Shrnutí" in text
    note = [e for e in drain(q) if e["type"] == "notify" and e["title"].startswith("Multitasking")][-1]
    assert note["actions"][0]["action"] == "open_report"
    await rt.notice_action("open_report", {"path": str(p)})
    assert ("open_path", str(p)) in rt.platform.calls
    outside = tmp_path / "x.md"
    outside.write_text("x")
    await rt.notice_action("open_report", {"path": str(outside)})
    assert ("open_path", str(outside)) not in rt.platform.calls


# ---------------------------------------------------------------- money: from the phone too
async def test_money_goes_to_the_phone_at_once_and_waits_longer(rt, monkeypatch):
    from jarvis.tools import computer_use

    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    monkeypatch.setattr(rt, "user_away", lambda: False)                  # even at the PC
    seen = {}

    async def fake_confirm(call, second=False, timeout=None, phone=False):
        seen.update(timeout=timeout, phone=phone)
        rt.on_confirm_request("c1", "Peníze", phone=phone)
        return True
    monkeypatch.setattr(rt.agent, "_ask_confirm", fake_confirm)
    assert await computer_use.ask_money(rt, "Koupit 0,01 BTC") is True
    assert seen == {"timeout": computer_use.MONEY_CONFIRM_S, "phone": True} and pushed and pushed[0][0] == "confirm"
    pushed.clear()
    rt.on_confirm_request("c2", "Zavřít Steam")                            # other confirmations: only when away
    assert not pushed


# ---------------------------------------------------------------- agents on a schedule
async def test_agents_on_a_schedule(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    r = await tools.call("multitask_schedule", {"time": "08:00", "preset": "vyzkum", "topic": "trhy", "repeat": "weekdays"}, rt)
    assert r.ok and "Výzkum" in r.summary
    job = next(j for j in rt.scheduler.list() if j["kind"] == "multitask")
    assert job["payload"]["preset"] == "vyzkum" and job["spec"]["days"] == [0, 1, 2, 3, 4]
    plan = [{"name": "A", "task": "a"}]
    rt.router = FakeRouter([json.dumps(plan)] + ["hotovo"] * 5)
    await rt.scheduler._run(job)
    s = next(iter(rt.multitask.sessions.values()))
    assert s.preset == "vyzkum"
    await wait_done(s)
    r = await tools.call("multitask_schedule", {"time": "08:00"}, rt)
    assert not r.ok


# ---------------------------------------------------------------- the monitor test
async def test_the_monitor_test(rt, monkeypatch):
    from PIL import Image

    two_monitors(rt, monkeypatch)

    def shot(i):
        m = TWO[i - 1]
        buf = io.BytesIO()
        Image.new("RGB", (m["width"], m["height"])).save(buf, "PNG")
        return buf.getvalue()
    monkeypatch.setattr(rt.platform, "screenshot_monitor", shot)
    r = await tools.call("monitor_check", {}, rt)
    assert r.ok and "Monitor 2 (1280×1024): myš trefila střed, snímek sedí" in r.summary
    assert ("move", -640, 512) in rt.platform.calls                     # the monitor left of the main one
    assert not [c for c in rt.platform.calls if c[0] == "click"]        # never a click
    monkeypatch.setattr(rt.platform, "cursor_pos", lambda: (5, 5))
    r = await tools.call("monitor_check", {}, rt)
    assert not r.ok and "NETREFILA" in r.summary


def test_windows_clicks_go_straight_to_desktop_coordinates():
    import inspect

    from jarvis.tools.platform import windows

    src = inspect.getsource(windows.WindowsPlatform.click) if hasattr(windows, "WindowsPlatform") else inspect.getsource(windows)
    assert "_put_cursor" in src


# ---------------------------------------------------------------- from the phone
async def test_the_phone_cannot_start_monitor_agents_when_it_may_not(rt, monkeypatch):
    from jarvis import mobileplus

    two_monitors(rt, monkeypatch)
    tok = mobileplus.set_device_perms({"apps", "network"})
    try:
        with pytest.raises(PermissionError, match="Z telefonu"):
            await Multitask(rt).start("x", [{"kind": "screen", "task": "a", "monitor": 1}])
    finally:
        mobileplus._DEVICE_PERMS.reset(tok)


# ---------------------------------------------------------------- the morning news by your interests
async def test_the_morning_news_follows_your_interests(rt):
    import time

    from jarvis import stark
    from jarvis.worldwatch import WorldWatch  # noqa: F401

    rt.cfg.world.topics = ["cz", "world"]
    rt.cfg.world.interests = ["Valorant"]
    db = rt.world._db()
    now = time.time()
    for url, topic, title in (("u1", "cz", "Vláda schválila rozpočet"), ("u2", "world", "Summit v Bruselu"),
                              ("u3", "i:valorant", "Nový agent ve Valorantu"), ("u4", "cz", "Druhá česká zpráva")):
        db.exec("INSERT OR REPLACE INTO world_news (url, topic, title, source, published, fetched) VALUES (?, ?, ?, ?, ?, ?)",
                (url, topic, title, "x", now - 60, now))
    top = rt.world.top(3)
    assert top[0] == "Nový agent ve Valorantu (Valorant)" and "Vláda schválila rozpočet" in top and "Summit v Bruselu" in top
    assert await stark.headlines(rt) == top


# ---------------------------------------------------------------- the tools
async def test_the_new_tools(rt, monkeypatch):
    papertrade.of(rt).reset(5000)
    r = await tools.call("paper_trade", {"side": "buy", "symbol": "ETH", "price": 80000, "czk": 800}, rt)
    assert r.ok and "Nákup" in r.summary and "4 200" in r.summary
    r = await tools.call("paper_portfolio", {}, rt)
    assert r.ok and "ETH" in r.summary
    r = await tools.call("paper_reset", {"cash": 20000}, rt)
    assert r.ok and "20 000" in r.summary
    r = await tools.call("multitask_tell", {"agent": "nikdo", "message": "ahoj"}, rt)
    assert not r.ok
    r = await tools.call("multitask_preset", {"preset": "hra_fronta", "topic": ""}, rt)
    assert not r.ok and "potřebuje" in r.summary
    spec = tools.REGISTRY["multitask_preset"]
    assert spec.danger_if({"preset": "obchodni_stul", "paper": False}) and not spec.danger_if({"preset": "obchodni_stul", "paper": True})
