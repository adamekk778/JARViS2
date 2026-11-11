"""Groq kept saying "no brain" after one message: every message carried all ~650 tools (~85 000 tokens) while the
free tier allows ~8 000 a minute and ~200 000 a day. Now a message carries a small, fitting set of tools; a short
rate limit is waited out; a model used up for the day is swapped for another Groq model."""
import json

import httpx

from jarvis import tools
from jarvis.config import Brain, ProviderCfg
from jarvis.llm import router as router_mod
from jarvis.llm.router import Router
from jarvis.tools import select as sel

tools.load_builtin()


def sse(text):
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in text.split(" ")) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def groq_brain():
    return Brain(providers=[ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")], chain=["groq"],
                 first_token_timeout=5)


async def collect(r):
    out = ""
    async for ch in r.stream([{"role": "user", "content": "ahoj"}], None):
        out += ch.text
    return out


def test_a_message_carries_a_small_fitting_set_of_tools(rt):
    all_size = len(json.dumps(tools.schemas(rt.cfg.tools.disabled, rt.cfg), ensure_ascii=False))
    for text, must in [("pošli e-mail Petrovi", "email_send"), ("napiš mi web pro pekárnu", "make_website"),
                       ("najdi duplicitní fotky", "find_duplicates"), ("zavolej mámě", "phone_call"),
                       ("pusť na youtube lofi", "youtube_play")]:
        s = rt.agent._tool_schemas(text)
        names = [x["function"]["name"] for x in s]
        assert must in names and "find_tools" in names and len(names) <= 45
        assert len(json.dumps(s, ensure_ascii=False)) < all_size / 12      # was ~264 000 characters every time


def test_disabled_tools_are_never_offered(rt):
    rt.cfg.tools.disabled = ["email_send"]
    assert "email_send" not in [x["function"]["name"] for x in rt.agent._tool_schemas("pošli e-mail")]


async def test_find_tools_lists_what_fits(rt):
    from types import SimpleNamespace

    res = await tools.call("find_tools", {"query": "převést video do mp4"}, SimpleNamespace(cfg=rt.cfg, rt=rt, knowledge=None))
    assert res.ok and res.data["tools"] and all(n in tools.REGISTRY for n in res.data["tools"])


async def test_agent_adds_found_tools_for_the_next_step(rt):
    """The AI calls find_tools → the tools it found go with the next request."""
    from jarvis.llm.base import Chunk, ToolCall

    sent = []

    async def fake_stream(msgs, tools_, **kw):
        sent.append([t["function"]["name"] for t in tools_ or []])
        if len(sent) == 1:
            yield Chunk(tool_calls=[ToolCall("c1", "find_tools", {"query": "duplicitní soubory"})], done=True)
        else:
            yield Chunk(text="Hotovo", done=True)

    rt.router.stream = fake_stream
    await rt.agent.handle("ukliď mi disk", [], "chat")
    assert "find_duplicates" not in sent[0] and "find_duplicates" in sent[1]


async def test_short_rate_limit_is_waited_out(monkeypatch):
    waits, calls = [], []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(router_mod.asyncio, "sleep", fake_sleep)

    def handler(req):
        calls.append(json.loads(req.content)["model"])
        if len(calls) == 1:
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... on tokens per minute (TPM): '
                                            'Limit 8000, Used 7000, Requested 4000. Please try again in 6.5s."}}')
        return sse("ahoj")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    assert await collect(r) == "ahoj"
    assert calls == ["openai/gpt-oss-120b"] * 2 and waits and 6.5 <= waits[0] < 8


async def test_daily_limit_switches_to_another_groq_model_and_remembers():
    calls = []

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "whisper-large-v3")]})
        model = json.loads(req.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... on tokens per day (TPD): '
                                            'Limit 200000, Used 199000. Please try again in 41m12s."}}')
        return sse("jsemtu")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    assert await collect(r) == "jsemtu"
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    calls.clear()
    assert await collect(r) == "jsemtu"
    assert calls == ["openai/gpt-oss-20b"]                 # the used-up model is not asked again for now


def test_retry_after_parsing():
    f = router_mod.retry_after
    assert f(Exception("Please try again in 7.66s.")) == 7.66
    assert f(Exception("Please try again in 1m12.5s")) == 72.5
    assert f(Exception("try again in 450ms")) == 0.45
    assert f(Exception("boom")) is None


def test_search_matches_word_starts():
    assert "make_website" in sel.search(tools.REGISTRY, "web pro pekárnu", 10)


async def test_a_broken_tool_call_is_asked_again_and_tools_stay_on():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(bool(body.get("tools")))
        if len(calls) == 1:
            return httpx.Response(400, text='{"error":{"message":"Failed to call a function. Please adjust your prompt.",'
                                            '"code":"tool_use_failed"}}')
        return sse("ok")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    out = ""
    async for ch in r.stream([{"role": "user", "content": "ahoj"}], [{"type": "function", "function": {"name": "x", "parameters": {}}}]):
        out += ch.text
    assert out == "ok" and calls == [True, True] and "groq" not in r.no_tools
