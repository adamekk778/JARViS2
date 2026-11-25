"""3.14 návrhy 2, 3, 4, 28: Claude through Anthropic's own API (caching, effort, thinking, fallbacks), the newer
default models, the difficulty router."""
from types import SimpleNamespace as NS

import pytest

from conftest import FakeRouter
from jarvis.config import ProviderCfg
from jarvis.llm import claude, difficulty
from jarvis.llm.openai_compat import without_foreign
from jarvis.llm.presets import PRESETS


class FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e
        return gen()

    async def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, events, final):
        self.sent = []
        outer = self

        class Msgs:
            def stream(self, **params):
                outer.sent.append(params)
                return FakeStream(events, final)
        self.beta = NS(messages=Msgs())


def block(**kw):
    d = dict(kw)
    return NS(**d, to_dict=lambda: dict(d))


def final(content, stop="end_turn", **usage):
    return NS(content=content, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=usage.get("cr", 0), cache_creation_input_tokens=0))


OPENAI_MSGS = [
    {"role": "system", "content": "Jsi JARVIS."},
    {"role": "user", "content": [{"type": "text", "text": "co je na obrázku?"},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "t1", "type": "function", "function": {"name": "get_time", "arguments": "{}"},
         "extra_content": {"anthropic": {"thinking": [{"type": "thinking", "thinking": "", "signature": "sig"}]}}},
        {"id": "t2", "type": "function", "function": {"name": "weather", "arguments": '{"city": "Brno"}'}}]},
    {"role": "tool", "tool_call_id": "t1", "name": "get_time", "content": '{"ok": true}'},
    {"role": "tool", "tool_call_id": "t2", "name": "weather", "content": '{"ok": true}'},
]
TOOLS = [{"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object", "properties": {}}}}
         for n in ("open_app", "get_time", "weather", "make_website")]


def test_convert_round_trip():
    system, msgs = claude.convert(OPENAI_MSGS)
    assert system == [{"type": "text", "text": "Jsi JARVIS."}]
    assert msgs[0]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
    a = msgs[1]
    assert a["role"] == "assistant" and a["content"][0]["type"] == "thinking"           # the block goes back first
    assert [b["type"] for b in a["content"]] == ["thinking", "tool_use", "tool_use"]
    assert a["content"][2]["input"] == {"city": "Brno"}
    r = msgs[2]                                                                         # both results in ONE message
    assert r["role"] == "user" and [b["tool_use_id"] for b in r["content"]] == ["t1", "t2"]


def test_cache_marks_and_params():
    p = claude.Claude("anthropic", "https://api.anthropic.com/v1", "claude-opus-5-5", "k", max_tokens=2048)
    p.effort = "high"
    params = p.params(OPENAI_MSGS, TOOLS)
    tl = params["tools"]
    assert "cache_control" in tl[2] and "cache_control" not in tl[3]    # after the run of everyday tools
    assert all(t["eager_input_streaming"] for t in tl)
    assert params["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert params["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert params["max_tokens"] >= 16000 and "temperature" not in params
    assert params["output_config"] == {"effort": "high"}
    assert params["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    assert params["fallbacks"] == "default" and claude.BETAS_FALLBACK in params["betas"]
    h = claude.Claude("anthropic", "", "claude-haiku-5-5", "k").params(OPENAI_MSGS, None)
    assert "fallbacks" not in h and claude.BETAS_FALLBACK not in h["betas"] and "tools" not in h


async def test_stream_text_and_tool_calls():
    fin = final([block(type="thinking", thinking="", signature="s1"), block(type="text", text="Ahoj"),
                 block(type="tool_use", id="u1", name="get_time", input={})], stop="tool_use")
    c = FakeClient([NS(type="text", text="Ahoj")], fin)
    p = claude.Claude("anthropic", "", "claude-opus-5-5", "k", client=c)
    out = [ch async for ch in p.stream(OPENAI_MSGS, TOOLS)]
    assert out[0].text == "Ahoj"
    calls = out[-1].tool_calls
    assert calls[0].name == "get_time" and calls[0].extra["anthropic"]["thinking"][0]["signature"] == "s1"
    msg = calls[0].as_message()                       # → history → back to Claude with the thinking block
    _, back = claude.convert([{"role": "user", "content": "x"}, {"role": "assistant", "content": "", "tool_calls": [msg]}])
    assert back[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "s1"}
    assert p.last_usage["in"] == 10


async def test_refusal_and_cut_tool_call():
    c = FakeClient([], final([], stop="refusal"))
    p = claude.Claude("anthropic", "", "claude-opus-5-5", "k", client=c)
    out = [ch async for ch in p.stream([{"role": "user", "content": "x"}], None)]
    assert "odmítl" in out[-1].text
    c2 = FakeClient([], final([block(type="tool_use", id="u", name="write_text_file", input={"path": "a"})], stop="max_tokens"))
    p2 = claude.Claude("anthropic", "", "claude-opus-5-5", "k", client=c2)
    from jarvis.llm.base import ProviderError

    with pytest.raises(ProviderError) as e:
        [ch async for ch in p2.stream([{"role": "user", "content": "x"}], TOOLS)]
    assert e.value.is_bad_tool_call                   # the router asks again instead of running a half input


def test_router_builds_claude_and_new_defaults():
    from jarvis.config import Brain
    from jarvis.llm.router import build_provider

    p = build_provider(ProviderCfg(id="anthropic", preset="anthropic"), "k", Brain())
    assert isinstance(p, claude.Claude) and p.model == "claude-opus-5-5"
    assert PRESETS["anthropic"]["fast_model"] == "claude-haiku-5-5"
    assert PRESETS["ollama"]["model"] == "qwen3:4b" and PRESETS["openai"]["model"] == "gpt-5-mini"
    other = build_provider(ProviderCfg(id="x", preset="anthropic", base_url="https://gateway.example/v1"), "k", Brain())
    assert not isinstance(other, claude.Claude)        # an OpenAI-compatible gateway in front of Claude stays as it was


def test_foreign_thinking_stays_with_claude():
    out = without_foreign(OPENAI_MSGS)
    calls = out[2]["tool_calls"]
    assert "extra_content" not in calls[0] and OPENAI_MSGS[2]["tool_calls"][0]["extra_content"]   # copy, not edited


@pytest.mark.parametrize("text,tier", [
    ("ahoj", "fast"), ("díky moc", "fast"), ("jak se máš", "fast"), ("Ahoj Jarvisi", "fast"),
    ("pusť hudbu", "normal"), ("jaké bude zítra počasí v Brně", "normal"), ("připomeň mi koš", "normal"),
    ("naplánuj mi stěhování za tři týdny", "strong"), ("porovnej tyhle tři nabídky", "strong"),
    ("proč je můj počítač pomalý", "strong"), ("napiš kód na stahování faktur", "strong"),
    ("slovo " * 70, "strong"),
])
def test_difficulty(text, tier):
    assert difficulty.classify(text) == tier


def test_difficulty_modes():
    assert difficulty.classify("ahoj", agent_mode=True) == "strong"
    assert difficulty.classify("ahoj", attachments=1) != "fast"


async def test_agent_sends_tier(rt):
    rt.router = FakeRouter(["Ahoj!", "Hotovo."])
    await rt.agent.handle("ahoj")
    assert rt.router.calls[0]["fast"] is True and rt.router.calls[0]["effort"] == "low"
    await rt.agent.handle("naplánuj mi dovolenou v Itálii na týden")
    assert rt.router.calls[-1]["effort"] == "high" and rt.router.calls[-1]["fast"] is False
