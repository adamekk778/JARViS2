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
    assert ids[:2] == ["groq", "cerebras"] and ids[-1] == "omniroute"
    g = items[0]
    assert g["key"] and g["label"] == "Groq" and 100 <= g["limited_s"] <= 120
    c = items[1]
    assert c["key"] and c["limited_s"] == 0 and "429" in c["error"]
    assert secrets.get("cerebras").startswith("csk-")
