""""Jen offline" hid every cloud AI and the song lyrics without a word: now it says so, and pasting a key ends it."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from jarvis import brainkey, nowplaying
from jarvis.config import Brain, ProviderCfg
from jarvis.llm.base import AllProvidersFailed
from jarvis.llm.router import Router


def test_router_names_offline_mode_instead_of_no_provider():
    brain = Brain(providers=[ProviderCfg(id="groq", preset="groq", base_url="https://api.groq.com/openai/v1", model="m")],
                  chain=["groq"], offline_only=True)
    with pytest.raises(AllProvidersFailed) as e:
        asyncio.run(Router(brain, lambda k: "x").complete([{"role": "user", "content": "hi"}]))
    assert "Jen offline" in str(e.value) and "žádný poskytovatel" not in str(e.value)


def test_router_names_missing_key_when_nothing_is_set():
    brain = Brain(providers=[], chain=[])
    with pytest.raises(AllProvidersFailed) as e:
        asyncio.run(Router(brain, lambda k: "").complete([{"role": "user", "content": "hi"}]))
    assert "API klíč" in str(e.value)


def test_pasting_a_key_switches_offline_mode_off(monkeypatch, tmp_path):
    from jarvis.runtime import Runtime

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(brainkey.secrets, "set", lambda *a: None)
    rt = Runtime(persist_config=False)
    rt.update_config({"brain": {"offline_only": True}})

    async def ok(pid):
        return {"ok": True, "ms": 120}

    r = asyncio.run(brainkey.apply(rt, "gsk_" + "a" * 40, ok))
    assert r["ok"] and rt.cfg.brain.offline_only is False
    assert "Jen offline" in r["message"]


def test_lyrics_say_why_in_offline_mode():
    sent = []
    rt = NS(cfg=NS(notch=NS(lyrics=True), brain=NS(offline_only=True)), media_state={"title": "Song"},
            bus=NS(publish=lambda t, **k: sent.append((t, k))))
    asyncio.run(nowplaying.publish_lyrics(rt, {"title": "Song", "artist": "Band"}))
    assert rt.lyrics_state["reason"] == "offline" and sent[0][0] == "lyrics"
