"""3.13: JARVIS listens on only after an answer to something you said (never after an announcement), the phone on its
charger shows quietly in the notch and can start an automation."""
from conftest import drain
from fastapi.testclient import TestClient

from jarvis.automations import describe_trigger, match_event
from jarvis.config import Automation, AutoTrigger, Config
from jarvis.server.app import create_app

REMOTE = ("192.168.1.50", 5000)


class _Agent:
    def pending_confirm(self):
        return None


class _Ptt:
    def __init__(self):
        self.n = 0

    def set(self):
        self.n += 1


def _loop(rt):
    from jarvis.voice.loop import VoiceLoop

    vl = VoiceLoop.__new__(VoiceLoop)
    vl.rt, vl._confirm_id, vl.followup_active, vl.paused, vl._ptt = rt, None, False, False, _Ptt()
    rt.agent = _Agent()
    return vl


def test_listens_on_only_after_an_answer_to_your_voice(rt):
    rt.cfg.voice.followup = True
    vl = _loop(rt)
    for announcement in ("", "automation", "protocol", "chat"):           # "Napájení připojeno", the greeting, a typed chat
        vl._after_speech(announcement)
    assert vl._ptt.n == 0 and vl.followup_active is False
    vl._after_speech("voice")                                             # "Hey Jarvis, …" → the answer → you may go on
    assert vl._ptt.n == 1 and vl.followup_active is True


def test_without_follow_up_nothing_listens_even_after_a_voice_answer(rt):
    rt.cfg.voice.followup = False
    vl = _loop(rt)
    vl._after_speech("voice")
    assert vl._ptt.n == 0


def test_replies_are_tagged_and_announcements_are_not(rt):
    calls = []

    class Speaker:
        async def say(self, text, lang="cs", reply_to=""):
            calls.append((text, reply_to))

    rt.speaker = Speaker()
    rt.cfg.voice.speak_mode = "always"
    import asyncio

    async def run():
        rt.speak("Napájení připojeno.")
        rt.maybe_speak("Je 16:50.", "voice")
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert ("Napájení připojeno.", "") in calls and ("Je 16:50.", "voice") in calls


def test_phone_plugged_in_shows_quietly_in_the_notch(rt):
    q = rt.bus.subscribe()
    rt.phone.on_battery(60, False)                 # the first report only learns the state
    assert not [e for e in drain(q) if e["type"] in ("phone_event", "phone_power")]
    rt.phone.on_battery(61, True)                  # plugged in
    ev = drain(q)
    notch = [e for e in ev if e["type"] == "phone_event"]
    assert notch and notch[0]["text"] == "Telefon se nabíjí" and notch[0]["pct"] == 61 and notch[0]["kind"] == "power"
    assert any(e["type"] == "phone_power" and e["charging"] for e in ev)
    assert not [e for e in ev if e["type"] in ("toast", "speak")]
    rt.phone.on_battery(99, True)
    rt.phone.on_battery(100, True)                 # full
    assert [e["text"] for e in drain(q) if e["type"] == "phone_event"] == ["Telefon je nabitý"]
    rt.phone.on_battery(100, False)                # unplugged
    assert [e["text"] for e in drain(q) if e["type"] == "phone_event"] == ["Telefon odpojen"]


def test_the_notice_can_be_switched_off_but_automations_still_hear_it(rt):
    rt.cfg.phone_link.notch_events = False
    q = rt.bus.subscribe()
    rt.phone.on_battery(50, False)
    rt.phone.on_battery(50, True)
    ev = drain(q)
    assert not [e for e in ev if e["type"] == "phone_event"] and [e for e in ev if e["type"] == "phone_power"]


def test_the_phone_tells_at_once_through_the_api(rt):
    c = TestClient(create_app(rt, manage_runtime=False), client=REMOTE)
    assert c.post("/api/phone/event", json={"kind": "power", "charging": True, "level": 42}).status_code == 401
    q = rt.bus.subscribe()
    hdr = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    assert c.post("/api/phone/event", json={"kind": "power", "charging": True, "level": 42}, headers=hdr).json() == {"ok": True}
    ev = [e for e in drain(q) if e["type"] == "phone_event"]
    assert ev and ev[0]["right"] == "42 %" and rt.phone.battery["charging"] is True     # even as the first news after start
    assert c.post("/api/phone/event", json={"kind": "power", "charging": True, "level": "x"}, headers=hdr).status_code == 400


def test_phone_triggers_for_automations():
    plug = Automation(id="a", name="Telefon nabíjí", trigger=AutoTrigger(type="phone_power", value="in"))
    unplug = Automation(id="b", name="Telefon pryč", trigger=AutoTrigger(type="phone_power", value="out"))
    low = Automation(id="c", name="Slabý telefon", trigger=AutoTrigger(type="phone_battery", value="20"))
    on = {"type": "phone_power", "charging": True, "level": 64}
    assert match_event(plug, on) == {"percent": 64, "text": "Telefon se nabíjí, 64 %"}
    assert match_event(unplug, on) is None
    assert match_event(unplug, {"type": "phone_power", "charging": False, "level": 90}) is not None
    assert match_event(low, {"type": "phone_battery", "level": 19, "was": 21})["percent"] == 19
    assert match_event(low, {"type": "phone_battery", "level": 18, "was": 19}) is None        # once, when it crosses
    assert describe_trigger(plug.trigger) == "když dám telefon nabíjet"
    assert describe_trigger(low.trigger) == "když baterie telefonu klesne pod 20 %"
    assert Config().phone_link.notch_events is True


def test_the_notch_never_takes_the_focus_from_a_game(rt, monkeypatch):
    """pywebview's show() activates the window – over a full-screen game (Valorant) the game then minimises."""
    from types import SimpleNamespace

    import pytest

    from jarvis.desktop import host as host_mod
    from jarvis.desktop import winutil

    seen = []
    monkeypatch.setattr(winutil, "window_handle", lambda win, title: 4242)
    monkeypatch.setattr(winutil, "find_window", lambda title: 4242)
    monkeypatch.setattr(winutil, "show_quietly", lambda hwnd: seen.append(("show", hwnd)) or True)
    monkeypatch.setattr(winutil, "hide_quietly", lambda hwnd: seen.append(("hide", hwnd)) or True)
    monkeypatch.setattr(winutil, "make_topmost", lambda hwnd: seen.append(("top", hwnd)))
    h = host_mod.DesktopHost(rt, "http://127.0.0.1:8765")
    h.notch = SimpleNamespace(show=lambda: pytest.fail("activating show() used"), hide=lambda: pytest.fail("pywebview hide used"))
    h.toggle_notch(False)
    h.toggle_notch(True)
    assert ("hide", 4242) in seen and ("show", 4242) in seen
