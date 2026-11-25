"""3.14 hlas (návrhy 1, 37, 38, 39, 41, 43, 44, 45, 48) on synthetic audio."""
import time

import numpy as np
import pytest

from conftest import FakeRouter
from jarvis import quality, tools
from jarvis.voice import style, voiceid

tools.load_builtin()
SR = 16000
RNG = np.random.default_rng(7)


def voice(f0: float, formants: tuple, seconds: float = 2.0, jitter: float = 0.0) -> np.ndarray:
    """A vowel-like voice: harmonics of f0 shaped by formant peaks, with slow pitch movement and a little noise."""
    t = np.arange(int(SR * seconds)) / SR
    f = f0 * (1 + 0.03 * np.sin(2 * np.pi * (1.3 + jitter) * t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = np.zeros_like(t)
    for k in range(1, 25):
        hz = k * f0
        amp = sum(np.exp(-((hz - fm) / 120) ** 2) for fm in formants) + 0.02
        x += amp * np.sin(k * phase)
    x += 0.01 * RNG.standard_normal(len(t))
    return (0.2 * x / np.max(np.abs(x))).astype(np.float32)


ADAM = [voice(110 + i, (700, 1200, 2500), jitter=i * 0.1) for i in range(5)]
JANA = [voice(220 + i, (400, 2300, 3000), jitter=i * 0.1) for i in range(5)]


def test_profiles_identify(tmp_path):
    p = voiceid.Profiles(tmp_path)
    p.enroll("Adam", ADAM, owner=True)
    p.enroll("Jana", JANA)
    assert p.identify(voice(112, (700, 1200, 2500), jitter=0.33))[0] == "Adam"
    assert p.identify(voice(224, (400, 2300, 3000), jitter=0.33))[0] == "Jana"
    assert p.owner() == "Adam"
    with pytest.raises(ValueError):
        p.enroll("X", ADAM[:2])
    assert voiceid.Profiles(tmp_path).owner() == "Adam"          # saved


def chirp(f_from: float, f_to: float, seconds: float = 0.6) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    f = np.linspace(f_from, f_to, len(t))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.4 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    return (0.3 * x + 0.01 * RNG.standard_normal(len(t))).astype(np.float32)


def test_own_wake_word(tmp_path):
    w = voiceid.WakeWord(tmp_path)
    w.train("Jarvisi", [chirp(300 + i * 5, 900 + i * 5) for i in range(6)])
    assert w.ready and w.word == "Jarvisi"
    assert w.check(chirp(310, 905))[0]
    assert not w.check(chirp(1200, 400))[0]                       # the other way round = another word
    assert voiceid.WakeWord(tmp_path).ready                       # saved
    w.clear()
    assert not voiceid.WakeWord(tmp_path).ready


def test_short_utterance_collector():
    c = voiceid.ShortUtterance(0.08)
    out = None
    for i in range(30):
        out = c.feed(b"\x01\x00" * 10, 3 <= i < 10) or out      # 0.56 s of speech then a pause
    assert out is not None
    c2 = voiceid.ShortUtterance(0.08)
    assert all(c2.feed(b"\x00\x00", True) is None for _ in range(30))   # 2.4 s of talking is not a wake word


def test_whisper():
    assert not voiceid.is_whisper(voice(120, (700, 1200, 2500)))
    noise = (0.05 * RNG.standard_normal(SR * 2)).astype(np.float32)
    assert voiceid.is_whisper(noise)


def test_pronounce_and_tone(rt):
    from jarvis import config

    rt.cfg = config.apply_patch(rt.cfg, {"voice": {"pronounce": [{"src": "JARVIS", "dst": "Džárvis"}]}})
    assert style.pronounce(rt.cfg, "Ahoj, tady JARVIS.") == "Ahoj, tady Džárvis."
    v = rt.cfg.voice
    assert style.prosody(rt, v, hour=23) == ("-8%", "+0Hz", "-20%")
    assert style.prosody(rt, v, hour=7) == ("+5%", "+2Hz", "+0%")
    rt.voiceid.whisper_until = time.monotonic() + 30
    assert style.prosody(rt, v, hour=14)[2] == "-45%"
    rt.cfg.voice.adaptive_tone = False
    rt.voiceid.whisper_until = 0
    assert style.prosody(rt, v, hour=23) == ("+0%", "+0Hz", "+0%")


def test_voice_latency(rt):
    style.mark_end(rt)
    rt.voice_t_end -= 0.8
    style.mark_sound(rt)
    style.mark_sound(rt)                                           # only the first sound counts
    lat = quality.voice_latency(rt)
    assert lat["answers"] == 1 and 750 <= lat["median_ms"] <= 1500


async def test_phrase_routine(rt):
    from jarvis.config import Automation, AutoTrigger, ProtocolStep

    a = Automation(id="sleep", name="Jdu spát", trigger=AutoTrigger(type="phrase", value="jdu spát"),
                   steps=[ProtocolStep(tool="volume", args={"action": "mute"})])
    rt.cfg.automations.items.append(a)
    fired = []
    rt.automations.fire = lambda a, vars=None, reason="", force=False: fired.append((a.id, reason)) or True
    rt.router = FakeRouter(["nic"])
    out = await rt.agent.handle("Jarvisi, jdu spát")
    assert fired == [("sleep", "phrase")] and "Jdu spát" in out and not rt.router.calls
    assert rt.automations.phrase_match("pusť hudbu") is None


async def test_owner_only_by_voice(rt):
    rt.voiceid.profiles.people = {"Adam": {"vec": [1.0], "threshold": 0.9, "owner": True}}
    rt.voiceid.last_speaker, rt.voiceid.last_at = "Jana", time.time()
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "Nemůžu."])
    await rt.agent.handle("vypni počítač", source="voice")
    card = rt.memory.recent(1)[0]["meta"]["tools"][0]
    assert card["ok"] is False and "majitele" in card["summary"]
    assert not rt.agent.pending_confirm()
    rt.voiceid.last_speaker = "Adam"
    assert rt.voiceid.owner_ok()
    assert "Jana" not in rt.voiceid.prompt()


def test_record_frame(rt):
    from jarvis.voice.loop import VoiceLoop

    loop = VoiceLoop(rt)
    seq = [False] * 2 + [True] * 6 + [False] * 6
    it = iter(seq)
    loop._is_speech = lambda frame, vad, np_: next(it)
    import threading

    loop._rec = {"short": True, "buf": bytearray(), "speech": 0.0, "silence": 0.0, "event": threading.Event(), "out": None}
    for _ in seq:
        loop._record_frame(b"\x01\x00" * 1280, None, np)
    assert loop._rec["event"].is_set() and len(loop._rec["out"]) > 0
