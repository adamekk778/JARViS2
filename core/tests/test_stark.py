"""3.2 Stark: protocols, the morning briefing, the guardian."""
import asyncio
import datetime as dt

from conftest import FakeRouter, drain

from jarvis import config, stark, tools
from jarvis.config import ProtocolStep, Protocol


def test_default_protocols_and_lookup(rt):
    assert [p.id for p in rt.cfg.stark.protocols] == ["rano", "prace", "hry", "party", "noc"]
    assert stark.find_protocol(rt, "párty").id == "party"
    assert stark.find_protocol(rt, "Protokol PARTY").id == "party"
    assert stark.find_protocol(rt, "noc").id == "noc"
    assert stark.find_protocol(rt, "herni rezim").id == "hry"
    assert stark.find_protocol(rt, "neexistuje") is None and stark.find_protocol(rt, "") is None


def test_every_default_step_uses_a_real_tool(rt):
    for p in rt.cfg.stark.protocols:
        for s in p.steps:
            assert not s.tool or s.tool in tools.REGISTRY, (p.id, s.tool)


async def test_protocol_runs_steps_without_ai_and_skips_pause_when_nothing_plays(rt):
    rt.router = FakeRouter([])            # no AI call allowed
    rt.media_state = {"playing": False}
    q = rt.bus.subscribe()
    text = await stark.run_protocol(rt, stark.find_protocol(rt, "noc"))
    assert "Dobrou noc" in text
    calls = [c[0] for c in rt.platform.calls]
    assert "media_key" not in calls                      # nothing was playing → no play/pause toggle
    assert ("set_dark_mode", True) in rt.platform.calls and rt.platform.volume == 15
    ev = drain(q)
    assert [e["text"] for e in ev if e["type"] == "user_message"] == ["▶ Protokol Dobrou noc"]
    done = next(e for e in ev if e["type"] == "assistant_done")
    assert [t["name"] for t in done["tools"]] == ["set_dark_mode", "volume"]
    assert rt.router.calls == []


async def test_protocol_pauses_music_when_playing(rt):
    rt.media_state = {"playing": True}
    await stark.run_protocol(rt, stark.find_protocol(rt, "prace"))
    assert ("media_key", "play_pause") in rt.platform.calls


async def test_protocol_ask_step_goes_to_the_ai(rt):
    rt.router = FakeRouter(["Pouštím lo-fi."])
    p = Protocol(id="x", name="Test", steps=[ProtocolStep(say="Jdeme na to."), ProtocolStep(ask="pusť lo-fi")])
    out = await stark.run_protocol(rt, p)
    assert "Jdeme na to." in out and "Pouštím lo-fi." in out
    assert rt.router.calls[0]["messages"][-1]["content"] == "pusť lo-fi"


async def test_dangerous_step_still_needs_confirmation(rt):
    p = Protocol(id="off", name="Vypnout", steps=[ProtocolStep(tool="system_power", args={"action": "shutdown"})])
    task = asyncio.create_task(stark.run_protocol(rt, p))
    q = rt.bus.subscribe()
    for _ in range(50):
        await asyncio.sleep(0.02)
        if rt.agent.pending_confirm():
            break
    cid = rt.agent.pending_confirm()
    assert cid, "the shutdown step must ask first"
    rt.agent.confirm(cid, False)
    text = await task
    assert not any(c[0] == "power" for c in rt.platform.calls) and "Nepovedlo se" in text


async def test_run_protocol_tool_starts_it_after_the_answer(rt):
    rt.router = FakeRouter([[("run_protocol", {"name": "herní režim"})], "Spouštím herní režim."])
    q = rt.bus.subscribe()
    await rt.agent.handle("spusť herní režim")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if rt.platform.volume == 60:
            break
    assert rt.platform.volume == 60
    assert any(e["type"] == "protocol" and e["id"] == "hry" for e in drain(q))


async def test_briefing_offline_still_speaks_like_jarvis(rt, monkeypatch):
    async def no_weather(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr("jarvis.tools.weather.fetch_weather", no_weather)
    rt.cfg = config.apply_patch(rt.cfg, {"general": {"address_as": "pane"}})
    b = await stark.briefing(rt, dt.datetime(2026, 10, 26, 7, 30), news=False)
    assert b["text"].startswith("Dobré ráno, pane. Je pondělí 26. října, 07:30.")
    assert "Na dnešek nemáte nic naplánováno." in b["text"]
    assert "weather" not in b


async def test_briefing_with_weather_rain_and_plans(rt, monkeypatch):
    async def weather(ctx, city):
        return {"city": "Praha", "temp": 11.6, "desc": "zataženo", "days": [{"max": 15.2, "min": 6, "rain_pct": 70}]}

    monkeypatch.setattr("jarvis.tools.weather.fetch_weather", weather)
    now = dt.datetime.now().replace(hour=8, minute=0)
    rt.timers.add(600, "Pizza")
    b = await stark.briefing(rt, now, news=False)
    assert "V Praha je 12 °C a zataženo, přes den až 15 °C a 70 % šance na déšť" in b["text"]
    assert "Pizza" in b["text"]


def test_briefing_due_once_per_morning(rt):
    morning = dt.datetime(2026, 10, 26, 8, 0)
    assert stark.briefing_due(rt, morning)
    assert not stark.briefing_due(rt, morning.replace(hour=14))
    stark.briefing_done(rt, morning)
    assert not stark.briefing_due(rt, morning.replace(hour=9))
    assert stark.briefing_due(rt, morning + dt.timedelta(days=1))
    rt.cfg = config.apply_patch(rt.cfg, {"stark": {"briefing_auto": False}})
    assert not stark.briefing_due(rt, morning + dt.timedelta(days=2))


def test_guardian_battery_once_per_level_and_reset_on_charge():
    st, cfg = stark.GuardState(), config.Stark()
    snap = {"battery_percent": 19, "charging": False, "cpu_percent": 5, "ram_percent": 40, "disk_free_gb": 100}
    assert [a[0] for a in stark.evaluate(st, snap, 0, cfg)] == ["battery"]
    assert stark.evaluate(st, {**snap, "battery_percent": 15}, 20, cfg) == []
    assert "kriticky" not in stark.evaluate(st, {**snap, "battery_percent": 9}, 40, cfg)[0][2]
    assert "kriticky" in stark.evaluate(st, {**snap, "battery_percent": 4}, 60, cfg)[0][2]
    stark.evaluate(st, {**snap, "charging": True, "battery_percent": 30}, 80, cfg)
    assert [a[0] for a in stark.evaluate(st, {**snap, "battery_percent": 20}, 100, cfg)] == ["battery"]


def test_guardian_cpu_needs_two_minutes_and_has_cooldown():
    st, cfg = stark.GuardState(), config.Stark()
    hot = {"cpu_percent": 97, "ram_percent": 40, "top_cpu": "chrome.exe"}
    alerts = [stark.evaluate(st, hot, i * 20, cfg) for i in range(6)]
    assert alerts[:5] == [[]] * 5 and alerts[5][0][0] == "cpu" and "chrome.exe" in alerts[5][0][2]
    assert stark.evaluate(st, hot, 140, cfg) == []                     # cooldown
    assert stark.evaluate(st, hot, 120 + 1800, cfg)[0][0] == "cpu"
    st2 = stark.GuardState()
    spiky = [stark.evaluate(st2, {"cpu_percent": c, "ram_percent": 40}, i, cfg) for i, c in enumerate([99, 99, 40, 99, 99, 99])]
    assert all(a == [] for a in spiky)


def test_guardian_disk_daily_and_internet_after_30s():
    st, cfg = stark.GuardState(), config.Stark()
    low = {"cpu_percent": 5, "ram_percent": 40, "disk_free_gb": 2.5}
    assert stark.evaluate(st, low, 0, cfg, today="2026-10-26")[0][0] == "disk"
    assert stark.evaluate(st, low, 10, cfg, today="2026-10-26") == []
    ok = {"cpu_percent": 5, "ram_percent": 40}
    assert stark.evaluate(st, ok, 100, cfg, offline=True) == []
    assert stark.evaluate(st, ok, 120, cfg, offline=True) == []
    assert stark.evaluate(st, ok, 131, cfg, offline=True)[0][0] == "offline"
    assert stark.evaluate(st, ok, 150, cfg, offline=True) == []
    assert stark.evaluate(st, ok, 160, cfg, offline=False)[0][0] == "online"


async def test_boot_greets_or_briefs(rt, monkeypatch):
    said = []
    monkeypatch.setattr(rt, "speak", lambda text, lang="cs": said.append(text))
    rt.cfg = config.apply_patch(rt.cfg, {"stark": {"briefing_auto": False}})
    await stark.boot(rt)
    assert said == ["JARVIS online. Všechny systémy připraveny, pane."]


def test_protocol_ws_and_settings_roundtrip(rt):
    from fastapi.testclient import TestClient
    from jarvis.server.app import create_app

    rt.router = FakeRouter([])
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=("127.0.0.1", 5000)).websocket_connect("/ws") as ws:
        welcome = ws.receive_json()
        assert [p["id"] for p in welcome["settings"]["stark"]["protocols"]][:2] == ["rano", "prace"]
        mine = {"id": "film", "name": "Kino", "icon": "film-strip", "steps": [{"tool": "volume", "args": {"action": "set", "level": 40}},
                                                                               {"say": "Příjemnou zábavu."}]}
        ws.send_json({"type": "settings_set", "patch": {"stark": {"protocols": [mine]}}})
        ws.send_json({"type": "protocol_run", "id": "kino"})
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "assistant_done":
                break
        assert m["text"] == "Příjemnou zábavu." and rt.platform.volume == 40


def test_slow_weather_does_not_freeze_other_messages(rt, monkeypatch):
    """Offline the weather lookup takes up to 15 s; the HUD and the notch must keep working meanwhile."""
    import time
    from fastapi.testclient import TestClient
    from jarvis.server.app import create_app

    async def slow(*a, **k):
        await asyncio.sleep(1.5)
        return {"city": "Praha", "temp": 5, "desc": "jasno", "days": []}

    monkeypatch.setattr("jarvis.tools.weather.fetch_weather", slow)
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)).websocket_connect("/ws") as ws:
        ws.receive_json()
        t0 = time.monotonic()
        ws.send_json({"type": "weather_get"})
        ws.send_json({"type": "timers_get"})
        order = []
        while len(order) < 2:
            m = ws.receive_json()
            if m["type"] in ("weather", "timers"):
                order.append((m["type"], time.monotonic() - t0))
        assert order[0][0] == "timers" and order[0][1] < 1.0 and order[1][0] == "weather"
