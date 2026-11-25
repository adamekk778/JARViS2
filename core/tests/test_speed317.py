"""3.17 Rychlost: the voice in pieces, the AI asked before the end of the sentence, the hour-long cache, your tempo,
the speed wizard, the live text by a tiny model."""
from __future__ import annotations

import asyncio
import io

import numpy as np
from conftest import FakeRouter

from jarvis import tools


def _mp3(seconds: float = 1.0, sr: int = 24000) -> bytes:
    import av

    buf = io.BytesIO()
    out = av.open(buf, "w", format="mp3")
    s = out.add_stream("libmp3lame", rate=sr)
    s.layout = "mono"
    t = np.arange(int(sr * seconds)) / sr
    fr = av.AudioFrame.from_ndarray((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(1, -1), format="flt", layout="mono")
    fr.sample_rate = sr
    for p in s.encode(fr):
        out.mux(p)
    for p in s.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


def test_mp3_is_decoded_piece_by_piece():
    from jarvis.voice.streamplay import Mp3Decoder

    data = _mp3(1.0)
    dec = Mp3Decoder()
    got: list[np.ndarray] = []
    first_at = None
    for i in range(0, len(data), 400):                       # as it comes over the network
        blocks = dec.feed(data[i:i + 400])
        if blocks and first_at is None:
            first_at = i + 400
        got += blocks
    got += dec.feed(None)
    total = sum(len(b) for b in got)
    assert dec.rate == 24000 and 0.9 * 24000 <= total <= 1.2 * 24000
    assert first_at is not None and first_at < len(data) / 2           # sound long before the whole sentence is there


def test_streamed_playback_writes_blocks_and_obeys_stop(rt, monkeypatch):
    import queue
    import sys
    import threading
    import types

    from jarvis.voice import streamplay

    written = []

    class Out:
        def __init__(self, **kw):
            self.kw = kw

        def start(self):
            pass

        def write(self, b):
            written.append(len(b))

        def stop(self):
            pass

        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(OutputStream=Out))
    sp = types.SimpleNamespace(_stop=threading.Event(), on_first_sound=None)
    heard = []
    sp.on_first_sound = lambda: heard.append(1)
    q: queue.Queue = queue.Queue()
    data = _mp3(0.5)
    for i in range(0, len(data), 500):
        q.put(data[i:i + 500])
    q.put(None)
    assert streamplay.play_queue(sp, q, rt) is True and sum(written) > 10000 and heard == [1]
    sp._stop.set()
    q2: queue.Queue = queue.Queue()
    q2.put(data)
    q2.put(None)
    assert streamplay.play_queue(sp, q2, rt) is False


async def test_speaker_streams_the_first_sentence(rt, monkeypatch):
    from jarvis.voice import streamplay, tts

    rt.update_config({"voice": {"tts_engine": "edge", "effect": "none"}})
    sp = tts.Speaker(rt)
    assert sp.can_stream()
    chunks = [_mp3(0.3)[i:i + 300] for i in range(0, len(_mp3(0.3)), 300)]

    async def fake_edge(text, voice, rate, pitch, volume):
        for c in chunks:
            await asyncio.sleep(0)
            yield c
    monkeypatch.setattr(streamplay, "edge_chunks", fake_edge)
    monkeypatch.setattr(streamplay, "play_queue", lambda speaker, q, rt_, g=1.0: _drain(q))
    assert await sp.stream_and_play("Dobrý den, pane.") is True
    rt.update_config({"voice": {"effect": "robot"}})
    assert not sp.can_stream()                                         # a studio effect needs the whole sentence


def _drain(q) -> bool:
    n = 0
    while True:
        x = q.get(timeout=5)
        if x is None:
            return n > 0
        n += 1


async def test_ai_asked_before_the_end_is_used_when_the_words_stay(rt):
    tools.load_builtin()
    rt.router = FakeRouter(["Austrálie má hlavní město Canberra."])
    assert await rt.agent.speculate("jaké je hlavní město Austrálie")
    await asyncio.sleep(0.05)
    assert rt.agent._spec["done"] and len(rt.router.calls) == 1
    out = await rt.agent.handle("jaké je hlavní město Austrálie", source="voice")
    assert "Canberra" in out and len(rt.router.calls) == 1               # no second request: the early one was used
    from jarvis import latency

    assert latency.get(rt).turns[-1]["info"].get("speculative") == 1


async def test_ai_asked_before_the_end_is_dropped_when_you_go_on(rt):
    tools.load_builtin()
    rt.router = FakeRouter(["Canberra.", "Sydney je největší město."])
    await rt.agent.speculate("jaké je hlavní město Austrálie")
    await asyncio.sleep(0.05)
    out = await rt.agent.handle("jaké je hlavní město Austrálie a které je největší", source="voice")
    assert "Sydney" in out and len(rt.router.calls) == 2


async def test_ai_ahead_never_runs_a_tool_early(rt):
    tools.load_builtin()
    rt.router = FakeRouter([[("get_time", {})], "Je tolik."])
    await rt.agent.speculate("řekni mi přesný čas v Tokiu prosím pěkně")
    await asyncio.sleep(0.05)
    assert rt.agent._spec["chunks"] and rt.agent._spec["chunks"][-1].tool_calls    # the AI wants a tool…
    assert not getattr(rt.agent, "_turn_calls", [])                     # …but nothing ran
    rt.agent.cancel_spec()
    assert rt.agent._spec is None


async def test_no_speculation_for_secrets_or_commands(rt):
    tools.load_builtin()
    rt.router = FakeRouter([])
    assert not await rt.agent.speculate("pusť hudbu")                    # an instant command: no need
    rt.update_config({"voice": {"speculate": False}})
    assert not await rt.agent.speculate("jaké je hlavní město Austrálie")


def test_one_hour_cache_marks():
    from jarvis.llm.claude import convert, convert_tools, mark_cache
    from jarvis.config import Config
    from jarvis.prompt import build_system_prompt

    system, msgs = convert([{"role": "system", "content": build_system_prompt(Config(), [], False, "")},
                            {"role": "user", "content": "ahoj"}])
    tl = convert_tools([tools.REGISTRY["get_time"].schema()] if tools.REGISTRY else [])
    mark_cache(tl, system, msgs, "1h")
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert all("cache_control" not in t for t in tl)                     # longer entries first: no 5-minute tool mark
    assert msgs[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


async def test_cache_stats_in_diagnostics(rt):
    from jarvis import diagnostics

    rt.router.cache_stats = {"claude": {"in": 200, "cache_read": 1800, "cache_write": 0, "requests": 6}}
    assert diagnostics.cache_stats(rt) == [{"provider": "claude", "requests": 6, "from_cache_pct": 90, "written_pct": 0, "tokens": 2000}]


def test_your_tempo(rt):
    from jarvis.voice import fastear

    p = fastear.Pace(rt)
    assert p.silence(0.6) == 0.6                                        # not enough pauses yet
    for x in [0.3, 0.35, 0.4, 0.45, 0.5] * 4:
        p.record(x)
    assert p.silence(0.6) == 0.65                                       # p90 0.5 + 0.15
    p.save()
    assert fastear.Pace(rt).pauses[-1] == 0.5                           # kept
    q = fastear.Pace(rt)
    q.pauses = [0.15] * 30
    assert q.silence(0.6) == 0.45                                       # quick speaker: shorter, never below 0.45
    rt.update_config({"voice": {"adaptive_pace": False}})
    assert q.silence(0.6) == 0.6


def test_speculator_reports_pauses_and_unsure_words():
    from jarvis.voice import fastear
    from jarvis.voice.text import Endpointer

    pauses, unsure, stale = [], [], []
    ep = Endpointer(0.08, 0.6)
    sp = fastear.Speculator(lambda b: "hm jo", 2, 0.6)
    sp.on_pause, sp.on_unsure, sp.on_stale = pauses.append, unsure.append, (lambda: stale.append(1))
    audio = bytearray()
    for speech in [True] * 5 + [False] * 4:
        audio += b"x" * 10
        ep.feed(speech)
        sp.step(ep, audio, speech)
        if sp.fut is not None:
            sp.fut.result()
            sp.step(ep, audio, speech)
    assert unsure == ["hm jo"]
    for speech in [True] * 2:
        audio += b"x" * 10
        ep.feed(speech)
        sp.step(ep, audio, speech)
    assert pauses and abs(pauses[0] - 0.32) < 0.01 and stale == [1]
    sp.close()


async def test_speed_wizard(rt, monkeypatch):
    from jarvis import speedwizard

    monkeypatch.setattr(speedwizard, "_cuda", lambda: True)

    async def ollama(rt_):
        return ["llama3:8b"]
    monkeypatch.setattr(speedwizard, "_ollama_models", ollama)
    recs = {r["id"]: r for r in await speedwizard.recommendations(rt)}
    assert not recs["stt_gpu"]["done"] and recs["reflex"]["pull"] == "qwen3:1.7b"
    pulled = []

    class Local:
        async def pull(self, name):
            pulled.append(name)
            return True
    rt.local = Local()
    ok, text = await speedwizard.apply(rt, "reflex")
    assert ok and pulled == ["qwen3:1.7b"] and rt.cfg.brain.reflex_model == "qwen3:1.7b"
    ok, _ = await speedwizard.apply(rt, "stt_gpu")
    assert ok and rt.cfg.voice.stt_provider == "local" and rt.cfg.voice.stt_download_ok
    assert (await speedwizard.apply(rt, "nonsense"))[0] is False


def test_live_text_uses_the_tiny_model(rt, monkeypatch):
    from jarvis.voice import loop as vloop

    made = []

    class FakeTr:
        def __init__(self, cfg):
            made.append(cfg.stt_model)

        def transcribe(self, pcm, sr=16000, prompt=""):
            return "ahoj"
    monkeypatch.setattr(vloop, "Transcriber", FakeTr)
    vl = vloop.VoiceLoop.__new__(vloop.VoiceLoop)
    vl.rt = rt
    vl.clean_utterance = lambda b, np_: b
    assert vl._partial_stt(b"\x00\x00" * 100, np) == "ahoj" and made == ["tiny"]
    vl._partial_stt(b"\x00\x00" * 100, np)
    assert made == ["tiny"]                                              # made once
