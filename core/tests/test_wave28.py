"""OMEGA wave 28 (voice and audio): noise suppression, automatic gain, echo cancellation (also lined up in time like
the real player and microphone), double talk, microphone check, speaker labels on synthetic voices (also in call
transcripts), wake-word calibration, ducking other programs, bookmarks and pronunciation practice."""
import json
import wave

import numpy as np
import pytest

from jarvis import media, tools, voiceplus
from jarvis.voice import dsp

tools.load_builtin()
SR = 16000
VOWELS = {"a": (730, 1090, 2440), "e": (530, 1840, 2480), "i": (270, 2290, 3010), "o": (570, 840, 2410), "u": (300, 870, 2240)}


def speechlike(seconds, seed, level=0.5):
    """Band-limited noise with a syllable rhythm – loud and quiet moments like speech."""
    r = np.random.default_rng(seed)
    n = int(seconds * SR)
    s = np.fft.rfft(r.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    s = np.fft.irfft(s * ((f > 200) & (f < 3500)), n) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * np.arange(n) / SR)) ** 2
    return (level * s / np.abs(s).max()).astype(np.float32)


def voice(seconds, f0, tract, seed):
    """A synthetic talker: jittered glottal pulses at f0 through the formants of a run of vowels × tract length."""
    r = np.random.default_rng(seed)
    n, syl = int(seconds * SR), int(0.25 * SR)
    out = np.zeros(n)
    first = int(r.integers(5))
    for k, start in enumerate(range(0, n, syl)):
        m = min(syl, n - start)
        pulses, pos, f = np.zeros(m), 0.0, f0 * (1 + 0.04 * r.standard_normal())
        while pos < m:
            pulses[int(pos)] = 1
            pos += SR / (f * (1 + 0.01 * r.standard_normal()))
        fr = np.fft.rfftfreq(m, 1 / SR)
        env = sum(1 / (1 + ((fr - F * tract) / 90) ** 2) for F in VOWELS["aeiou"[(first + k) % 5]])
        out[start:start + m] = np.fft.irfft(np.fft.rfft(pulses) * env, m) * np.hanning(m)
    return (0.3 * out / np.abs(out).max()).astype(np.float32)


def erle(before, after):
    return 10 * np.log10((before ** 2).mean() / (after ** 2).mean())


def test_noise_suppression_and_gain():
    clean = speechlike(4, 9)
    noise = (0.05 * np.random.default_rng(1).standard_normal(SR * 5)).astype(np.float32)
    y, info = dsp.denoise(clean + noise[:SR * 4], SR, noise[SR * 4:])
    assert info["noise_reduction_db"] > 12
    quiet = np.abs(clean) < 0.01                                         # the pauses: almost only noise
    assert erle(noise[:SR * 4][quiet], y[quiet]) > 8 and np.corrcoef(y, clean)[0, 1] > 0.8
    far, g = dsp.agc(clean * 0.02, SR)
    assert g["gain_db"] > 15 and np.abs(far).max() <= 10 ** (-1 / 20) + 1e-6
    loud, g2 = dsp.agc(np.clip(clean * 4, -1, 1), SR)
    assert g2["gain_db"] < 0 and np.abs(loud).max() <= 0.9


def _room(far, seed=0, delay=40):
    rng = np.random.default_rng(seed)
    ir = np.zeros(1200)
    ir[delay] = 0.6
    ir[delay:1200] += rng.standard_normal(1200 - delay) * 0.08 * np.exp(-np.arange(1200 - delay) / 200)
    return np.convolve(far, ir)[:len(far)].astype(np.float32)


def test_echo_canceller_and_double_talk():
    far = speechlike(6, 1)
    mic = _room(far) + 0.001 * np.random.default_rng(2).standard_normal(len(far)).astype(np.float32)
    a = dsp.EchoCanceller()
    out = np.concatenate([a.process(mic[i:i + 256], far[i:i + 256]) for i in range(0, len(mic) - 255, 256)])
    assert erle(mic[4 * SR:], out[4 * SR:]) > 25
    near = speechlike(2, 5, 0.3)
    mic2 = mic.copy()
    mic2[3 * SR:5 * SR] += near
    b = dsp.EchoCanceller()
    out2 = np.concatenate([b.process(mic2[i:i + 256], far[i:i + 256]) for i in range(0, len(mic2) - 255, 256)])
    seg = slice(3 * SR + SR // 2, 5 * SR)
    assert np.corrcoef(out2[seg], near[SR // 2:])[0, 1] > 0.8          # the person talking over JARVIS survives


def test_delay_estimate():
    far = speechlike(1, 3)
    d, conf = dsp.gcc_phat(np.concatenate([np.zeros(1600, np.float32), far])[:SR], far, 8000)
    assert d == 1600 and conf > 5


def test_echo_path_lines_up_player_and_microphone():
    """The player writes 24 kHz chunks; the sound card adds 120 ms; the microphone hears the room 50 ms later still."""
    ep = dsp.EchoPath(SR)
    far24 = np.interp(np.linspace(0, SR * 5 - 1, 24000 * 5), np.arange(SR * 5), speechlike(5, 11)).astype(np.float32)
    far16 = np.interp(np.linspace(0, len(far24) - 1, SR * 5), np.arange(len(far24)), far24).astype(np.float32)
    device = int(0.12 * SR)
    mic = _room(np.concatenate([np.zeros(device, np.float32), far16])[:SR * 5], delay=800)
    t0, out = 100.0, []
    for i in range(0, SR * 5, 1280):
        t = t0 + i / SR
        ep.played(far24[int(i * 1.5):int((i + 1280) * 1.5)], 24000, t)
        out.append(ep.clean(mic[i:i + 1280], t))
    out = np.concatenate(out)
    assert ep.delay is not None and abs(ep.delay - device) < 300
    assert erle(mic[3 * SR:], out[3 * SR:]) > 15
    assert np.array_equal(ep.clean(mic[:1280], t0 + 60), mic[:1280])       # long after JARVIS spoke: untouched


def test_mic_report():
    good = speechlike(3, 4) + 0.0005 * np.random.default_rng(0).standard_normal(SR * 3).astype(np.float32)
    r = dsp.mic_report(good)
    assert r["verdict"] == "výborné" and r["snr_db"] > 30 and not r["advice"]
    weak = speechlike(3, 4, 0.004) + 0.006 * np.random.default_rng(0).standard_normal(SR * 3).astype(np.float32)
    w = dsp.mic_report(weak)
    assert w["verdict"] == "slabé" and any("blíž" in a for a in w["advice"])
    clip = np.clip(speechlike(3, 4) * 5, -1, 1)
    assert any("přebuzuje" in a for a in dsp.mic_report(clip)["advice"])
    with pytest.raises(ValueError):
        dsp.mic_report(np.zeros(100, np.float32))


def _talk(order, spk, gap=0.3):
    parts, segs, t = [], [], 0.0
    for i, k in enumerate(order):
        parts.append(voice(2.0, *spk[k], seed=i))
        segs.append((t, t + 2.0))
        t += 2.0
        parts.append(np.zeros(int(gap * SR), np.float32))
        t += gap
    x = np.concatenate(parts)
    return x + 0.003 * np.random.default_rng(0).standard_normal(len(x)).astype(np.float32), segs


def test_speaker_labels():
    order = [0, 1, 0, 0, 1, 1, 0, 1, 2, 0, 2, 1]
    x, segs = _talk(order, [(120, 1.0), (210, 1.18), (160, 0.9)])
    r = dsp.diarize(x, SR, segs)
    assert r["speakers"] == 3 and r["labels"] == order
    one = dsp.diarize(x, SR, [segs[i] for i, k in enumerate(order) if k == 0])
    assert one["speakers"] == 1
    same_pitch, s2 = _talk([0, 1, 1, 0, 1, 0, 0, 1], [(130, 1.0), (130, 1.25)])
    assert dsp.diarize(same_pitch, SR, s2)["labels"] == [0, 1, 1, 0, 1, 0, 0, 1]    # same height, different voice
    pulses = np.zeros(SR)
    pulses[::SR // 160] = 1                                                # exactly 160 Hz, through an "a" vowel
    fr = np.fft.rfftfreq(SR, 1 / SR)
    vowel = np.fft.irfft(np.fft.rfft(pulses) * sum(1 / (1 + ((fr - F) / 90) ** 2) for F in VOWELS["a"]), SR)
    assert dsp.pitch(vowel) == pytest.approx(160, rel=0.02) and dsp.pitch(np.zeros(SR, np.float32)) is None


def _wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def test_call_transcript_names_the_other_voices(tmp_path):
    from jarvis.notetaker import label_speakers, merge

    order = [0, 1, 0, 1, 1, 0]
    x, segs = _talk(order, [(115, 1.0), (220, 1.2)])
    _wav(tmp_path / "sys.wav", x)
    labelled = label_speakers(tmp_path / "sys.wav", [(s, e, f"věta {i}") for i, (s, e) in enumerate(segs)])
    assert [w for *_, w in labelled] == [f"Ostatní {k + 1}" for k in order]
    lines = merge([(20.0, 21.0, "Díky, beru.")], labelled)
    assert lines[0]["who"] == "Ostatní 1" and lines[1]["who"] == "Ostatní 2" and lines[-1]["who"] == "Já"
    assert label_speakers(tmp_path / "nic.wav", [(0, 1, "a")]) == [(0, 1, "a")]


def test_wake_threshold():
    r = dsp.recommend_threshold([0.01, 0.08, 0.12], [0.7, 0.55, 0.9])
    assert r["ok"] and 0.12 < r["threshold"] < 0.55 and r["caught"] == "3/3"
    bad = dsp.recommend_threshold([0.6], [0.5, 0.7])
    assert not bad["ok"] and "neliší" in bad["advice"]
    scores = [0.0] * 5 + [0.2, 0.8, 0.6] + [0.0] * 20 + [0.3, 0.65] + [0.0] * 3
    assert voiceplus.peaks(scores) == [0.8, 0.65]


async def test_wake_calibration_tool(rt):
    class FakeLoop:
        available = True

        def __init__(self):
            self.runs = [[0.02, 0.1, 0.05] * 20, [0.0] * 4 + [0.3, 0.75] + [0.0] * 20 + [0.6] + [0.0] * 20 + [0.82]]

        def collect_wake_scores(self, seconds):
            return self.runs.pop(0)
    rt.voice = FakeLoop()
    assert "fraze" in (await tools.call("wake_word_calibrate", {"step": "ticho"}, rt)).summary
    r = await tools.call("wake_word_calibrate", {"step": "fraze", "apply": True}, rt)
    assert r.data["ok"] and r.data["applied"] and rt.cfg.voice.wake_threshold == r.data["threshold"] and 0.1 < r.data["threshold"] < 0.6


def test_ducker_counts_listening_and_speaking(rt):
    d = dsp.Ducker(rt.platform, lambda: 0.3)
    d.acquire()
    d.acquire()
    d.release()
    assert [c for c in rt.platform.calls if c[0] == "duck_audio"] == [("duck_audio", 0.3)]
    d.release()
    d.release()
    assert [c for c in rt.platform.calls if c[0] == "duck_audio"] == [("duck_audio", 0.3), ("duck_audio", None)]


def test_utterance_cleaning_in_the_loop(rt):
    from jarvis.voice.loop import VoiceLoop

    vl = VoiceLoop.__new__(VoiceLoop)
    vl.rt = rt
    from collections import deque

    noise = (0.03 * np.random.default_rng(5).standard_normal(SR)).astype(np.float32)
    vl._recent = deque([(noise[i:i + 1280] * 32767).astype(np.int16).tobytes() for i in range(0, SR, 1280)], maxlen=12)
    speech = speechlike(3, 6, 0.2)
    noisy = speech + (0.03 * np.random.default_rng(6).standard_normal(len(speech))).astype(np.float32)
    raw = (noisy * 32767).astype(np.int16).tobytes()
    out = np.frombuffer(vl.clean_utterance(raw, np), dtype=np.int16).astype(np.float32) / 32768

    def snr(y):                                                        # speech vs everything else, gain-independent
        a = (y @ speech) / (speech @ speech)
        return 10 * np.log10(((a * speech) ** 2).sum() / ((y - a * speech) ** 2).sum())
    level = 20 * np.log10(np.sqrt((out ** 2).mean()))
    assert snr(out) > snr(noisy) + 2 and level > -30
    rt.update_config({"voice": {"noise_suppression": False, "auto_gain": False}})
    assert vl.clean_utterance(raw, np) == raw
    vl.echo = dsp.EchoPath(SR)
    frame = raw[:2560]
    assert vl._frame((frame, 5.0), np) == frame                           # JARVIS is not speaking: frame untouched


async def test_mic_check_tool(rt, monkeypatch):
    seen = []
    rt.bus.publish = lambda t, **kw: seen.append((t, kw))
    monkeypatch.setattr(dsp, "record", lambda seconds, rate=SR, device=None: speechlike(seconds, 8, 0.004) + 0.006 * np.random.default_rng(0).standard_normal(int(seconds * SR)).astype(np.float32))
    r = await tools.call("mic_check", {"seconds": 3}, rt)
    assert r.ok and r.data["verdict"] == "slabé" and "blíž" in r.summary
    assert ("state", {"state": "listening"}) in seen and seen[-1] == ("state", {"state": "idle"})   # never silent recording

    def broken(*a, **k):
        raise OSError("Error querying device -1")
    monkeypatch.setattr(dsp, "record", broken)
    assert "Soukromí → Mikrofon" in (await tools.call("mic_check", {}, rt)).summary


async def test_bookmarks(rt):
    rt.memory.add_message("user", "Kolik stojí letenka do Lisabonu?")
    rt.memory.add_message("assistant", "Nejlevnější 3 400 Kč, odlet v pátek.")
    r = await tools.call("voice_bookmark", {"label": "letenky"}, rt)
    assert r.data["kind"] == "chat" and "Lisabonu" in r.data["context"]
    nt = rt.notetaker
    nt.state, nt.current, nt.started = "recording", "n9", __import__("time").time() - 125
    r = await tools.call("voice_bookmark", {"label": "cena"}, rt)
    assert r.data["kind"] == "note" and 124 <= r.data["at"] <= 127 and "2:0" in r.summary
    nt.state, nt.current = "idle", None
    lines = [{"who": "Já", "start": 100, "end": 110, "text": "Kolik by to stálo?"}, {"who": "Ostatní", "start": 118, "end": 130, "text": "Celkem 48 tisíc bez DPH."},
             {"who": "Já", "start": 400, "end": 410, "text": "Na shledanou."}]
    rt.db.exec("INSERT INTO notes VALUES ('n9', 1, 'Nabídka', 500, 'done', ?, '', '[]', '[]', '')", (json.dumps(lines, ensure_ascii=False),))
    b = (await tools.call("voice_bookmarks", {"query": "48 tisíc"}, rt)).data
    assert len(b) == 1 and b[0]["at"] == "2:05" and "48 tisíc" in b[0]["context"] and "Na shledanou" not in b[0]["context"]
    assert len((await tools.call("voice_bookmarks", {}, rt)).data) == 2


def test_pronunciation_scoring():
    words = [{"word": "Dobrý", "start": 0.0, "end": 0.4, "p": 0.97}, {"word": "den,", "start": 0.4, "end": 0.7, "p": 0.95},
             {"word": "jag", "start": 0.8, "end": 1.0, "p": 0.5}, {"word": "máte", "start": 1.1, "end": 1.5, "p": 0.41},
             {"word": "dneska", "start": 1.6, "end": 2.0, "p": 0.9}]
    r = voiceplus.pronunciation("Dobrý den, jak se máte?", words)
    assert r["good"] == 2 and r["total"] == 5 and r["score"] == 40
    assert r["wrong"] == [{"word": "jak", "heard": "jag"}] and r["missing"] == ["se"] and r["unclear"][0]["word"] == "máte" and r["extra"] == ["dneska"]
    assert any("„jak“ (slyšel jsem „jag“)" in t for t in r["tips"])
    with pytest.raises(ValueError):
        voiceplus.pronunciation("  ", words)


async def test_pronunciation_and_labels_tools(rt, tmp_path):
    d = tmp_path / "zvuk"
    d.mkdir()
    order = [0, 1, 1, 0, 1, 0]
    x, segs = _talk(order, [(118, 1.0), (205, 1.2)])
    _wav(d / "porada.wav", x)

    class FakeSTT:
        def segments(self, path, progress=None):
            return [(s, e, f"věta {i}") for i, (s, e) in enumerate(segs)]

        def words(self, audio, language=None):
            return [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35, "p": 0.95} for i, w in enumerate("The weather is lovely today".split())]
    rt.dictation._own_stt = FakeSTT()
    r = await tools.call("label_speakers", {"file": str(d / "porada.wav")}, rt)
    assert r.data["speakers"] == 2 and [ln["who"] for ln in r.data["lines"]] == ["Mluvčí 1", "Mluvčí 2", "Mluvčí 1", "Mluvčí 2", "Mluvčí 1"]
    assert sum(r.data["talk_seconds"].values()) == pytest.approx(12, abs=1)
    p = await tools.call("pronunciation_practice", {"sentence": "The weather is lovely today.", "audio": str(d / "porada.wav")}, rt)
    assert p.data["score"] == 100 and "100 %" in p.summary
    assert not (await tools.call("label_speakers", {"file": str(d / "nic.wav")}, rt)).ok


def test_media_read_back(tmp_path):
    x = speechlike(1, 2)
    _wav(tmp_path / "a.wav", x)
    y, rate = media.read_audio(tmp_path / "a.wav")
    assert rate == SR and np.abs(media._mono(y) - x).max() < 1e-3


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="relace zvuku Windows")
def test_real_windows_ducking():
    from jarvis.tools.platform.windows import WindowsPlatform

    p = WindowsPlatform()
    p.duck_audio(0.3)                     # whatever is playing on the runner (often nothing) goes down …
    p.duck_audio(None)                    # … and back; neither may fail
    assert p.__dict__.get("_ducked") == {}
