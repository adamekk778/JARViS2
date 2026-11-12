"""Saving power: the wake-word model runs only while there is sound, cheap background watchers, one volume reader."""
import numpy as np
import pytest

from jarvis.voice.loop import VoiceLoop


class FakeWW:
    def __init__(self):
        self.fed = []

    def predict(self, a):
        self.fed.append(int(np.abs(a).max()))
        return {"hey_jarvis": 0.0}


def frame(level: int) -> bytes:
    rng = np.random.default_rng(level)
    return (rng.standard_normal(1280) * level).astype(np.int16).tobytes()


@pytest.fixture
def vl(rt):
    v = VoiceLoop.__new__(VoiceLoop)
    from collections import deque

    v._recent, v._score_sink = deque(maxlen=12), None
    return v


def run(vl, ww, levels, t0=0.0):
    out = []
    for i, lv in enumerate(levels):
        f = frame(lv)
        vl._recent.append(f)
        out.append(vl._wake_gate(f, ww, None, np, now=t0 + i * 0.08))
    return out


def test_quiet_room_skips_the_model(vl):
    ww = FakeWW()
    out = run(vl, ww, [40] * 100)                # 8 s of a quiet room
    assert sum(out) <= 30                        # only the first moments while it learns the room (≤ 2.4 s)
    assert not any(out[40:])                     # then nothing runs


def test_speech_wakes_it_with_the_frames_before_and_a_tail(vl):
    ww = FakeWW()
    run(vl, ww, [40] * 60)
    ww.fed.clear()
    out = run(vl, ww, [40, 40, 2500, 2500, 2500] + [40] * 40, t0=10.0)
    assert out[:2] == [False, False] and out[2] is True
    assert len(ww.fed) >= 2                      # the two quiet frames before "Hey" went in first
    assert all(out[2:5]) and all(out[5:5 + 20])  # the whole phrase and ~1.6 s after it
    assert not any(out[-10:])                    # then it sleeps again


def test_calibration_measures_every_frame(vl):
    vl._score_sink = []
    assert all(run(vl, FakeWW(), [40] * 50))


def test_a_noisy_room_still_hears_speech(vl):
    ww = FakeWW()
    run(vl, ww, [600] * 80)                      # a loud fan
    out = run(vl, ww, [600] * 30 + [4000] * 5, t0=20.0)
    assert not any(out[:30][-5:]) and out[30] is True


def test_installer_watch_reads_command_lines_only_for_msiexec(monkeypatch):
    import psutil

    from jarvis import sysplus

    asked = []

    class P:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}

        def cmdline(self):
            asked.append(self.info["name"])
            return ["msiexec.exe", "/i", "app.msi"]

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [P(1, "chrome.exe"), P(2, "msiexec.exe"), P(3, "Setup_v2.exe"), P(4, "code.exe")])
    procs = sysplus.installer_procs()
    assert asked == ["msiexec.exe"]                       # nobody else's command line is read
    assert sysplus.installers(procs) == {2: "msiexec.exe", 3: "Setup_v2.exe"}


def test_download_snapshot_lists_files_with_sizes(tmp_path):
    from jarvis import sysplus

    (tmp_path / "a.zip").write_bytes(b"x" * 10)
    (tmp_path / "b.crdownload").write_bytes(b"x" * 3)
    (tmp_path / "dir").mkdir()
    assert sysplus._snapshot(tmp_path) == {"a.zip": 10, "b.crdownload": 3}
    assert sysplus._snapshot(tmp_path / "missing") == {}


def test_volume_reader_feeds_the_mood(rt, monkeypatch):
    from jarvis import sysplus

    got = []
    rt.volume_feeds_mood = True
    monkeypatch.setattr(rt, "call_soon", lambda fn, *a: fn(*a))
    monkeypatch.setattr(rt.mood, "on_audio", lambda v, m: got.append((v, m)))
    last = sysplus._volume_publish(rt, (40, False), None, lambda *a, **k: None)
    last = sysplus._volume_publish(rt, (40, False), last, lambda *a, **k: None)   # unchanged → nothing
    sysplus._volume_publish(rt, (55, False), last, lambda *a, **k: None)
    assert got == [(40, False), (55, False)]


def test_speech_model_not_loaded_at_start_loads_on_talk_and_goes_when_unused(rt, monkeypatch):
    import threading
    import time as _t
    from types import SimpleNamespace

    from jarvis.voice import stt as stt_mod

    loads = []
    t = stt_mod.Transcriber(SimpleNamespace(stt_provider="local", stt_model="small", stt_language="cs", stt_download_ok=True))
    monkeypatch.setattr(threading, "Timer", lambda s, f: SimpleNamespace(start=lambda: None, daemon=True))

    def fake_local():
        loads.append(1)
        t._model, t._model_name, t._used = object(), "small", _t.monotonic()
        return t._model

    monkeypatch.setattr(t, "_local", fake_local)
    assert t._model is None                                  # nothing in memory until somebody talks
    t.prefetch()
    for _ in range(100):
        if t._model is not None:
            break
        _t.sleep(0.01)
    assert t._model is not None and loads == [1]
    t.prefetch()                                             # already there → no second load
    assert loads == [1]
    assert t.release_if_idle(now=t._used + 60) is False      # used a minute ago: stays
    assert t.release_if_idle(now=t._used + 601) is True and t._model is None
    t.cfg.stt_provider = "groq"
    t.prefetch()                                             # Groq in the cloud: nothing local to load
    _t.sleep(0.05)
    assert loads == [1]


def test_voice_loop_does_not_load_the_speech_model_at_start():
    import inspect

    from jarvis.voice.loop import VoiceLoop

    assert "warmup" not in inspect.getsource(VoiceLoop.start)
