"""Mozek+ (návrhy 24, 25, 29): learned rules, 👍 / 👎 under answers and what they say about the AIs."""
from __future__ import annotations

from ... import brainplus
from . import handles


@handles("rules_get")
async def rules_get(c, m: dict) -> None:
    await c.send("rules", items=brainplus.rules(c.rt))


@handles("rule_delete", local_only=True)
async def rule_delete(c, m: dict) -> None:
    brainplus.delete_rule(c.rt, int(m.get("id", 0) or 0))
    await c.send("rules", items=brainplus.rules(c.rt))


@handles("rule_add", local_only=True)
async def rule_add(c, m: dict) -> None:
    brainplus.add_rule(c.rt, str(m.get("text", "")), source="ručně")
    await c.send("rules", items=brainplus.rules(c.rt))


@handles("answer_rate")
async def answer_rate(c, m: dict) -> None:
    ok = brainplus.rate(c.rt, str(m.get("id", "")), bool(m.get("good")), str(m.get("comment", "")))
    if not ok:
        await c.send("error", message="Tuhle odpověď už nenajdu.")
        return
    await c.send("ratings", **brainplus.rating_stats(c.rt), rated=str(m.get("id", "")), good=bool(m.get("good")))


@handles("ratings_get")
async def ratings_get(c, m: dict) -> None:
    await c.send("ratings", **brainplus.rating_stats(c.rt))


# ---------- 3.14 Úplně offline (návrh 31) ----------
@handles("offline_pack_get", slow=True)
async def offline_pack_get(c, m: dict) -> None:
    from ... import offlinepack

    await c.send("offline_pack", **(await offlinepack.status(c.rt)))


@handles("offline_pack_prepare", local_only=True, slow=True)
async def offline_pack_prepare(c, m: dict) -> None:
    from ... import offlinepack

    def progress(key: str, text: str) -> None:
        c.rt.bus.publish("offline_pack_progress", key=key, text=text)
        from ...notchplus import live

        live(c.rt, "offline", "Úplně offline", "wifi-slash", text=text[:24])
    res = await offlinepack.prepare(c.rt, switch=bool(m.get("switch")), progress=progress)
    await c.send("offline_pack", **res)


@handles("offline_pack_test", slow=True)
async def offline_pack_test(c, m: dict) -> None:
    from ... import offlinepack

    await c.send("offline_pack_test_result", **(await offlinepack.test(c.rt)))


# ---------- 3.14 the brain in one click: Claude, Ollama, … and its models ----------
@handles("brain_tiles_get")
async def brain_tiles_get(c, m: dict) -> None:
    from ... import brainpick

    await c.send("brain_tiles", tiles=brainpick.tiles(c.rt), current=brainpick.current(c.rt))


@handles("brain_models_get", slow=True)
async def brain_models_get(c, m: dict) -> None:
    from ... import brainpick

    try:
        out = await brainpick.models(c.rt, str(m.get("key", "")))
    except ValueError as e:
        await c.send("brain_models", key=str(m.get("key", "")), models=[], current="", error=str(e))
        return
    await c.send("brain_models", key=str(m.get("key", "")), **out)


@handles("brain_use")
async def brain_use(c, m: dict) -> None:
    from ... import brainpick

    only = m.get("only")
    try:
        res = brainpick.use(c.rt, str(m.get("key", "")), str(m.get("model", "") or ""), bool(only) if only is not None else None)
    except ValueError as e:
        await c.send("error", message=str(e))
        return
    await c.send("brain_used", **res)
    await c.send("brain_tiles", tiles=brainpick.tiles(c.rt), current=brainpick.current(c.rt))
    if res["preset"] in ("ollama", "lmstudio") and getattr(c.rt, "local", None) is not None:
        c.spawn(c.rt.local.warm(res["model"] or None))       # loaded now, so the first answer is quick
