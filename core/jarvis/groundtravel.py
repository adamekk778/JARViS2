"""3.19 Vlaky a autobusy (návrh 3): RegioJet live – connections with prices and free seats from its public timetable –
and the purchase on its site in JARVIS' browser (it stops before paying, like every payment); České dráhy, Leo Express,
FlixBus and the rest through the IDOS search.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import unicodedata
from typing import Any
from urllib.parse import urlencode

log = logging.getLogger("jarvis.groundtravel")

RJ_API = "https://brn-ybus-pubapi.sa.cz/restapi"
RJ_SITE = "https://regiojet.cz/"
CITIES_TTL_S = 7 * 86400


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)).strip()


async def _get(path: str, params: dict | None = None, transport: Any = None) -> Any:
    from .connectors import http

    async with http(transport=transport, timeout=20) as c:
        r = await c.get(RJ_API + path, params=params, headers={"X-Lang": "cs", "X-Currency": "CZK", "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


async def cities(transport: Any = None) -> list[dict]:
    """RegioJet's towns [{id, name, country, aliases}] – kept on this PC for a week."""
    from . import paths

    f = paths.sub("travel") / "regiojet-cities.json"
    try:
        if f.exists() and time.time() - f.stat().st_mtime < CITIES_TTL_S:
            return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    data = await _get("/consts/locations", transport=transport)
    out = [{"id": c["id"], "name": c["name"], "country": k.get("code", ""), "aliases": c.get("aliases") or []}
           for k in data or [] for c in k.get("cities") or []]
    try:
        f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


async def find_city(name: str, transport: Any = None) -> dict | None:
    want = _fold(name)
    if not want:
        return None
    best = None
    for c in await cities(transport):
        names = [_fold(c["name"])] + [_fold(a) for a in c["aliases"]]
        if want in names:
            return c
        if best is None and any(n.startswith(want) for n in names):
            best = c
    return best


async def search(frm: str, to: str, day: str, transport: Any = None) -> dict:
    """{from, to, routes: [{dep, arr, kind, transfers, price_from, seats, bookable, minutes}], buy_url} or {error}."""
    a, b = await find_city(frm, transport), await find_city(to, transport)
    if not a or not b:
        return {"error": f"RegioJet nejezdí {'z ' + frm if not a else 'do ' + to}."}
    q = {"tariffs": "REGULAR", "fromLocationType": "CITY", "fromLocationId": a["id"], "toLocationType": "CITY",
         "toLocationId": b["id"], "departureDate": day}
    d = await _get("/routes/search/simple", q, transport)
    routes = []
    for r in (d or {}).get("routes") or []:
        try:
            dep = dt.datetime.fromisoformat(r["departureTime"][:19])
            arr = dt.datetime.fromisoformat(r["arrivalTime"][:19])
        except (KeyError, ValueError):
            continue
        routes.append({"dep": dep.isoformat(timespec="minutes"), "arr": arr.isoformat(timespec="minutes"),
                       "kind": "vlak" if "TRAIN" in (r.get("vehicleTypes") or []) else "bus",
                       "transfers": int(r.get("transfersCount") or 0), "price_from": r.get("priceFrom"),
                       "seats": r.get("freeSeatsCount"), "bookable": bool(r.get("bookable")),
                       "minutes": int((arr - dep).total_seconds() // 60)})
    buy = RJ_SITE + "?" + urlencode({k: v for k, v in q.items()})
    return {"from": a["name"], "to": b["name"], "day": day, "routes": routes, "buy_url": buy}


def line(r: dict) -> str:
    t = f"{r['dep'][11:16]}–{r['arr'][11:16]}"
    price = f", od {r['price_from']:g} Kč" if isinstance(r.get("price_from"), (int, float)) else ""
    seats = f", volných {r['seats']}" if r.get("seats") is not None else ""
    change = f", {r['transfers']}× přestup" if r["transfers"] else ""
    return f"{t} {r['kind']}{change}{price}{seats}" + ("" if r["bookable"] else " (nejde koupit)")
