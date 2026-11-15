"""3.12 Přehled AI: each brain in your order with its key, a used-up limit and its last error."""
import time

from jarvis import brainkey, secrets
from jarvis.llm import quota


def test_overview_lists_keys_limits_and_order(rt):
    import asyncio

    async def ok(pid):
        return {"ok": True, "message": "ok", "ms": 1}

    asyncio.run(brainkey.apply(rt, "csk-" + "a" * 40, ok))
    asyncio.run(brainkey.apply(rt, "gsk_" + "b" * 48, ok))
    rt.router.update(rt.cfg.brain)
    rt.router.limited[("groq", "openai/gpt-oss-120b")] = time.monotonic() + 120
    rt.router.last_errors["cerebras"] = "429 rate limit"
    items = quota.overview(rt)
    ids = [i["id"] for i in items]
    assert ids[:2] == ["groq", "cerebras"] and ids[-2:] == ["omniroute", "ollama"]
    g = items[0]
    assert g["key"] and g["label"] == "Groq" and 100 <= g["limited_s"] <= 120
    c = items[1]
    assert c["key"] and c["limited_s"] == 0 and "429" in c["error"]
    assert secrets.get("cerebras").startswith("csk-")


def test_background_work_goes_to_the_pc_ai_when_it_is_ready(rt):
    """Šetřič limitů: a chat summary (light) is answered by the AI on this PC; what you ask still goes to the cloud."""
    import asyncio

    from jarvis.llm.router import Router

    seen = []

    class Fake:
        def __init__(self, pid):
            self.pid, self.model = pid, "m"

        async def stream(self, msgs, tools, model=None):
            from jarvis.llm.base import Chunk

            seen.append(self.pid)
            yield Chunk(text="ok")

    import jarvis.llm.router as R

    brain = rt.cfg.brain.model_copy(deep=True)
    brain.chain = ["groq", "ollama"]
    from jarvis.config import ProviderCfg

    brain.providers = [ProviderCfg(id="groq", preset="groq", model="x"), ProviderCfg(id="ollama", preset="ollama", model="y")]
    r = Router(brain, lambda pid: "k", None)
    orig = R.build_provider
    R.build_provider = lambda pcfg, key, b, t: Fake(pcfg.id)
    try:
        async def ready():
            return True
        r.local_ready = ready
        asyncio.run(r.complete([{"role": "user", "content": "x"}], light=True))
        asyncio.run(r.complete([{"role": "user", "content": "x"}]))
        brain.save_limits = False
        asyncio.run(r.complete([{"role": "user", "content": "x"}], light=True))
    finally:
        R.build_provider = orig
    assert seen == ["ollama", "groq", "groq"]
