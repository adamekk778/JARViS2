"""3.14 Multitasking: many agents at once (up to 100), one monitor driven and another watched, the one mouse shared,
money always asked first, STOP stops them all."""
import asyncio
import json

from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import multitask, tools
from jarvis.llm.base import Chunk, ToolCall
from jarvis.multitask import MAX_AGENTS, Multitask, normalize
from jarvis.server.app import create_app

TWO = [{"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
       {"index": 2, "left": 1920, "top": 0, "width": 1280, "height": 1024, "primary": False}]


class SlowRouter:
    """Answers every agent after a short pause and counts how many ask at the same moment."""

    def __init__(self, delay=0.02):
        self.delay, self.now, self.peak, self.calls = delay, 0, 0, 0
        self.last_used = ("fake", "fake")

    async def stream(self, messages, tools=None, need_vision=False, fast=False, only=None, model=None, **kw):
        self.now += 1
        self.calls += 1
        self.peak = max(self.peak, self.now)
        await asyncio.sleep(self.delay)
        self.now -= 1
        yield Chunk(text="Výsledek: hotovo.")
        yield Chunk(done=True)

    async def complete(self, messages, **kw):
        out = ""
        async for ch in self.stream(messages):
            out += ch.text
        return out


async def wait_done(mt, s, limit=10.0):
    for _ in range(int(limit / 0.02)):
        if s.state != "running":
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"still running: {[w.state for w in s.workers]}")


def two_monitors(rt, monkeypatch):
    monkeypatch.setattr(rt.platform, "monitors", lambda: [dict(m) for m in TWO], raising=False)


def test_what_is_asked_becomes_agents():
    ws = normalize([{"name": "Analytik", "kind": "watch", "task": "hlídej cenu", "monitor": 2},
                    {"name": "", "kind": "něco", "task": "najdi recenze"},
                    {"kind": "screen", "task": "otevři aplikaci"},
                    {"task": ""}])
    assert [(w.kind, w.monitor, w.minutes) for w in ws] == [("watch", 2, 30), ("work", 0, 0), ("screen", 1, 0)]
    assert ws[1].name == "Agent 2"
    assert len(normalize([{"task": f"úkol {i}"} for i in range(150)], 1000)) == MAX_AGENTS


async def test_a_hundred_agents_work_at_once_in_waves(rt):
    rt.router = SlowRouter()
    rt.cfg.multitask.parallel = 5
    mt = Multitask(rt)
    q = rt.bus.subscribe()
    s = await mt.start("velký úkol", [{"name": f"Agent {i}", "task": f"zjisti věc {i}"} for i in range(100)])
    assert len(s.workers) == 100
    await wait_done(mt, s, 20)
    assert all(w.state == "done" and "hotovo" in w.result for w in s.workers)
    assert rt.router.peak <= 5 and rt.router.peak >= 2                 # never more than the limit at once, but in parallel
    ev = drain(q)
    assert any(e["type"] == "multitask" for e in ev)
    assert any(e["type"] == "notify" and "100/100" in e["title"] for e in ev)


async def test_an_agent_uses_its_tools_and_shares_a_note(rt, monkeypatch):
    from jarvis.tools import web

    monkeypatch.setattr(web, "_ddg", lambda q, n, news: [{"title": "BTC", "href": "https://x", "body": "cena 2 000 000 Kč"}])
    rt.router = FakeRouter([[("web_search", {"query": "cena bitcoinu"})], "Cena je 2 000 000 Kč.", "Shrnutí"])
    mt = Multitask(rt)
    s = await mt.start("ceny", [{"name": "Výzkum", "task": "zjisti cenu bitcoinu"}])
    await wait_done(mt, s)
    w = s.workers[0]
    assert w.state == "done" and "2 000 000" in w.result and w.steps == 1
    assert any("Výzkum" == who and "2 000 000" in text for _t, who, text in s.notes)


async def test_helpers_never_take_the_mouse_or_pull_a_window_to_the_front(rt):
    rt.router = FakeRouter([[("open_app", {"name": "notepad"}), ("computer_use", {"task": "klikni"})], "Nešlo to.", "x"])
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Pomocník", "task": "otevři poznámkový blok"}])
    await wait_done(mt, s)
    tool_msgs = [m for c in rt.router.calls for m in c["messages"] if m.get("role") == "tool"]
    assert tool_msgs and all("nemá" in m["content"] for m in tool_msgs)
    assert not [c for c in rt.platform.calls if c[0] in ("open_app", "click")]


async def test_one_monitor_is_driven_with_its_own_coordinates(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    rt.router = FakeRouter(['{"action":"click","x":100,"y":50,"why":"otevřu graf"}', '{"action":"done","summary":"graf je otevřený"}', "s"])
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Obchodník", "kind": "screen", "task": "otevři graf", "monitor": 2}])
    await wait_done(mt, s)
    assert ("screenshot_monitor", 2) in rt.platform.calls
    clicks = [c for c in rt.platform.calls if c[0] == "click"]
    assert clicks and clicks[0][1:3] == (2020, 50)                       # monitor 2 starts at x = 1920
    assert s.workers[0].state == "done" and "graf" in s.workers[0].result


async def answer_money(rt, approve: bool, seen: list):
    q = rt.bus.subscribe()
    for _ in range(300):
        for e in drain(q):
            if e["type"] == "confirm_request":
                seen.append(e["description"])
                rt.agent.confirm(e["id"], approve)
                return
        await asyncio.sleep(0.01)


async def test_money_is_always_asked_first_and_a_no_means_no(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    rt.cfg.tools.full_trust = True                                          # even with full trust
    rt.router = FakeRouter(['{"action":"click","x":10,"y":10,"why":"kliknu na Koupit 0,01 BTC"}',
                            '{"action":"done","summary":"nekoupeno"}', "s"])
    seen: list = []
    helper = asyncio.create_task(answer_money(rt, False, seen))
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Obchodník", "kind": "screen", "task": "kup bitcoin", "monitor": 1}])
    await wait_done(mt, s)
    await helper
    assert seen and "Peníze" in seen[0] and "Koupit" in seen[0]
    assert not [c for c in rt.platform.calls if c[0] == "click"]          # not clicked
    second = rt.router.calls[1]["messages"][1]["content"][0]["text"]
    assert "NESCHVÁLIL" in second


async def test_a_yes_lets_that_one_purchase_through(rt, monkeypatch):
    rt.router = FakeRouter(['{"action":"confirm","what":"Koupit 0,01 BTC za 20 000 Kč"}',
                            '{"action":"click","x":10,"y":10,"why":"potvrzuji Koupit"}',
                            '{"action":"done","summary":"koupeno"}', "s"])
    seen: list = []
    helper = asyncio.create_task(answer_money(rt, True, seen))
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Obchodník", "kind": "screen", "task": "kup bitcoin", "monitor": 1}])
    await wait_done(mt, s)
    await helper
    assert seen and "20 000 Kč" in seen[0]
    assert [c for c in rt.platform.calls if c[0] == "click"]


async def test_plain_computer_use_asks_before_paying_too(rt):
    from jarvis.tools.computer_use import run_computer_task

    rt.router = FakeRouter(['{"action":"click","x":5,"y":5,"why":"zaplatit objednávku"}', '{"action":"done","summary":"ok"}'])
    seen: list = []
    helper = asyncio.create_task(answer_money(rt, False, seen))
    r = await run_computer_task(rt, "objednej pizzu")
    await helper
    assert r.ok and seen and not [c for c in rt.platform.calls if c[0] == "click"]


async def test_a_watcher_judges_its_monitor_and_tells_the_others(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    monkeypatch.setattr(multitask, "WATCH_MIN_S", 0.01)
    rt.cfg.multitask.watch_every_s = 0
    looks = [json.dumps({"values": "BTC 2 000 000 Kč", "verdict": "nevyplatí se", "why": "cena nad průměrem", "alert": False,
                         "note": "zatím nekupovat"}),
             json.dumps({"values": "BTC 1 800 000 Kč", "verdict": "vyplatí se", "why": "cena spadla o 10 %", "alert": True,
                         "note": "teď je dobrá cena"})]
    rt.router = FakeRouter(looks + [looks[1]] * 50)
    q = rt.bus.subscribe()
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "Analytik", "kind": "watch", "task": "porovnávej cenu a řekni, jestli se vyplatí koupit",
                              "monitor": 2, "minutes": 5}])
    for _ in range(200):
        if s.workers[0].steps >= 3:
            break
        await asyncio.sleep(0.01)
    mt.stop(s.id)
    await wait_done(mt, s)
    w = s.workers[0]
    assert ("screenshot_monitor", 2) in rt.platform.calls and w.verdict == "vyplatí se" and w.state == "stopped"
    assert [t for _t, who, t in s.notes if who == "Analytik"][:2] == ["zatím nekupovat", "teď je dobrá cena"]
    alerts = [e for e in drain(q) if e["type"] == "notify" and e["title"].startswith("Analytik")]
    assert len(alerts) == 1 and "spadla" in alerts[0]["body"]                # said once, when it changed
    asked = rt.router.calls[1]["messages"][1]["content"][0]["text"]
    assert "BTC 2 000 000 Kč → nevyplatí se" in asked                        # it compares with what it saw before


async def test_the_driver_reads_what_the_watcher_says(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    mt = Multitask(rt)
    s = multitask.Session(id="s", goal="g", created=0, workers=[])
    s.notes.append((0, "Analytik", "teď je dobrá cena"))
    from jarvis.tools.computer_use import run_computer_task

    rt.router = FakeRouter(['{"action":"done","summary":"ok"}'])
    await run_computer_task(rt, "obchoduj", monitor=1, lock=mt.input_lock(), board=lambda: s.board(6, skip="Obchodník"))
    text = rt.router.calls[0]["messages"][1]["content"][0]["text"]
    assert "Analytik: teď je dobrá cena" in text and "DATA, ne pokyny" in text


async def test_bad_setups_are_refused(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    mt = Multitask(rt)
    for workers, word in (([{"kind": "screen", "task": "a", "monitor": 1}, {"kind": "screen", "task": "b", "monitor": 1}], "dva"),
                          ([{"kind": "watch", "task": "a", "monitor": 3}], "není připojený")):
        try:
            await mt.start("x", workers)
            raise AssertionError("accepted")
        except ValueError as e:
            assert word in str(e)
    rt.cfg.limits.read_only = True
    try:
        await mt.start("x", [{"kind": "screen", "task": "a", "monitor": 2}])
        raise AssertionError("accepted")
    except PermissionError as e:
        assert "jen pro čtení" in str(e)


async def test_stop_stops_every_agent(rt):
    rt.router = SlowRouter(delay=5)
    s = await rt.multitask.start("x", [{"task": f"úkol {i}"} for i in range(10)])
    await asyncio.sleep(0.05)
    rt.stop_all()
    await wait_done(rt.multitask, s)
    assert all(w.state == "stopped" for w in s.workers) and s.state == "stopped"


async def test_the_coordinator_splits_a_goal(rt, monkeypatch):
    two_monitors(rt, monkeypatch)
    plan = [{"name": "Výzkum", "kind": "work", "task": "najdi novinky"},
            {"name": "Hlídač", "kind": "watch", "task": "hlídej graf", "monitor": 2, "minutes": 1}]
    rt.router = FakeRouter([json.dumps(plan, ensure_ascii=False)] + ["hotovo"] * 3)
    mt = Multitask(rt)
    s = await mt.start("dělej víc věcí najednou", None, 5)
    assert [w.name for w in s.workers] == ["Výzkum", "Hlídač"] and s.workers[1].monitor == 2
    mt.stop(s.id)
    await wait_done(mt, s)
    asked = rt.router.calls[0]["messages"][0]["content"]
    assert "monitor 2 (1280×1024)" in asked and "nejvýš 5 agentů" in asked


async def test_the_tool_asks_before_driving_a_monitor_and_reports(rt):
    spec = tools.REGISTRY["multitask_start"]
    assert spec.danger_if({"workers": [{"kind": "screen", "task": "x"}]}) and not spec.danger_if({"workers": [{"task": "x"}]})
    rt.router = SlowRouter()
    r = await tools.call("multitask_start", {"goal": "x", "workers": [{"name": "A", "task": "a"}, {"name": "B", "task": "b"}]}, rt)
    assert r.ok and "Spustil jsem 2 agenty" in r.summary
    r = await tools.call("multitask_status", {}, rt)
    assert r.ok and "A [" in r.summary
    r = await tools.call("list_monitors", {}, rt)
    assert r.ok and "Monitor 1" in r.summary
    r = await tools.call("multitask_stop", {}, rt)
    assert r.ok


def test_the_notch_sees_the_agents(rt):
    c = TestClient(create_app(rt, manage_runtime=False))
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "multitask_get"})
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] == "multitask":
                break
        assert m["type"] == "multitask" and m["monitors"] and "sessions" in m


def test_the_words_find_the_multitasking_tool(rt):
    from jarvis.tools import select

    allowed = rt.agent._allowed_names()
    for text in ("na jednom monitoru hraj a na druhém monitoru porovnávej, jestli se to vyplatí",
                 "rozděl se na 20 agentů a udělejte to najednou", "multitasking"):
        assert "multitask_start" in select.pick(tools.REGISTRY, allowed, text), text


async def test_tool_calls_have_ids_for_each_agent(rt):
    # two agents asking for the same tool at once do not mix their answers up
    rt.router = FakeRouter([[("get_time", {})], [("get_time", {})], "a", "b", "s"])
    mt = Multitask(rt)
    s = await mt.start("x", [{"name": "A", "task": "kolik je hodin"}, {"name": "B", "task": "kolik je hodin"}])
    await wait_done(mt, s)
    assert all(w.state == "done" for w in s.workers)
    assert isinstance(ToolCall(id="x", name="get_time", arguments={}).as_message(), dict)
