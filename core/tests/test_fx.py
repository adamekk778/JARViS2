"""3.15 Mega animace: effects tiers, the frame-rate report, the pause over games, the web unit tests."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from jarvis import config, diagnostics

WEB = Path(__file__).resolve().parents[2] / "web"


async def test_fx_report_reaches_diagnostics(rt):
    from jarvis.server.handlers.fx import fx_report

    class C:
        pass

    c = C()
    c.rt = rt
    await fx_report(c, {"page": "hud", "fps": 58, "tier": "ultra"})
    await fx_report(c, {"page": "notch", "fps": "x", "tier": "high"})          # nonsense is ignored
    await fx_report(c, {"page": "evil<script>", "fps": 60, "tier": "high"})     # unknown windows too
    await fx_report(c, {"page": "dashboard", "fps": 9999, "tier": "warp"})
    stats = diagnostics.fx_stats(rt)
    assert {s["page"] for s in stats} == {"hud", "dashboard"}
    assert next(s for s in stats if s["page"] == "dashboard") ["fps"] == 500 and next(s for s in stats if s["page"] == "dashboard")["tier"] == ""
    assert diagnostics.fx_stats(rt, now=time.time() + 600) == []                # a closed window disappears


def test_fx_quality_setting():
    c = config.Config()
    assert c.appearance.fx_quality == "auto"
    assert "appearance.fx_quality" in config.SETTABLE_BY_VOICE
    c2 = config.apply_patch(c, {"appearance": {"fx_quality": "ultra"}})
    assert c2.appearance.fx_quality == "ultra"
    with pytest.raises(Exception):
        config.apply_patch(c, {"appearance": {"fx_quality": "insane"}})


def test_protocol_knows_the_new_messages():
    from jarvis.server import ws

    assert "fx_report" in ws.CLIENT_TYPES and "fx_pause" in ws.SERVER_TYPES


@pytest.mark.skipif(shutil.which("node") is None or not (WEB / "node_modules").exists(), reason="no node / web deps here")
def test_web_unit_tests():
    files = sorted(str(p) for p in (WEB / "tests" / "unit").glob("*.test.ts"))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--test", *files], cwd=WEB,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


async def test_hud_voice_commands(rt):
    from jarvis import tools

    tools.load_builtin()
    hooks, events = [], []
    rt.ui_hook = hooks.append
    rt.bus.publish = lambda t, **d: events.append((t, d))
    r = await tools.call("hud_control", {"action": "zoom_in"}, rt)
    assert r.ok and hooks == ["hud"] and events[-1] == ("hud_cmd", {"action": "zoom_in"})
    r = await tools.call("hud_control", {"action": "close"}, rt)
    assert r.ok and hooks[-1] == "hud-close" and events[-1][1]["action"] == "zoom_in"     # closing sends no command
    r = await tools.call("hud_control", {"action": "selfdestruct"}, rt)
    assert not r.ok


def test_protocol_event_carries_the_steps(rt):
    from jarvis import stark
    from jarvis.config import Protocol, ProtocolStep

    p = Protocol(id="kino", name="Kino", steps=[ProtocolStep(tool="media_control", args={"action": "play_pause"}),
                                                ProtocolStep(say="Užijte si film, pane."), ProtocolStep(ask="ztlum světla v obýváku")])
    labels = stark.protocol_labels(p)
    assert len(labels) == 3 and labels[1].startswith("„Užijte si film") and labels[2] == "ztlum světla v obýváku"


def test_live_cards():
    from jarvis.livecards import card

    w = card("weather", True, {"city": "Brno", "temp": 3.4, "desc": "déšť", "code": 63,
                               "days": [{"max": 5, "min": 1, "rain_pct": 80}, {"max": 7.2, "min": 2, "rain_pct": 10}]})
    assert w["kind"] == "weather" and w["sky"] == "rain" and w["temp"] == 3.4 and w["days"][0]["rain"] == 80
    assert card("weather", True, {"code": 0})["sky"] == "clear" and card("weather", True, {"code": 73})["sky"] == "snow"
    f = card("flight_status", True, {"trip": {"kind": "flight", "number": "FR 1234", "origin": "PRG", "dest": "BCN"}, "live": {"on_ground": False}})
    assert f == {"kind": "flight", "number": "FR 1234", "from": "Praha", "to": "Barcelona", "flying": True}
    p = card("parcels_list", True, {"parcels": [{"shop": "Alza", "state": "ready"}, {"carrier_name": "PPL", "state": "open"}]})
    assert [i["state"] for i in p["items"]] == ["ready", "open"] and p["items"][1]["name"] == "PPL"
    assert card("now_playing_info", True, {"title": "Song", "artist": "X"})["kind"] == "music"
    assert card("body_status", True, {"level": "easy", "now": {"sleep_h": 5.1, "rest_hr": 66}})["sleep"] == 5.1
    assert card("body_status", True, {"level": "unknown"}) is None
    assert card("weather", False, {"code": 63}) is None and card("open_app", True, {"x": 1}) is None
    assert card("parcels_list", True, {"parcels": []}) is None


async def test_tool_end_carries_the_live_card(rt):
    from conftest import FakeRouter

    from jarvis import tools

    tools.load_builtin()
    seen = []
    orig = rt.bus.publish

    def publish(t, **d):
        if t == "tool_end":
            seen.append((t, d))
        return orig(t, **d)

    rt.bus.publish = publish

    async def fake_weather(ctx, city: str = ""):
        return tools.ToolResult(True, "Brno: déšť", data={"city": "Brno", "temp": 4, "desc": "déšť", "code": 61, "days": []})

    spec = tools.REGISTRY["weather"]
    old = spec.func
    spec.func = fake_weather
    try:
        rt.router = FakeRouter([[("weather", {"city": "Brno"})], "Prší."])
        await rt.agent.handle("jaké je počasí v Brně?", [], "chat")
    finally:
        spec.func = old
    ends = [d for t, d in seen if t == "tool_end"]
    assert ends and ends[-1]["live"]["kind"] == "weather" and ends[-1]["live"]["sky"] == "rain"


def test_motif_setting():
    c = config.apply_patch(config.Config(), {"appearance": {"motif": "mark"}})
    assert c.appearance.motif == "mark" and "appearance.motif" in config.SETTABLE_BY_VOICE


def test_edith_boxes_for_augmented_reality():
    from jarvis.eyes import split_objects

    text, objs = split_objects('Na stole je hrnek a notebook.\nOBJEKTY: [{"label": "hrnek", "box": [0.1, 0.5, 0.25, 0.8]},'
                               ' {"label": "notebook", "box": [0.4, 0.3, 1.4, 0.9]}, {"label": "nic", "box": [0.5, 0.5, 0.5, 0.5]}, {"x": 1}]')
    assert text == "Na stole je hrnek a notebook."
    assert objs == [{"label": "hrnek", "box": [0.1, 0.5, 0.25, 0.8]}, {"label": "notebook", "box": [0.4, 0.3, 1.0, 0.9]}]
    assert split_objects("Jen text bez rámečků.") == ("Jen text bez rámečků.", [])
    assert split_objects("Text\nOBJEKTY: [nejde to přečíst")[1] == []


async def test_edith_answer_carries_objects(rt):
    from conftest import FakeRouter

    from jarvis.server.handlers.voice import edith_ask

    rt.router = FakeRouter(['Je to kytara.\nOBJEKTY: [{"label": "kytara", "box": [0.2, 0.1, 0.8, 0.95]}]'])
    sent = []

    class C:
        async def send(self, t, **d):
            sent.append((t, d))

    c = C()
    c.rt = rt
    await edith_ask(c, {"id": "x1", "image": "data:image/jpeg;base64,AAAA", "mode": "identify"})
    t, d = sent[-1]
    assert t == "edith_answer" and d["text"] == "Je to kytara." and d["objects"][0]["label"] == "kytara"
    assert "OBJEKTY" in rt.router.calls[0]["messages"][0]["content"][0]["text"]


async def test_sos_state_for_the_phone(rt):
    from jarvis import safety

    events = []
    orig = rt.bus.publish
    rt.bus.publish = lambda t, **d: (events.append((t, d)) if t == "emergency_state" else None) or orig(t, **d)
    rt.phone_push = lambda *a, **k: True
    e = safety.emergency(rt)
    await e.start("upadl jsem", wait=30)
    assert events[-1][1]["active"] and events[-1][1]["until"] > 0
    e.cancel()
    import asyncio

    await asyncio.sleep(0.05)
    assert events[-1][1]["active"] is False
