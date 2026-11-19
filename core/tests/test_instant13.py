"""3.13: everyday commands without the AI (just as fast with Ollama), recording what the PC plays, picking the AI by its
logo, the ElevenLabs front-page voice, and a quick local AI (warm, no thinking aloud, fewer tools)."""
import asyncio
import json
import time

import httpx
import numpy as np
import pytest
from conftest import FakeRouter

from jarvis import instant, soundrec
from jarvis.llm import local
from jarvis.voice import studio


@pytest.mark.parametrize("text,call", [
    ("Jarvisi, nahraj mi zvuk, co teď pustím", ("sound_record_start", {})),
    ("stop nahrávání", ("sound_record_stop", {})),
    ("hlasitost na 30", ("volume", {"action": "set", "level": 30})),
    ("dej hlasitěji", ("volume", {"action": "up"})),
    ("vypni zvuk", ("volume", {"action": "mute"})),
    ("další písnička", ("media_control", {"action": "next"})),
    ("kolik je hodin?", ("get_time", {})),
    ("minutka na pět minut", ("set_timer", {"seconds": 300})),
    ("otevři Spotify", ("open_app", {"name": "spotify"})),
    ("zavři Discord", ("close_app", {"name": "discord"})),
])
def test_everyday_commands_are_caught(text, call):
    p = instant.plan(text)
    assert p and p.calls == [call]


@pytest.mark.parametrize("text", ["pusť Eminema", "zastav", "zavři okno", "otevři poslední stažený soubor", "nahraj obrazovku",
                                  "napiš e-mail Petrovi, že přijdu později a pošli ho", "vysvětli mi, jak funguje fotosyntéza"])
def test_anything_else_goes_to_the_ai(text):
    assert instant.plan(text) is None


async def test_a_command_is_done_without_asking_the_ai(rt):
    rt.router = FakeRouter([])                          # any AI call would answer "konec"
    out = await rt.agent.handle("hlasitost na 40")
    assert rt.router.calls == [] and ("set_volume", 40) in rt.platform.calls and out.strip()
    out = await rt.agent.handle("kolik je hodin")
    assert out.startswith("Je ") and rt.router.calls == []


async def test_a_failed_open_lets_the_ai_try(rt, monkeypatch):
    def nope(name):
        raise FileNotFoundError(name)
    monkeypatch.setattr(rt.platform, "open_app", nope)
    rt.router = FakeRouter(["Tuhle aplikaci nemáš nainstalovanou."])
    out = await rt.agent.handle("otevři Neexistujici")
    assert len(rt.router.calls) == 1 and "nainstalovanou" in out


async def test_instant_can_be_switched_off(rt):
    rt.cfg.agent.instant = False
    rt.router = FakeRouter(["Nastavuji."])
    await rt.agent.handle("hlasitost na 40")
    assert len(rt.router.calls) == 1


class Loop:
    def __init__(self):
        self.n = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        self.n += 1
        time.sleep(0.005)
        return np.full((numframes, 2), 0.25, dtype=np.float32)


def test_recording_what_the_pc_plays_to_a_wav(rt, tmp_path, monkeypatch):
    import wave

    rec = soundrec.SoundRecorder(rt, source=Loop)
    path = rec.start("písnička")
    time.sleep(0.25)
    st = rec.stop()
    assert not rec.on and path.exists() and path.suffix == ".wav" and path.name.startswith("písnička_")
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 48000 and w.getnframes() > 2048
    assert st["path"] == str(path)


def test_picking_an_ai_by_its_logo(rt):
    from fastapi.testclient import TestClient

    from jarvis.config import ProviderCfg
    from jarvis.server.app import create_app

    rt.cfg.brain.providers = [ProviderCfg(id="gemini", preset="gemini", model="gemini-3.8-flash"),
                              ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b"),
                              ProviderCfg(id="ollama", preset="ollama", model="qwen3:8b", enabled=False)]
    rt.cfg.brain.chain = ["gemini", "groq", "ollama"]
    warmed = []

    async def warm(model=None):
        warmed.append(model)
        return True
    rt.local.warm = warm
    with TestClient(create_app(rt, manage_runtime=False)) as c, c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "brain_pick", "id": "groq"})
        time.sleep(0.3)
        assert rt.cfg.brain.chain[:2] == ["groq", "gemini"]
        ws.send_json({"type": "brain_pick", "id": "ollama"})
        time.sleep(0.5)
    assert rt.cfg.brain.chain[0] == "ollama" and next(p for p in rt.cfg.brain.providers if p.id == "ollama").enabled
    assert warmed == ["qwen3:8b"]


def test_local_ai_does_not_think_aloud_and_stays_loaded():
    assert local.think_value("qwen3:8b") is False and local.think_value("gpt-oss:20b") == "low"
    assert local.think_value("llama3.1:8b") is None and local.think_value("qwen2.5:3b") is None
    opts, keep = local.mode_options("balanced", 8)
    assert opts["num_ctx"] >= 8192 and keep == "60m"
    assert local.mode_options("performance", 8)[1] == "-1"
    assert local.recommend({"gpus": [{"vram_gb": 16}], "ram_gb": 32})[0] == "gpt-oss:20b"
    assert local.recommend({"gpus": [{"vram_gb": 8}], "ram_gb": 16})[0] == "qwen3:8b"
    assert local.recommend({"gpus": [], "ram_gb": 8})[0] == "qwen3:4b"


async def test_ollama_gets_think_off():
    from jarvis.llm.ollama import Ollama

    sent = []

    def h(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, text=json.dumps({"message": {"content": "Ahoj"}, "done": True}) + "\n")
    o = Ollama("ollama", "http://localhost:11434", "qwen3:8b", transport=httpx.MockTransport(h))
    out = [c async for c in o.stream([{"role": "user", "content": "ahoj"}], None)]
    assert sent[0]["think"] is False and any(c.text == "Ahoj" for c in out)


def test_a_local_ai_gets_fewer_tools(rt):
    from jarvis.config import ProviderCfg

    rt.cfg.brain.providers = [ProviderCfg(id="ollama", preset="ollama", model="qwen3:8b"), ProviderCfg(id="gemini", preset="gemini")]
    rt.cfg.brain.chain = ["ollama", "gemini"]
    small = len(rt.agent._tool_schemas("pošli soubor do telefonu a nastav budík a zkontroluj počasí a e-maily"))
    rt.cfg.brain.chain = ["gemini", "ollama"]
    big = len(rt.agent._tool_schemas("pošli soubor do telefonu a nastav budík a zkontroluj počasí a e-maily"))
    assert small < big


def test_the_front_page_voice_is_offered_and_added_on_first_use():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/v1/voices":
            return httpx.Response(200, json={"voices": [{"voice_id": "abc12345", "name": "Můj hlas", "category": "cloned"}]})
        if req.url.path == "/v1/text-to-speech/UgBBYS2sOqTuMpoF3BR0":
            return httpx.Response(404, json={"detail": {"status": "voice_not_found", "message": "A voice with the voice_id was not found."}})
        if req.url.path == "/v1/shared-voices":
            assert req.url.params["search"] == "Mark - Natural Conversations"
            return httpx.Response(200, json={"voices": [{"voice_id": "UgBBYS2sOqTuMpoF3BR0", "public_owner_id": "owner1"}]})
        if req.url.path == "/v1/voices/add/owner1/UgBBYS2sOqTuMpoF3BR0":
            return httpx.Response(200, json={"voice_id": "NewMarkVoice1"})
        if req.url.path == "/v1/text-to-speech/NewMarkVoice1":
            return httpx.Response(200, content=b"ID3mp3")
        return httpx.Response(500)
    t = httpx.MockTransport(h)
    voices = asyncio.run(studio.eleven_voices("k", transport=t))
    assert voices[0]["id"] == "UgBBYS2sOqTuMpoF3BR0" and voices[0]["featured"] and any(v["own"] for v in voices)
    audio = asyncio.run(studio.eleven_synth("Dobrý den", "k", "UgBBYS2sOqTuMpoF3BR0", "eleven_multilingual_v2", transport=t))
    assert audio == b"ID3mp3" and ("POST", "/v1/voices/add/owner1/UgBBYS2sOqTuMpoF3BR0") in seen
