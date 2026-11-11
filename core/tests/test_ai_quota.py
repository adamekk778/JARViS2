"""3.12 How much of today's free AI is left (notch "Groq · 70 %") and a notice when another AI takes over."""
import json

import httpx

from jarvis.config import Brain, ProviderCfg
from jarvis.llm.quota import Quota, brain_state
from jarvis.llm.router import Router


def sse(text):
    body = f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\ndata: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream", "x-ratelimit-limit-requests": "1000",
                                        "x-ratelimit-remaining-requests": "700"}, content=body.encode())


def test_left_pct_takes_the_lower_of_headers_and_own_count():
    q = Quota()
    q.from_headers("groq", "openai/gpt-oss-120b", {"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "900"})
    assert q.left_pct("groq", "groq", "openai/gpt-oss-120b", 0, 0) == 90
    assert q.left_pct("groq", "groq", "openai/gpt-oss-120b", 150_000, 0) == 25      # tokens today are the tighter one
    assert q.left_pct("x", "custom", "m", 10, 1) is None                            # unknown → nothing shown


async def test_router_reads_headers_and_brain_state_says_left(rt):
    rt.cfg.brain.providers = [ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")]
    rt.cfg.brain.chain = ["groq"]
    rt.router = Router(rt.cfg.brain, lambda _: "gsk_x", httpx.MockTransport(lambda req: sse("ahoj")))
    async for _ in rt.router.stream([{"role": "user", "content": "ahoj"}], None):
        pass
    st = brain_state(rt)
    assert st["provider"] == "groq" and st["left"] == 70


async def test_switching_to_a_backup_ai_is_announced_once(rt):
    said = []
    rt.notify = lambda title, body, **k: said.append((title, body)) or 1

    def handler(req):
        if req.url.host == "api.groq.com":
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... tokens per day (TPD). Please try again in 3h2m."}}')
        return sse("ahoj")

    brain = Brain(providers=[ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b"),
                             ProviderCfg(id="gemini", preset="gemini", model="gemini-2.5-flash")], chain=["groq", "gemini"],
                  first_token_timeout=5)
    r = Router(brain, lambda _: "k", httpx.MockTransport(handler))
    r.on_switch = rt._brain_switched
    for _ in range(2):
        async for _ in r.stream([{"role": "user", "content": "ahoj"}], None):
            pass
    assert len(said) == 1 and "Groq" in said[0][1] and "Gemini" in said[0][1]
