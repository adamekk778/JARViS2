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
        if model == "gemini-flash-latest":
            return httpx.Response(503, text=BUSY)
        body = 'data: {"choices":[{"delta":{"content":"funguju"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def test_overloaded_model_moves_to_a_lighter_one():
    asked = []
    brain = Brain(providers=[ProviderCfg(id="gemini", preset="gemini", base_url="https://g.example/v1beta/openai",
                                         model="gemini-flash-latest", fast_model="gemini-flash-lite-latest")], chain=["gemini"])
    out = asyncio.run(Router(brain, lambda k: "AIzaKEY", _transport(asked)).complete([{"role": "user", "content": "hi"}]))
    assert out == "funguju" and asked[:2] == ["gemini-flash-latest", "gemini-flash-lite-latest"]


def test_high_demand_counts_as_a_working_key():
    ok, msg = brainkey.explain("gemini: HTTP 503: " + BUSY)
    assert ok and "Klíč funguje" in msg
