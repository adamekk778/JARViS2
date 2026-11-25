"""3.14 Ochrana a nouze: cameras, doorbell, emergency, weekly briefing, kids mode, the guard's photo."""
import asyncio
import json
import time

import httpx
from conftest import FakeRouter

from jarvis import safety, tools

tools.load_builtin()


def test_interesting_camera_events():
    person = {"id": "1", "label": "person", "camera": "vchod", "zones": ["vchod"]}
    assert safety.interesting(person, [], 23, False)                         # at night: every person
    assert not safety.interesting(person, [], 14, False)                     # by day: only watched zones…
    assert safety.interesting(person, ["vchod"], 14, False)
    assert safety.interesting(person, [], 14, True)                          # …or while you are away
    assert not safety.interesting({**person, "label": "cat"}, [], 23, False)
    assert not safety.interesting({**person, "false_positive": True}, [], 23, False)


async def test_frigate_person_comes_with_a_photo(rt):
    def handler(req: httpx.Request):
        if req.url.path == "/api/events":
            return httpx.Response(200, json=[{"id": "e1", "label": "person", "camera": "zahrada", "zones": []},
                                             {"id": "e2", "label": "car", "camera": "vjezd", "zones": []}])
        if req.url.path.endswith("/snapshot.jpg"):
            return httpx.Response(200, content=b"\xff\xd8jpeg")
        return httpx.Response(404)

    rt.transport = httpx.MockTransport(handler)
    rt.update_config({"home": {"frigate_url": "http://frigate.local:5000"}})
    sent = []
    rt.phone_push = lambda kind, **d: sent.append(d) or True
    cams = safety.cameras(rt)
    night = time.mktime((2026, 11, 24, 23, 30, 0, 0, 0, -1))
    told = await cams.check(now=night)
    assert [e["id"] for e in told] == ["e1"] and sent and "zahrada" in sent[0]["body"]
    msgs = rt.memory.recent(5)
    assert msgs and msgs[-1]["attachments"]
    assert await cams.check(now=night + 10) == []                            # the same event is not told twice


async def test_doorbell_rings_once(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda name: "t" if name == "ha_token" else "")
    state = {"v": "off"}

    def handler(req: httpx.Request):
        if req.url.path == "/api/states":
            return httpx.Response(200, json=[{"entity_id": "binary_sensor.zvonek", "state": state["v"], "attributes": {}}])
        return httpx.Response(200, content=b"\xff\xd8")

    rt.transport = httpx.MockTransport(handler)
    rt.update_config({"home": {"url": "http://ha.local:8123", "doorbell_entity": "binary_sensor.zvonek"}})
    rt.phone_push = lambda kind, **d: True
    cams = safety.cameras(rt)
    assert not await cams.doorbell()
    state["v"] = "on"
    assert await cams.doorbell()
    assert not await cams.doorbell()                                          # still pressed: once


async def test_emergency_texts_contacts_when_you_do_not_answer(rt):
    rt.update_config({"privacy": {"emergency_contacts": [{"name": "Máma", "phone": "+420777111222"}]}})
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    e = safety.emergency(rt)
    await e.start("upadl jsem", "https://maps.google.com/?q=50.1,14.4", wait=0.05)
    await asyncio.sleep(0.2)
    sms = [d for k, d in pushed if k == "sms"]
    assert sms and sms[0]["to"] == "+420777111222" and "maps.google.com" in sms[0]["text"] and "upadl" in sms[0]["text"]
    assert e.last["sent"] == ["Máma"]


async def test_emergency_cancelled_in_time(rt):
    rt.update_config({"privacy": {"emergency_contacts": [{"name": "Máma", "phone": "+420777111222"}]}})
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append(kind) or True
    r = await tools.call("emergency_help", {"reason": "je mi zle"}, rt)
    assert r.ok
    ok = await tools.call("emergency_ok", {}, rt)
    assert ok.ok and "ruším" in ok.summary.lower()
    await asyncio.sleep(0.05)
    assert "sms" not in pushed
    done, msg = await rt.notice_action("emergency_ok", {})
    assert done


async def test_kids_mode_blocks_and_guides(rt):
    await tools.call("kids_mode", {"on": True}, rt)
    assert safety.kids_on(rt)
    assert safety.kids_blocks(rt, "app_install", {})
    assert safety.kids_blocks(rt, "home_control", {"target": "zámek dveří", "action": "off"})
    assert not safety.kids_blocks(rt, "weather", {})
    rt.router = FakeRouter([[("app_install", {"name": "Fortnite"})], "Na to se zeptej rodičů."])
    await rt.agent.handle("nainstaluj fortnite", [], "chat")
    system = rt.router.calls[0]["messages"][0]["content"]
    assert "Dětský režim" in system
    tool_msgs = [m for m in rt.router.calls[1]["messages"] if m.get("role") == "tool"]
    assert "dětském režimu" in tool_msgs[-1]["content"]


async def test_weekly_briefing(rt, monkeypatch):
    from jarvis import network

    monkeypatch.setattr(network, "known", lambda rt: {"aa:bb:cc:dd:ee:01"})

    async def devices(rt):
        return [{"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.2", "name": "PC"}, {"mac": "aa:bb:cc:dd:ee:99", "ip": "192.168.1.66", "name": ""}]

    monkeypatch.setattr(network, "devices", devices)
    r = await tools.call("security_briefing", {}, rt)
    assert r.ok and "192.168.1.66" in r.summary


async def test_guard_photo_only_when_switched_on(rt, monkeypatch):
    assert await safety.guard_photo(rt, "Někdo") == ""
    rt.update_config({"privacy": {"guard_photo": True}})
    from jarvis import webcam

    monkeypatch.setattr(webcam, "grab", lambda idx=0: "frame")
    monkeypatch.setattr(webcam, "jpeg", lambda frame, quality=80: b"\xff\xd8photo")
    aid = await safety.guard_photo(rt, "V 22:10 někdo začal používat tvoje PC")
    assert aid and rt.memory.recent(2)[-1]["attachments"] == [aid]
    _ = json
