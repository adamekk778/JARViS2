"""3.18 Po rezervaci (návrhy 10–12, 15, 17, 19): a booked trip looks after itself.

- Right away: into Cesty (and the HUD map), the calendar, a notice to the phone; the confirmation into the trip's
  folder (Dokumenty JARVIS → Cesty), a business trip also into the costs table for the accountant.
- Reminders: free cancellation ends tomorrow / in 3 hours, online check-in 24 h before a flight, a passport that runs
  out within 6 months after the trip, the weather at the destination 2 days before, a packing list the day before.
- Price watch: a booked hotel you can cancel for free got ≥ 5 % cheaper for the same dates → you hear it (and decide;
  nothing is rebooked without you).
- Watches: "dej vědět, až bude Řím pod 4 000 Kč" – checked twice a day.
- Spend: what trips cost this month and this year (Cesty page, "kolik jsem letos utratil za cesty").
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import booking

log = logging.getLogger("jarvis.tripcare")

SQL = """CREATE TABLE IF NOT EXISTS trip_reminders (booking_id INTEGER, kind TEXT, PRIMARY KEY (booking_id, kind));
         CREATE TABLE IF NOT EXISTS travel_watches (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, criteria TEXT,
           max_price REAL, currency TEXT, last_price REAL, active INTEGER DEFAULT 1, created REAL, checked REAL, told REAL)"""
CHEAPER = 0.05


def _db(rt: Any) -> Any:
    for stmt in SQL.split(";"):
        if stmt.strip():
            rt.db.exec(stmt)
    return rt.db


def _ts(s: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "")[:19]).timestamp()
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(str(s)[:10]).timestamp()
        except (TypeError, ValueError):
            return None


# ------------------------------------------------------------------------------------------ right after the booking
def travel_dir() -> Path:
    """Dokumenty\\JARVIS\\Cesty (next to the reports and missions)."""
    from .pcreport import reports_dir

    d = reports_dir().parent / "Cesty"
    d.mkdir(parents=True, exist_ok=True)
    return d


def folder(b: dict) -> Path:
    from .cad import slug

    d = travel_dir() / f"{str(b.get('start', ''))[:10]}-{slug(b.get('city') or b.get('name') or 'cesta')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def after_booking(rt: Any, b: dict, res: dict, off: dict) -> list[str]:
    """What happens once a booking is confirmed; returns what was done (for the answer)."""
    done = []
    try:
        from . import travel

        for leg in off.get("legs") or [] if b["kind"] == "flight" else []:    # flights: delay, gate, when to leave
            dep, arr = _ts(leg.get("dep") or ""), _ts(leg.get("arr") or "")
            m = re.match(r"^([A-Z0-9]{2})\s?(\d{1,4})$", str(leg.get("flight") or ""))
            if dep and m:
                travel.add(rt, {"kind": "flight", "number": f"{m.group(1)} {int(m.group(2))}", "dep": dep, "arr": arr,
                                "origin": leg.get("from") or "", "dest": leg.get("to") or "",
                                "info": {"booking": res["ref"]}}, source="booking")
        done.append("Cesty")                       # hotels are listed from the bookings themselves
    except Exception as e:  # noqa: BLE001
        log.debug("trip: %s", e)
    try:
        from . import tools

        when = str(b["start"])[:16].replace(" ", "T")
        if len(when) == 10:
            when += "T15:00"                       # a hotel: check-in in the afternoon
        title = ("Let " if b["kind"] == "flight" else "Hotel ") + (b.get("name") or "")
        r = await tools.call("calendar_add", {"title": title[:80], "start": when, "minutes": 60, "location": b.get("city", "")}, rt)
        if r.ok:
            done.append("kalendář")
    except Exception as e:  # noqa: BLE001
        log.debug("calendar: %s", e)
    try:
        d = folder(b)
        (d / f"potvrzeni-{res['ref']}.json").write_text(json.dumps(res.get("raw") or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / f"potvrzeni-{res['ref']}.txt").write_text(summary_text(b, res), encoding="utf-8")
        done.append("složka cesty")
        if b.get("business"):
            costs(rt, b)
            done.append("náklady pro účetní")
    except OSError as e:
        log.debug("folder: %s", e)
    rt.phone_push("notify", title="Rezervováno", body=summary_text(b, res)[:380])
    done.append("telefon")
    p = passport_problem(rt, b)
    if p:
        rt.notify("Pas", p, speak=False)
    return done


def summary_text(b: dict, res: dict) -> str:
    money = f"{res['total']:,.2f} {res['currency']}".replace(",", " ")
    lines = [f"{'Let' if b['kind'] == 'flight' else 'Hotel'}: {b.get('name', '')}", f"Kdy: {b.get('start', '')} – {b.get('end', '')}",
             f"Cena: {money}", f"Číslo rezervace: {res.get('confirmation') or res['ref']}"]
    if b.get("free_cancel_until"):
        lines.append(f"Zrušení zdarma do: {b['free_cancel_until']}")
    if b.get("pay_at_property"):
        lines.append("Platí se na hotelu.")
    if res.get("sandbox"):
        lines.append("ZKUŠEBNÍ rezervace – nic se nezaplatilo.")
    return "\n".join(lines)


def costs(rt: Any, b: dict) -> Path:
    """A business trip → one row in Cesty/naklady.csv (Excel opens it; the accountant gets it as it is)."""
    p = travel_dir() / "naklady.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(["datum", "co", "kde", "od", "do", "castka", "mena", "cislo"])
        w.writerow([time.strftime("%Y-%m-%d"), b.get("name", ""), b.get("city", ""), b.get("start", ""), b.get("end", ""),
                    f"{b.get('total', 0):.2f}".replace(".", ","), b.get("currency", ""), b.get("ref", "")])
    return p


def passport_problem(rt: Any, b: dict) -> str:
    until = getattr(rt.cfg.booking, "passport_until", "") or ""
    end = _ts(b.get("end") or b.get("start") or "")
    exp = _ts(until)
    if not exp or not end:
        return ""
    if exp < end + 182 * 86400:
        return (f"Pas ti platí do {until} – některé země chtějí aspoň 6 měsíců po návratu. Zkontroluj podmínky cíle "
                f"({b.get('city') or b.get('name')}).")
    return ""


# ------------------------------------------------------------------------------------------ reminders
def _once(rt: Any, bid: int, kind: str) -> bool:
    db = _db(rt)
    if db.one("SELECT 1 FROM trip_reminders WHERE booking_id=? AND kind=?", (bid, kind)):
        return False
    db.exec("INSERT INTO trip_reminders (booking_id, kind) VALUES (?,?)", (bid, kind))
    return True


async def reminders(rt: Any, now: float | None = None) -> list[str]:
    now = now or time.time()
    said: list[str] = []
    for b in booking.bookings(rt):
        if b["status"] != "confirmed":
            continue
        start = _ts(b["start"])
        fc = _ts(b.get("free_cancel_until") or "")
        name = b.get("name") or "rezervace"
        if fc and 0 < fc - now <= 86400 and _once(rt, b["id"], "cancel_24h"):
            said.append(f"Zrušení zdarma u {name} končí zítra ({b['free_cancel_until'].replace('T', ' ')}).")
        if fc and 0 < fc - now <= 3 * 3600 and _once(rt, b["id"], "cancel_3h"):
            said.append(f"Poslední 3 hodiny, kdy jde {name} zrušit zdarma.")
        if b["kind"] == "flight" and start and 0 < start - now <= 24 * 3600 and _once(rt, b["id"], "checkin"):
            said.append(f"Online check-in na let {name} je otevřený (odlet {b['start'][:16].replace('T', ' ')}).")
        if start and 0 < start - now <= 2 * 86400 and b.get("city") and _once(rt, b["id"], "weather"):
            try:
                from . import tools

                r = await tools.call("weather", {"city": b["city"]}, rt)
                if r.ok:
                    said.append(f"Počasí v {b['city']} na cestu: {r.summary}")
            except Exception as e:  # noqa: BLE001
                log.debug("trip weather: %s", e)
        if start and 0 < start - now <= 86400 and _once(rt, b["id"], "packing"):
            said.append(await packing(rt, b))
    for s in said:
        rt.notify("Cesta", s, target="all", speak=False)
    return said


async def packing(rt: Any, b: dict) -> str:
    nights = max(1, int(((_ts(b["end"]) or 0) - (_ts(b["start"]) or 0)) / 86400) or 1)
    try:
        txt = await rt.router.complete([
            {"role": "system", "content": "Napiš krátký seznam věcí na cestu (česky, max 12 položek, jen čárkami oddělené)."},
            {"role": "user", "content": f"{'Let' if b['kind'] == 'flight' else 'Hotel'} {b.get('name', '')}, {b.get('city', '')}, "
                                        f"{nights} nocí, od {str(b['start'])[:10]}."}])
        return "Na zítřejší cestu nezapomeň: " + str(txt or "").strip()[:400]
    except Exception:  # noqa: BLE001
        return "Na zítřejší cestu nezapomeň: doklady, nabíječku, léky, platební kartu."


# ------------------------------------------------------------------------------------------ cheaper now? / watches
async def price_watch(rt: Any, transport: Any = None) -> list[str]:
    """A booked LiteAPI hotel you can still cancel for free: the same hotel and dates, cheaper now?"""
    said = []
    for b in booking.bookings(rt):
        if b["status"] != "confirmed" or b["provider"] != "liteapi" or not b["refundable"] or b["kind"] != "hotel":
            continue
        fc = _ts(b.get("free_cancel_until") or "")
        if fc and fc < time.time():
            continue
        row = rt.db.one("SELECT data FROM bookings WHERE id=?", (b["id"],))
        off = (json.loads(row["data"]) or {}).get("offer", {}) if row else {}
        if not off.get("hotel_id"):
            continue
        body = {"hotelIds": [off["hotel_id"]], "checkin": str(b["start"])[:10], "checkout": str(b["end"])[:10],
                "currency": b["currency"], "guestNationality": rt.cfg.booking.nationality or "CZ", "timeout": 10,
                "occupancies": [{"adults": 2, "children": []}], "refundableRatesOnly": True}
        try:
            data = (await booking._lite("POST", booking.LITE_API + "/hotels/rates", body=body, transport=transport)).get("data") or []
        except Exception as e:  # noqa: BLE001
            log.debug("price watch: %s", e)
            continue
        totals = [float(((r.get("retailRate") or {}).get("total") or [{}])[0].get("amount") or 0)
                  for h in data for t in h.get("roomTypes") or [] for r in t.get("rates") or []]
        totals = [t for t in totals if t > 0]
        if totals and min(totals) <= b["total"] * (1 - CHEAPER) and _once(rt, b["id"], f"cheaper:{int(min(totals))}"):
            save = b["total"] - min(totals)
            said.append(f"{b['name']} je teď o {save:,.0f} {b['currency']} levnější pro stejné termíny – tvoje rezervace jde "
                        f"zrušit zdarma. Chceš přerezervovat?".replace(",", " "))
    for s in said:
        rt.notify("Levnější hotel", s, target="all", speak=False)
    return said


def add_watch(rt: Any, kind: str, criteria: dict, max_price: float, currency: str) -> int:
    db = _db(rt)
    db.exec("INSERT INTO travel_watches (kind, criteria, max_price, currency, last_price, created, checked, told) "
            "VALUES (?,?,?,?,?,?,?,?)", (kind, json.dumps(criteria, ensure_ascii=False), max_price, currency.upper(), 0, time.time(), 0, 0))
    row = db.one("SELECT MAX(id) AS id FROM travel_watches")
    return int(row["id"])


def watches(rt: Any) -> list[dict]:
    out = []
    for r in _db(rt).all("SELECT * FROM travel_watches WHERE active=1 ORDER BY id"):
        d = dict(r)
        d["criteria"] = json.loads(d["criteria"])
        out.append(d)
    return out


def stop_watch(rt: Any, wid: int) -> bool:
    cur = _db(rt).exec("UPDATE travel_watches SET active=0 WHERE id=?", (wid,))
    return bool(getattr(cur, "rowcount", 0))


async def check_watches(rt: Any, search: Any = None) -> list[str]:
    """search(rt, kind, criteria) → the cheapest total found (or None)."""
    said = []
    for w in watches(rt):
        c = w["criteria"]
        if (c.get("checkin") or c.get("date") or "9999") < time.strftime("%Y-%m-%d"):
            stop_watch(rt, w["id"])
            continue
        try:
            best = await (search or _cheapest)(rt, w["kind"], c)
        except Exception as e:  # noqa: BLE001
            log.debug("watch: %s", e)
            continue
        _db(rt).exec("UPDATE travel_watches SET checked=?, last_price=? WHERE id=?",
                     (time.time(), float(best[0]) if best else 0, w["id"]))
        if best and booking.to_czk(best[0], best[1]) <= booking.to_czk(w["max_price"], w["currency"]):
            what = c.get("city") or f"{c.get('origin', '')}→{c.get('destination', '')}"
            said.append(f"{what} je teď za {best[0]:,.0f} {best[1]} – pod tvým limitem {w['max_price']:,.0f} {w['currency']}. "
                        "Řekni „ukaž nabídky“ a vyberu nejlepší.".replace(",", " "))
            stop_watch(rt, w["id"])
    for s in said:
        rt.notify("Cena klesla", s, target="all", speak=False)
    return said


async def _cheapest(rt: Any, kind: str, c: dict) -> tuple[float, str] | None:
    if kind == "flight":
        offers = await booking.flight_search(rt, c) if booking.duffel_key() else []
    elif booking.lite_key():
        offers = await booking.lite_search(rt, c)
    elif booking.duffel_key():
        offers = await booking.duffel_stays_search(rt, c)
    else:
        return None
    if not offers:
        return None
    o = min(offers, key=lambda x: x["total"])
    return o["total"], o["currency"]


# ------------------------------------------------------------------------------------------ what trips cost
def spend(rt: Any, year: int | None = None) -> dict:
    year = year or dt.date.today().year
    by_month: dict[str, float] = {}
    trips = []
    for r in booking._db(rt).all("SELECT * FROM bookings WHERE status!='cancelled' AND sandbox=0 ORDER BY created"):
        when = dt.date.fromtimestamp(r["created"])
        if when.year != year:
            continue
        czk = booking.to_czk(r["total"], r["currency"])
        by_month[f"{when.month:02d}"] = by_month.get(f"{when.month:02d}", 0) + czk
        trips.append({"name": r["name"], "city": r["city"], "start": r["start"], "total": r["total"], "currency": r["currency"],
                      "czk": czk, "kind": r["kind"], "business": bool(r["business"])})
    return {"year": year, "total_czk": round(sum(by_month.values())), "by_month": {k: round(v) for k, v in sorted(by_month.items())},
            "trips": trips, "business_czk": round(sum(t["czk"] for t in trips if t["business"]))}


async def loop(rt: Any) -> None:
    await asyncio.sleep(120)
    n = 0
    while True:
        try:
            if getattr(rt.cfg.booking, "reminders", True):
                await reminders(rt)
            if n % 12 == 0:                         # twice a day: prices
                if getattr(rt.cfg.booking, "price_watch", True):
                    await price_watch(rt)
                await check_watches(rt)
        except Exception as e:  # noqa: BLE001
            log.debug("tripcare: %s", e)
        n += 1
        await asyncio.sleep(3600)
