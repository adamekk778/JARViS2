"""3.18 Hledání cest podle popisu (návrhy 1–4, 7): "Řím, 3 noci od pátku, do 150 € za noc, pěšky do centra, snídaně,
parkování, hodnocení 8+, zrušení zdarma" → the criteria (the AI reads your words, JARVIS checks them and asks only
for what is missing) → 3–5 best offers, each with why, the total with fees, the cancellation terms and a map pin.

What you chose before counts ("jako minule"): breakfast, stars, the price per night, the extras in your words – kept
on this PC and used to order the next offers. Rates you can cancel for free and those paid at the hotel come first.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
from typing import Any
from urllib.parse import urlencode

PROMPT = (
    "Převeď požadavek na cestu do JSON. Dnes je {today} ({weekday}). Odpověz JEN JSON: "
    '{{"kind": "hotel|flight|trip", "city": "cílové město (hotel)", "country": "ISO-2 kód země nebo \\"\\"", '
    '"checkin": "YYYY-MM-DD", "checkout": "YYYY-MM-DD", "adults": 2, "children": [věky], "rooms": 1, '
    '"max_per_night": číslo nebo null, "currency": "EUR|CZK|…", "min_rating": 0-10 nebo null, "stars": 1-5 nebo null, '
    '"near": "kam blízko (centrum, pláž, …) nebo \\"\\"", "must": ["snídaně", "parkování", "zrušení zdarma", "wifi", '
    '"bazén", "tichý pokoj", …], "origin": "IATA odkud (lety)", "destination": "IATA kam (lety)", "date": "YYYY-MM-DD", '
    '"return_date": "YYYY-MM-DD nebo \\"\\"", "direct": false, "like_last_time": false, '
    '"with": ["křestní jména spolucestujících, jak je uživatel řekl"]}}. '
    'Neznámé nech prázdné ("" nebo null), nic nevymýšlej. „Od pátku na 3 noci“ = nejbližší pátek a +3 dny.')
WEEKDAYS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
MUST_WORDS = {"snídaně": ("snidan", "breakfast"), "parkování": ("parkov", "parking"), "zrušení zdarma": ("zruseni zdarma", "free cancel"),
              "wifi": ("wifi", "wi-fi"), "bazén": ("bazen", "pool"), "tichý pokoj": ("tich", "quiet"),
              "vysoké patro": ("vysok", "high floor"), "klimatizace": ("klima", "air con"), "zvíře": ("pes", "zvire", "pet")}
PREF_SQL = "CREATE TABLE IF NOT EXISTS travel_prefs (k TEXT PRIMARY KEY, v TEXT, n INTEGER, updated REAL)"


def _fold(s: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(ch))


def _date(s: Any) -> str:
    try:
        return dt.date.fromisoformat(str(s)[:10]).isoformat()
    except (TypeError, ValueError):
        return ""


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(v)))) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def clean(raw: dict, today: dt.date | None = None) -> tuple[dict, list[str]]:
    """The AI's criteria checked: dates real and in the future, numbers numbers; (criteria, what is missing)."""
    today = today or dt.date.today()
    c: dict[str, Any] = {"kind": raw.get("kind") if raw.get("kind") in ("hotel", "flight", "trip") else "hotel"}
    c["city"] = str(raw.get("city") or "").strip()[:60]
    c["country"] = str(raw.get("country") or "").strip().upper()[:2]
    c["checkin"], c["checkout"] = _date(raw.get("checkin")), _date(raw.get("checkout"))
    if c["checkin"] and c["checkin"] < today.isoformat():
        c["checkin"] = ""
    if c["checkin"] and (not c["checkout"] or c["checkout"] <= c["checkin"]):
        c["checkout"] = ""
    c["adults"] = _int(raw.get("adults"), 2, 1, 9)
    c["children"] = [int(a) for a in (raw.get("children") or []) if str(a).isdigit() and int(a) < 18][:4]
    c["rooms"] = _int(raw.get("rooms"), 1, 1, 5)
    for k in ("max_per_night", "min_rating", "stars"):
        try:
            c[k] = float(raw[k]) if raw.get(k) not in (None, "") else None
        except (TypeError, ValueError):
            c[k] = None
    c["currency"] = (str(raw.get("currency") or "") or "CZK").upper()[:3]
    c["near"] = str(raw.get("near") or "")[:60]
    c["must"] = [str(m)[:30] for m in (raw.get("must") or []) if str(m).strip()][:10]
    c["free_cancel_only"] = any("zrus" in _fold(m) or "cancel" in _fold(m) for m in c["must"])
    c["origin"] = str(raw.get("origin") or "").upper()[:3]
    c["destination"] = str(raw.get("destination") or "").upper()[:3]
    c["date"], c["return_date"] = _date(raw.get("date")), _date(raw.get("return_date"))
    c["direct"] = bool(raw.get("direct"))
    c["like_last_time"] = bool(raw.get("like_last_time"))
    c["with"] = [str(n).strip()[:30] for n in (raw.get("with") or []) if str(n).strip()][:8]
    missing: list[str] = []
    if c["kind"] in ("hotel", "trip"):
        missing += [n for k, n in (("city", "kam (město)"), ("checkin", "od kdy"), ("checkout", "do kdy")) if not c[k]]
    if c["kind"] in ("flight", "trip") and (c["origin"] or c["kind"] == "flight"):
        missing += [n for k, n in (("origin", "odkud letíš"), ("destination", "kam letíš"), ("date", "kdy letíš")) if not c[k]]
    return c, missing


async def understand(rt: Any, text: str, today: dt.date | None = None) -> tuple[dict, list[str]]:
    today = today or dt.date.today()
    msgs = [{"role": "system", "content": PROMPT.format(today=today.isoformat(), weekday=WEEKDAYS[today.weekday()])},
            {"role": "user", "content": text[:1500]}]
    out = str(await rt.router.complete(msgs) or "")
    m = re.search(r"\{.*\}", out, re.S)
    try:
        raw = json.loads(m.group(0)) if m else {}
    except ValueError:
        raw = {}
    c, missing = clean(raw if isinstance(raw, dict) else {}, today)
    f = _fold(text)                                     # the extras in your own words count even if the AI missed one
    for name, keys in MUST_WORDS.items():
        if any(k in f for k in keys) and name not in c["must"]:
            c["must"].append(name)
    if "jako minule" in f or "like last time" in f:
        c["like_last_time"] = True
    c["free_cancel_only"] = c["free_cancel_only"] or "zruseni zdarma" in f
    if not c.get("currency") or c["currency"] == "CZK":
        c["currency"] = (rt.cfg.booking.currency or "CZK").upper() if not re.search(r"€|eur", f) else "EUR"
    c["nationality"] = rt.cfg.booking.nationality or "CZ"
    return c, missing


# ------------------------------------------------------------------------------------------ what you liked before
def learn(rt: Any, off: dict, c: dict) -> None:
    """After a booking: what this choice says about you."""
    rt.db.exec(PREF_SQL)

    def bump(k: str, v: Any) -> None:
        row = rt.db.one("SELECT v, n FROM travel_prefs WHERE k=?", (k,))
        n = (row["n"] if row else 0) + 1
        rt.db.exec("INSERT OR REPLACE INTO travel_prefs (k, v, n, updated) VALUES (?,?,?,?)", (k, json.dumps(v), n, time.time()))
    if off.get("kind") != "hotel":
        return
    bump("breakfast", bool(off.get("breakfast")))
    if off.get("stars"):
        bump("stars", float(off["stars"]))
    bump("per_night_czk", round(_czk(off.get("per_night", 0), off.get("currency", "")), 0))
    bump("refundable", bool(off.get("refundable")))
    for m in c.get("must") or []:
        bump("must:" + m, True)


def prefs(rt: Any) -> dict:
    rt.db.exec(PREF_SQL)
    out: dict[str, Any] = {"must": []}
    for r in rt.db.all("SELECT * FROM travel_prefs"):
        v = json.loads(r["v"])
        if r["k"].startswith("must:"):
            if r["n"] >= 2:
                out["must"].append(r["k"][5:])
        else:
            out[r["k"]] = v
    return out


def _czk(amount: Any, cur: str) -> float:
    from .booking import to_czk

    try:
        return to_czk(float(amount or 0), cur)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------------------------------ the best few, with why
def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def rank(offers: list[dict], c: dict, p: dict | None = None, center: tuple[float, float] | None = None,
         prefer_free: bool = True, prefer_property: bool = True, limit: int = 5) -> list[dict]:
    p = p or {}
    out = []
    for o in offers:
        if c.get("max_per_night") and o.get("per_night") and _czk(o["per_night"], o["currency"]) > \
                _czk(c["max_per_night"], c.get("currency") or o["currency"]) * 1.02:
            continue
        if c.get("min_rating") and o.get("rating") and float(o["rating"]) < c["min_rating"]:
            continue
        if c.get("free_cancel_only") and o.get("kind") == "hotel" and o.get("refundable") is False and o.get("provider") == "liteapi":
            continue
        if center and o.get("lat") is not None and o.get("lon") is not None:
            o["km"] = round(_km(center, (float(o["lat"]), float(o["lon"]))), 1)
        out.append(o)
    if not out:
        return []
    prices = [_czk(o["total"], o["currency"]) for o in out]
    lo, hi = min(prices), max(prices) or 1
    want_breakfast = "snídaně" in (c.get("must") or []) or (c.get("like_last_time") and p.get("breakfast"))
    for o, pr in zip(out, prices):
        s = 1.0 - (pr - lo) / max(1.0, hi - lo)                          # cheaper is better
        s += (float(o.get("rating") or 0) / 10) * 1.2                   # well rated
        if prefer_free and o.get("refundable"):
            s += 0.6
        if prefer_property and o.get("pay_at_property"):
            s += 0.4
        if want_breakfast and o.get("breakfast"):
            s += 0.5
        if o.get("km") is not None and (c.get("near") or "centr" in _fold(c.get("near", ""))):
            s += max(0.0, 0.8 - o["km"] * 0.25)
        if c.get("like_last_time") and p.get("stars") and o.get("stars"):
            s -= abs(float(o["stars"]) - float(p["stars"])) * 0.2
        o["score"] = round(s, 3)
    out.sort(key=lambda o: -o["score"])
    best = out[:limit]
    cheapest = min(best, key=lambda o: _czk(o["total"], o["currency"]))
    top = max(best, key=lambda o: float(o.get("rating") or 0))
    near = min((o for o in best if o.get("km") is not None), key=lambda o: o["km"], default=None)
    for o in best:
        why = []
        if o is cheapest:
            why.append("nejlevnější")
        if o is top and o.get("rating"):
            why.append(f"nejlépe hodnocený ({_cz(o['rating'])}/10)")
        if near is o and o.get("km") is not None:
            why.append(f"nejblíž ({_cz(o['km'])} km)")
        if o.get("refundable"):
            why.append("zrušení zdarma" + (f" do {fmt_when(o['free_cancel_until'])}" if o.get("free_cancel_until") else ""))
        if o.get("pay_at_property"):
            why.append("platíš až na hotelu")
        if o.get("breakfast"):
            why.append("se snídaní")
        o["why"] = ", ".join(why) or "dobrý poměr ceny a hodnocení"
    return best


def _cz(v: Any) -> str:
    """8.7 → "8,7" (Czech decimals, also for reading aloud)."""
    return f"{float(v):g}".replace(".", ",")


def fmt_when(iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", ""))
        return f"{d.day}. {d.month}. {d:%H:%M}" if (d.hour or d.minute) else f"{d.day}. {d.month}."
    except ValueError:
        return iso


def line(o: dict) -> str:
    money = f"{o['total']:,.0f} {o['currency']}".replace(",", " ")
    if o["kind"] == "flight":
        legs = "; ".join(f"{lg['from']}→{lg['to']} {str(lg['dep'])[5:16].replace('T', ' ')}"
                         + (f" ({lg['stops']}× přestup)" if lg["stops"] else " (přímý)") for lg in o.get("legs") or [])
        return f"{o['n']}) {o['name']}: {legs} – {money}" + (" – lze vrátit" if o.get("refundable") else "")
    stars = f" {'★' * int(o['stars'])}" if o.get("stars") else ""
    rating = f", {_cz(o['rating'])}/10" if o.get("rating") else ""
    return (f"{o['n']}) {o['name']}{stars}{rating} – {money} celkem ({o['nights']} n.)"
            + (f", {_cz(o['km'])} km" if o.get("km") is not None else "") + f" – {o.get('why', '')}")


# ------------------------------------------------------------------------------------------ without a key: the site itself
def site_url(site: str, c: dict) -> str:
    adults, rooms = int(c.get("adults") or 2), int(c.get("rooms") or 1)
    if site == "airbnb":
        return f"https://www.airbnb.com/s/{c.get('city', '')}/homes?" + urlencode(
            {"checkin": c.get("checkin", ""), "checkout": c.get("checkout", ""), "adults": adults})
    if site == "getyourguide":
        return "https://www.getyourguide.com/s/?" + urlencode({"q": f"{c.get('city', '')} {c.get('what', '')}".strip()})
    if site == "google_flights":
        q = f"Flights from {c.get('origin', '')} to {c.get('destination', '')} on {c.get('date', '')}"
        return "https://www.google.com/travel/flights?" + urlencode({"q": q + (f" returning {c['return_date']}" if c.get("return_date") else "")})
    return "https://www.booking.com/searchresults.html?" + urlencode(
        {"ss": c.get("city", ""), "checkin": c.get("checkin", ""), "checkout": c.get("checkout", ""),
         "group_adults": adults, "no_rooms": rooms, "group_children": len(c.get("children") or [])})
