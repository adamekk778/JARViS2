"""3.17 Změřit rychlost: typical read-only requests + the voice there and back, measured, then cleaned up."""
from __future__ import annotations

import asyncio
import io
import wave

from conftest import FakeRouter

from jarvis import speedcheck, tools


def _wav(seconds: float = 0.3, sr: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x10\x00" * int(seconds * sr))
    return buf.getvalue()


async def test_requests_are_measured_in_their_own_conversation(rt):
    tools.load_builtin()
    before = rt.memory.current_conversation
    rt.router = FakeRouter(["Fotosyntéza je …", "Canberra."])
    rows = await speedcheck.run_requests(rt, ["kolik je hodin", "vysvětli fotosyntézu", "hlavní město Austrálie"])
    assert [r["how"] for r in rows] == ["bez AI", "AI", "AI"]
    assert all(r["total_ms"] >= 0 for r in rows) and rows[1]["first_word_ms"] is not None
    assert rt.memory.current_conversation == before                        # back where you were
    assert not rt.db.one("SELECT id FROM conversations WHERE title='Měření rychlosti'")
    assert rt.db.one("SELECT COUNT(*) AS n FROM tool_memory")["n"] == 0 if rt.db.one(
        "SELECT name FROM sqlite_master WHERE name='tool_memory'") else True   # nothing learnt from the check


async def test_voice_there_and_back(rt):
    class Sp:
        async def _synth(self, text, lang="cs", override=None):
            await asyncio.sleep(0)
            return _wav(), "audio/wav"

    class Tr:
        def transcribe(self, pcm, sr=16000, prompt=""):
            assert sr == 16000 and len(pcm) > 1000
            return "Kolik je hodin"

    class Voice:
        transcriber = Tr()
    rt.speaker, rt.voice = Sp(), Voice()
    rows = await speedcheck.run_voice(rt, ["Kolik je hodin?", "Rozsviť v kuchyni."])
    assert rows[0]["match"] == 1.0 and rows[0]["tts_ms"] >= 0 and rows[0]["stt_ms"] >= 0
    assert rows[1]["match"] < 0.6
    s = speedcheck.summary([{"how": "AI", "first_word_ms": 800, "total_ms": 1500, "tools": 1, "found_tool_first_try": True}], rows)
    assert s["first_word_ms"] == 800 and s["first_try_pct"] == 100 and s["stt_match"] is not None
    assert "první slovo za 800 ms" in speedcheck.say({"summary": s})


async def test_the_button(rt, monkeypatch):
    from jarvis.server.handlers.speed import speedcheck_get, speedcheck_run

    sent = []
    rt.bus.publish = lambda t, **d: sent.append((t, d))

    class C:
        def __init__(self):
            self.rt = rt
            self.tasks = []

        async def send(self, t, **d):
            sent.append((t, d))

        def spawn(self, coro):
            self.tasks.append(asyncio.get_running_loop().create_task(coro))
    tools.load_builtin()
    rt.router = FakeRouter(["Odpověď."] * 30)
    monkeypatch.setattr(speedcheck, "REQUESTS", ["kolik je hodin", "kdo napsal Babičku"])
    c = C()
    await speedcheck_run(c, {"voice": False})
    await asyncio.gather(*c.tasks)
    done = [d for t, d in sent if t == "speedcheck" and not d.get("running")]
    assert done and "report" in done[-1] and done[-1]["report"]["summary"]["requests"] == 2
    await speedcheck_get(c, {})
    assert sent[-1][1]["report"]["summary"]["requests"] == 2
