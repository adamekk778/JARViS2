"""3.14 JARVIS v celém domě: satellites, speakers, welcome home, other PCs, electricity prices."""
import datetime as dt
import json

import httpx
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis import energy, house, nodes, tools

tools.load_builtin()


def app_for(rt):
    from jarvis.server.app import create_app

    return create_app(rt, manage_runtime=False)


def test_satellite_speaks_ollama_and_openai(rt):
    from jarvis.server.houseroutes import satellite_key

    key = satellite_key(rt)
    rt.router = FakeRouter(["Rozsvítil jsem v kuchyni.", "Je 21 stupňů."])
    c = TestClient(app_for(rt), client=("192.168.1.50", 50000))
    assert c.get(f"/ha/{key}/kuchyn/api/tags").json()["models"][0]["name"] == "jarvis"
    r = c.post(f"/ha/{key}/kuchyn/api/chat", json={"model": "jarvis", "stream": False,
                                                    "messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "rozsviť"}]})
    assert r.json()["message"]["content"].startswith("Rozsvítil") and r.json()["done"]
    assert house.of(rt).room == "kuchyn"
    system = rt.router.calls[0]["messages"][0]["content"]
    assert "satelitu" in system and "kuchyn" in system
    r = c.post(f"/ha/{key}/obyvak/v1/chat/completions", json={"messages": [{"role": "user", "content": "kolik je stupňů"}]})
    assert r.json()["choices"][0]["message"]["content"].startswith("Je 21")


def test_satellite_stream_and_guards(rt):
    from jarvis.server.houseroutes import satellite_key

    key = satellite_key(rt)
    rt.router = FakeRouter(["Ahoj."])
    c = TestClient(app_for(rt), client=("192.168.1.50", 50000))
    r = c.post(f"/ha/{key}/kuchyn/api/chat", json={"messages": [{"role": "user", "content": "ahoj"}]})
    lines = [json.loads(x) for x in r.text.strip().splitlines()]
    assert lines[0]["message"]["content"].startswith("Ahoj") and lines[-1]["done"]
    assert c.get("/ha/spatny-klic/kuchyn/api/tags").status_code == 404
    outside = TestClient(app_for(rt), client=("8.8.8.8", 50000))
    assert outside.get(f"/ha/{key}/kuchyn/api/tags").status_code == 404        # only the home network


async def test_announce_in_jarvis_voice_through_home_assistant(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda name: "ha-token" if name == "ha_token" else "")
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.url.path, json.loads(req.content or b"{}")))
        return httpx.Response(200, json=[])

    rt.transport = httpx.MockTransport(handler)
    rt.update_config({"home": {"url": "http://ha.local:8123", "speakers": ["media_player.obyvak"],
                               "room_speakers": {"Kuchyň": "media_player.kuchyn"}}})

    class Spk:
        speaking = False

        async def synth(self, text, lang="cs", override=None):
            return b"ID3fake", "audio/mpeg"

    rt.speaker = Spk()
    r = await tools.call("house_announce", {"text": "Večeře je hotová", "where": "kuchyň"}, rt)
    assert r.ok
    path, body = calls[-1]
    assert path == "/api/services/media_player/play_media" and body["entity_id"] == ["media_player.kuchyn"]
    tid = body["media_content_id"].rsplit("/", 1)[1].split(".")[0]
    assert house.audio_for(tid) == (b"ID3fake", "audio/mpeg")
    c = TestClient(app_for(rt))
    assert c.get(f"/tts/{tid}.mp3").content == b"ID3fake"
    await tools.call("house_announce", {"text": "Všichni ke stolu"}, rt)
    assert calls[-1][1]["entity_id"] == ["media_player.obyvak", "media_player.kuchyn"]
    rt.update_config({"home": {"tts_entity": "tts.piper"}})
    await tools.call("house_announce", {"text": "Test"}, rt)
    assert calls[-1][0] == "/api/services/tts/speak" and calls[-1][1]["message"] == "Test"


async def test_welcome_home_after_being_away(rt):
    h = house.of(rt)
    spoken = []
    rt.speak = lambda text, *a, **k: spoken.append(text)
    events = []
    q = rt.bus.subscribe()
    h.phone_home = lambda: False
    assert await h.tick(now=1000.0) == ""
    rt.notices.appendleft({"title": "Balík doručen", "body": "x", "ts": 2000.0})
    h.phone_home = lambda: True
    assert await h.tick(now=1000.0 + 10 * 60) == ""                 # 10 min away: no fuss
    h.phone_home = lambda: False
    await h.tick(now=1700.0)
    h.phone_home = lambda: True
    assert await h.tick(now=1700.0 + 45 * 60) == "arrived"
    assert spoken and spoken[-1].startswith("Vítejte doma") and "Balík doručen" in spoken[-1]
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e["type"] == "phone_zone" and e["event"] == "enter" for e in events)


def test_where_you_are(rt):
    h = house.of(rt)
    rt.platform.idle_seconds = lambda: 5
    assert h.where() == "pc"
    rt.platform.idle_seconds = lambda: 900
    h.note_room("kuchyn")
    assert h.where() == "room:kuchyn"


def test_house_scenes_added_once(rt):
    added = house.ensure_scenes(rt)
    assert set(added) == {"domu", "kino", "odchod", "spanek"}
    rt.update_config({"stark": {"protocols": [p.model_dump() for p in rt.cfg.stark.protocols if p.id != "kino"]}})
    assert house.ensure_scenes(rt) == []                              # deleted on purpose: not brought back


class FakeWS:
    def __init__(self, script):
        self.script, self.sent = list(script), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def recv(self):
        return json.dumps(self.script.pop(0))


async def test_node_ask_relays_confirmations_here(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda name: "secret-key" if name == "node:herni pc" else "")
    monkeypatch.setattr(secrets, "set", lambda name, value: None)
    nodes.add(rt, "herní PC", "http://192.168.1.20:8765", "", "AA:BB:CC:DD:EE:FF")
    assert "token" not in rt.cfg.home.nodes[0]                       # the key is not in the settings
    ws = FakeWS([{"type": "welcome"}, {"type": "confirm_request", "id": "c1", "tool": "system_power", "args": {"action": "shutdown"}},
                 {"type": "assistant_done", "text": "Vypínám."}])
    asked = []

    async def confirm(call, **k):
        asked.append(call.name)
        return True

    rt.agent._ask_confirm = confirm
    seen_url = []
    r = await nodes.ask(rt, nodes.find(rt, "herni pc"), "vypni počítač", connect=lambda url: seen_url.append(url) or ws)
    assert r["ok"] and r["answer"] == "Vypínám." and asked == ["system_power"]
    assert ws.sent[1] == {"type": "user_text", "text": "vypni počítač", "attachments": []}
    assert ws.sent[2] == {"type": "confirm_response", "id": "c1", "approved": True}
    assert seen_url[0] == "ws://192.168.1.20:8765/ws?token=secret-key"
    assert nodes.mac_ok("AA:BB:CC:DD:EE:FF") and not nodes.mac_ok("nic")


def test_spot_prices_and_cheapest_window():
    data = {"hoursToday": [{"hour": h, "priceEur": 100, "priceCZK": 2500 if h not in (3, 4) else 900, "level": "low"} for h in range(24)],
            "hoursTomorrow": [{"hour": h, "priceEur": 80, "priceCZK": 2000 if h not in (2, 3) else 500, "level": "low"} for h in range(24)]}
    items = energy.parse(data, dt.date(2026, 11, 24))
    assert len(items) == 48 and items[3]["czk_kwh"] == 0.9
    now = dt.datetime(2026, 11, 24, 21, 15)
    w = energy.cheapest_window(items, 2, now, dt.datetime(2026, 11, 25, 7, 0))
    assert w["start"] == dt.datetime(2026, 11, 25, 2, 0) and w["avg"] == 0.5
    w = energy.cheapest_window(items, 2, dt.datetime(2026, 11, 24, 0, 30))
    assert w["start"] == dt.datetime(2026, 11, 25, 2, 0)              # tomorrow's 0.5 beats today's 0.9
    s = energy.summary(items, now)
    assert s["now"]["hour"] == 21 and s["cheapest"][0]["czk_kwh"] == 0.5 and s["tomorrow"]


async def test_energy_plan_schedules_at_the_cheapest_hour(rt, monkeypatch):
    data = {"hoursToday": [{"hour": h, "priceEur": 1, "priceCZK": 3000} for h in range(24)],
            "hoursTomorrow": [{"hour": h, "priceEur": 1, "priceCZK": 400 if h == 4 else 3000} for h in range(24)]}
    monkeypatch.setattr(energy, "_CACHE", {"at": 0.0, "data": None})
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    added = []

    class Sched:
        def add(self, spec, kind, args, title):
            added.append((spec, args))
            return {"id": "j1", "title": title, "spec_text": "jednou"}

    rt.scheduler = Sched()
    r = await tools.call("energy_plan", {"what": "zapni zásuvku pračky", "hours": 1}, rt)
    assert r.ok and "04:00 zítra" in r.summary
    assert added[0][1] == {"prompt": "zapni zásuvku pračky"}
