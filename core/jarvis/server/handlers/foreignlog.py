"""3.18 Bezpečí → Co zkoušel cizí text: the steps foreign text led to and your answers (this PC only)."""
from __future__ import annotations

from . import handles


@handles("foreign_log_get", local_only=True)
async def foreign_log_get(c, m: dict) -> None:
    from ... import trust

    await c.send("foreign_log", items=trust.foreign_list(c.rt))
