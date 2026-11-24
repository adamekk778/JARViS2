"""3.14 Mapa světa v HUD (návrh 49): what goes on the map – home, the car, the trips, planes over the house."""
from __future__ import annotations

import logging

from . import handles

log = logging.getLogger("jarvis.server.world")


async def map_data(rt) -> dict:
    from ... import car, travel

    out: dict = {"home": None, "car": None, "trips": [], "planes": []}
    try:
        from ...eyes import home_coords

        lat, lon, city = await home_coords(rt)
        out["home"] = {"lat": lat, "lon": lon, "name": city}
    except Exception as e:  # noqa: BLE001 – no city / offline: the map still shows the radar
        log.debug("map home: %s", e)
    if car.entities(rt).get("location") and getattr(rt, "home", None) is not None and rt.cfg.home.url:
        try:
            text, data = await car.status(rt)
            if data.get("lat") is not None:
                out["car"] = {"lat": data["lat"], "lon": data["lon"], "text": text}
        except Exception as e:  # noqa: BLE001
            log.debug("map car: %s", e)
    for t in travel.upcoming(rt, days=30):
        pts = []
        for code in (t.get("origin"), t.get("dest")):
            if code in travel.AIRPORTS:
                a = travel.AIRPORTS[code]
                pts.append({"code": code, "name": a[0], "lat": a[1], "lon": a[2]})
        out["trips"].append({"text": travel.describe(t), "kind": t["kind"], "points": pts})
    return out


@handles("world_map_get", slow=True)
async def world_map_get(c, m: dict) -> None:
    data = await map_data(c.rt)
    if m.get("planes"):
        try:
            from ...eyes import sky

            s = await sky(c.rt, 60)
            data["planes"] = [{"lat": p["lat"], "lon": p["lon"], "callsign": p.get("callsign", ""), "alt_m": p.get("alt_m")}
                              for p in s.get("planes", []) if p.get("lat") is not None and p.get("lon") is not None][:60]
        except Exception as e:  # noqa: BLE001
            log.debug("map planes: %s", e)
    await c.send("world_map", **data)
