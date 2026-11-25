"""3.14 návrh 31: Úplně offline – status, prepare only on request, the round-trip test."""
import io
import wave

import numpy as np

from conftest import FakeRouter
from jarvis import offlinepack


def _wav(text):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes((np.zeros(22050) * 0).astype(np.int16).tobytes())
    return buf.getvalue()


async def test_status_lists_sizes(rt, monkeypatch):
    async def st():
        return {"running": True, "installed": [], "recommended": ["qwen3:8b"]}
    monkeypatch.setattr(rt.local, "status", st)
    monkeypatch.setattr(offlinepack, "_stt_ready", lambda rt: False)
    monkeypatch.setattr(offlinepack, "_piper_ready", lambda rt: True)
    s = await offlinepack.status(rt)
    keys = {p["key"]: p for p in s["parts"]}
    assert not s["ready"] and keys["llm"]["model"] == "qwen3:8b" and keys["llm"]["size_gb"] == 5.2
    assert s["download_gb"] == round(5.2 + keys["stt"]["size_gb"], 2)


async def test_prepare_pulls_and_switches(rt, monkeypatch):
    async def st():
        return {"running": True, "installed": [], "recommended": ["qwen3:4b"]}
    pulled = []

    async def pull(name):
        pulled.append(name)
        return True
    monkeypatch.setattr(rt.local, "status", st)
    monkeypatch.setattr(rt.local, "pull", pull)
    monkeypatch.setattr(offlinepack, "_stt_ready", lambda rt: True)
    monkeypatch.setattr(offlinepack, "_piper_ready", lambda rt: True)
    res = await offlinepack.prepare(rt, switch=True)
    assert pulled == ["qwen3:4b"] and not res["errors"] and rt.cfg.brain.offline_only
    assert rt.cfg.voice.stt_provider == "local" and rt.cfg.voice.tts_engine == "piper"


async def test_round_trip(rt, monkeypatch):
    from jarvis.voice import stt, tts

    monkeypatch.setattr(tts, "piper_synth", lambda text, voice, custom=False: _wav(text))
    monkeypatch.setattr(stt.Transcriber, "_run", lambda self, audio, prompt="": "hlasitost na 30 procent")
    rt.router = FakeRouter(["5"])
    res = await offlinepack.test(rt)
    by = {i["key"]: i for i in res["items"]}
    assert by["tts"]["ok"] and by["stt"]["ok"] and by["command"]["ok"] and by["llm"]["ok"] and res["ok"]
