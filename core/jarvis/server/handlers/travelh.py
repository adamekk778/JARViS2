"""3.18 Cesty page: bookings, price watches, what trips cost. Cancelling goes through the chat (it asks twice); this
page only shows and stops watches."""
from __future__ import annotations

from . import handles


@handles("travel_get", local_only=True)
async def travel_get(c, m: dict) -> None:
    from ... import booking, money, tripcare

    rt = c.rt
    await money.ensure_rates(rt)
    b = rt.cfg.booking
    g, missing = booking.guest(rt)
    await c.send("travel", bookings=booking.bookings(rt, include_past=bool(m.get("past"))), watches=tripcare.watches(rt),
                 spend=tripcare.spend(rt), month_czk=round(booking.spent_this_month(rt)),
                 limits={"max_per_booking": b.max_per_booking, "monthly_budget": b.monthly_budget},
                 providers={"liteapi": bool(booking.lite_key()), "duffel": bool(booking.duffel_key()),
                            "sandbox": booking.sandbox()},
                 traveller_missing=missing)


@handles("travel_watch_stop", local_only=True)
async def travel_watch_stop(c, m: dict) -> None:
    from ... import tripcare

    try:
        tripcare.stop_watch(c.rt, int(m.get("id") or 0))
    except (TypeError, ValueError):
        pass
    await travel_get(c, {})


@handles("travel_drill", local_only=True, slow=True)
async def travel_drill(c, m: dict) -> None:
    """3.19 Zkušební rezervace (test keys only): every step and how long it took."""
    from ... import booking

    await c.send("travel_drill", running=True, steps=[])
    steps = await booking.drill(c.rt)
    await c.send("travel_drill", running=False, steps=steps)
