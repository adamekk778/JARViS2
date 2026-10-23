import io
import wave

import pytest

from jarvis.voice.text import Endpointer, parse_yes_no, strip_markdown


def test_strip_markdown():
    s = strip_markdown("## Výsledek\n**Tučně** a [odkaz](https://x.cz)\n```py\nprint(1)\n```\n- bod")
    assert "**" not in s and "#" not in s and "print" not in s and "odkaz" in s and "bod" in s


def test_yes_no():
    assert parse_yes_no("Ano, proveď to") is True
    assert parse_yes_no("jo") is True
    assert parse_yes_no("ne, nech to být") is False
    assert parse_yes_no("co je za počasí") is None


def test_endpointer():
    ep = Endpointer(0.08, silence_s=0.8, no_speech_s=1.0)
    for _ in range(5):
        assert ep.feed(True) is None
    out = [ep.feed(False) for _ in range(10)]
    assert out.index("done") == 9
    ep2 = Endpointer(0.08, no_speech_s=0.4)
    res = [ep2.feed(False) for _ in range(5)]
    assert res[-1] == "timeout"


async def test_tts_falls_back_to_piper(rt, monkeypatch):
    from jarvis.voice import tts

    async def boom(*a, **k):
        raise RuntimeError("offline")

    def fake_piper(text, voice):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 100)
        return buf.getvalue()

    monkeypatch.setattr(tts, "edge_synth", boom)
    monkeypatch.setattr(tts, "piper_synth", fake_piper)
    audio, mime = await tts.Speaker(rt).synth("Ahoj")
    assert mime == "audio/wav" and audio[:4] == b"RIFF"
    pcm, sr = tts.decode_to_pcm(audio)
    assert sr == 22050 and len(pcm) == 100


def test_pcm_to_wav_roundtrip():
    from jarvis.voice.stt import pcm_to_wav

    wav = pcm_to_wav(b"\x01\x00" * 160, 16000)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 160


def test_voice_note_from_phone(rt):
    """Phone sends a recorded voice note → it is transcribed on the PC and goes to the agent."""
    from conftest import FakeRouter
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    class FakeSTT:
        def transcribe_file(self, path):
            return "pusť hudbu"

    class FakeVoice:
        transcriber = FakeSTT()

    rt.voice = FakeVoice()
    rt.router = FakeRouter(["Pouštím hudbu."])
    with TestClient(create_app(rt), client=("127.0.0.1", 1)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "hello", "client": "mobile"})
            aid = c.post("/api/upload", files={"file": ("hlas.webm", b"\x1aE\xdf\xa3....", "audio/webm")}).json()["id"]
            ws.send_json({"type": "voice_upload", "attachment_id": aid})
            got = None
            for _ in range(60):
                m = ws.receive_json()
                if m["type"] == "user_message":
                    got = m
                if m["type"] == "assistant_done":
                    break
            assert got["text"] == "pusť hudbu" and got["source"] == "mobile_voice"


@pytest.mark.parametrize("old_api", [True, False])
def test_wakeword_loader_compat(monkeypatch, old_api):
    import sys
    import types

    calls = {}

    class Model:
        def __init__(self, **kw):
            if old_api and "wakeword_models" in kw:
                raise TypeError("unexpected")
            calls.update(kw)

    oww = types.ModuleType("openwakeword")
    oww.models = {"hey_jarvis": {"model_path": "/m/hey_jarvis.onnx"}}
    oww.utils = types.SimpleNamespace(download_models=lambda names: None)
    mod = types.ModuleType("openwakeword.model")
    mod.Model = Model
    monkeypatch.setitem(sys.modules, "openwakeword", oww)
    monkeypatch.setitem(sys.modules, "openwakeword.model", mod)
    from jarvis.voice.loop import load_wakeword

    load_wakeword("hey_jarvis")
    assert ("wakeword_model_paths" in calls) == old_api
