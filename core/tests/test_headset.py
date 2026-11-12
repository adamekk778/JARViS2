"""3.12 Hlas se sluchátky: the phone's visible voice window → text → JARVIS → the answer as audio for the headphones."""
import base64
from types import SimpleNamespace

import pytest


@pytest.fixture
def client(rt, monkeypatch):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    saved, deleted, asked = [], [], []

    async def save(name, data, mime="", conv_id=None):
        saved.append((name, data, mime))
        return SimpleNamespace(id="a1", text=None, error=None)

    async def ensure(aid):
        return SimpleNamespace(id=aid, text=rt._heard, error=rt._err)

    async def handle(text, atts=None, source="chat", **k):
        asked.append((text, source))
        return "Je dvanáct hodin, pane."

    async def synth(text, lang="cs", override=None):
        return b"ID3mp3", "audio/mpeg"

    rt._heard, rt._err = "kolik je hodin", None
    monkeypatch.setattr(rt.store, "save", save)
    monkeypatch.setattr(rt.store, "ensure", ensure)
    monkeypatch.setattr(rt.store, "delete", lambda aid: deleted.append(aid))
    monkeypatch.setattr(rt.agent, "handle", handle)
    rt.speaker = SimpleNamespace(synth=synth)
    c = TestClient(create_app(rt, manage_runtime=False), client=("100.70.1.2", 5000))
    c.saved, c.deleted, c.asked = saved, deleted, asked
    return c


def post(c, rt, body=b"RIFF....WAVEfmt ", token=None):
    return c.post("/api/phone/voice", content=body, headers={"Authorization": f"Bearer {token or rt.cfg.phone.token}", "Content-Type": "audio/wav"})


def test_question_from_the_headphones_gets_a_spoken_answer(client, rt):
    r = post(client, rt).json()
    assert r["heard"] == "kolik je hodin" and r["reply"] == "Je dvanáct hodin, pane."
    assert base64.b64decode(r["audio"]) == b"ID3mp3" and r["mime"] == "audio/mpeg"
    assert client.asked == [("kolik je hodin", "headset")]
    assert client.deleted == ["a1"]                                  # the recording itself is not kept


def test_pc_stays_quiet_for_headset_answers(rt):
    rt.cfg.voice.speak_mode = "always"
    assert rt.wants_speech("headset") is False                      # the answer plays in the headphones only
    assert rt.wants_speech("voice") is True


def test_not_understood_and_no_stt(client, rt):
    rt._heard = ""
    assert "Nerozuměl" in post(client, rt).json()["reply"]
    rt._err = "no stt"
    assert "Převod řeči" in post(client, rt).json()["reply"]
    assert client.asked == []                                        # nothing reached the AI


def test_only_the_paired_phone_and_short_recordings(client, rt):
    from jarvis import headset

    assert post(client, rt, token="wrong").status_code == 401
    assert post(client, rt, body=b"").status_code == 400
    assert post(client, rt, body=b"x" * (headset.MAX_AUDIO + 1)).status_code == 413


def test_without_tts_the_phone_reads_the_text(client, rt):
    rt.speaker = None
    r = post(client, rt).json()
    assert r["reply"] and "audio" not in r
