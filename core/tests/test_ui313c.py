"""3.13 round 2: a game menu task ("zapni kompetitivní hru a vyber Jett"), Herní režim, how an automation speaks up,
notice buttons and history, more phone news, talking over JARVIS, calibration, the extra self-checks."""
import asyncio
import json

import numpy as np
from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import NEWS, selfcheck
from jarvis.config import Automation, AutoTrigger, ProtocolStep
from jarvis.server.app import create_app
from jarvis.tools import computer_use as cu

REMOTE = ("192.168.1.50", 5000)


# ---------------------------------------------------------------- a game menu task
async def test_a_game_task_waits_in_the_queue_and_remembers_the_way(rt, monkeypatch, tmp_path):
    monkeypatch.setattr(cu, "_howto_file", lambda: tmp_path / "howto_apps.json")
    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        slept.append(s)
        await real_sleep(0)
    monkeypatch.setattr(cu.asyncio, "sleep", fake_sleep)
    rt.platform.screen_size = lambda: (128, 72)
    rt.router = FakeRouter(['{"action":"click","x":64,"y":10,"why":"PLAY"}', '{"action":"click","x":30,"y":20,"why":"Competitive"}',
                            '{"action":"wait","seconds":25,"why":"fronta"}', '{"action":"click","x":40,"y":60,"why":"Jett"}',
                            '{"action":"click","x":64,"y":66,"why":"LOCK IN"}', '{"action":"done","summary":"Jett zamčená"}'])
    r = await cu.run_computer_task(rt, "zapni kompetitivní hru a vyber Jett", minutes=15, app="Valorant")
    assert r.ok and 25 in slept                                  # it may wait longer than 10 s in the queue
    sys_prompt = rt.router.calls[0][0]["content"] if isinstance(rt.router.calls[0], list) else ""
    saved = cu.saved_steps("valorant")
    assert "Jett" in saved and "LOCK IN" in saved
    # next time the way it worked is in the instructions
    rt.router = FakeRouter(['{"action":"done","summary":"ok"}'])
    await cu.run_computer_task(rt, "zapni kompetitivní hru a vyber Jett", minutes=15, app="Valorant")
    first = rt.router.calls[0]
    text = json.dumps(first, ensure_ascii=False)
    assert "minule v Valorant fungovalo" in text and "LOCK IN" in text and sys_prompt is not None


def test_anti_cheat_note_once_per_game(monkeypatch, tmp_path):
    monkeypatch.setattr(cu, "_howto_file", lambda: tmp_path / "howto_apps.json")
    assert "anti-cheat" in cu.anti_cheat_note("Valorant", "vyber Jett")
    assert cu.anti_cheat_note("Valorant", "vyber Jett") == ""
    assert cu.anti_cheat_note("Excel", "udělej graf") == ""


# ---------------------------------------------------------------- Herní režim
def _playing(rt, monkeypatch):
    from jarvis.desktop import winutil
    from jarvis.tools import apps

    monkeypatch.setattr(winutil, "foreground_is_fullscreen", lambda: True)
    monkeypatch.setattr(apps, "front_is_game", lambda info=None, fullscreen=None: True)
    rt.platform.foreground_info = lambda: {"exe": "VALORANT-Win64-Shipping.exe"}


async def test_while_you_play_announcements_wait_and_come_after_in_one_sentence(rt, monkeypatch):
    _playing(rt, monkeypatch)
    said = []

    class Speaker:
        async def say(self, text, lang="cs", reply_to=""):
            said.append(text)
    rt.speaker = Speaker()
    assert rt.attention.busy_reason() == "hra"
    rt.speak("Napájení připojeno.", announce="Automatizace Nabíječka")         # an automation's line: held
    rt.notify("WhatsApp", "Máma: Přijdeš?")                                       # a notice: held
    await asyncio.sleep(0)
    assert said == [] and len(rt.attention.deferred) == 2
    rt.speak("Je 16:50.", reply_to="voice")                                       # an answer to you: never held
    await asyncio.sleep(0.01)
    assert said == ["Je 16:50."]
    monkeypatch.setattr(rt.attention, "busy_reason", lambda now=None: "")
    s = rt.attention.flush()
    assert s["game"] and s["title"].startswith("Během hry: 2") and "Automatizace Nabíječka" in s["spoken"]


def test_game_quiet_can_be_switched_off(rt, monkeypatch):
    _playing(rt, monkeypatch)
    rt.cfg.voice.game_quiet = False
    assert not rt.attention.deferred
    rt.speak("Napájení připojeno.", announce="Automatizace Nabíječka")
    assert not rt.attention.deferred


# ---------------------------------------------------------------- how an automation speaks up
async def test_an_automation_can_be_quiet_or_go_to_the_phone(rt):
    from jarvis.stark import run_protocol

    spoken, pushed = [], []
    rt.speak = lambda text, lang="cs", reply_to="", announce="": spoken.append((text, announce))
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    a = Automation(id="n", name="Nabíječka", trigger=AutoTrigger(type="power"), steps=[ProtocolStep(say="Napájení připojeno.")], say="notch")
    await run_protocol(rt, a, "Automatizace", say=a.say)
    assert spoken == [] and pushed == []
    await run_protocol(rt, a, "Automatizace", say="phone")
    assert pushed and pushed[0][1]["title"] == "Automatizace Nabíječka" and spoken == []
    await run_protocol(rt, a, "Automatizace", say="voice")
    assert spoken == [("Napájení připojeno.", "Automatizace Nabíječka")]
    assert Automation(id="x", name="x").say == "voice"


# ---------------------------------------------------------------- notice buttons and history
def test_notices_have_buttons_and_a_history(rt):
    q = rt.bus.subscribe()
    rt._timer_fired("Pizza")
    ev = [e for e in drain(q) if e["type"] == "notify"]
    assert ev and [a["label"] for a in ev[0]["actions"]] == ["+5 min", "Ok"]
    assert rt.notices[0]["title"] == "⏲ Pizza"
    c = TestClient(create_app(rt, manage_runtime=False))
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "notices_get"})
        got = ws.receive_json()
        while got["type"] != "notices":
            got = ws.receive_json()
        assert got["items"][0]["title"] == "⏲ Pizza"
        ws.send_json({"type": "notice_action", "action": "timer_more", "args": {"label": "Pizza", "minutes": 5}})
        got = ws.receive_json()
        while got["type"] != "quick_result":
            got = ws.receive_json()
        assert got["ok"] and any(t["label"] == "Pizza" for t in rt.timers.list())


def test_break_snooze_comes_back_in_ten_minutes(rt):
    rt.cfg.powers.break_minutes = 60
    act = rt.activity
    act.snooze_break(10, now=10_000.0)
    assert act._break_said is False and abs((10_000.0 - act._active_since) - 50 * 60) < 1


# ---------------------------------------------------------------- the phone: headphones, Do Not Disturb
def test_headphones_and_do_not_disturb_from_the_phone(rt):
    c = TestClient(create_app(rt, manage_runtime=False), client=REMOTE)
    hdr = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    q = rt.bus.subscribe()
    c.post("/api/phone/event", json={"kind": "headphones", "on": True, "name": "Nothing Ear"}, headers=hdr)
    c.post("/api/phone/event", json={"kind": "dnd", "on": True}, headers=hdr)
    ev = [e for e in drain(q) if e["type"] == "phone_event"]
    assert [(e["text"], e["right"]) for e in ev] == [("Nothing Ear", "Připojeno"), ("Telefon: Nerušit", "Zapnuto")]


# ---------------------------------------------------------------- talking over JARVIS
def test_talking_over_jarvis_stops_it_but_its_own_echo_does_not(rt):
    from jarvis.voice.loop import FRAME, VoiceLoop

    vl = VoiceLoop.__new__(VoiceLoop)
    vl.rt = rt

    class Sp:
        speaking = True
    vl.speaker = Sp()
    vl._floor = 200.0
    loud = (np.sin(np.linspace(0, 400, FRAME)) * 6000).astype(np.int16).tobytes()
    quiet = (np.sin(np.linspace(0, 400, FRAME)) * 300).astype(np.int16).tobytes()
    vl._is_speech = lambda frame, vad, np_: True
    t = 100.0
    assert not vl._talk_over(loud, None, np, now=t)                     # the first moment of its speech: never
    hits = [vl._talk_over(loud, None, np, now=t + 1 + i * 0.08) for i in range(10)]
    assert any(hits) and hits.index(True) >= 6                          # ~0.6 s of clear speech
    vl.speaker.speaking = True
    assert not any(vl._talk_over(quiet, None, np, now=t + 3 + i * 0.08) for i in range(20))   # what is left of its own voice
    rt.cfg.voice.barge_in = False
    assert not any(vl._talk_over(loud, None, np, now=t + 6 + i * 0.08) for i in range(20))


# ---------------------------------------------------------------- self-check, what's new
def test_self_check_covers_wake_word_notch_and_phone(rt):
    keys = {r["key"]: r for r in (selfcheck.wake(rt), selfcheck.notch(rt), selfcheck.phone(rt))}
    assert set(keys) == {"wake", "notch", "phone"}
    assert all(r["ok"] in (True, False, None) and r["detail"] for r in keys.values())
    rt.clients = {"x": {"client": "notch"}}
    assert selfcheck.notch(rt)["ok"] is True


def test_whats_new_shows_the_new_batch(rt):
    import re
    from pathlib import Path

    ts = (Path(__file__).resolve().parents[2] / "web" / "src" / "shared" / "whatsnew.ts").read_text("utf-8")
    newest = re.findall(r'^  "(\d+\.\d+)": \[', ts, re.M)[0]          # the first batch in "Co je nového"
    assert rt.whats_new_due() == NEWS == newest
