import sys

import pytest
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis import lang

LOCAL = ("127.0.0.1", 5000)


@pytest.mark.parametrize("text,expected", [
    ("Open Spotify and play some music please", "en"),
    ("What time is it in London?", "en"),
    ("otevři Spotify", "cs"),
    ("pusť mi nějakou hudbu", "cs"),
    ("ok", "cs"),
    ("Spotify", "cs"),
])
def test_detect(text, expected):
    assert lang.detect(text) == expected


async def test_agent_english_hint(rt):
    rt.router = FakeRouter(["It is ten o'clock."])
    await rt.agent.handle("what time is it", lang="en")
    assert "Odpověz anglicky" in rt.router.calls[0]["messages"][0]["content"]


async def test_agent_czech_no_hint(rt):
    rt.router = FakeRouter(["Je deset."])
    await rt.agent.handle("kolik je hodin")
    assert "Odpověz anglicky" not in rt.router.calls[0]["messages"][0]["content"]


def test_chat_text_english(rt):
    rt.router = FakeRouter(["Sure."])
    with TestClient(__import__("jarvis.server.app", fromlist=["create_app"]).create_app(rt, manage_runtime=False),
                    client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_text", "text": "Could you please open the calculator for me"})
        for _ in range(60):
            if ws.receive_json()["type"] == "assistant_done":
                break
    assert "Odpověz anglicky" in rt.router.calls[0]["messages"][0]["content"]


def test_tts_voice_choice(rt):
    from jarvis.voice.tts import Speaker

    sp = Speaker(rt)
    assert sp._voice_for("en") == (rt.cfg.voice.tts_voice_en, rt.cfg.voice.piper_voice_en)
    assert sp._voice_for("cs") == (rt.cfg.voice.tts_voice, rt.cfg.voice.piper_voice)


class _StubAgent:
    def __init__(self):
        self.calls = []

    def pending_confirm(self):
        return None


def _loop_with_stub(rt):
    from jarvis.voice.loop import VoiceLoop

    vl = VoiceLoop.__new__(VoiceLoop)
    vl.rt = rt
    vl._confirm_id = None
    vl.followup_active = True
    submitted = []
    rt.submit = lambda coro: (submitted.append(coro), coro.close())
    return vl, submitted


@pytest.mark.parametrize("phrase", ["díky, to je vše", "Stop.", "that's all"])
def test_followup_ends_on_phrase(rt, phrase):
    vl, submitted = _loop_with_stub(rt)
    vl.handle_transcript(phrase, "cs")
    assert submitted == [] and vl.followup_active is False


def test_transcript_goes_to_agent(rt):
    vl, submitted = _loop_with_stub(rt)
    vl.handle_transcript("pusť hudbu", "cs")
    assert len(submitted) == 1


def test_audio_devices_empty_without_sounddevice(monkeypatch):
    from jarvis.voice import devices

    monkeypatch.setitem(sys.modules, "sounddevice", None)
    assert devices.list_devices() == {"inputs": [], "outputs": []}


def test_ws_audio_devices(rt, monkeypatch):
    from jarvis.voice import devices

    monkeypatch.setattr(devices, "list_devices", lambda: {"inputs": ["Mic"], "outputs": ["Repro"]})
    with TestClient(__import__("jarvis.server.app", fromlist=["create_app"]).create_app(rt, manage_runtime=False),
                    client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_devices_get"})
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] == "audio_devices":
                break
        assert m == {"type": "audio_devices", "inputs": ["Mic"], "outputs": ["Repro"]}
        ws.send_json({"type": "voice_mode", "on": True})
        ws.send_json({"type": "ping"})
        for _ in range(30):
            if ws.receive_json()["type"] == "pong":
                break
    assert rt.voice_mode is True
