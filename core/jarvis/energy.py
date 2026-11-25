"""3.14 Energie domu (návrh 24): the Czech spot price of electricity (OTE day-ahead market, via spotovaelektrina.cz – free,
no account) – the cheapest and the dearest hours today and tomorrow, and "start the washing machine / charge the car
in the cheapest 3 hours before 7:00" as a one-time task at the right moment.

Prices are the market price per MWh (shown per kWh); what you pay also has distribution, fees and VAT on top – the
ORDER of the hours is what matters for planning.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json"
_CACHE: dict = {"at": 0.0, "data": None}
CACHE_S = 900


def parse(data: dict, today: dt.date) -> list[dict]:
    """→ [{"start": datetime, "hour": 0–23, "czk_kwh": float, "eur_mwh": float, "level": str}] for today and tomorrow."""
    out = []
    for key, day in (("hoursToday", today), ("hoursTomorrow", today + dt.timedelta(days=1))):
        for it in (data or {}).get(key) or []:
            try:
                h = int(it["hour"])
                out.append({"start": dt.datetime.combine(day, dt.time(h)), "hour": h,
                            "czk_kwh": round(float(it["priceCZK"]) / 1000, 3), "eur_mwh": float(it.get("priceEur") or 0),
                            "level": str(it.get("level") or "")})
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out, key=lambda x: x["start"])


async def prices(rt: Any, client: Any = None) -> list[dict]:
    if _CACHE["data"] is not None and time.time() - _CACHE["at"] < CACHE_S:
        return parse(_CACHE["data"], dt.date.today())
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get(URL, timeout=10)
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            await c.aclose()
    _CACHE.update(at=time.time(), data=data)
    return parse(data, dt.date.today())


def cheapest_window(items: list[dict], hours: int, after: dt.datetime, before: dt.datetime | None = None) -> dict | None:
    """The cheapest block of `hours` whole hours that starts at/after `after` (the current hour counts) and ends by `before`."""
    hours = max(1, min(int(hours), 12))
    cand = [x for x in items if x["start"] + dt.timedelta(hours=1) > after]
    best = None
    for i in range(len(cand) - hours + 1):
        block = cand[i:i + hours]
        if any(block[k + 1]["start"] - block[k]["start"] != dt.timedelta(hours=1) for k in range(hours - 1)):
            continue
        end = block[-1]["start"] + dt.timedelta(hours=1)
        if before is not None and end > before:
            continue
        avg = sum(x["czk_kwh"] for x in block) / hours
        if best is None or avg < best["avg"]:
            best = {"start": max(block[0]["start"], after.replace(second=0, microsecond=0)), "end": end, "avg": round(avg, 3)}
    return best


def summary(items: list[dict], now: dt.datetime) -> dict:
    today = [x for x in items if x["start"].date() == now.date()]
    nowh = next((x for x in today if x["hour"] == now.hour), None)
    rest = [x for x in items if x["start"] + dt.timedelta(hours=1) > now]
    cheap = sorted(rest, key=lambda x: x["czk_kwh"])[:3]
    dear = sorted(rest, key=lambda x: -x["czk_kwh"])[:3]
    return {"now": nowh, "cheapest": cheap, "dearest": dear, "tomorrow": any(x["start"].date() > now.date() for x in items)}


def say_hour(x: dict, now: dt.datetime) -> str:
    day = "" if x["start"].date() == now.date() else "zítra "
    return f"{day}{x['hour']}–{x['hour'] + 1} h ({x['czk_kwh']:.2f} Kč/kWh)".replace(".", ",")
