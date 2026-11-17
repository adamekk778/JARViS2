"""Gemini "high demand" (503): the key is fine – a lighter model answers, and the key is accepted."""
import asyncio
import json

import httpx

from jarvis import brainkey
from jarvis.config import Brain, ProviderCfg
from jarvis.llm.router import Router

BUSY = '{"error": {"code": 503, "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.", "status": "UNAVAILABLE"}}'


def _transport(asked):
    def handler(req: httpx.Request):
        model = json.loads(req.content)["model"]
        asked.append(model)
        if model == "gemini-3.8-flash":
            return httpx.Response(503, text=BUSY)
        body = 'data: {"choices":[{"delta":{"content":"funguju"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def test_overloaded_model_moves_to_a_lighter_one():
    asked = []
    brain = Brain(providers=[ProviderCfg(id="gemini", preset="gemini", base_url="https://g.example/v1beta/openai",
                                         model="gemini-3.8-flash", fast_model="gemini-3.5-flash-lite")], chain=["gemini"])
    out = asyncio.run(Router(brain, lambda k: "AIzaKEY", _transport(asked)).complete([{"role": "user", "content": "hi"}]))
    assert out == "funguju" and asked[:2] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


def test_high_demand_counts_as_a_working_key():
    ok, msg = brainkey.explain("gemini: HTTP 503: " + BUSY)
    assert ok and "Klíč funguje" in msg


def test_gemini_gets_its_thought_signatures_back():
    """Gemini 3 signs the thought behind a tool call; without the signature in the next request it answers 400."""
    from jarvis.llm.base import ToolCallAssembler
    from jarvis.llm.openai_compat import GEMINI_SKIP, best_gemini, pick_model

    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append(body)
        if len(seen) == 1:
            sse = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function","function":{"name":"get_time",'
                   '"arguments":"{}"},"extra_content":{"google":{"thought_signature":"SIG-A"}}}]}}]}\n\ndata: [DONE]\n\n')
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        calls = [m for m in body["messages"] if m.get("tool_calls")]
        for m in calls:                                  # what Gemini checks
            if not m["tool_calls"][0].get("extra_content", {}).get("google", {}).get("thought_signature"):
                return httpx.Response(400, text='{"error":{"message":"Function call is missing a thought_signature"}}')
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hotovo"}}]}\n\ndata: [DONE]\n\n',
                              headers={"content-type": "text/event-stream"})

    from jarvis.llm.openai_compat import OpenAICompat

    prov = OpenAICompat("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "AIza",
                        transport=httpx.MockTransport(handler))

    async def go():
        calls = None
        async for ch in prov.stream([{"role": "user", "content": "kolik je hodin"}], [{"type": "function", "function": {"name": "get_time"}}]):
            calls = ch.tool_calls or calls
        msgs = [{"role": "user", "content": "kolik je hodin"},
                {"role": "assistant", "content": None, "tool_calls": [c.as_message() for c in calls]},
                {"role": "tool", "tool_call_id": "c1", "name": "get_time", "content": "12:00"},
                # an older step made by another AI (no signature at all)
                {"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": "a", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "x", "name": "a", "content": "ok"}]
        text = ""
        async for ch in prov.stream(msgs, None):
            text += ch.text
        return calls, text
    calls, text = asyncio.run(go())
    assert calls[0].extra == {"google": {"thought_signature": "SIG-A"}} and text == "hotovo"
    sent = [m for m in seen[1]["messages"] if m.get("tool_calls")]
    assert sent[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG-A"
    assert sent[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == GEMINI_SKIP
    # other services never get the Google field
    asm = ToolCallAssembler()
    asm.add([{"index": 0, "id": "a", "function": {"name": "x", "arguments": "{}"}}])
    assert "extra_content" not in asm.result()[0].as_message()
    # a switched-off model: the newest general Flash from Google's list
    models = ["models/gemini-3.5-flash-lite", "models/gemini-3.8-flash", "models/gemini-3.6-flash", "models/gemini-2.5-flash-image",
              "models/gemini-3.9-flash-preview", "models/gemini-embedding-2", "models/gemini-4-hydrogen"]
    assert best_gemini(models) == "gemini-3.8-flash" and pick_model(models) == "gemini-3.8-flash"
