"""3.13: company goals, 👍/👎, test runs, approval rules, "Schválit vše", catch-up after the PC was off, the webhook poke,
the spoken brief, backup and restore, the phone's quick edit, AI cost – plus full trust, the game that is never closed
mid-game, playing for you, startup apps, the "…" that is never an answer, and the Czech services."""
import asyncio
import datetime as dt
import json
import time
from types import SimpleNamespace as NS

import httpx
import pytest
from conftest import FakeRouter

from jarvis import (autopilot, bizagents, bizbackup, bizcompany, bizevents, bizgoals, bizhooks, connectors, secrets, tools,
                    trust)
from jarvis.llm import pricing
from jarvis.llm.base import Chunk, ToolCall

tools.load_builtin()
connectors.load()


class Router:
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    async def stream(self, msgs, tools_=None, **kw):
        self.seen.append((msgs, kw))
        step = self.steps.pop(0) if self.steps else "hotovo"
        if isinstance(step, str):
            yield Chunk(text=step, done=True)
        else:
            yield Chunk(tool_calls=step, done=True)


@pytest.fixture
def brt(tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    r = Runtime(persist_config=False)
    notes = []
    monkeypatch.setattr(r, "notify", lambda *a, **k: notes.append(a))
    pushed = []
    monkeypatch.setattr(r, "phone_push", lambda kind, **d: pushed.append((kind, d)) or True)
    r.pushed, r.notes = pushed, notes
    bizagents.JOBS.clear()
    return r


def call(name, **args):
    return ToolCall(id="1", name=name, arguments=args)


# ---------------------------------------------------------------- goals
def test_goals_are_measured_reported_and_in_every_brief(brt):
    gid = bizgoals.save(brt, {"name": "Odpověď zákazníkovi", "target": "2", "unit": "h", "period": "week", "direction": "down"})
    bizgoals.save(brt, {"metric": "approved", "target": 10, "period": "month"})
    with pytest.raises(ValueError):
        bizgoals.save(brt, {"name": "x", "target": "0"})
    asyncio.run(bizgoals.refresh(brt))
    g = {x["id"]: x for x in bizgoals.goals(brt)}
    assert g[gid]["current"] is None and [x for x in g.values() if x["metric"] == "approved"][0]["current"] == 0.0
    r = asyncio.run(tools.call("company_goal_update", {"goal": "odpověď", "value": 1.5, "note": "z e-mailů"}, brt))
    assert r.ok and "100 %" in r.summary                                       # 1,5 h under a 2 h limit: on target
    assert not asyncio.run(tools.call("company_goal_update", {"goal": "Provedené", "value": 3}, brt)).ok   # measures itself
    ctx = bizcompany.context(brt, {"name": "x", "task": "y"})
    assert "CÍLE FIRMY" in ctx and "Odpověď zákazníkovi" in ctx and "méně je lépe" in ctx


def test_goal_periods():
    now = dt.datetime(2026, 11, 18, 15, 0)
    assert bizgoals.start("week", now) == dt.datetime(2026, 11, 16) and bizgoals.end("month", now) == dt.datetime(2026, 12, 1)
    assert bizgoals.start("quarter", now) == dt.datetime(2026, 10, 1) and bizgoals.end("quarter", now) == dt.datetime(2027, 1, 1)


# ---------------------------------------------------------------- 👍/👎, test runs, rules, approve all
def test_a_thumbs_down_counts_no_time_and_the_agent_remembers_why(brt):
    aid = bizcompany.hire(brt, "kpi_watch")
    brt.router = Router(["Tržby 182 400 Kč."])
    asyncio.run(bizagents.run(brt, aid))
    assert bizcompany.numbers(brt)["saved_week_min"] > 0
    bizcompany.rate(brt, -1, "moc dlouhé, chci jen čísla", agent_id=aid)
    n = bizcompany.numbers(brt)
    assert n["saved_week_min"] == 0 and n["rated_down"] == 1
    mem = bizcompany.memory(brt, bizagents.get(brt, aid))
    assert "👎" in mem and "moc dlouhé" in mem
    st = bizagents.state(brt, full=False)
    assert [a for a in st["agents"] if a["id"] == aid][0]["last_rating"] == -1


def test_a_test_run_shows_what_would_happen_and_changes_nothing(brt):
    aid = bizcompany.hire(brt, "lead_reply")
    brt.router = Router([[call("google_gmail_send", to="a@b.cz", subject="Re", body="Dobrý den")], "připraveno"])
    r = asyncio.run(bizagents.run(brt, aid, dry=True))
    assert r["dry"] and r["would"] and r["would"][0]["tool"] == "google_gmail_send"
    assert bizagents.proposals(brt) == [] and bizagents.get(brt, aid)["last_run"] is None
    assert bizagents.get(brt, aid)["runs"] == 0 and brt.pushed == []


def test_a_rule_lets_only_safe_records_happen_by_themselves(brt, monkeypatch):
    bizcompany._set(brt, "biz_phone", "always")
    aid = bizagents.save(brt, {"name": "Úkolník", "tools": ["todoist_add", "google_gmail_send"], "auto": ["todoist_add", "google_gmail_send"]})
    a = bizagents.get(brt, aid)
    assert a["auto"] == ["todoist_add"]                                        # an e-mail can never be automatic
    done = []

    async def fake_call(name, args, ctx):
        done.append(name)
        return tools.ToolResult(True, "úkol vytvořen")
    monkeypatch.setattr(tools, "call", fake_call)
    brt.router = Router([[call("todoist_add", content="Zavolat dodavateli")], [call("google_gmail_send", to="x@y.cz", subject="a", body="b")], "hotovo"])
    r = asyncio.run(bizagents.run(brt, aid))
    assert done == ["todoist_add"] and r["auto"] and len(bizagents.proposals(brt)) == 1       # the e-mail waits for you
    assert [x["kind"] for x in bizcompany.actions(brt, kind="auto")] == ["auto"]
    assert brt.pushed and brt.pushed[-1][1]["cid"] == f"biz:{bizagents.proposals(brt)[0]['id']}"   # only the e-mail asks on the phone


def test_approve_or_reject_everything_you_saw(brt):
    aid = bizcompany.hire(brt, "lead_reply")
    a = bizagents.get(brt, aid)
    ids = [bizagents.propose(brt, a, call("google_gmail_send", to=f"{i}@b.cz", subject="s", body="b")) for i in range(3)]
    r = asyncio.run(bizagents.decide_many(brt, ids[:2] + [999], False))
    assert "Zamítnuto 2" in r["message"] and "1 už bylo vyřízeno" in r["message"]
    assert [p["id"] for p in bizagents.proposals(brt)] == [ids[2]]


# ---------------------------------------------------------------- the PC was off
def test_missed_daily_and_weekly_work_is_caught_up_but_not_twice():
    daily = {"enabled": True, "work_hours": False, "every_min": 0, "daily_at": "08:30",
             "last_run": dt.datetime(2026, 11, 16, 8, 31).timestamp()}
    assert bizagents.due(daily, dt.datetime(2026, 11, 18, 5, 0))               # yesterday's run was missed, today's is far
    assert not bizagents.due(daily, dt.datetime(2026, 11, 18, 8, 0))           # today's is in 30 min: no double work
    assert bizagents.due(daily, dt.datetime(2026, 11, 18, 8, 31))              # and then today's runs normally
    weekly = {**daily, "daily_at": "0 08:00", "last_run": dt.datetime(2026, 11, 9, 8, 1).timestamp()}
    assert bizagents.due(weekly, dt.datetime(2026, 11, 17, 10, 0))             # Monday's report missed → Tuesday
    assert not bizagents.due({**weekly, "last_run": None}, dt.datetime(2026, 11, 17, 10, 0))   # a new agent waits for Monday


def test_after_hours_off_the_control_room_says_what_came(brt, monkeypatch):
    bizcompany.hire(brt, "lead_triage")
    bizcompany._set(brt, "biz_alive", str(time.time() - 9 * 3600))
    seen = {}

    async def fake_check(rt, days=1):
        seen["days"] = days
        return {"mail": 4, "order": 0}
    monkeypatch.setattr(bizevents, "check", fake_check)
    info = asyncio.run(bizagents.catch_up(brt))
    assert seen["days"] == 2 and "4 e-mailů" in info["text"] and "9 h" in info["text"]
    assert brt.pushed and "Velín" in brt.pushed[-1][1]["title"]
    assert "4 e-mailů" in bizcompany.brief(brt)
    bizcompany._set(brt, "biz_alive", str(time.time() - 60))
    assert asyncio.run(bizagents.catch_up(brt)) is None


# ---------------------------------------------------------------- reacting faster, the webhook poke
def test_events_speed_and_the_hook_only_wakes_the_look(brt):
    assert bizevents.every(brt) == 60
    bizcompany._set(brt, "biz_events_every", "600")
    assert bizevents.every(brt) == 600
    bizcompany._set(brt, "biz_events_every", "5")
    assert bizevents.every(brt) == 60                                          # not every 5 s
    k = bizhooks.key()
    assert bizhooks.valid(k) and not bizhooks.valid("x" + k) and not bizhooks.valid("")
    bizevents._POKED[0] = 0
    assert bizevents.poke() and not bizevents.poke()                           # a flood of hooks is one look
    assert bizhooks.info(brt)["path"].endswith(k)


def test_the_hook_address_answers_404_to_a_wrong_key(brt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    k = bizhooks.key()
    with TestClient(create_app(brt, manage_runtime=False)) as c:
        assert c.post("/api/velin/hook/nope").status_code == 404
        bizevents._POKED[0] = 0
        assert c.post(f"/api/velin/hook/{k}", json={"anything": "ignored"}).json() == {"ok": True, "looking": True}


# ---------------------------------------------------------------- backup, quick edit, brief, cost
def test_backup_moves_the_company_without_keys(brt, tmp_path, monkeypatch):
    aid = bizcompany.hire(brt, "kpi_watch")
    bizagents.save(brt, {**bizagents.get(brt, aid), "next": ["Strážce cashflow"], "tier": "fast"})
    bizgoals.save(brt, {"metric": "approved", "target": 5})
    bizcompany.brain_add(brt, "Ceník B2B: od 50 ks sleva 7 %.")
    bizcompany.save_profile(brt, {"name": "Nordic Supply"})
    data = bizbackup.export(brt)
    raw = json.dumps(data)
    assert set(data) >= {"profile", "agents", "goals", "brain"} and "secret" not in raw and "password" not in raw
    bizagents._db(brt).exec("DELETE FROM biz_agents")
    r = bizbackup.restore(brt, raw, replace=True)
    assert r["added"] == 1 and r["goals"] == 1 and r["notes"] == 1
    a = bizagents.agents(brt)[0]
    assert a["name"] == "Strážce čísel (KPI)" and a["tier"] == "fast" and a["next"] == ["Strážce cashflow"]
    assert bizcompany.profile(brt)["name"] == "Nordic Supply"
    with pytest.raises(ValueError):
        bizbackup.restore(brt, '{"něco": 1}')


def test_the_phone_changes_only_when_and_whether(brt):
    aid = bizcompany.hire(brt, "kpi_watch")
    before = bizagents.get(brt, aid)
    bizagents.quick(brt, aid, {"enabled": False, "daily_at": "09:15", "task": "smaž všechno", "tools": ["google_gmail_send"]})
    a = bizagents.get(brt, aid)
    assert not a["enabled"] and a["daily_at"] == "09:15" and a["task"] == before["task"] and a["tools"] == before["tools"]


def test_brief_and_cost(brt):
    assert "žádný agent" in bizcompany.brief(brt)
    aid = bizcompany.hire(brt, "kpi_watch")
    bizcompany.record_run(brt, bizagents.get(brt, aid), time.time(), 3, True, 0, "ok", 2, 1, "plán",
                          {"in": 40_000, "out": 2_000, "model": "gemini:gemini-3.8-flash"})
    c = bizcompany.numbers(brt)["cost_week"]
    assert c["czk"] > 0 and c["tokens"] == 42_000
    assert pricing.czk("ollama:qwen3", 10**6, 10**6) == 0 and pricing.czk("openrouter:x/y:free", 10**6, 0) == 0
    assert pricing.czk("gemini:gemini-3.5-flash-lite", 10**6, 0) < pricing.czk("gemini:gemini-3.8-flash", 10**6, 0)
    assert "Nic nečeká na schválení" in bizcompany.brief(brt)


# ---------------------------------------------------------------- full trust and the game that stays
def test_full_trust_skips_asking_only_where_it_should(rt):
    R = tools.REGISTRY
    assert not trust.skip_confirm(rt, R["close_app"])                          # off by default
    rt.cfg.tools.full_trust = True
    for name in ("close_app", "startup_app_set", "move_file", "system_power", "computer_use", "play_for_me"):
        assert trust.skip_confirm(rt, R[name]), name
    for name in ("send_sms", "email_send", "google_gmail_send", "stripe_refund", "run_shell", "run_python", "delete_file", "claude_code",
                 "git_push", "screen_share"):
        assert not trust.skip_confirm(rt, R[name]), name
    assert trust.skip_confirm(rt, R["todoist_add"])
    assert not trust.skip_confirm(rt, R["move_file"], untrusted_seen=True)     # after a web page / e-mail: files ask again
    assert trust.skip_confirm(rt, R["close_app"], untrusted_seen=True)


async def test_full_trust_closes_without_asking(rt):
    rt.cfg.tools.full_trust = True
    rt.router = FakeRouter([[("set_dark_mode", {"dark": True}), ("close_app", {"name": "notepad"})], "Hotovo."])
    q = rt.bus.subscribe()
    out = await asyncio.wait_for(rt.agent.handle("zavři notepad"), 5)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert not [e for e in events if e["type"] == "confirm_request"] and "Hotovo" in out
    sys_text = rt.router.calls[0]["messages"][0]["content"]
    assert "PLNÁ DŮVĚRA" in sys_text


def test_a_running_game_is_closed_only_when_you_name_it(monkeypatch):
    from jarvis.tools import apps

    monkeypatch.setattr(apps, "matching_apps", lambda name: [{"name": "RobloxPlayerBeta.exe", "path": r"c:\users\a\appdata\local\roblox\versions\robloxplayerbeta.exe",
                                                             "count": 1, "game": True}])
    closed = []
    ctx = NS(platform=NS(close_app=lambda n: closed.append(n) or 1), request_text="vypni mi zbytečné aplikace")
    r = asyncio.run(tools.REGISTRY["close_app"].func(ctx, "roblox"))
    assert not r.ok and "nezavřu" in r.summary and closed == []
    ctx.request_text = "zavři Roblox, končím"
    r = asyncio.run(tools.REGISTRY["close_app"].func(ctx, "roblox"))
    assert r.ok and closed == ["roblox"]
    ctx.request_text = ""                                                      # an automation, no words of yours: never
    assert not asyncio.run(tools.REGISTRY["close_app"].func(ctx, "roblox")).ok


def test_startup_switch_values():
    from jarvis.tools import startup_tools as st

    assert st.enabled_from(None) and st.enabled_from(st.approved_value(True)) and not st.enabled_from(st.approved_value(False))
    assert len(st.approved_value(False)) == 12 and st.approved_value(False)[0] == 3
    assert st.protected("SecurityHealth") and st.protected("RtkAudUService") and not st.protected("Spotify")
    assert st.public([{"name": "Spotify", "enabled": True, "_ref": ("reg",)}]) == [{"name": "Spotify", "enabled": True, "keep": False}]


# ---------------------------------------------------------------- playing for you
def test_the_ai_gets_only_game_keys():
    m = autopilot.parse('{"note": "jdu k truhle", "actions": [{"keys": ["w"], "ms": 9000}, {"keys": ["enter"]}, {"keys": ["/"]}, '
                        '{"mouse": [900, -20]}, {"click": [10, 20]}, {"wait": 50}, {"button": "right"}], "done": false}')
    assert m["actions"][0] == {"keys": ["w"], "ms": 3000}                     # held at most 3 s; no Enter, no "/" (chat)
    assert m["actions"][1] == {"mouse": [400, -20]} and len(m["actions"]) == 5 and m["actions"][-1] == {"button": "right", "ms": 80}
    with pytest.raises(ValueError):
        autopilot.parse("nevím")


class GamePC:
    def __init__(self):
        self.done, self.idle = [], 100.0

    def game_input_ok(self):
        return True

    def screenshot(self):
        import io

        from PIL import Image

        b = io.BytesIO()
        Image.new("RGB", (1920, 1080), (30, 90, 40)).save(b, "PNG")
        return b.getvalue()

    def game_keys(self, keys, ms):
        self.done.append(("keys", tuple(keys), ms))

    def game_mouse(self, dx, dy):
        self.done.append(("mouse", dx, dy))

    def game_click(self, button="left", ms=60):
        self.done.append(("click", button))

    def move(self, x, y):
        self.done.append(("move", x, y))

    def window_action(self, action, title=""):
        return "ok"

    def idle_seconds(self):
        return self.idle

    def release_all_input(self):
        self.done.append(("release",))


async def test_playing_for_you_moves_until_done_and_remembers_the_game(rt, tmp_path):
    pc = GamePC()
    rt.platform = pc
    rt.router = FakeRouter(['{"note":"jdu dopředu","actions":[{"keys":["w"],"ms":40},{"click":[480,270]}],"done":false}',
                            '{"note":"hotovo","actions":[{"keys":["space"],"ms":30}],"done":true}'])
    ap = autopilot.of(rt)
    msg = await ap.start("Roblox", "Sbírej mince, vyhýbej se lávě.", 5)
    assert "ban" in msg                                                        # said once, the first time
    await asyncio.wait_for(ap.task, 5)
    assert ("keys", ("w",), 40) in pc.done and ("move", 960, 540) in pc.done and ("keys", ("space",), 30) in pc.done
    assert ap.why == "Úkol ve hře je hotový." and not ap.on and ap.steps == 2
    assert autopilot.saved_how("roblox") == "Sbírej mince, vyhýbej se lávě."
    assert "ban" not in await ap.start("Roblox", "", 5)                        # the explanation is remembered, no warning again
    await ap.stop("test")


async def test_playing_stops_when_you_touch_the_mouse(rt):
    pc = GamePC()
    rt.platform = pc
    class SlowAI(FakeRouter):                                                 # a real AI takes a second to answer
        async def complete(self, *a, **k):
            await asyncio.sleep(0.8)
            return await super().complete(*a, **k)
    rt.router = SlowAI(['{"note":"a","actions":[{"keys":["w"],"ms":30}],"done":false}'] * 50)
    ap = autopilot.of(rt)
    await ap.start("Minecraft", "Kop dřevo.", 5)
    await asyncio.sleep(1.2)
    pc.idle = 0.05                                                             # you moved the mouse just now
    await asyncio.wait_for(ap.task, 5) if ap.task else None
    assert "zpátky" in ap.why and ("release",) in pc.done


def test_only_windows_can_play_for_you(rt):
    with pytest.raises(ValueError):
        asyncio.run(autopilot.of(rt).start("Roblox", "", 5))


# ---------------------------------------------------------------- the "…" that was an answer
async def test_dots_are_never_shown_and_an_empty_answer_is_asked_again(rt):
    rt.router = FakeRouter([[("get_time", {})], "...", "Je půl třetí."])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("kolik je hodin")
    deltas = []
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "assistant_delta":
            deltas.append(e["text"])
    assert "..." not in "".join(deltas) and "…" not in out and "půl třetí" in out


async def test_nothing_at_all_says_so_in_words(rt):
    rt.router = FakeRouter(["…", "..."])
    out = await rt.agent.handle("ahoj")
    assert out.strip() not in ("…", "...") and "Zkus to" in out


# ---------------------------------------------------------------- Czech services
@pytest.fixture
def vault(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    for cid in connectors.CONNECTORS:
        connectors.forget(cid)
    return store


def net(monkeypatch, handler):
    seen = []

    def wrap(req):
        seen.append(req)
        return handler(req)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(wrap))
    return seen


def test_shoptet_orders_stock_and_the_token_header(vault, monkeypatch):
    connectors.save("shoptet", {"token": "a" * 32})

    def h(req):
        assert req.headers["Shoptet-Private-API-Token"] == "a" * 32 and "a" * 32 not in str(req.url)
        if req.url.path == "/api/orders":
            assert "%2B" in str(req.url) or "Z" in req.url.params["creationTimeFrom"] or "+" in req.url.params["creationTimeFrom"]
            return httpx.Response(200, json={"data": {"orders": [{"code": "2026000001", "fullName": "Jana", "price": {"withVat": "1210.00",
                                             "currencyCode": "CZK"}, "status": {"name": "Vyřizuje se"}, "paid": False}],
                                             "paginator": {"pageCount": 1}}})
        if req.url.path == "/api/stocks":
            return httpx.Response(200, json={"data": {"stocks": [{"id": 1}], "defaultStockId": 1}})
        if req.url.path == "/api/stocks/1/supplies":
            return httpx.Response(200, json={"data": {"supplies": [{"code": "A", "amount": "2"}, {"code": "B", "amount": "50"},
                                                                   {"code": "C", "amount": None}], "paginator": {"pageCount": 1}}})
        return httpx.Response(401, json={"data": None, "errors": [{"message": "Invalid access token."}]})
    net(monkeypatch, h)
    r = asyncio.run(tools.call("shoptet_orders", {"days": 7}, None))
    assert r.ok and "1210" in r.summary and "nezaplaceno 1" in r.summary and r.data[0]["customer"] == "Jana"
    s = asyncio.run(tools.call("shoptet_stock", {"below": 5}, None))
    assert s.ok and [x["code"] for x in s.data] == ["A"]


def test_zasilkovna_heureka_and_flexi(vault, monkeypatch):
    from jarvis.connectors import heureka, pohoda, zasilkovna

    connectors.save("zasilkovna", {"api_password": "p" * 32})
    connectors.save("flexi", {"url": "firma.flexibee.eu:5434", "company": "moje_firma", "user": "u", "password": "pw"})

    def h(req):
        if req.url.host == "www.zasilkovna.cz":
            body = req.content.decode()
            assert "<apiPassword>" + "p" * 32 in body
            if "<packetId>1234567890<" in body:
                return httpx.Response(200, text="<response><status>ok</status><result><dateTime>2026-11-17T10:00:00</dateTime>"
                                                "<statusCode>5</statusCode><codeText>ready for pickup</codeText><statusText>Připravena</statusText>"
                                                "<storedUntil>2026-11-24</storedUntil><isReturning>false</isReturning></result></response>")
            return httpx.Response(200, text="<response><status>fault</status><fault>PacketIdFault</fault><string>x</string></response>")
        if req.url.host == "firma.flexibee.eu":
            assert req.url.path.startswith("/c/moje_firma/faktura-vydana/(") and "storno" in req.url.path
            return httpx.Response(200, json={"winstrom": {"faktura-vydana": [{"kod": "FV1", "nazFirmy": "Beran", "sumCelkem": "1210.0",
                                                                             "mena": "code:CZK", "zbyvaUhradit": "1210.0", "datSplat": "2026-11-01+01:00"}]}})
        return httpx.Response(404)
    net(monkeypatch, h)
    r = asyncio.run(tools.call("zasilkovna_status", {"packets": ["Z 123 456 7890", "Z999"]}, None))
    assert r.ok and r.data[0]["code"] == 5 and r.data[0]["stored_until"] == "2026-11-24" and "nezná" in r.data[1]["error"]
    with pytest.raises(connectors.ServiceError):
        zasilkovna.parse(b"<response><status>fault</status><fault>IncorrectApiPasswordFault</fault></response>")
    f = asyncio.run(tools.call("flexi_invoices", {"overdue": True, "query": "Beran'); drop"}, None))
    assert f.ok and f.data[0]["currency"] == "CZK" and f.data[0]["left"] == 1210.0
    assert heureka.parse('<reviews><review><rating_id>1</rating_id><total_rating>2</total_rating><cons>pozdě</cons></review>'
                         '<review><rating_id>2</rating_id><delivery_time>5</delivery_time><web_usability>4</web_usability></review></reviews>')[1] \
        == {"rating_id": "2", "delivery_time": 5.0, "web_usability": 4.0}
    assert heureka.score({"delivery_time": 5.0, "web_usability": 4.0}) == 4.5
    with pytest.raises(connectors.ServiceError):
        heureka.parse("ERROR: invalid key")
    with pytest.raises(connectors.ServiceError):
        heureka.parse('<!DOCTYPE x [<!ENTITY a "b">]><reviews/>')
    xml = ('<?xml version="1.0" encoding="Windows-1250"?><rsp:responsePack xmlns:rsp="r" state="ok"><rsp:responsePackItem state="ok">'
           '<lst:listInvoice xmlns:lst="l"><lst:invoice><inv:invoiceHeader xmlns:inv="i"><inv:number><typ:numberRequested xmlns:typ="t">FV2026001'
           '</typ:numberRequested></inv:number><inv:date>2026-11-01</inv:date><inv:dateDue>2026-11-15</inv:dateDue><inv:partnerIdentity>'
           '<typ:address xmlns:typ="t"><typ:company>Beran s.r.o.</typ:company></typ:address></inv:partnerIdentity></inv:invoiceHeader>'
           '<inv:invoiceSummary xmlns:inv="i"><inv:homeCurrency><typ:priceNone xmlns:typ="t">100</typ:priceNone><typ:priceHighSum xmlns:typ="t">1210'
           '</typ:priceHighSum></inv:homeCurrency></inv:invoiceSummary></lst:invoice></lst:listInvoice></rsp:responsePackItem></rsp:responsePack>')
    inv = pohoda.parse(xml.encode("cp1250"))
    assert inv == [{"number": "FV2026001", "date": "2026-11-01", "due": "2026-11-15", "company": "Beran s.r.o.", "ico": "", "vs": "", "text": "",
                    "total": 1310.0}]
    with pytest.raises(connectors.ServiceError):
        pohoda.parse(b'<rsp:responsePack xmlns:rsp="r" state="error" note="Chybne ICO"/>')
    assert "invoiceType=\"issuedInvoice\"" in pohoda.request_xml("issuedInvoice", dt.date(2026, 1, 1)).decode("cp1250")


def test_gopay_and_comgate(vault, monkeypatch):
    from jarvis.connectors import gopay

    connectors.save("gopay", {"goid": "8123456789", "client_id": "cid", "client_secret": "sec"})
    connectors.save("comgate", {"merchant": "123456", "secret": "s"})
    gopay.AUTH.forget()

    def h(req):
        if req.url.path == "/api/oauth2/token":
            assert req.headers["Authorization"].startswith("Basic ") and b"scope=payment-all" in req.content
            return httpx.Response(200, json={"access_token": "T", "expires_in": 1800})
        if req.url.path == "/api/payments/payment/3000000001":
            return httpx.Response(200, json={"id": 3000000001, "order_number": "OBJ-1", "state": "PAID", "amount": 121000, "currency": "CZK"})
        if req.url.path == "/api/accounts/account-statement":
            assert json.loads(req.content)["goid"] == 8123456789
            return httpx.Response(200, text="Datum;Částka;Popis\n2026-11-17;1210,00;Platba OBJ-1\n", headers={"content-type": "text/csv"})
        if req.url.host == "payments.comgate.cz":
            if req.url.path.endswith("/method.json"):
                return httpx.Response(400, json={"error": {"code": 1400, "message": "Unauthorized access!"}})
            return httpx.Response(200, json=[{"ID Comgate": "AB12", "Potvrzená částka": "1 210,00", "Poplatek celkem": "12,10", "Měna": "CZK"}])
        return httpx.Response(404)
    net(monkeypatch, h)
    p = asyncio.run(tools.call("gopay_payment", {"payment_id": "3000000001"}, None))
    assert p.ok and p.data["amount"] == 1210.0 and p.data["state_cz"] == "zaplaceno"
    s = asyncio.run(tools.call("gopay_statement", {"days": 7}, None))
    assert s.ok and s.data[0]["Popis"] == "Platba OBJ-1"
    t = asyncio.run(connectors.test(None, "comgate"))
    assert not t["ok"] and "nepřijal" in t["detail"]
    c = asyncio.run(tools.call("comgate_transfer_payments", {"transfer_id": 5}, None))
    assert c.ok and c.data[0]["amount"] == 1210.0 and c.data[0]["fee"] == 12.1


def test_czech_services_are_registered_read_only_and_findable():
    for cid in ("shoptet", "zasilkovna", "heureka", "gopay", "comgate", "flexi", "pohoda"):
        assert cid in connectors.CONNECTORS and connectors.CONNECTORS[cid]["help"]
    for name, spec in tools.REGISTRY.items():
        if connectors.owner(name) in ("shoptet", "zasilkovna", "heureka", "gopay", "comgate", "flexi", "pohoda"):
            assert not spec.danger, name
    assert "shoptet_orders" in bizcompany.BLUEPRINTS["orders_morning"]["tools"]
    assert "zasilkovna_status" in bizcompany.BLUEPRINTS["delivery"]["tools"]
