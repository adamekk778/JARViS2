import json

import httpx
import pytest

from jarvis.config import Brain, ProviderCfg
from jarvis.llm.base import AllProvidersFailed
from jarvis.llm.router import Router


def sse(*events):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def text_events(text):
    return [{"choices": [{"delta": {"content": t}}]} for t in text.split(" ")]


def brain(*ids):
    return Brain(providers=[ProviderCfg(id=i, preset="custom", base_url=f"http://{i}/v1", model="m") for i in ids],
                 chain=list(ids), first_token_timeout=2)


async def collect(router, tools=None, **kw):
    text, calls = "", None
    async for ch in router.stream([{"role": "user", "content": "hi"}], tools, **kw):
        text += ch.text
        if ch.tool_calls:
            calls = ch.tool_calls
    return text, calls


async def test_fallback_on_500():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "a":
            return httpx.Response(500, text="boom")
        return sse(*text_events("ahoj"))

    r = Router(brain("a", "b"), lambda _: "", httpx.MockTransport(handler))
    text, _ = await collect(r)
    assert text == "ahoj" and seen == ["a", "b"] and r.last_used[0] == "b"


async def test_fallback_on_429_and_connect_error():
    def handler(req):
        if req.url.host == "a":
            return httpx.Response(429, text="rate limit")
        if req.url.host == "b":
            raise httpx.ConnectError("down")
        return sse(*text_events("ok"))

    r = Router(brain("a", "b", "c"), lambda _: "", httpx.MockTransport(handler))
    assert (await collect(r))[0] == "ok"


async def test_tools_unsupported_retries_without_tools():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "tools" in body:
            return httpx.Response(400, text='{"error":"model does not support tools"}')
        return sse(*text_events("bez"))

    r = Router(brain("a"), lambda _: "", httpx.MockTransport(handler))
    tools = [{"type": "function", "function": {"name": "x", "parameters": {"type": "object", "properties": {}}}}]
    assert (await collect(r, tools))[0] == "bez"
    assert "a" in r.no_tools
    await collect(r, tools)
    assert "tools" not in bodies[-1]


async def test_streamed_tool_call_assembled():
    events = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "youtube_play", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"query": "aven'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'gers"}'}}]}}]},
    ]
    r = Router(brain("a"), lambda _: "", httpx.MockTransport(lambda req: sse(*events)))
    _, calls = await collect(r, [{"type": "function", "function": {"name": "youtube_play"}}])
    assert calls[0].name == "youtube_play" and calls[0].arguments == {"query": "avengers"} and calls[0].id == "c1"


async def test_all_fail():
    r = Router(brain("a", "b"), lambda _: "", httpx.MockTransport(lambda req: httpx.Response(503)))
    with pytest.raises(AllProvidersFailed) as e:
        await collect(r)
    assert set(e.value.errors) == {"a", "b"}


async def test_api_key_header_and_plain_json():
    def handler(req):
        assert req.headers["authorization"] == "Bearer KEY"
        return httpx.Response(200, json={"choices": [{"message": {"content": "json ok"}}]})

    r = Router(brain("a"), lambda _: "KEY", httpx.MockTransport(handler))
    assert (await collect(r))[0] == "json ok"


async def test_ollama_ndjson_tool_call():
    def handler(req):
        assert req.url.path == "/api/chat"
        lines = [
            {"message": {"content": "", "tool_calls": [{"function": {"name": "volume", "arguments": {"level": 30}}}]}},
            {"message": {"content": ""}, "done": True},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    b = Brain(providers=[ProviderCfg(id="ollama", preset="ollama", base_url="http://localhost:11434", model="q")], chain=["ollama"])
    r = Router(b, lambda _: "", httpx.MockTransport(handler))
    _, calls = await collect(r, [{"type": "function", "function": {"name": "volume"}}])
    assert calls[0].arguments == {"level": 30}


async def test_offline_only_skips_cloud():
    b = Brain(providers=[ProviderCfg(id="g", preset="groq", model="m"), ProviderCfg(id="o", preset="ollama", model="q")],
              chain=["g", "o"], offline_only=True)
    assert [p.id for p in Router(b, lambda _: "").providers()] == ["o"]
