"""3.18 Rezervace cest (návrhy 5–9, 16): hotels and flights found by your description, booked – and paid – only after
your confirmation.

Providers (keys in the keyring, Nastavení → Propojení):
- LiteAPI (hotels): search, rates, prebook (the price locked and checked again), book. Payment: the card you saved
  in your LiteAPI account (ACC_CREDIT_CARD) or its wallet – JARVIS never sees a card number. A "sand_" key = test mode:
  everything works, nothing is booked or charged.
- Duffel (hotels "Stays" and flights): search, quote / offer re-check, book from your Duffel balance.
- Without a key: the browser – JARVIS fills everything in and stops before paying (tools/browser.py never clicks
  "Zaplatit / Rezervovat" without your confirmation, whatever the trust setting).

Safety (all of it, every time): the booking tools always ask, twice (the second time with the exact amount), from the
phone with your fingerprint when you are away; never just because some page or e-mail said so; a limit per booking and
a monthly budget; right before paying the price is checked again – a different price or terms stop it and ask again.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger("jarvis.booking")

LITE_API = "https://api.liteapi.travel/v3.0"
LITE_BOOK = "https://book.liteapi.travel/v3.0"
DUFFEL = "https://api.duffel.com"
OFFER_TTL_S = 30 * 60
PRICE_TOLERANCE = 0.005           # a re-checked price may differ by 0.5 % (rounding), more stops the booking
SQL = """CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, ref TEXT, kind TEXT,
         name TEXT, city TEXT, start TEXT, end TEXT, total REAL, currency TEXT, refundable INTEGER, free_cancel_until TEXT,
         pay_at_property INTEGER, status TEXT, sandbox INTEGER, data TEXT, created REAL, business INTEGER DEFAULT 0)"""


class BookingError(Exception):
    pass


def cfg(rt: Any) -> Any:
    return rt.cfg.booking


def _db(rt: Any) -> Any:
    rt.db.exec(SQL)
    return rt.db


# ------------------------------------------------------------------------------------------ keys and HTTP
def lite_key() -> str:
    from . import connectors

    return connectors.value("liteapi", "api_key").strip() if connectors.configured("liteapi") else ""


def duffel_key() -> str:
    from . import connectors

    return connectors.value("duffel", "access_token").strip() if connectors.configured("duffel") else ""


def sandbox() -> bool:
    k = lite_key()
    return k.startswith("sand_") if k else duffel_key().startswith("duffel_test")


async def _lite(method: str, url: str, body: dict | None = None, params: dict | None = None, transport: Any = None,
                timeout: float = 40) -> dict:
    from .connectors import http

    async with http(transport=transport, timeout=timeout) as c:
        r = await c.request(method, url, json=body, params=params, headers={"X-API-Key": lite_key(), "Accept": "application/json"})
    if r.status_code == 401:
        raise BookingError("LiteAPI nepřijalo klíč – zkontroluj ho v Nastavení → Propojení → LiteAPI.")
    if r.status_code == 429:
        raise BookingError("LiteAPI teď odmítá moc dotazů – zkus to za chvíli.")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        raise BookingError(f"LiteAPI: {err.get('message') or r.status_code}")
    return data if isinstance(data, dict) else {"data": data}


async def _duffel(method: str, path: str, body: dict | None = None, params: dict | None = None, transport: Any = None,
                  timeout: float = 60) -> dict:
    from .connectors import http

    async with http(transport=transport, timeout=timeout) as c:
        r = await c.request(method, DUFFEL + path, json={"data": body} if body is not None else None, params=params,
                            headers={"Authorization": f"Bearer {duffel_key()}", "Duffel-Version": "v2",
                                     "Accept": "application/json"})
    if r.status_code == 401:
        raise BookingError("Duffel nepřijal přístupový token – zkontroluj ho v Nastavení → Propojení → Duffel.")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        errs = data.get("errors") if isinstance(data, dict) else None
        msg = (errs[0].get("message") if isinstance(errs, list) and errs and isinstance(errs[0], dict) else "") or r.status_code
        raise BookingError(f"Duffel: {msg}")
    return (data.get("data") if isinstance(data, dict) else None) or {}


# ------------------------------------------------------------------------------------------ the offers found (in memory)
def _offers(rt: Any) -> dict:
    o = getattr(rt, "travel_offers", None)
    if o is None:
        o = rt.travel_offers = {}
    now = time.time()
    for k in [k for k, v in o.items() if now - v.get("found", 0) > OFFER_TTL_S]:
        o.pop(k, None)
    return o


def remember(rt: Any, offers: list[dict]) -> list[dict]:
    """Keep the offers of one search as 1, 2, 3… (the numbers you say: "beru dvojku")."""
    store = _offers(rt)
    store.clear()
    for i, off in enumerate(offers, start=1):
        off["n"] = i
        off["found"] = time.time()
        store[str(i)] = off
    return offers


def offer(rt: Any, n: Any) -> dict | None:
    return _offers(rt).get(str(n).strip().lstrip("#"))


# ------------------------------------------------------------------------------------------ LiteAPI hotels
def _lite_rate(hotel: dict, rt_: dict, rate: dict, nights: int) -> dict:
    total = (rate.get("retailRate") or {}).get("total") or []
    amount = float(total[0].get("amount") or 0) if total else 0.0
    cur = str(total[0].get("currency") or "") if total else ""
    pol = rate.get("cancellationPolicies") or {}
    infos = sorted(pol.get("cancelPolicyInfos") or [], key=lambda x: str(x.get("cancelTime", "")))
    refundable = pol.get("refundableTag") == "RFN"
    free_until = str(infos[0].get("cancelTime") or "")[:16].replace(" ", "T") if refundable and infos else ""
    pay = [str(p) for p in rate.get("paymentTypes") or []]
    return {"provider": "liteapi", "kind": "hotel", "offer_id": rt_.get("offerId"), "hotel_id": hotel.get("id"),
            "name": hotel.get("name") or "", "address": hotel.get("address") or "", "city": hotel.get("city") or "",
            "lat": hotel.get("latitude"), "lon": hotel.get("longitude"), "stars": hotel.get("stars"),
            "rating": hotel.get("rating"), "reviews": hotel.get("reviewCount"), "photo": hotel.get("main_photo") or "",
            "room": rt_.get("name") or rate.get("name") or "", "board": rate.get("boardName") or "",
            "breakfast": str(rate.get("boardType") or "") not in ("RO", ""), "refundable": refundable,
            "free_cancel_until": free_until, "pay_at_property": any("PROPERTY" in p for p in pay), "total": round(amount, 2),
            "currency": cur, "nights": nights, "per_night": round(amount / max(1, nights), 2)}


async def lite_search(rt: Any, c: dict, transport: Any = None) -> list[dict]:
    """Hotels in the city with their cheapest fitting rate each."""
    hotels = (await _lite("GET", LITE_API + "/data/hotels", params={
        "cityName": c["city"], "countryCode": c.get("country") or "", "limit": 60,
        **({"minRating": c["min_rating"]} if c.get("min_rating") else {}),
        **({"starRating": ",".join(str(s) for s in range(int(c["stars"]), 6))} if c.get("stars") else {}),
    }, transport=transport)).get("data") or []
    if not hotels:
        return []
    by_id = {h["id"]: h for h in hotels if h.get("id")}
    body = {"hotelIds": list(by_id)[:50], "checkin": c["checkin"], "checkout": c["checkout"], "currency": c["currency"],
            "guestNationality": c.get("nationality") or "CZ", "timeout": 10, "maxRatesPerHotel": 3,
            "occupancies": [{"adults": int(c.get("adults") or 2), "children": list(c.get("children") or [])}
                            for _ in range(int(c.get("rooms") or 1))]}
    if c.get("free_cancel_only"):
        body["refundableRatesOnly"] = True
    rates = (await _lite("POST", LITE_API + "/hotels/rates", body=body, transport=transport, timeout=60)).get("data") or []
    nights = nights_of(c)
    out = []
    for h in rates:
        hotel = by_id.get(h.get("hotelId")) or {"id": h.get("hotelId")}
        cands = [_lite_rate(hotel, t, r, nights) for t in h.get("roomTypes") or [] for r in (t.get("rates") or [])[:1]]
        cands = [x for x in cands if x["offer_id"] and x["total"] > 0]
        if cands:
            out.append(min(cands, key=lambda x: x["total"]))
    return out


async def lite_recheck(rt: Any, off: dict, transport: Any = None) -> dict:
    """Prebook: the price is locked and given again (and whether the terms changed)."""
    d = (await _lite("POST", LITE_BOOK + "/rates/prebook", body={"offerId": off["offer_id"], "usePaymentSdk": False},
                     transport=transport, timeout=60)).get("data") or {}
    return {"ref": d.get("prebookId"), "total": float(d.get("price") or 0), "currency": str(d.get("currency") or ""),
            "changed": bool(d.get("cancellationChanged") or d.get("boardChanged") or (d.get("priceDifferencePercent") or 0))}


async def lite_book(rt: Any, off: dict, pre: dict, guest: dict, transport: Any = None) -> dict:
    method = getattr(cfg(rt), "liteapi_payment", "ACC_CREDIT_CARD")
    holder = {"firstName": guest["first"], "lastName": guest["last"], "email": guest["email"], "phone": guest["phone"]}
    body = {"prebookId": pre["ref"], "holder": holder, "payment": {"method": method},
            "clientReference": f"jarvis-{int(time.time())}",
            "guests": [{"occupancyNumber": 1, "firstName": guest["first"], "lastName": guest["last"], "email": guest["email"]}]}
    d = (await _lite("POST", LITE_BOOK + "/rates/book", body=body, transport=transport, timeout=90)).get("data") or {}
    if str(d.get("status") or "").upper() != "CONFIRMED":
        raise BookingError(f"Hotel rezervaci nepotvrdil (stav {d.get('status') or '?'}).")
    return {"ref": str(d.get("bookingId") or ""), "confirmation": str(d.get("hotelConfirmationCode") or ""),
            "total": float(d.get("price") or pre["total"]), "currency": str(d.get("currency") or pre["currency"]),
            "sandbox": bool(d.get("sandbox")) or sandbox(), "raw": d}


async def lite_cancel(rt: Any, ref: str, transport: Any = None) -> dict:
    d = (await _lite("PUT", LITE_BOOK + f"/bookings/{ref}", transport=transport, timeout=60)).get("data") or {}
    return {"status": str(d.get("status") or ""), "fee": d.get("cancellation_fee"), "refund": d.get("refund_amount"),
            "currency": d.get("currency")}


# ------------------------------------------------------------------------------------------ Duffel stays + flights
def _duffel_stay(r: dict, nights: int) -> dict:
    a = r.get("accommodation") or {}
    loc = a.get("location") or {}
    geo = loc.get("geographic_coordinates") or {}
    amount = float(r.get("cheapest_rate_total_amount") or 0)
    return {"provider": "duffel", "kind": "hotel", "offer_id": r.get("id"), "hotel_id": a.get("id"), "name": a.get("name") or "",
            "address": ((loc.get("address") or {}).get("line_one") or ""), "city": ((loc.get("address") or {}).get("city_name") or ""),
            "lat": geo.get("latitude"), "lon": geo.get("longitude"), "stars": a.get("rating"), "rating": a.get("review_score"),
            "reviews": a.get("review_count"), "photo": ((a.get("photos") or [{}])[0] or {}).get("url", ""), "room": "",
            "board": "", "breakfast": False, "refundable": False, "free_cancel_until": "", "pay_at_property": False,
            "total": round(amount, 2), "currency": str(r.get("cheapest_rate_currency") or ""), "nights": nights,
            "per_night": round(amount / max(1, nights), 2)}


async def duffel_stays_search(rt: Any, c: dict, transport: Any = None) -> list[dict]:
    from . import travel

    where = await travel.geocode(rt, c["city"])
    if not where:
        raise BookingError(f"Město {c['city']} nenajdu na mapě.")
    body = {"check_in_date": c["checkin"], "check_out_date": c["checkout"], "rooms": int(c.get("rooms") or 1),
            "guests": [{"type": "adult"}] * int(c.get("adults") or 2),
            "location": {"radius": int(c.get("radius_km") or 5),
                         "geographic_coordinates": {"latitude": where[0], "longitude": where[1]}}}
    if c.get("free_cancel_only"):
        body["free_cancellation_only"] = True
    d = await _duffel("POST", "/stays/search", body, transport=transport)
    return [_duffel_stay(r, nights_of(c)) for r in (d.get("results") or [])[:40] if r.get("id")]


async def duffel_stay_rate(rt: Any, off: dict, transport: Any = None) -> dict:
    """The cheapest rate of a search result – the price you were shown – with its real terms (fetch all rates)."""
    d = await _duffel("POST", f"/stays/search_results/{off['offer_id']}/actions/fetch_all_rates", transport=transport)
    rates = [r for room in ((d.get("accommodation") or {}).get("rooms") or []) for r in room.get("rates") or []]
    if not rates:
        raise BookingError("Hotel už nemá volný pokoj.")
    r = min(rates, key=lambda x: float(x.get("total_amount") or 1e12))
    tl = r.get("cancellation_timeline") or []
    return {"rate_id": r.get("id"), "board": r.get("board_type") or "", "refundable": bool(tl),
            "free_cancel_until": str(tl[0].get("before") or "")[:16] if tl else "",
            "pay_at_property": r.get("payment_type") not in (None, "pay_now"),
            "total": float(r.get("total_amount") or 0), "currency": str(r.get("total_currency") or "")}


async def duffel_stay_recheck(rt: Any, off: dict, transport: Any = None) -> dict:
    rate = await duffel_stay_rate(rt, off, transport)
    worse = off.get("refundable") and not rate["refundable"]          # shown as free to cancel, now it is not
    off.update(rate_id=rate["rate_id"], refundable=rate["refundable"], free_cancel_until=rate["free_cancel_until"],
               pay_at_property=rate["pay_at_property"], board=rate["board"] or off.get("board", ""))
    q = await _duffel("POST", "/stays/quotes", {"rate_id": rate["rate_id"]}, transport=transport)
    return {"ref": q.get("id"), "total": float(q.get("total_amount") or 0), "currency": str(q.get("total_currency") or ""),
            "changed": bool(worse)}


async def duffel_stay_book(rt: Any, off: dict, pre: dict, guest: dict, transport: Any = None) -> dict:
    d = await _duffel("POST", "/stays/bookings", {"quote_id": pre["ref"], "email": guest["email"], "phone_number": guest["phone"],
                                                  "guests": [{"given_name": guest["first"], "family_name": guest["last"]}]},
                      transport=transport, timeout=120)
    if str(d.get("status") or "") != "confirmed":
        raise BookingError(f"Hotel rezervaci nepotvrdil (stav {d.get('status') or '?'}).")
    return {"ref": str(d.get("id") or ""), "confirmation": str(d.get("reference") or ""), "total": pre["total"],
            "currency": pre["currency"], "sandbox": sandbox(), "raw": d}


async def duffel_stay_cancel(rt: Any, ref: str, transport: Any = None) -> dict:
    d = await _duffel("POST", f"/stays/bookings/{ref}/actions/cancel", transport=transport)
    return {"status": str(d.get("status") or ""), "fee": None, "refund": None, "currency": None}


def _flight(o: dict) -> dict:
    sl = o.get("slices") or []
    legs = []
    for s in sl:
        seg = s.get("segments") or []
        if not seg:
            continue
        legs.append({"from": (seg[0].get("origin") or {}).get("iata_code"), "to": (seg[-1].get("destination") or {}).get("iata_code"),
                     "dep": seg[0].get("departing_at"), "arr": seg[-1].get("arriving_at"), "stops": len(seg) - 1,
                     "carrier": (seg[0].get("operating_carrier") or seg[0].get("marketing_carrier") or {}).get("name"),
                     "flight": f"{(seg[0].get('marketing_carrier') or {}).get('iata_code', '')}{seg[0].get('marketing_carrier_flight_number', '')}"})
    cond = o.get("conditions") or {}
    ref = cond.get("refund_before_departure") or {}
    return {"provider": "duffel", "kind": "flight", "offer_id": o.get("id"), "name": (o.get("owner") or {}).get("name") or "",
            "legs": legs, "refundable": bool(ref.get("allowed")), "total": float(o.get("total_amount") or 0),
            "currency": str(o.get("total_currency") or ""), "expires": o.get("expires_at"),
            "passengers": [p.get("id") for p in o.get("passengers") or []]}


async def flight_search(rt: Any, c: dict, transport: Any = None) -> list[dict]:
    slices = [{"origin": c["origin"], "destination": c["destination"], "departure_date": c["date"]}]
    if c.get("return_date"):
        slices.append({"origin": c["destination"], "destination": c["origin"], "departure_date": c["return_date"]})
    body = {"slices": slices, "passengers": [{"type": "adult"}] * int(c.get("adults") or 1),
            "cabin_class": c.get("cabin") or "economy"}
    if c.get("direct"):
        body["max_connections"] = 0
    d = await _duffel("POST", "/air/offer_requests", body, params={"return_offers": "true", "supplier_timeout": 20000},
                      transport=transport, timeout=60)
    offers = sorted(d.get("offers") or [], key=lambda o: float(o.get("total_amount") or 1e12))[:20]
    return [_flight(o) for o in offers if o.get("id")]


async def flight_recheck(rt: Any, off: dict, transport: Any = None) -> dict:
    o = await _duffel("GET", f"/air/offers/{off['offer_id']}", transport=transport)
    return {"ref": o.get("id"), "total": float(o.get("total_amount") or 0), "currency": str(o.get("total_currency") or ""),
            "changed": False, "passengers": [p.get("id") for p in o.get("passengers") or []]}


async def flight_book(rt: Any, off: dict, pre: dict, guest: dict, transport: Any = None) -> dict:
    pids = pre.get("passengers") or off.get("passengers") or []
    if len(pids) != 1:
        raise BookingError("Letenky pro víc cestujících zatím rezervuji jen přes prohlížeč.")
    if not guest.get("born_on"):
        raise BookingError("Pro letenku chybí datum narození (Cesty → Údaje a limity).")
    pax = [{"id": pids[0], "given_name": guest["first"], "family_name": guest["last"], "born_on": guest["born_on"],
            "title": guest.get("title") or "mr", "gender": guest.get("gender") or "m", "email": guest["email"],
            "phone_number": guest["phone"]}]
    d = await _duffel("POST", "/air/orders", {"selected_offers": [pre["ref"]], "passengers": pax,
                                              "payments": [{"type": "balance", "amount": f"{pre['total']:.2f}", "currency": pre["currency"]}]},
                      transport=transport, timeout=120)
    if not d.get("id"):
        raise BookingError("Aerolinka objednávku nepotvrdila.")
    return {"ref": str(d["id"]), "confirmation": str(d.get("booking_reference") or ""), "total": float(d.get("total_amount") or pre["total"]),
            "currency": str(d.get("total_currency") or pre["currency"]), "sandbox": not bool(d.get("live_mode", True)), "raw": d}


async def flight_cancel_quote(rt: Any, ref: str, transport: Any = None) -> dict:
    d = await _duffel("POST", "/air/order_cancellations", {"order_id": ref}, transport=transport)
    return {"id": d.get("id"), "refund": d.get("refund_amount"), "currency": d.get("refund_currency"), "expires": d.get("expires_at")}


async def flight_cancel_confirm(rt: Any, cancellation_id: str, transport: Any = None) -> dict:
    d = await _duffel("POST", f"/air/order_cancellations/{cancellation_id}/actions/confirm", transport=transport)
    return {"status": "cancelled" if d.get("confirmed_at") else "pending", "refund": d.get("refund_amount"),
            "currency": d.get("refund_currency"), "fee": None}


# ------------------------------------------------------------------------------------------ the rules around money
def nights_of(c: dict) -> int:
    import datetime as dt

    try:
        return max(1, (dt.date.fromisoformat(c["checkout"]) - dt.date.fromisoformat(c["checkin"])).days)
    except (KeyError, ValueError):
        return 1


def to_czk(amount: float, currency: str) -> float:
    """CZK value for the limits: today's ČNB rate (3.19), a rough estimate only without any rate."""
    from .money import to_czk as czk

    return czk(amount, currency)


def spent_this_month(rt: Any, now: float | None = None) -> float:
    t = time.localtime(now or time.time())
    since = time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    rows = _db(rt).all("SELECT total, currency FROM bookings WHERE created >= ? AND status != 'cancelled' AND sandbox = 0", (since,))
    return sum(to_czk(r["total"], r["currency"]) for r in rows)


def limit_problem(rt: Any, total: float, currency: str) -> str:
    c = cfg(rt)
    czk = to_czk(total, currency)
    if c.max_per_booking and czk > c.max_per_booking:
        return f"rezervace za ~{czk:,.0f} Kč je nad tvým limitem {c.max_per_booking:,.0f} Kč (Cesty → Údaje a limity)".replace(",", " ")
    if c.monthly_budget and spent_this_month(rt) + czk > c.monthly_budget:
        return (f"tenhle měsíc by cesty stály přes rozpočet {c.monthly_budget:,.0f} Kč (už ~{spent_this_month(rt):,.0f} Kč)"
                .replace(",", " "))
    return ""


def guest(rt: Any) -> tuple[dict, str]:
    """The holder's details from Cesty → Údaje a limity (they stay on this PC); ('', why) when something is missing."""
    c = cfg(rt)
    g = {"first": c.first_name.strip(), "last": c.last_name.strip(), "email": c.email.strip(), "phone": c.phone.strip(),
         "born_on": c.born_on.strip(), "title": c.title, "gender": c.gender}
    missing = [k for k, n in (("first", "jméno"), ("last", "příjmení"), ("email", "e-mail"), ("phone", "telefon")) if not g[k]]
    return g, ("chybí " + ", ".join(n for k, n in (("first", "jméno"), ("last", "příjmení"), ("email", "e-mail"), ("phone", "telefon"))
                                   if k in missing) + " (Cesty → Údaje a limity)") if missing else ""


def price_changed(before: float, cur_before: str, after: float, cur_after: str) -> bool:
    if (cur_before or "").upper() != (cur_after or "").upper():
        return True
    return before <= 0 or abs(after - before) / before > PRICE_TOLERANCE


async def recheck(rt: Any, off: dict, transport: Any = None) -> dict:
    if off["kind"] == "flight":
        return await flight_recheck(rt, off, transport)
    if off["provider"] == "liteapi":
        return await lite_recheck(rt, off, transport)
    return await duffel_stay_recheck(rt, off, transport)


async def book(rt: Any, off: dict, transport: Any = None, business: bool = False) -> dict:
    """Confirmed by you (twice) already: limits, the price once more, then the booking itself."""
    g, why = guest(rt)
    if why:
        raise BookingError(why)
    from .money import ensure_rates

    await ensure_rates(rt)                                   # the limits in CZK with today's ČNB rate
    why = limit_problem(rt, off["total"], off["currency"])
    if why:
        raise BookingError(why)
    pre = await recheck(rt, off, transport)
    if pre.get("changed") or price_changed(off["total"], off["currency"], pre["total"], pre["currency"]):
        old = f"{off['total']:,.2f} {off['currency']}".replace(",", " ")
        off.update(total=pre["total"], currency=pre["currency"])            # the new price is what you confirm next time
        raise BookingError(f"cena nebo podmínky se mezitím změnily (z {old} na {pre['total']:,.2f} {pre['currency']}) – "
                           "nic jsem nezaplatil; když chceš, potvrď znovu".replace(",", " "))
    if off["kind"] == "flight":
        res = await flight_book(rt, off, pre, g, transport)
    elif off["provider"] == "liteapi":
        res = await lite_book(rt, off, pre, g, transport)
    else:
        res = await duffel_stay_book(rt, off, pre, g, transport)
    legs = off.get("legs") or []
    start = (legs[0]["dep"] if legs else off.get("checkin")) or ""
    end = (legs[-1]["arr"] if legs else off.get("checkout")) or ""
    _db(rt).exec("INSERT INTO bookings (provider, ref, kind, name, city, start, end, total, currency, refundable, free_cancel_until, "
                 "pay_at_property, status, sandbox, data, created, business) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (off["provider"], res["ref"], off["kind"], off.get("name", ""), off.get("city", ""), start, end, res["total"],
                  res["currency"], int(bool(off.get("refundable"))), off.get("free_cancel_until", ""),
                  int(bool(off.get("pay_at_property"))), "confirmed", int(bool(res["sandbox"])),
                  json.dumps({"offer": {k: v for k, v in off.items() if k != "found"}, "confirmation": res["confirmation"]},
                             ensure_ascii=False)[:20000], time.time(), int(bool(business))))
    row = _db(rt).one("SELECT * FROM bookings WHERE ref=? ORDER BY id DESC", (res["ref"],))
    return {**res, "id": row["id"] if row else None}


def _when(s: str) -> str:
    from .travelsearch import fmt_when

    return fmt_when(str(s or "")[:16]) if s else ""


def precheck(rt: Any, args: dict) -> str:
    """travel_book before anything is asked: '' = fine; else why it cannot go on (nothing is paid either way)."""
    off = offer(rt, args.get("option"))
    if not off:
        return "Tahle nabídka už neplatí (nabídky vydrží 30 minut) – řekni, ať hledám znovu. NEPROVEDENO."
    try:
        expected = float(args.get("expected_total") or 0)
    except (TypeError, ValueError):
        expected = 0.0
    if price_changed(off["total"], off["currency"], expected, str(args.get("currency") or "")):
        return (f"Částka nesouhlasí: nabídka {off['n']} stojí {off['total']:,.2f} {off['currency']}".replace(",", " ")
                + " – řekni uživateli správnou cenu. NEPROVEDENO.")
    return ""


def confirm_text(rt: Any, name: str, args: dict) -> str:
    """What the confirmation says – the phone shows only this: the real offer from JARVIS' own search (never the
    AI's words) with the exact amount and the terms."""
    if name == "travel_book":
        off = offer(rt, args.get("option"))
        if not off:
            return ""
        money = f"{off['total']:,.2f} {off['currency']}".replace(",", " ")
        if off["kind"] == "flight":
            legs = off.get("legs") or []
            what = f"let {off.get('name', '')} " + ", ".join(f"{lg['from']}→{lg['to']} {_when(lg['dep'])}" for lg in legs)
        else:
            what = f"{off.get('name', '')}, {off.get('city', '')} {_when(off.get('checkin', ''))}–{_when(off.get('checkout', ''))}"
        terms = ("zrušení zdarma" + (f" do {_when(off['free_cancel_until'])}" if off.get("free_cancel_until") else "")) \
            if off.get("refundable") else "NEVRATNÉ"
        pay = "platí se na hotelu" if off.get("pay_at_property") else "zaplatí se hned"
        test = " – ZKUŠEBNÍ, nic se nezaplatí" if off["provider"] == "liteapi" and sandbox() else ""
        return f"Zaplatit {money}: {what.strip()} ({terms}, {pay}){test}"
    if name == "booking_cancel":
        b = find_booking(rt, args.get("booking_ref"))
        if not b:
            return ""
        free = b.get("free_cancel_until") or ""
        terms = f"zdarma do {_when(free)}" if b["refundable"] and free else "může být poplatek" if b["refundable"] else "nevratná"
        return f"Zrušit rezervaci: {b['name']} {_when(b['start'])} ({b['total']:,.2f} {b['currency']}, {terms})".replace(",", " ")
    return ""


def bookings(rt: Any, include_past: bool = False) -> list[dict]:
    rows = _db(rt).all("SELECT * FROM bookings ORDER BY start")
    today = time.strftime("%Y-%m-%d")
    out = []
    for r in rows:
        d = dict(r)
        if not include_past and (d["end"] or "")[:10] < today:
            continue
        d.pop("data", None)
        out.append(d)
    return out


def find_booking(rt: Any, key: Any) -> dict | None:
    k = str(key or "").strip()
    rows = [dict(r) for r in _db(rt).all("SELECT * FROM bookings WHERE status='confirmed' ORDER BY start")]
    if k.isdigit():
        hit = next((r for r in rows if str(r["id"]) == k), None)
        if hit:
            return hit
    k = k.lower()
    return next((r for r in rows if k and (k in (r["name"] or "").lower() or k in (r["city"] or "").lower() or k == r["ref"].lower())), None)


async def cancel(rt: Any, b: dict, cancellation_id: str = "", transport: Any = None) -> dict:
    if b["kind"] == "flight":
        if not cancellation_id:
            raise BookingError("u letenky nejdřív zjisti podmínky zrušení (booking_cancel_check)")
        res = await flight_cancel_confirm(rt, cancellation_id, transport)
    elif b["provider"] == "liteapi":
        res = await lite_cancel(rt, b["ref"], transport)
    else:
        res = await duffel_stay_cancel(rt, b["ref"], transport)
    if "cancel" in res.get("status", "").lower():
        _db(rt).exec("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
    return res


# ------------------------------------------------------------------------------------------ 3.19 a test booking (návrh 9)
DRILL_GUEST = {"first": "Jarvis", "last": "Test", "email": "test@example.com", "phone": "+420000000000", "born_on": "1990-01-01",
               "title": "mr", "gender": "m"}


async def drill(rt: Any, transport: Any = None) -> list[dict]:
    """Zkušební rezervace: with a TEST key only – search → price check → booking → cancellation, each step timed; nothing
    is stored among your bookings and nothing is paid. A live key is refused (never a real booking from a button)."""
    import datetime as dt

    out: list[dict] = []

    async def step(name: str, coro: Any) -> Any:
        t0 = time.monotonic()
        try:
            res = await coro
            out.append({"step": name, "ok": True, "ms": int((time.monotonic() - t0) * 1000), "detail": ""})
            return res
        except Exception as e:  # noqa: BLE001
            out.append({"step": name, "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": str(e)[:200]})
            return None
    day = dt.date.today() + dt.timedelta(days=30)
    g = DRILL_GUEST
    lk, dk = lite_key(), duffel_key()
    if lk and not lk.startswith("sand_"):
        out.append({"step": "LiteAPI", "ok": None, "ms": 0, "detail": "ostrý klíč – zkušební rezervaci dělám jen se zkušebním (sand_…)"})
    elif lk:
        c = {"city": "Prague", "country": "CZ", "checkin": day.isoformat(), "checkout": (day + dt.timedelta(days=1)).isoformat(),
             "adults": 1, "rooms": 1, "currency": "EUR", "nationality": "CZ"}
        found = await step("Hotely: hledání (LiteAPI)", lite_search(rt, c, transport))
        if found:
            off = min(found, key=lambda o: o["total"])
            pre = await step(f"Hotely: kontrola ceny ({off['total']:g} {off['currency']})", lite_recheck(rt, off, transport))
            if pre:
                res = await step("Hotely: rezervace (zkušební)", lite_book(rt, off, pre, g, transport))
                if res:
                    await step("Hotely: zrušení", lite_cancel(rt, res["ref"], transport))
        elif found == []:
            out[-1].update(ok=False, detail="nic nenalezeno")
    if dk and not dk.startswith("duffel_test"):
        out.append({"step": "Duffel", "ok": None, "ms": 0, "detail": "ostrý token – zkušební rezervaci dělám jen s duffel_test_…"})
    elif dk:
        found = await step("Lety: hledání (Duffel)", flight_search(rt, {"origin": "PRG", "destination": "LHR", "date": day.isoformat(),
                                                                        "adults": 1}, transport))
        if found:
            off = found[0]
            pre = await step(f"Lety: kontrola ceny ({off['total']:g} {off['currency']})", flight_recheck(rt, off, transport))
            if pre:
                res = await step("Lety: objednávka (zkušební)", flight_book(rt, off, pre, g, transport))
                if res:
                    q = await step("Lety: podmínky zrušení", flight_cancel_quote(rt, res["ref"], transport))
                    if q and q.get("id"):
                        await step("Lety: zrušení", flight_cancel_confirm(rt, q["id"], transport))
    if not lk and not dk:
        out.append({"step": "Klíč", "ok": None, "ms": 0, "detail": "vlož zkušební klíč LiteAPI (sand_…) nebo Duffel (duffel_test_…) v Propojení"})
    return out


async def selfcheck(rt: Any) -> list[dict]:
    """Kontrola funkcí: can JARVIS search and book (test keys say so; nothing is booked)."""
    from .integrationcheck import _r

    out = []
    if lite_key():
        try:
            await _lite("GET", LITE_API + "/data/hotels", params={"cityName": "Praha", "countryCode": "CZ", "limit": 1})
            out.append(_r("liteapi", "Hotely (LiteAPI)", True, "Klíč platí" + (" – zkušební režim, nic se nezaplatí." if sandbox() else ".")))
        except Exception as e:  # noqa: BLE001
            out.append(_r("liteapi", "Hotely (LiteAPI)", False, str(e)[:200], "Propojení → LiteAPI"))
    if duffel_key():
        try:
            await _duffel("GET", "/air/airlines", params={"limit": 1})
            out.append(_r("duffel", "Lety a hotely (Duffel)", True, "Token platí."))
        except Exception as e:  # noqa: BLE001
            out.append(_r("duffel", "Lety a hotely (Duffel)", False, str(e)[:200], "Propojení → Duffel"))
    if not out:
        out.append(_r("travel", "Rezervace cest", None, "Bez klíče rezervuji přes prohlížeč (zastavím se před platbou).",
                      "Propojení → LiteAPI (hotely) nebo Duffel (lety, hotely)."))
    g, why = guest(rt)
    if why:
        out.append(_r("traveller", "Údaje pro rezervace", None, why.capitalize() + "."))
    return out
