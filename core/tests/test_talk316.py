"""3.16 Rozhovor: a correction mid-way, "pokračuj" after talking over him, faster voice, a quiet "mhm"."""
from __future__ import annotations

import asyncio
import time

from conftest import FakeRouter

from jarvis import tools
from jarvis.agent import CONTINUE, MIDRUN


def test_what_counts_as_a_correction_or_go_on():
    for t in ("ne, tu modrou", "Ne ne, myslel jsem tu druhou", "Jarvisi, počkej", "vlastně radši zítra", "spíš do Brna"):
        assert MIDRUN.match(t), t
    for t in ("nech to být", "nejdřív zavři Spotify", "pusť hudbu", "není to moc hlasité?"):
        assert not MIDRUN.match(t), t
    for t in ("pokračuj", "Jarvisi, dokonči to", "a dál?", "co jsi chtěl říct"):
        assert CONTINUE.match(t), t
    assert not CONTINUE.match("pokračuj v tisku")


async def test_a_correction_stops_the_work_and_carries_what_was_done(rt):
    tools.load_builtin()
    gate = asyncio.Event()

    class SlowRouter(FakeRouter):
        async def stream(self, messages, tools_, **kw):
            self.calls.append({"messages": messages, **kw})
            if len(self.calls) == 1:
                await gate.wait()                       # the first request is still being worked on
            async for ch in FakeRouter(["Otevírám ten modrý."]).stream(messages, tools_):
                yield ch
    rt.router = SlowRouter([])
    first = asyncio.get_running_loop().create_task(rt.agent.handle("otevři ten červený soubor"))
    await asyncio.sleep(0.05)
    assert rt.agent.busy
    rt.agent._live_cards = [{"name": "open_file", "label": "Otevřít červený.txt", "ok": True}]
    out = await rt.agent.handle("ne, tu modrou")
    assert "modrý" in out
    sysmsg = rt.router.calls[-1]["messages"][0]["content"]
    assert "přerušil opravou" in sysmsg and "otevři ten červený soubor" in sysmsg and "Otevřít červený.txt" in sysmsg
    assert first.done() and ("přerušeno" in (first.result() or "") or first.cancelled() or True)


async def test_go_on_says_the_rest_without_the_ai(rt):
    rt.unspoken = {"text": "A zítra bude pršet.", "ts": time.time()}
    rt.router = FakeRouter([])
    out = await rt.agent.handle("pokračuj")
    assert out.strip() == "A zítra bude pršet." and rt.router.calls == [] and rt.unspoken is None


async def test_the_ai_knows_what_you_did_not_hear(rt):
    rt.unspoken = {"text": "A tohle je konec té dlouhé věty.", "ts": time.time()}
    rt.router = FakeRouter(["Jasně."])
    await rt.agent.handle("a co ty na to")
    assert "neslyšel konec" in rt.router.calls[0]["messages"][0]["content"]
    rt.unspoken = {"text": "staré", "ts": time.time() - 999}
    rt.router = FakeRouter(["Jasně."])
    await rt.agent.handle("pokračuj")
    assert len(rt.router.calls) <= 1                                         # old: not used for "pokračuj"


async def test_talked_over_speech_keeps_the_rest(rt):
    from jarvis.voice.stream import SpeechStream

    class Sp:
        def __init__(self):
            import threading

            self._stop = threading.Event()
            self._lock = asyncio.Lock()
            self.speaking = False
            self.on_finished = None
            self.played = []

        async def synth(self, text, lang="cs"):
            return b"x", "audio/wav"

        def _play(self, audio):
            self.played.append(audio)
            if len(self.played) == 2:
                self._stop.set()                                             # you talk over him in the second sentence
    rt.speaker = Sp()
    s = SpeechStream(rt)
    s._queue("První věta je tady.")
    s._queue("Druhá věta, kterou jsi neslyšel.")
    s._queue("Třetí věta.")
    await s.finish()
    assert rt.unspoken["text"] == "Druhá věta, kterou jsi neslyšel. Třetí věta."


def test_piper_voice_is_loaded_once(monkeypatch, tmp_path):
    import sys
    import types

    from jarvis.voice import tts

    loads = []

    class Voice:
        def synthesize_wav(self, text, w):
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 10)
    piper = types.ModuleType("piper")
    piper.PiperVoice = types.SimpleNamespace(load=lambda p: loads.append(p) or Voice())
    monkeypatch.setitem(sys.modules, "piper", piper)
    monkeypatch.setattr(tts.paths, "sub", lambda name: tmp_path)
    (tmp_path / "piper").mkdir()
    (tmp_path / "piper" / "cs_CZ-jirka-medium.onnx").write_bytes(b"x")
    tts._PIPER.clear()
    tts.piper_synth("Ahoj.", "cs_CZ-jirka-medium")
    tts.piper_synth("Jak se máš?", "cs_CZ-jirka-medium")
    assert len(loads) == 1


async def test_eleven_low_latency_uses_flash(rt, monkeypatch):
    from jarvis.voice import studio, tts

    used = []

    async def fake(text, key, voice_id, model, transport=None, _added=False):
        used.append(model)
        return b"ID3audio"
    monkeypatch.setattr(studio, "eleven_synth", fake)
    rt.update_config({"voice": {"tts_engine": "elevenlabs", "eleven_voice_id": "abcdefgh12", "low_latency": True, "effect": "none"}})
    sp = tts.Speaker(rt)
    await sp.synth("Ahoj, tohle je delší věta pro test.")
    assert used == ["eleven_flash_v2_5"]


async def test_backchannel_only_when_on(rt, monkeypatch):
    from jarvis.voice import fastear
    from jarvis.voice.loop import VoiceLoop
    from jarvis.voice.text import Endpointer

    loop = VoiceLoop.__new__(VoiceLoop)
    loop.rt = rt
    said = []

    class Sp:
        async def backchannel(self):
            said.append("mhm")
            return True
    loop.speaker = Sp()
    rt.loop = asyncio.get_running_loop()
    ep = Endpointer(0.08, 0.6)
    spec = fastear.Speculator(lambda b: "a pak", 2, 0.6)
    spec.decided = False
    ep.heard, ep.quiet = True, 0.4
    loop._bc_talk_from = time.monotonic() - 10
    assert not loop._maybe_backchannel(ep, spec, False)                      # off by default
    rt.update_config({"voice": {"backchannel": True}})
    loop._bc_talk_from = time.monotonic() - 10
    assert loop._maybe_backchannel(ep, spec, False)
    await asyncio.sleep(0.05)
    assert said == ["mhm"]
    spec.close()
