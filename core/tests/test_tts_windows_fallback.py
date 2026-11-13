"""A real PC (3.10.186): the firewall refused JARVIS's internet, Edge and Piper (download) failed and JARVIS was
silent. The voice built into Windows is the offline last resort."""
import asyncio
import sys

from jarvis.voice import tts


def test_windows_voice_is_the_last_resort(rt, monkeypatch):
    async def edge_fail(*a, **k):
        raise RuntimeError("[WinError 10013] přístup k soketu zakázán")

    def piper_fail(*a, **k):
        raise RuntimeError("Piper hlas se nepodařilo stáhnout")

    used = []
    monkeypatch.setattr(tts, "edge_synth", edge_fail)
    monkeypatch.setattr(tts, "piper_synth", piper_fail)
    monkeypatch.setattr(tts, "windows_synth", lambda text, lang="cs": used.append((text, lang)) or b"RIFF" + b"\0" * 2000)
    monkeypatch.setattr(sys, "platform", "win32")
    audio, mime = asyncio.run(tts.Speaker(rt).synth("Dobrý den."))
    assert mime == "audio/wav" and audio.startswith(b"RIFF") and used == [("Dobrý den.", "cs")]


def test_not_offered_off_windows(rt, monkeypatch):
    async def edge_fail(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(tts, "edge_synth", edge_fail)
    monkeypatch.setattr(tts, "piper_synth", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(sys, "platform", "linux")
    try:
        asyncio.run(tts.Speaker(rt).synth("Ahoj."))
        raise AssertionError("expected an error")
    except RuntimeError as e:
        assert "offline" in str(e)
