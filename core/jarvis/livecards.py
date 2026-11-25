"""3.15 Mega animace (návrh 25): the small live picture under a tool's result in the chat – rain falling on the weather,
a plane flying the route, a parcel on its way, a song's wave, the body's state. Only a few plain numbers and words go
to the page (never the whole tool result)."""
from __future__ import annotations

from typing import Any

RAIN = (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82)
SNOW = (71, 73, 75, 77, 85, 86)
STORM = (95, 96, 99)


def _num(v: Any) -> float | None:
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def card(name: str, ok: bool, data: Any) -> dict | None:
    """The live card for this tool's result, or None (most tools have none)."""
    if not ok or not isinstance(data, (dict, list)):
        return None
    if name == "weather" and isinstance(data, dict):
        code = int(data.get("code") or 0)
        sky = "storm" if code in STORM else "snow" if code in SNOW else "rain" if code in RAIN else "cloud" if code in (2, 3, 45, 48) \
            else "clear"
        days = [{"max": _num(d.get("max")), "min": _num(d.get("min")), "rain": int(d.get("rain_pct") or 0)} for d in (data.get("days") or [])[:5]]
        return {"kind": "weather", "sky": sky, "temp": _num(data.get("temp")), "city": str(data.get("city") or "")[:40],
                "desc": str(data.get("desc") or "")[:40], "days": days}
    if name in ("flight_status", "trips_list", "trip_add") and isinstance(data, dict):
        from .travel import AIRPORTS

        t = data.get("trip") or (data.get("trips") or [None])[0] or (data if data.get("number") else None)
        if not isinstance(t, dict):
            return None
        live = data.get("live") or {}
        return {"kind": "flight" if t.get("kind") == "flight" else "train", "number": str(t.get("number") or ""),
                "from": AIRPORTS.get(t.get("origin", ""), (t.get("origin", ""),))[0][:24] if t.get("origin") else "",
                "to": AIRPORTS.get(t.get("dest", ""), (t.get("dest", ""),))[0][:24] if t.get("dest") else "",
                "flying": bool(live and not live.get("on_ground"))}
    if name == "parcels_list" and isinstance(data, dict):
        items = data.get("parcels") or []
        return {"kind": "parcel", "items": [{"name": str(p.get("shop") or p.get("carrier_name") or "Balík")[:30],
                                             "state": p.get("state") or "open"} for p in items[:4]]} if items else None
    if name in ("now_playing_info", "media_control") and isinstance(data, dict) and data.get("title"):
        return {"kind": "music", "title": str(data.get("title"))[:60], "artist": str(data.get("artist") or "")[:60]}
    if name in ("hotel_search", "flight_search", "travel_offers", "trip_plan") and isinstance(data, dict) and data.get("card"):
        return offers_card(data["card"])                # 3.18 the offers side by side
    if name == "body_status" and isinstance(data, dict) and data.get("level") not in (None, "unknown"):
        now = data.get("now") or {}
        return {"kind": "body", "level": data["level"], "sleep": _num(now.get("sleep_h")), "rest_hr": _num(now.get("rest_hr"))}
    return None


def offers_card(c: dict) -> dict | None:
    """3.18 Cesty: up to 5 offers side by side – number, name, total, per night, rating, distance, terms, why."""
    items: list[dict] = []
    for o in (c.get("offers") or [])[:5]:
        if not isinstance(o, dict):
            continue
        legs = [{"from": str(lg.get("from") or "")[:4], "to": str(lg.get("to") or "")[:4], "dep": str(lg.get("dep") or "")[:16],
                 "stops": int(lg.get("stops") or 0)} for lg in (o.get("legs") or [])[:2] if isinstance(lg, dict)]
        items.append({"n": int(o.get("n") or len(items) + 1), "kind": "flight" if o.get("kind") == "flight" else "hotel",
                      "name": str(o.get("name") or "")[:60], "stars": _num(o.get("stars")), "rating": _num(o.get("rating")),
                      "total": _num(o.get("total")), "currency": str(o.get("currency") or "")[:3],
                      "per_night": _num(o.get("per_night")), "nights": int(o.get("nights") or 0), "km": _num(o.get("km")),
                      "why": str(o.get("why") or "")[:120], "refundable": bool(o.get("refundable")),
                      "pay_at_property": bool(o.get("pay_at_property")), "breakfast": bool(o.get("breakfast")), "legs": legs})
    return {"kind": "offers", "title": str(c.get("title") or "")[:40], "items": items} if items else None
