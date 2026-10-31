"""Voice studio: effects, an own Piper voice from files, ElevenLabs, the engine order with fallbacks."""
import io
import json
import wave

import httpx
import numpy as np
import pytest

from jarvis.voice import studio, tts


def _wav(n=2400, sr=24000, freq=220.0):
    t = np.arange(n) / sr
    pcm = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return studio.encode_wav(pcm, sr), pcm, sr


@pytest.mark.parametrize("name", ["jarvis", "radio", "robot", "hall"])
def test_effects_change_the_sound_and_stay_in_range(name):
    _, pcm, sr = _wav()
    out = studio.apply_effect(pcm, sr, name)
    assert out.shape == pcm.shape and np.isfinite(out).all() and np.max(np.abs(out)) <= 1.0
    assert not np.allclose(out, pcm, atol=1e-3)
    assert studio.apply_effect(pcm, sr, "none") is not None and np.allclose(studio.apply_effect(pcm, sr, "none"), pcm)


def test_radio_cuts_the_bass():
    _, low, sr = _wav(freq=80.0)
    assert np.max(np.abs(studio.apply_effect(low, sr, "radio"))) < 0.1


def test_import_own_piper_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "piper_dir", lambda: tmp_path)
    onnx, cfg = tmp_path / "Můj hlas.onnx", tmp_path / "Můj hlas.onnx.json"
    onnx.write_bytes(b"\x08" * 1_200_000)
    cfg.write_text(json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8")
    name = studio.import_piper(onnx, cfg)
    assert name == "Můj_hlas" and [v["id"] for v in studio.custom_voices()] == ["Můj_hlas"]
    bad = tmp_path / "x.onnx.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="sample_rate"):
        studio.import_piper(onnx, bad)
    tiny = tmp_path / "t.onnx"
    tiny.write_bytes(b"1")
    with pytest.raises(ValueError, match="malý"):
        studio.import_piper(tiny, cfg)
    assert studio.delete_custom("Můj_hlas") and studio.custom_voices() == []


def test_piper_refuses_paths_as_names():
    with pytest.raises(RuntimeError, match="neplatný"):
        tts.piper_synth("ahoj", "../../etc/passwd", True)


async def test_elevenlabs_synth_and_voices():
    seen = {}

    def handler(req):
        seen["key"] = req.headers.get("xi-api-key")
        if req.url.path.endswith("/voices"):
            return httpx.Response(200, json={"voices": [{"voice_id": "abcDEF123456", "name": "Rachel", "category": "premade"},
                                                        {"voice_id": "mine0000ABCD", "name": "Můj hlas", "category": "cloned"}]})
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=b"ID3mp3")

    tr = httpx.MockTransport(handler)
    voices = await studio.eleven_voices("k1", tr)
    assert voices[0] == {"id": "mine0000ABCD", "name": "Můj hlas", "own": True}
    audio = await studio.eleven_synth("Ahoj", "k1", "mine0000ABCD", "eleven_multilingual_v2", tr)
    assert audio == b"ID3mp3" and seen["key"] == "k1" and seen["body"]["model_id"] == "eleven_multilingual_v2"
    with pytest.raises(RuntimeError, match="API klíč"):
        await studio.eleven_synth("Ahoj", "", "mine0000ABCD", "", tr)
    with pytest.raises(RuntimeError, match="neplatné"):
        await studio.eleven_synth("Ahoj", "k1", "../x", "", tr)
    denied = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "invalid"}))
    with pytest.raises(RuntimeError, match="odmítl"):
        await studio.eleven_synth("Ahoj", "k1", "mine0000ABCD", "", denied)


async def test_edge_catalogue_keeps_czech_first_and_multilingual(monkeypatch):
    import edge_tts

    async def fake_list():
        return [{"ShortName": "en-US-AndrewMultilingualNeural", "Locale": "en-US", "Gender": "Male"},
                {"ShortName": "fr-FR-HenriNeural", "Locale": "fr-FR", "Gender": "Male"},
                {"ShortName": "cs-CZ-VlastaNeural", "Locale": "cs-CZ", "Gender": "Female"}]

    studio._cache.pop("edge", None)
    monkeypatch.setattr(edge_tts, "list_voices", fake_list)
    v = await studio.edge_voices()
    assert [x["id"] for x in v] == ["cs-CZ-VlastaNeural", "en-US-AndrewMultilingualNeural"]
    assert v[0]["name"] == "Vlasta" and v[0]["gender"] == "žena" and v[1]["multi"]
    studio._cache.pop("edge", None)


async def test_engine_order_and_effect(rt, monkeypatch):
    calls = []

    async def edge(text, voice, *a):
        calls.append(("edge", voice))
        return _wav()[0]

    async def eleven(text, key, voice_id, model, transport=None):
        calls.append(("eleven", voice_id))
        raise RuntimeError("v ElevenLabs došel měsíční limit znaků")

    monkeypatch.setattr(tts, "edge_synth", edge)
    monkeypatch.setattr(studio, "eleven_synth", eleven)
    rt.cfg.voice.tts_engine = "elevenlabs"
    rt.cfg.voice.eleven_voice_id = "mine0000ABCD"
    rt.cfg.voice.effect = "robot"
    audio, mime = await tts.Speaker(rt).synth("Ahoj")
    assert calls == [("eleven", "mine0000ABCD"), ("edge", rt.cfg.voice.tts_voice)]     # limit reached → Microsoft voice
    assert mime == "audio/wav"                                                          # the effect re-encodes
    with wave.open(io.BytesIO(audio)) as w:
        assert w.getnframes() == 2400
    calls.clear()
    await tts.Speaker(rt).synth("Ahoj", override={"tts_engine": "edge", "tts_voice": "cs-CZ-VlastaNeural", "effect": "none"})
    assert calls == [("edge", "cs-CZ-VlastaNeural")] and rt.cfg.voice.tts_engine == "elevenlabs"   # a preview saves nothing


def test_voice_studio_messages_are_in_the_protocol():
    import pathlib

    from jarvis.server import ws

    ts = (pathlib.Path(__file__).parents[2] / "web" / "src" / "shared" / "protocol.ts").read_text(encoding="utf-8")
    for t in ("voices_get", "voice_preview", "voice_import", "voice_delete"):
        assert t in ws.CLIENT_TYPES and f'"{t}"' in ts
    for t in ("voices", "voice_sample"):
        assert t in ws.SERVER_TYPES and f'"{t}"' in ts
    assert {"voice_import", "voice_delete", "voice_preview"} <= ws.LOCAL_ONLY
