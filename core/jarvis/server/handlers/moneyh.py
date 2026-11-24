"""3.19 Peníze: one overview of what goes out this month (AI, trips, subscriptions, approved money steps) – this PC only."""
from __future__ import annotations

from . import handles


@handles("money_get", local_only=True, slow=True)
async def money_get(c, m: dict) -> None:
    from ... import money

    await money.ensure_rates(c.rt)
    await c.send("money", **money.overview(c.rt))
