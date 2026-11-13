"""3.12 speech recognition without a 0.5 GB download: with a Groq key, voice and live subtitles use Groq."""
from types import SimpleNamespace

from jarvis import secrets
from jarvis.voice import stt as stt_mod


def make(provider, ready=False, monkeypatch=None):
    t = stt_mod.Transcriber(SimpleNamespace(stt_provider=provider, stt_model="small", stt_language="cs"))
    monkeypatch.setattr(t, "local_ready", lambda: ready)
    stt_mod.Transcriber._groq_seen = (0.0, False)
    return t


def test_auto_uses_groq_with_a_key_else_this_pc(monkeypatch):
    secrets.set("groq", "")
    assert make("auto", monkeypatch=monkeypatch).provider() == "local"
    secrets.set("groq", "gsk_" + "k" * 40)
    assert make("auto", monkeypatch=monkeypatch).provider() == "groq"
    assert make("auto", ready=True, monkeypatch=monkeypatch).provider() == "groq"


def test_local_choice_without_the_model_falls_back_to_groq(monkeypatch):
    """The old default "local" with nothing downloaded: no voice, no subtitles – unless Groq can do it."""
    secrets.set("groq", "gsk_" + "k" * 40)
    assert make("local", ready=False, monkeypatch=monkeypatch).provider() == "groq"
    assert make("local", ready=True, monkeypatch=monkeypatch).provider() == "local"     # downloaded: stays offline
    secrets.set("groq", "")
    assert make("local", ready=False, monkeypatch=monkeypatch).provider() == "local"


def test_subtitles_start_with_a_groq_key_and_no_download(rt, monkeypatch):
    from jarvis import livesubs

    secrets.set("groq", "gsk_" + "k" * 40)
    stt_mod.Transcriber._groq_seen = (0.0, False)
    t = stt_mod.Transcriber(rt.cfg.voice)
    monkeypatch.setattr(t, "local_ready", lambda: False)
    monkeypatch.setattr(rt.dictation, "_stt", lambda: t)
    monkeypatch.setattr(livesubs.LiveSubs, "_recorder", lambda self: (_ for _ in ()).throw(OSError("no speaker in CI")))
    r = livesubs.get(rt).start()
    assert "stáhni" not in r["message"] and "Zvuk z počítače" in r["message"]   # past the model check, stops at the speaker


def test_a_groq_brain_key_also_feeds_speech(rt):
    import asyncio

    from jarvis import brainkey

    secrets.set("groq", "")
    provs = [p.model_dump() for p in rt.cfg.brain.providers] + [{"id": "groq", "preset": "groq", "base_url": "x", "model": "m"}]
    rt.update_config({"brain": {"providers": provs}})
    provs2 = [p.model_dump() for p in rt.cfg.brain.providers]
    for p in provs2:
        if p["id"] == "groq":
            p["id"] = "muj-groq"
    rt.update_config({"brain": {"providers": provs2, "chain": ["muj-groq"]}})

    async def ok(pid):
        return {"ok": True, "ms": 1}

    asyncio.run(brainkey.apply(rt, "gsk_" + "z" * 48, ok))
    assert secrets.get("groq") == "gsk_" + "z" * 48                 # speech finds it under "groq"


def test_no_silent_download_of_the_speech_model(monkeypatch):
    """Without a Groq key and without the user's yes, talking never starts a 0.5 GB download – it says what to do."""
    import numpy as np
    import pytest

    secrets.set("groq", "")
    t = make("auto", ready=False, monkeypatch=monkeypatch)
    monkeypatch.setattr(t, "_local", lambda: (_ for _ in ()).throw(AssertionError("must not load/download")))
    with pytest.raises(RuntimeError, match="Groq"):
        t._run(np.zeros(1600, dtype=np.float32))
    t.prefetch()                                     # the warm-up while you speak does not download either


def test_the_installer_voice_pack_is_used_without_download(rt, monkeypatch, tmp_path):
    """3.12 the installer downloads Whisper into models/whisper/faster-whisper-small – JARVIS loads it from there."""
    from jarvis import paths
    from jarvis.voice.stt import Transcriber

    d = paths.sub("models") / "whisper" / "faster-whisper-small"
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.bin").write_bytes(b"x")
    loaded = []

    class FakeWhisper:
        def __init__(self, name, **kw):
            loaded.append((name, kw.get("download_root")))

    import sys
    import types

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper))
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 0))
    t = Transcriber(rt.cfg.voice)
    assert t.local_ready()
    t._arm = lambda: None
    t._local()
    assert loaded and loaded[0][0] == str(d)
