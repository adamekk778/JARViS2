"""3.14 Mozek a roboti: night learning, the life timeline, missions over days, what-if, vacuum / mower, the drone."""
import asyncio
import datetime as dt
import json
import time

import httpx
import pytest
from conftest import FakeRouter

from jarvis import lifelog, nightlearn, quests, robots, tools, whatif

tools.load_builtin()


# ---------------------------------------------------------------------------------------------- 52
async def test_night_learning_keeps_lessons_and_tells_the_morning(rt):
    m = rt.memory
    m.add_message("user", "pusť mi ranní playlist")
    m.add_message("assistant", "Pouštím Ranní kávu na YouTube.")
    m.add_message("user", "ne, myslel jsem na Spotify, ne YouTube")
    m.add_message("user", "převeď mi tohle video na gif")
    m.add_message("assistant", "To neumím, nemám nástroj na převod videa.")
    c = nightlearn.cases(rt, time.time() - 3600)
    assert c["corrections"][0]["asked"] == "pusť mi ranní playlist" and "Spotify" in c["corrections"][0]["correction"]
    assert c["cant"][0]["asked"] == "převeď mi tohle video na gif"
    rt.router = FakeRouter([json.dumps({"lessons": ["Hudbu pouštět na Spotify, ne na YouTube"],
                                        "skill_ideas": [{"name": "Video na GIF", "what": "převede krátké video na GIF"}],
                                        "fixes": []}, ensure_ascii=False)])
    r = await nightlearn.run(rt)
    assert r["lessons"] == ["Hudbu pouštět na Spotify, ne na YouTube"]
    assert any("Spotify" in f["text"] for f in rt.memory.facts())
    line = nightlearn.morning_line(rt)
    assert line.startswith("V noci jsem se naučil: Hudbu pouštět na Spotify") and "„Video na GIF“" in line
    rt.router = FakeRouter([json.dumps({"lessons": ["Hudbu pouštět na Spotify, ne na YouTube"]})])
    await nightlearn.run(rt)
    assert sum("Spotify" in f["text"] for f in rt.memory.facts()) == 1          # the same lesson only once
    r = await tools.call("night_learn", {}, rt)
    assert r.ok and "Spotify" in r.summary


# ---------------------------------------------------------------------------------------------- 53
@pytest.fixture
def vault(monkeypatch):
    from jarvis import secrets

    store: dict = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    return store


def test_life_timeline_is_encrypted_and_skips_private_windows(rt, vault):
    rt.cfg.privacy.life_log = True
    rec = lifelog.Recorder(rt)
    t0 = dt.datetime(2026, 11, 17, 9, 0).timestamp()
    for i in range(0, 31):                                     # an hour in VS Code on one file, then the bank, then Chrome
        rec.step(t0 + i * 120, {"app": "Code", "title": "budget.py – Projekt X"}, 5)
    rec.step(t0 + 62 * 60, {"app": "Chrome", "title": "Internetové bankovnictví – Fio banka"}, 5)
    for i in range(0, 10):
        rec.step(t0 + 64 * 60 + i * 120, {"app": "Chrome", "title": "GitHub – pull requests"}, 5)
    rec.step(t0 + 90 * 60, {"app": "Chrome", "title": "GitHub – pull requests"}, 6 * 60)   # left 6 min ago → flushed
    lifelog.add(rt, "note", {"text": "dokončil jsem návrh rozpočtu"}, t0 + 3000)
    raw = rt.db.all("SELECT data FROM life")
    assert raw and all(b"budget" not in bytes(r["data"]) and b"rozpo" not in bytes(r["data"]) for r in raw)   # encrypted
    s = lifelog.day_summary(rt, dt.date(2026, 11, 17))
    assert [a["app"] for a in s["apps"]] == ["Code", "Chrome"] and s["apps"][0]["titles"] == ["budget.py – Projekt X"]
    assert all("bankovnictví" not in t for a in s["apps"] for t in a["titles"])
    text = lifelog.describe_day(s)
    assert text.startswith("Úterý 17. 11.: u PC od 09:00") and "Code 1 h" in text and "dokončil jsem návrh rozpočtu" in text
    assert lifelog.wipe(rt) == len(raw) and lifelog.entries(rt, dt.date(2026, 11, 17)) == []


def test_parse_day():
    today = dt.date(2026, 11, 24)                              # a Tuesday
    assert lifelog.parse_day("včera", today) == dt.date(2026, 11, 23)
    assert lifelog.parse_day("minulé úterý", today) == dt.date(2026, 11, 17)
    assert lifelog.parse_day("v pondělí", today) == dt.date(2026, 11, 23)
    assert lifelog.parse_day("předminulý pátek", today) == dt.date(2026, 11, 13)
    assert lifelog.parse_day("12. 11.", today) == dt.date(2026, 11, 12)
    assert lifelog.parse_day("30. 12.", today) == dt.date(2025, 12, 30)
    assert lifelog.parse_day("nevím kdy", today) is None


async def test_life_tools_need_your_yes(rt, vault):
    r = await tools.call("life_day", {"day": "včera"}, rt)
    assert "vypnutá" in r.summary
    r = await tools.call("life_log_set", {"action": "on", "days": 30}, rt)
    assert rt.cfg.privacy.life_log and rt.cfg.privacy.life_log_days == 30
    assert tools.REGISTRY["life_log_set"].danger_if({"action": "wipe"}) and not tools.REGISTRY["life_log_set"].danger_if({"action": "on"})
    r = await tools.call("life_note", {"text": "první poznámka"}, rt)
    assert r.ok
    r = await tools.call("life_day", {"day": "dnes"}, rt)
    assert "první poznámka" in r.summary


# ---------------------------------------------------------------------------------------------- 54
def test_quest_answer_parsing():
    r = quests.parse("Prošel jsem Sreality.\nPOZNÁMKY: viděno 3 byty, nejlevnější 5,8 mil.\nZPRÁVA: Nový byt 2+kk Brno-střed za 5,6 mil.\nHOTOVO: ne")
    assert r == {"notes": "viděno 3 byty, nejlevnější 5,8 mil.", "report": "Nový byt 2+kk Brno-střed za 5,6 mil.", "done": False}
    assert quests.parse("POZNÁMKY: nic nového\nZPRÁVA: nic\nHOTOVO: ano")["report"] == ""
    assert quests.parse("POZNÁMKY: x\nZPRÁVA: nic\nHOTOVO: ano")["done"]


async def test_quest_runs_over_days(rt):
    q = quests.start(rt, "hlídej byty 2+kk v Brně do 6 mil.", every_h=6, days=3, now=1000.0)
    prompts = []

    async def handle(text, attachments=None, source="chat", record_user=True, extra_system="", **kw):
        prompts.append((text, extra_system))
        return "POZNÁMKY: viděl jsem byty A, B\nZPRÁVA: Nový byt C za 5,9 mil.\nHOTOVO: ne"

    rt.agent.handle = handle
    said = []
    rt.notify = lambda title, text, **kw: said.append((title, text))
    assert quests.due(quests.get(rt, q["id"]), 1000.0)
    await quests.step(rt, quests.get(rt, q["id"]), now=1000.0)
    q2 = quests.get(rt, q["id"])
    assert q2["runs"] == 1 and q2["notes"] == "viděl jsem byty A, B" and "nic nekupuj" in prompts[0][1]
    assert said[-1] == ("Mise: hlídej byty 2+kk v Brně do 6 mil.", "Nový byt C za 5,9 mil.")
    assert not quests.due(q2, 1000.0 + 3600) and quests.due(q2, 1000.0 + 6 * 3600)
    await quests.step(rt, q2, now=1000.0 + 6 * 3600)
    assert "viděl jsem byty A, B" in prompts[1][0] and "den 1 z 3" in prompts[1][0]
    r = await tools.call("quest_stop", {"which": "byty"}, rt)
    assert r.ok and quests.listing(rt) == []
    r = await tools.call("quest_start", {"goal": "sleduj zprávy o fúzi", "every_hours": 0.1, "days": 500}, rt)
    assert r.ok and r.data["every_h"] == 1.0 and r.data["until"] - r.data["created"] <= 60 * 86400 + 1


# ---------------------------------------------------------------------------------------------- 55
def test_what_if_numbers_are_exact():
    s = whatif.savings(5000, 15, 7)
    r = 0.07 / 12
    closed = 5000 * ((1 + r) ** 180 - 1) / r
    assert abs(s["final"] - closed) < 1 and s["paid"] == 900_000
    ln = whatif.loan(4_000_000, 5, 30)
    assert abs(ln["payment"] - 21_472.86) < 0.05 and ln["points"][-1][1] < 1
    t = whatif.time_budget(60, 2)
    assert round(t["per_year_h"]) == 365 and round(t["total_h"]) == 730
    p = whatif.project([{"name": "návrh", "best": 2, "likely": 4, "worst": 10}, {"name": "vývoj", "best": 5, "likely": 8, "worst": 20}])
    assert p["naive"] == 12 and p["p50"] > 12 and p["p50"] < p["p80"] < p["p95"] <= 30 and p["chance_naive"] < 50
    out = whatif.run("savings", {"monthly": 5000, "years": 15, "rate_pct": 5}, {"rate_pct": 8})
    assert "rozdíl" in out["text"] and out["svg"].startswith("<svg") and "<script" not in out["svg"] and "8 % ročně" in out["svg"]


async def test_what_if_tool_returns_a_chart(rt):
    r = await tools.call("what_if", {"kind": "loan", "amount": 4_000_000, "rate_pct": 5, "years": 30, "b_rate_pct": 4}, rt)
    assert r.ok and "Splátka 21 473 Kč" in r.summary and "méně" in r.summary
    r = await tools.call("what_if", {"kind": "project"}, rt)
    assert not r.ok


# ---------------------------------------------------------------------------------------------- 57 vacuum + mower
async def test_vacuum_rooms_and_mower_confirmation(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda k: "t" if k == "ha_token" else "")
    calls = []

    def handler(req: httpx.Request):
        if req.url.path == "/api/states":
            return httpx.Response(200, json=[
                {"entity_id": "vacuum.roborock", "state": "docked", "attributes": {"friendly_name": "Roborock", "battery_level": 92}},
                {"entity_id": "lawn_mower.automower", "state": "docked", "attributes": {"friendly_name": "Automower"}}])
        calls.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json=[])

    rt.transport = httpx.MockTransport(handler)
    rt.update_config({"home": {"url": "http://ha.local:8123", "vacuum_rooms": {"Kuchyň": [16, 17]}}})
    r = await tools.call("robots_status", {}, rt)
    assert "Roborock stojí v doku, baterie 92 %" in r.summary and "Automower stojí v doku" in r.summary
    r = await tools.call("vacuum_control", {"action": "clean", "room": "kuchyni"}, rt)
    assert r.ok and calls[-1] == ("/api/services/vacuum/send_command",
                                  {"entity_id": "vacuum.roborock", "command": "app_segment_clean", "params": [16, 17]})
    r = await tools.call("vacuum_control", {"action": "clean", "room": "garáž"}, rt)
    assert calls[-1][0] == "/api/services/vacuum/start" and "nemám přiřazenou" in r.summary
    await tools.call("vacuum_control", {"action": "dock"}, rt)
    assert calls[-1][0] == "/api/services/vacuum/return_to_base"
    spec = tools.REGISTRY["mower_control"]
    assert spec.danger_if({"action": "start"}) and not spec.danger_if({"action": "dock"})


# ---------------------------------------------------------------------------------------------- 58 the drone
class FakeTello:
    def __init__(self, battery=80, refuse=()):
        self.sent = []
        self.battery = battery
        self.refuse = set(refuse)

    def __call__(self, cmd):
        self.sent.append(cmd)
        if cmd == "battery?":
            return str(self.battery)
        return "error" if cmd.split()[0] in self.refuse else "ok"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def test_drone_limits():
    link, clock = FakeTello(battery=20), Clock()
    d = robots.Drone(link, clock)
    with pytest.raises(robots.DroneError, match="25 %"):
        await d.takeoff()                                          # too little battery
    link.battery = 80
    assert "Vzlétl" in await d.takeoff() and d.height == 80
    assert await d.move("up", 300) == "Letím nahoru 70 cm." and d.height == 150      # capped at 1,5 m
    assert "Výš nepoletím" in await d.move("up", 50)
    assert await d.move("forward", 500) == "Letím dopředu 100 cm."                   # at most 1 m a move
    assert await d.move("left", 5) == "Letím doleva 20 cm."                          # the SDK's minimum
    await d.land()
    assert link.sent[-1] == "land" and not d.flying
    with pytest.raises(robots.DroneError):
        await d.move("up", 50)                                     # not flying


async def test_drone_lands_on_errors_and_after_two_minutes():
    link, clock = FakeTello(refuse=("forward",)), Clock()
    d = robots.Drone(link, clock)
    await d.takeoff()
    d._stop_guard()
    with pytest.raises(robots.DroneError):
        await d.move("forward", 50)
    assert link.sent[-1] == "land" and not d.flying                # any error → land
    link.refuse = set()
    await d.takeoff()
    d._stop_guard()
    clock.t += 10
    assert await d.guard_step() == "alive" and link.sent[-1] == "battery?"     # keeps the link alive
    clock.t += robots.MAX_FLIGHT_S
    assert await d.guard_step() == "landed" and link.sent[-1] == "land"


async def test_room_tour_and_the_tool_asks_first(rt):
    link = FakeTello()
    rt._drone = robots.Drone(link, Clock())
    spec = tools.REGISTRY["drone"]
    assert spec.danger_if({"action": "takeoff"}) and spec.danger_if({"action": "emergency"}) and not spec.danger_if({"action": "land"})
    msg = await rt._drone.room_tour(80)
    assert "80 × 80" in msg
    assert link.sent == ["command", "battery?", "takeoff"] + ["forward 80", "cw 90"] * 4 + ["land"]
    r = await tools.call("drone", {"action": "status"}, rt)
    assert r.ok and "baterie 80 %" in r.summary
    r = await tools.call("drone", {"action": "fly to mars"}, rt)
    assert not r.ok
    await asyncio.sleep(0)
