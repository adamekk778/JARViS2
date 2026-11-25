"""3.18 (D11–D13, F17–F18): the live transcript reads only new audio, Claude's cache warmed again after a long pause,
spoken progress while several tools work, agent.py split (old imports still work), the long-run monitor and a soak."""
from __future__ import annotations

import asyncio
import gc
import time
import tracemalloc

import numpy as np
from conftest import FakeRouter

from jarvis import resmon, tools
from jarvis.voice.fastear import LiveWindow

SR = 16000


def _pcm(seconds: float) -> bytes:
    return (np.zeros(int(SR * seconds), dtype=np.int16)).tobytes()


# ------------------------------------------------------------------------------------------ D11 the live window
def test_live_window_confirms_words_and_reads_only_new_audio():
    script = [
        [{"word": "zapni", "start": 0.2, "end": 0.6}],
        [{"word": "zapni", "start": 0.2, "end": 0.6}, {"word": "světlo", "start": 0.7, "end": 1.2}],
        [{"word": "zapni", "start": 0.2, "end": 0.6}, {"word": "světlo", "start": 0.7, "end": 1.2},
         {"word": "v", "start": 2.6, "end": 2.7}],
        [{"word": "v", "start": 2.0, "end": 2.1}, {"word": "kuchyni", "start": 2.2, "end": 2.9}],
    ]
    lengths: list[float] = []

    def words(audio):
        lengths.append(len(audio) / SR)
        return script[len(lengths) - 1]
    lw = LiveWindow(words)
    assert lw.update(_pcm(1.0)) == "zapni"
    assert lw.update(_pcm(2.0)) == "zapni světlo"                     # window too short to confirm yet
    assert lw.update(_pcm(3.0)) == "zapni světlo v"                   # agreed twice + long enough → confirmed
    assert lw.committed == ["zapni", "světlo"] and lw.offset == int(1.2 * SR) * 2
    assert lw.update(_pcm(4.0)) == "zapni světlo v kuchyni"
    assert lengths[-1] < 3.0                                          # the last read started after "světlo"


def test_live_window_stays_bounded_on_a_long_monologue():
    calls: list[float] = []

    def words(audio):
        n = len(audio) / SR
        calls.append(n)
        return [{"word": f"w{i}-{len(calls)}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(int(n / 0.5))]
    lw = LiveWindow(words)
    for s in range(1, 60):
        lw.update(_pcm(float(s)))
    assert max(calls) <= LiveWindow.MAX_WINDOW_S + 1.5                  # never re-reads a minute of audio


def test_too_little_audio_is_not_read():
    lw = LiveWindow(lambda a: (_ for _ in ()).throw(AssertionError("read")))
    assert lw.update(_pcm(0.1)) == ""


# ------------------------------------------------------------------------------------------ D12 cache warm-up
async def test_cache_warm_only_when_claude_and_cold(rt, monkeypatch):
    from jarvis.config import ProviderCfg

    tools.load_builtin()
    assert await rt.agent.warm_cache() is None                         # no Claude in the chain
    rt.cfg.brain.providers.append(ProviderCfg(id="claude", preset="anthropic", base_url="", model="claude-opus-5-5"))
    seen = []

    async def warm(msgs, tools_, catalog=None):
        seen.append((msgs, tools_, catalog))
        return {"read": 0, "written": 12000}
    rt.router.warm_cache = warm
    rt.router.claude_at = time.time()
    assert await rt.agent.warm_cache() is None                         # still cached
    rt.router.claude_at = time.time() - 3500
    res = await rt.agent.warm_cache()
    assert res == {"read": 0, "written": 12000} and seen and seen[0][0][0]["role"] == "system"
    from jarvis import latency

    assert latency.get(rt).stats()["cache_warms"] == 1
    rt.update_config({"brain": {"cache_warm": False}})
    rt.router.claude_at = 0.0
    assert await rt.agent.warm_cache() is None


async def test_claude_warm_request_is_tiny_and_keeps_the_prefix():
    from jarvis.llm.claude import Claude

    sent = {}

    class Msgs:
        async def create(self, **p):
            sent.update(p)

            class U:
                cache_read_input_tokens, cache_creation_input_tokens = 0, 9000

            class M:
                usage = U()
            return M()

    class Beta:
        messages = Msgs()

    class Client:
        beta = Beta()
    c = Claude("claude", "https://api.anthropic.com", "claude-opus-5-5", "sk-test")
    c.client = lambda: Client()
    tool = [{"type": "function", "function": {"name": "weather", "description": "x", "parameters": {"type": "object", "properties": {}}}}]
    res = await c.warm_cache([{"role": "system", "content": "Pokyny"}, {"role": "user", "content": "…"}], tool)
    assert res["written"] == 9000 and sent["max_tokens"] == 1 and "thinking" not in sent
    full = c.params([{"role": "system", "content": "Pokyny"}, {"role": "user", "content": "…"}], tool)
    assert sent["system"] == full["system"] and sent["tools"] == full["tools"]         # the same cached prefix


# ------------------------------------------------------------------------------------------ D13 spoken progress
async def test_progress_says_what_is_done_and_what_is_left(rt, monkeypatch):
    from jarvis.llm.base import ToolCall

    said: list[str] = []

    class Speech:
        spoke = False

        def preface(self, line):
            said.append(line)
            self.spoke = True

        def progress(self, line):
            said.append(line)
    monkeypatch.setattr(type(rt.agent), "ACK_AFTER_S", 0.01)
    monkeypatch.setattr(type(rt.agent), "PROGRESS_S", 0.02)
    cards: list[dict] = []
    run = [ToolCall(id="1", name="weather", arguments={}), ToolCall(id="2", name="calendar_list", arguments={})]
    task = rt.agent._ack_later(Speech(), run, cards)
    await asyncio.sleep(0.015)
    cards.append({"name": "weather", "ok": True})
    await asyncio.sleep(0.08)
    task.cancel()
    assert said[0].startswith(("Moment", "Hned", "Pracuji")) and "Počasí mám, ještě kalendář." in said


async def test_speech_progress_only_before_the_answer(rt):
    from jarvis.voice.stream import SpeechStream

    class Spk:
        _stop = type("E", (), {"is_set": lambda self: False})()

        def can_stream(self):
            return False

        def has_phrase(self, *a):
            return False
    rt.speaker = Spk()
    s = SpeechStream(rt)
    queued = []
    s._queue = lambda piece: queued.append(piece)
    s.progress("Počasí mám.")
    s.answer_started = True
    s.progress("Ještě kalendář.")
    assert queued == ["Počasí mám."]


# ------------------------------------------------------------------------------------------ F17 the split keeps old imports
def test_agent_split_keeps_the_old_imports():
    from jarvis import agent, agent_fast, agent_helpers

    assert agent.describe_call is agent_helpers.describe_call and agent._waves is agent_helpers._waves
    assert issubclass(agent.Agent, agent_fast.FastPaths)
    assert hasattr(agent.Agent, "speculate") and hasattr(agent.Agent, "_done_by_tools")
    src = open(agent.__file__, encoding="utf-8").read()
    assert src.count("\n") < 950                                       # it was 1 250 lines


# ------------------------------------------------------------------------------------------ F18 the long run
def test_resmon_summary_and_leak_notice(rt):
    now = 1_000_000.0
    for i in range(288):                                               # a day, every 5 minutes, growing 300 MB / day
        resmon.record(rt, {"ts": now - 86400 + i * 300, "rss": 500 + i * 300 / 288, "cpu": 2.0, "threads": 40, "files": 30})
    s = resmon.summary(rt, now)
    assert s["n"] == 288 and 280 < s["grow_mb_day"] < 320 and s["leak"] and len(s["points"]) == 288
    told = []
    rt.notify = lambda title, body, **kw: told.append(title)
    assert resmon.check(rt, now) and told == ["JARVIS roste v paměti"]
    assert not resmon.check(rt, now + 3600)                            # once a day
    assert resmon.sample()["rss"] > 0


def test_resmon_flat_is_fine(rt):
    now = 2_000_000.0
    for i in range(100):
        resmon.record(rt, {"ts": now - 86400 + i * 864, "rss": 600 + (i % 3), "cpu": 1.0, "threads": 30, "files": 20})
    assert not resmon.summary(rt, now)["leak"]


async def test_soak_many_turns_do_not_grow(rt):
    """300 answers with tools: what JARVIS keeps per answer stays bounded (no list that only grows)."""
    tools.load_builtin()

    def script(n):
        out = []
        for i in range(n):
            out += [[("get_time", {})], f"Je {i} hodin."]
        return out
    rt.router = FakeRouter(script(400))

    async def turns(n):
        for i in range(n):
            await rt.agent.handle(f"kolik je hodin {i}?")
            rt.router.calls.clear()                                    # the fake AI's own log is not JARVIS
    await turns(60)                                                    # warm-up
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    await turns(140)
    gc.collect()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    grown = sum(s.size_diff for s in after.compare_to(before, "filename") if s.size_diff > 0)
    from jarvis import latency

    assert len(latency.get(rt).turns) <= 60
    assert grown < 6 * 2**20, f"grew {grown / 2**20:.1f} MB over 140 answers"
