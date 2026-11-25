"""3.14 Oči a uši: EDITH, screen buddy, faces, sounds of the house, the sky."""
import time

import httpx
import numpy as np
import pytest
from conftest import FakeRouter

from jarvis import eyes, faces, tools

tools.load_builtin()
JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="


async def test_edith_sends_the_frame_to_a_seeing_ai(rt):
    rt.router = FakeRouter(["Je to router TP-Link Archer C6."])
    out = await eyes.edith(rt, JPEG, "identify")
    assert out.startswith("Je to router")
    call = rt.router.calls[0]
    assert call["need_vision"] and call["messages"][0]["content"][1]["image_url"]["url"] == JPEG
    assert "Pojmenuj" in call["messages"][0]["content"][0]["text"]
    rt.router = FakeRouter(["Výstup"])
    await eyes.edith(rt, JPEG, "see", "kolik to stojí?")
    assert "kolik to stojí" in rt.router.calls[0]["messages"][0]["content"][0]["text"]
    with pytest.raises(ValueError):
        await eyes.edith(rt, "http://evil/x.png")
    from jarvis import shield

    assert any(r["tool"] == "edith" for r in shield.recent(rt)["rows"])


async def test_screen_buddy_speaks_only_when_it_sees_a_problem(rt):
    from jarvis import vision

    b = eyes.buddy(rt)
    b.MIN_GAP_S = 0
    img = np.zeros((200, 300, 3), dtype="uint8")
    tip = "V buňce B4 děláš dělení nulou – oprav vzorec."
    rt.router = FakeRouter(["OK", tip, tip])
    assert await b.look(vision.to_png(img)) == ""                  # "OK" = nothing to say
    assert await b.look(vision.to_png(img)) == "" and len(rt.router.calls) == 1   # the same screen: not asked again
    img2 = img.copy()
    img2[50:150, 50:250] = 255
    assert await b.look(vision.to_png(img2)) == tip
    img3 = img2.copy()
    img3[:, :100] = 128
    assert await b.look(vision.to_png(img3)) == ""                  # the same tip is not repeated


def test_smoke_alarm_and_crash_are_recognised():
    sr = 16000
    t = np.arange(int(sr * 0.25)) / sr
    quiet = np.random.default_rng(1).normal(0, 0.002, len(t)).astype("float32")
    beep = (0.5 * np.sin(2 * np.pi * 3150 * t)).astype("float32")
    sw = eyes.SoundWatch()
    for _ in range(8):
        assert sw.feed(quiet, now=0.0) == ""
    out = [sw.feed(beep, now=1.0 + i * 0.5) for i in range(4)]
    assert out.count("smoke_alarm") == 1                             # three beeps → once
    crash = np.random.default_rng(2).normal(0, 0.6, len(t)).astype("float32")
    sw2 = eyes.SoundWatch()
    for _ in range(8):
        sw2.feed(quiet, now=0.0)
    assert sw2.feed(crash, now=5.0) == "crash"
    speech = (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32")  # a voice in the room is not an alarm
    sw3 = eyes.SoundWatch()
    for _ in range(8):
        sw3.feed(quiet, now=0.0)
    assert all(sw3.feed(speech, now=6.0 + i) == "" for i in range(5))


def test_faces_matching_logic(tmp_path):
    p = faces.People(tmp_path)
    a = list(np.random.default_rng(1).normal(size=128))
    b = list(np.random.default_rng(2).normal(size=128))
    p.add("Adam", [a])
    near = list(np.asarray(a) + np.random.default_rng(3).normal(0, 0.1, 128))
    assert p.who(near)[0] == "Adam"
    assert p.who(b)[0] == ""                                         # a stranger
    assert faces.People(tmp_path).people.keys() == {"Adam"}          # saved
    assert p.forget("adam") and p.people == {}


async def test_faces_say_when_not_set_up(rt):
    r = await tools.call("who_is_here", {}, rt)
    assert not r.ok and "nastav rozpoznávání" in r.summary


def test_planes_around_and_bearing():
    states = [["abc123", "CSA123 ", "Czech Republic", 0, 0, 14.50, 50.10, 9000.0, False, 220.0, 90, 0, None, 9100.0, None, False, 0],
              ["def456", "RYR9  ", "Ireland", 0, 0, 16.60, 49.20, 11000.0, False, 230.0, 90, 0, None, None, None, False, 0],
              ["ground", "TAXI", "Czech Republic", 0, 0, 14.26, 50.10, 0.0, True, 5.0, 0, 0, None, 0, None, False, 0]]
    out = eyes.planes(states, 50.08, 14.43, 40)
    assert [p["callsign"] for p in out] == ["CSA123"] and out[0]["alt_m"] == 9100 and out[0]["dir"] in ("severovýchod", "východ")
    assert eyes.distance_km(50.08, 14.43, 49.19, 16.61) == pytest.approx(185, abs=5)


async def test_sky_overhead_tool(rt):
    def handler(req: httpx.Request):
        if req.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"latitude": 50.08, "longitude": 14.43}]})
        if req.url.host == "opensky-network.org":
            return httpx.Response(200, json={"time": 1, "states": [
                ["abc123", "CSA123 ", "Czech Republic", 0, 0, 14.50, 50.10, 9000.0, False, 220.0, 90, 0, None, 9100.0, None, False, 0]]})
        return httpx.Response(200, json={"latitude": 10.0, "longitude": 20.0, "visibility": "daylight"})

    rt.transport = httpx.MockTransport(handler)
    r = await tools.call("sky_overhead", {}, rt)
    assert r.ok and "CSA123" in r.summary and "ISS" in r.summary


async def test_sound_watch_modes(rt):
    r = await tools.call("sound_watch", {"mode": "away"}, rt)
    assert r.ok and rt.cfg.home.sound_watch == "away"
    w = eyes.sounds(rt)
    from jarvis import house

    house.of(rt).home = False
    assert w.wanted()
    house.of(rt).home = True
    assert not w.wanted()
    await tools.call("sound_watch", {"mode": "off"}, rt)
    assert not w.wanted()
    _ = time
