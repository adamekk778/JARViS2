"""3.17 Průvodce rychlostí: the recommendations for this PC, and one of them applied on a click."""
from __future__ import annotations

from . import handles


@handles("speedwizard_get", slow=True)
async def speedwizard_get(c, m: dict) -> None:
    from ... import speedwizard

    await c.send("speedwizard", items=await speedwizard.recommendations(c.rt))


@handles("speedwizard_apply", local_only=True, slow=True)
async def speedwizard_apply(c, m: dict) -> None:
    from ... import speedwizard

    ok, text = await speedwizard.apply(c.rt, str(m.get("id") or ""))
    await c.send("speedwizard", items=await speedwizard.recommendations(c.rt), ok=ok, text=text)
