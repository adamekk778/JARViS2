"""3.20 Auto+ (nápady 401–420 ze stránky „Nápady pro JARVISe“) a výdaje na auto (217).

- stav auta s termíny STK, servisu a pojištění (401), ceny paliva (402 – hlášené ceny a Tankerkönig pro Německo)
- chybové kódy OBD-II česky (403), kniha jízd (404), nabíječky pro elektromobil z Open Charge Map (405)
- přezutí podle teplot (406), dopravní info ráno přes TomTom (407 – s klíčem), spotřeba a cena za km (408, 217)
- kde jsem zaparkoval a hlídání parkovného (409), Android Auto (410 – zprávy od 3.14, režim v autě 123)
- pojištění před výročím (411), servisní historie (412), dálniční známka (413), dělení nákladů spolujízdy (414)
- statistiky jízd a jemné rady (415), horko v autě se zvířetem nebo dítětem (416 – s čidlem v autě)
- inzerát na prodej s hrubým odhadem ceny (417), body řidiče (418), plán dlouhé cesty (419), dezén z fotky (420)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cx_fuel (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, liters REAL, total REAL, odo REAL, full INT);
CREATE TABLE IF NOT EXISTS cx_costs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, amount REAL, note TEXT);
CREATE TABLE IF NOT EXISTS cx_service (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, km REAL, what TEXT, cost REAL, file TEXT);
CREATE TABLE IF NOT EXISTS cx_trips (id INTEGER PRIMARY KEY AUTOINCREMENT, start REAL, end REAL, frm TEXT, dest TEXT, km REAL,
  odo_start REAL, odo_end REAL, purpose TEXT DEFAULT 'soukromá');
CREATE TABLE IF NOT EXISTS cx_park (ts REAL, lat REAL, lon REAL, until REAL, note TEXT);
CREATE TABLE IF NOT EXISTS cx_prices (station TEXT, fuel TEXT, price REAL, ts REAL, lat REAL, lon REAL, PRIMARY KEY (station, fuel));
"""


def db(rt: Any):
    if not getattr(rt, "_carx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._carx_ready = True
    return rt.db


def kc(v: float) -> str:
    return f"{v:,.0f} Kč".replace(",", " ")


# ------------------------------------------------------------------ (403) OBD-II
OBD = {
    "P0100": "chyba snímače hmotnosti nasávaného vzduchu (MAF)", "P0101": "snímač MAF měří mimo rozsah – často špinavý",
    "P0115": "chyba čidla teploty chladicí kapaliny", "P0128": "motor se pomalu zahřívá – termostat zůstává otevřený",
    "P0130": "lambda sonda (před katalyzátorem) – chyba obvodu", "P0133": "lambda sonda reaguje pomalu",
    "P0171": "směs je příliš chudá (řada 1) – nasávání falešného vzduchu, MAF, tlak paliva",
    "P0172": "směs je příliš bohatá (řada 1) – vstřikovače, MAF, lambda",
    "P0174": "směs je příliš chudá (řada 2)", "P0175": "směs je příliš bohatá (řada 2)",
    "P0200": "chyba obvodu vstřikovačů", "P0217": "motor se přehřívá – ihned zastav a nech vychladnout",
    "P0234": "přeplňování turba je příliš vysoké", "P0299": "turbo nedává dost tlaku – únik v sání, turbo, regulace",
    "P0300": "náhodné vynechávání zapalování ve více válcích – svíčky, cívky, palivo",
    "P0301": "vynechává válec 1", "P0302": "vynechává válec 2", "P0303": "vynechává válec 3", "P0304": "vynechává válec 4",
    "P0325": "chyba snímače klepání", "P0335": "chyba snímače polohy klikového hřídele – auto může zhasínat",
    "P0340": "chyba snímače vačkového hřídele", "P0380": "žhavicí svíčky (diesel) – obvod",
    "P0400": "recirkulace výfukových plynů (EGR) – průtok", "P0401": "EGR – nedostatečný průtok (zanesený ventil)",
    "P0420": "katalyzátor (řada 1) má nízkou účinnost", "P0430": "katalyzátor (řada 2) má nízkou účinnost",
    "P0440": "systém odvětrání nádrže (EVAP) – chyba", "P0442": "malá netěsnost v systému EVAP – často víčko nádrže",
    "P0455": "velká netěsnost v systému EVAP – zkontroluj víčko nádrže", "P0500": "chyba snímače rychlosti vozidla",
    "P0505": "regulace volnoběhu – kolísavé otáčky", "P0562": "nízké napětí palubní sítě – baterie nebo alternátor",
    "P0563": "vysoké napětí palubní sítě – regulátor alternátoru", "P0600": "chyba komunikace řídicí jednotky",
    "P0700": "převodovka hlásí chybu – přečti kód z jednotky převodovky", "P0715": "snímač otáček vstupního hřídele převodovky",
    "P0741": "spojka měniče momentu převodovky nepracuje správně", "P2002": "filtr pevných částic (DPF) má nízkou účinnost",
    "P2463": "DPF je přeplněný sazemi – delší jízda po dálnici nebo servisní regenerace", "P242F": "DPF zanesený popelem",
    "P0087": "nízký tlak paliva v rampě", "P0088": "vysoký tlak paliva v rampě", "P0011": "časování vačkového hřídele (sání) mimo",
    "P0016": "nesoulad klikového a vačkového hřídele – rozvody, řetěz", "P0606": "závada procesoru řídicí jednotky",
    "U0100": "ztráta komunikace s řídicí jednotkou motoru", "U0121": "ztráta komunikace s ABS",
    "C0035": "snímač otáček levého předního kola (ABS)", "C0040": "snímač otáček pravého předního kola (ABS)",
    "B0001": "airbag řidiče – obvod (do servisu, airbag nemusí fungovat)",
}
SYSTEMS = {"P": "motor a převodovka", "C": "podvozek (ABS, řízení)", "B": "karoserie (airbagy, klimatizace, zámky)", "U": "komunikace jednotek"}
SUB = {"1": "palivo a vzduch", "2": "palivo a vstřikování", "3": "zapalování a vynechávání", "4": "emise", "5": "rychlost a volnoběh",
       "6": "řídicí jednotka", "7": "převodovka", "8": "převodovka", "0": "palivo, vzduch a emise"}


def obd_explain(code: str) -> dict:
    c = re.sub(r"\s", "", code or "").upper()
    if not re.fullmatch(r"[PCBU][0-3][0-9A-F]{3}", c):
        raise ValueError("Kód OBD vypadá třeba jako P0420 (písmeno a 4 znaky).")
    generic = c[1] in "02"
    text = OBD.get(c, "")
    serious = c in ("P0217", "P0016", "P0335", "B0001", "P0087") or c.startswith("P030")
    out = {"code": c, "system": SYSTEMS[c[0]], "generic": generic, "text": text,
           "area": SUB.get(c[2], "") if c[0] == "P" else "", "serious": serious}
    out["summary"] = (f"{c}: {text}." if text else f"{c}: {'obecný' if generic else 'výrobcem definovaný'} kód – {out['system']}"
                      + (f", oblast {out['area']}" if out["area"] else "") + ".") + (" Jeď opatrně rovnou do servisu." if serious else "")
    return out


# ------------------------------------------------------------------ (408, 217) spotřeba a náklady
def fuel_add(rt: Any, liters: float, total: float, odo: float, full: bool = True, ts: float | None = None) -> None:
    db(rt).exec("INSERT INTO cx_fuel (ts, liters, total, odo, full) VALUES (?,?,?,?,?)", (ts or time.time(), float(liters), float(total),
                                                                                         float(odo), int(full)))


def cost_add(rt: Any, kind: str, amount: float, note: str = "", ts: float | None = None) -> None:
    db(rt).exec("INSERT INTO cx_costs (ts, kind, amount, note) VALUES (?,?,?,?)", (ts or time.time(), kind[:30], float(amount), note[:120]))


def consumption(rt: Any) -> dict:
    """Full-to-full: litres since the previous full tank / km driven since then."""
    rows = [dict(r) for r in db(rt).all("SELECT * FROM cx_fuel ORDER BY odo")]
    fulls = [i for i, r in enumerate(rows) if r["full"]]
    per100 = []
    for a, b in zip(fulls, fulls[1:]):
        km = rows[b]["odo"] - rows[a]["odo"]
        liters = sum(r["liters"] for r in rows[a + 1:b + 1])
        if km > 20:
            per100.append(liters / km * 100)
    km_total = rows[-1]["odo"] - rows[0]["odo"] if len(rows) > 1 else 0
    fuel_cost = sum(r["total"] for r in rows[1:]) if len(rows) > 1 else 0
    other = sum(float(r["amount"]) for r in db(rt).all("SELECT amount FROM cx_costs"))
    return {"l_per_100": round(per100[-1], 1) if per100 else None, "avg_l_per_100": round(sum(per100) / len(per100), 1) if per100 else None,
            "km": round(km_total), "fuel_cost": round(fuel_cost), "other_cost": round(other),
            "per_km": round((fuel_cost + other) / km_total, 2) if km_total > 50 else None,
            "fuel_per_km": round(fuel_cost / km_total, 2) if km_total > 50 else None}


# ------------------------------------------------------------------ (412) servis, (401) stav, (411, 413)
def service_add(rt: Any, day: str, km: float, what: str, cost: float = 0, file: str = "") -> None:
    dt.date.fromisoformat(day)
    db(rt).exec("INSERT INTO cx_service (day, km, what, cost, file) VALUES (?,?,?,?,?)", (day, float(km), what[:200], float(cost), file))
    if cost:
        cost_add(rt, "servis", cost, what, dt.datetime.fromisoformat(day).timestamp())


def next_service(rt: Any, odo: float | None, today: dt.date, every_km: int = 15000, every_months: int = 12) -> str:
    last = db(rt).one("SELECT * FROM cx_service ORDER BY day DESC LIMIT 1")
    if not last:
        return ""
    due_day = dt.date.fromisoformat(last["day"]) + dt.timedelta(days=int(every_months * 30.4))
    due_km = float(last["km"]) + every_km
    parts = []
    left_days = (due_day - today).days
    if left_days <= 30:
        parts.append(f"servis podle času {'už měl být' if left_days < 0 else f'za {left_days} dní'}")
    if odo is not None and due_km - odo <= 1000:
        parts.append(f"servis podle km {'už měl být' if odo >= due_km else f'za {int(due_km - odo)} km'}")
    return ", ".join(parts)


async def status_line(rt: Any, today: dt.date | None = None) -> str:
    """(401) the car in one sentence: Home Assistant's state + the deadlines (STK, insurance, vignette) + the service."""
    from . import car, proactx

    today = today or dt.date.today()
    text, data = "", dict[str, Any]()
    try:
        text, data = await car.status(rt)
    except Exception:  # noqa: BLE001 – no car in Home Assistant: the deadlines alone
        text = "Auto:"
    carish = re.compile(r"stk|pojist|znamk|dalnic|servis|pneu|emis", re.I)
    due = [d for d in proactx.deadlines(rt) if carish.search(d["title"] + " " + d.get("kind", ""))][:4]
    extra = [f"{d['title']} {dt.date.fromisoformat(d['day']):%d. %m. %Y}" for d in due]
    srv = next_service(rt, data.get("odometer"), today)
    if srv:
        extra.append(srv)
    return text + (" Termíny: " + "; ".join(extra) + "." if extra else "")


INSURANCE_CHECK = ("Před výročím povinného ručení: porovnej nabídky (srovnávače pojištění), měj po ruce bonus (roky bez nehody), "
                   "VIN a technický průkaz; výpověď stačí podat 6 týdnů před výročím.")


def insurance_due(rt: Any, today: dt.date) -> list[str]:
    from . import proactx

    out = []
    for d in proactx.deadlines(rt):
        if re.search(r"pojist|ručen|ruceni", d["title"] + " " + d.get("kind", ""), re.I):
            left = (dt.date.fromisoformat(d["day"]) - today).days
            if left in (49, 45):
                out.append(f"{d['title']}: výročí za {left} dní. {INSURANCE_CHECK}")
    return out


def vignette(rt: Any, start: dt.date, country: str = "CZ", days: int = 365) -> dt.date:
    """(413) the vignette's validity as a deadline (the reminder comes a week and a day before)."""
    from . import proactx

    until = start + dt.timedelta(days=days - 1)
    proactx.add_deadline(rt, f"Dálniční známka {country.upper()}", until, "dálniční známka")
    return until


# ------------------------------------------------------------------ (404) kniha jízd, (415) styl jízdy
def trip_start(rt: Any, place: str = "", odo: float | None = None, ts: float | None = None) -> int:
    cur = db(rt).exec("INSERT INTO cx_trips (start, frm, odo_start) VALUES (?,?,?)", (ts or time.time(), place[:80], odo))
    return int(getattr(cur, "lastrowid", 0) or 0)


def trip_end(rt: Any, place: str = "", odo: float | None = None, km: float | None = None, ts: float | None = None) -> dict | None:
    row = db(rt).one("SELECT * FROM cx_trips WHERE end IS NULL ORDER BY start DESC LIMIT 1")
    if not row:
        return None
    dist = km if km is not None else (odo - row["odo_start"] if odo is not None and row["odo_start"] is not None else None)
    db(rt).exec("UPDATE cx_trips SET end=?, dest=?, odo_end=?, km=? WHERE id=?", (ts or time.time(), place[:80], odo, dist, row["id"]))
    return dict(db(rt).one("SELECT * FROM cx_trips WHERE id=?", (row["id"],)))


def trip_purpose(rt: Any, tid: int, purpose: str) -> bool:
    had = db(rt).one("SELECT id FROM cx_trips WHERE id=?", (int(tid),))
    db(rt).exec("UPDATE cx_trips SET purpose=? WHERE id=?", (purpose[:80], int(tid)))
    return bool(had)


def logbook_csv(rt: Any, month: str) -> str:
    """The month's trips for the accountant: date, from, to, purpose, km, odometer at start / end."""
    y, m = (int(x) for x in month.split("-"))
    a = dt.datetime(y, m, 1).timestamp()
    b = dt.datetime(y + (m == 12), m % 12 + 1, 1).timestamp()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Datum", "Odjezd", "Příjezd", "Odkud", "Kam", "Účel", "Km", "Stav tachometru – začátek", "Stav tachometru – konec"])
    for r in db(rt).all("SELECT * FROM cx_trips WHERE start >= ? AND start < ? AND end IS NOT NULL ORDER BY start", (a, b)):
        s, e = dt.datetime.fromtimestamp(r["start"]), dt.datetime.fromtimestamp(r["end"])
        w.writerow([f"{s:%d.%m.%Y}", f"{s:%H:%M}", f"{e:%H:%M}", r["frm"] or "", r["dest"] or "", r["purpose"],
                    "" if r["km"] is None else f"{r['km']:.0f}", "" if r["odo_start"] is None else f"{r['odo_start']:.0f}",
                    "" if r["odo_end"] is None else f"{r['odo_end']:.0f}"])
    return buf.getvalue()


def driving_stats(rt: Any, days: int = 30, now: float | None = None) -> dict:
    now = now or time.time()
    rows = [dict(r) for r in db(rt).all("SELECT * FROM cx_trips WHERE start >= ? AND end IS NOT NULL", (now - days * 86400,))]
    if not rows:
        return {"trips": 0, "tips": []}
    mins = [(r["end"] - r["start"]) / 60 for r in rows]
    night = sum(1 for r in rows if dt.datetime.fromtimestamp(r["start"]).hour >= 22 or dt.datetime.fromtimestamp(r["start"]).hour < 5)
    long_ = sum(1 for m in mins if m > 120)
    short = sum(1 for r in rows if (r["km"] or 99) < 3)
    tips = []
    if long_:
        tips.append(f"{long_}× jsi jel přes 2 hodiny v kuse – každé 2 h aspoň 15 min pauza, únava zpomaluje reakce jako alkohol.")
    if night >= max(2, len(rows) // 4):
        tips.append("Hodně jízd v noci – víc odpočinku před nimi, noční řízení je nejrizikovější.")
    if short >= max(3, len(rows) // 3):
        tips.append(f"{short} jízd kratších než 3 km – motor se nezahřeje a víc se opotřebí; zvaž kolo nebo pěšky.")
    return {"trips": len(rows), "km": round(sum(r["km"] or 0 for r in rows)), "hours": round(sum(mins) / 60, 1), "night": night,
            "long": long_, "short": short, "tips": tips}


# ------------------------------------------------------------------ (409) parkování
def park(rt: Any, lat: float, lon: float, minutes: int = 0, note: str = "", now: float | None = None) -> dict:
    now = now or time.time()
    until = now + minutes * 60 if minutes else None
    db(rt).exec("INSERT INTO cx_park VALUES (?,?,?,?,?)", (now, float(lat), float(lon), until, note[:80]))
    return {"lat": lat, "lon": lon, "until": until, "map": f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=18/{lat:.5f}/{lon:.5f}"}


def where_parked(rt: Any) -> dict | None:
    row = db(rt).one("SELECT * FROM cx_park ORDER BY ts DESC LIMIT 1")
    if not row:
        return None
    lat, lon = float(row["lat"]), float(row["lon"])
    return {"lat": lat, "lon": lon, "ts": row["ts"], "until": row["until"], "note": row["note"],
            "map": f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=18/{lat:.5f}/{lon:.5f}"}


def parking_due(rt: Any, now: float | None = None) -> str:
    now = now or time.time()
    p = where_parked(rt)
    if not p or not p["until"]:
        return ""
    left = (float(p["until"]) - now) / 60
    key = f"cx_park:{int(p['ts'])}"
    if 0 < left <= 10 and not rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
        return f"Parkovné končí za {int(left)} min."
    return ""


# ------------------------------------------------------------------ (402) ceny paliva, (405) nabíječky
def price_report(rt: Any, station: str, fuel: str, price: float, lat: float | None = None, lon: float | None = None) -> None:
    db(rt).exec("INSERT OR REPLACE INTO cx_prices VALUES (?,?,?,?,?,?)", (station[:60], fuel[:20], float(price), time.time(), lat, lon))


def cheapest(rt: Any, fuel: str = "natural", max_age_days: int = 14) -> list[dict]:
    rows = db(rt).all("SELECT * FROM cx_prices WHERE fuel=? AND ts >= ? ORDER BY price", (fuel, time.time() - max_age_days * 86400))
    return [dict(r) for r in rows]


def parse_tankerkoenig(data: dict) -> list[dict]:
    out = []
    for s in data.get("stations") or []:
        price = s.get("price") or s.get("e5") or s.get("diesel")
        if s.get("isOpen") and price:
            out.append({"name": f"{s.get('brand') or ''} {s.get('place') or ''}".strip(), "price_eur": float(price), "km": float(s.get("dist") or 0)})
    return sorted(out, key=lambda x: x["price_eur"])


def parse_ocm(data: list) -> list[dict]:
    out = []
    for p in data or []:
        a = p.get("AddressInfo") or {}
        conns = p.get("Connections") or []
        kw = max((float(c.get("PowerKW") or 0) for c in conns), default=0)
        out.append({"name": a.get("Title") or "Nabíječka", "km": round(float(a.get("Distance") or 0), 1), "kw": kw,
                    "lat": a.get("Latitude"), "lon": a.get("Longitude"), "operator": (p.get("OperatorInfo") or {}).get("Title") or "",
                    "fast": kw >= 50})
    return sorted(out, key=lambda x: (not x["fast"], x["km"]))


def charge_time(battery_kwh: float, from_pct: float, to_pct: float, kw: float) -> int:
    """Minutes at a charger (above 80 % it slows down – counted at half the power)."""
    if kw <= 0:
        return 0
    to80 = max(0.0, min(to_pct, 80) - from_pct) / 100 * battery_kwh
    above = max(0.0, to_pct - max(from_pct, 80)) / 100 * battery_kwh
    return round((to80 / (kw * 0.9) + above / (kw * 0.45)) * 60)


# ------------------------------------------------------------------ (406) přezutí, (416) horko v autě
def tyre_advice(daily_max: list[float], month: int, have: str = "") -> str:
    """The 7 °C rule: when the next days stay below 7 °C → winter tyres; above in spring → summer ones."""
    if len(daily_max) < 3:
        return ""
    avg = sum(daily_max[:5]) / min(5, len(daily_max))
    if month in (10, 11) and avg < 7 and have != "zimní":
        return f"Příští dny jen kolem {avg:.0f} °C – čas na zimní pneumatiky (od 1. 11. povinné při zimních podmínkách)."
    if month in (3, 4, 5) and avg > 10 and have != "letní":
        return f"Teploty kolem {avg:.0f} °C – zimní pneumatiky se teď rychle ojíždějí, můžeš přezout na letní."
    return ""


def car_heat(temp_c: float | None, driving: bool, occupied: bool) -> str:
    if temp_c is None or driving or not occupied:
        return ""
    if temp_c >= 30:
        return f"V autě je {temp_c:.0f} °C a podle nastavení v něm někdo zůstal – vyvětrej nebo pusť klimatizaci, hned!"
    return ""


# ------------------------------------------------------------------ (407) doprava, (419) dlouhá cesta, (414) spolujízda
def parse_tomtom(data: dict) -> dict:
    s = ((data.get("routes") or [{}])[0]).get("summary") or {}
    return {"minutes": round(float(s.get("travelTimeInSeconds") or 0) / 60), "delay_min": round(float(s.get("trafficDelayInSeconds") or 0) / 60),
            "km": round(float(s.get("lengthInMeters") or 0) / 1000, 1)}


async def traffic(rt: Any, a: tuple[float, float], b: tuple[float, float], client: Any = None) -> dict:
    from . import secrets

    key = secrets.get("tomtom")
    if not key:
        raise ValueError("Živou dopravu beru z TomTomu – klíč zdarma na developer.tomtom.com, ulož ho v Nastavení → Klíče.")
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json"
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get(url, params={"key": key, "traffic": "true"}, timeout=15)
    finally:
        if own:
            await c.aclose()
    r.raise_for_status()
    return parse_tomtom(r.json())


def long_trip_plan(km: float, minutes: int, ev_range_km: float | None = None) -> list[str]:
    out = [f"{round(km)} km, čistá jízda asi {minutes // 60} h {minutes % 60} min."]
    breaks = max(0, (minutes - 1) // 120)
    if breaks:
        out.append(f"{breaks}× přestávka 15–20 min (každé 2 h), celkem počítej s {round((minutes + breaks * 20) / 60, 1)} h.")
    if minutes > 9 * 60:
        out.append("Přes 9 hodin řízení – rozděl to na dva dny, přespi zhruba v polovině.")
    if ev_range_km:
        stops = max(0, int(km // (ev_range_km * 0.8)))
        if stops:
            out.append(f"Elektromobil: {stops}× nabíjení (počítám s 80 % dojezdu, nabíjej do 80 %).")
    return out


def rideshare(km: float, l_per_100: float, price_per_l: float, people: int, tolls: float = 0) -> dict:
    total = km * l_per_100 / 100 * price_per_l + tolls
    from .moneyx import split

    return {"total": round(total), "each": split(round(total), max(1, people))[0][1], "people": people}


# ------------------------------------------------------------------ (417) prodej, (418) body, (420) dezén
def price_estimate(bought_price: float, year: int, km: float, today: dt.date | None = None) -> dict:
    """A rough guide only: −20 % the first year, then −12 % a year, −2 % per 10 000 km above 15 000 km a year."""
    today = today or dt.date.today()
    age = max(0, today.year - year)
    v = bought_price * (0.8 if age >= 1 else 1.0) * (0.88 ** max(0, age - 1))
    over = max(0.0, km - 15000 * max(age, 1))
    v *= max(0.5, 1 - 0.02 * over / 10000)
    return {"estimate": round(v, -3), "low": round(v * 0.9, -3), "high": round(v * 1.1, -3),
            "note": "Hrubý odhad – skutečnou cenu ukáže srovnání stejných aut na inzertních serverech."}


def sale_ad(car: dict) -> str:
    keys = [("brand", ""), ("model", ""), ("year", "r. v. "), ("km", ""), ("fuel", ""), ("power", "")]
    head = " ".join(f"{p}{car[k]}" + (" km" if k == "km" else "") for k, p in keys if car.get(k))
    extras = ", ".join(car.get("equipment", []))
    return (f"{head}\n\nPrvní majitel: {'ano' if car.get('first_owner') else 'ne'}. Servisní knížka: {'ano' if car.get('service_book') else 'ne'}. "
            f"STK do {car.get('stk', '?')}.\nVýbava: {extras or '…'}.\nStav: {car.get('condition', 'udržovaný, bez nehody')}.\n"
            "Možnost prověření VIN a prohlídky v servisu. Cena dohodou při osobní prohlídce.")


def points_after(points: int, offence_free_months: int) -> int:
    """Driver's points: 4 points come off for every 12 months without an offence."""
    return max(0, points - 4 * (offence_free_months // 12))


TREAD_PROMPT = ("Na fotce je dezén pneumatiky. Odhadni hloubku dezénu v milimetrech (podle indikátorů opotřebení TWI, mince "
                "nebo měrky, pokud jsou vidět) a nerovnoměrné ojetí. Odpověz česky: odhad v mm, zda splňuje zákonné minimum "
                "(letní 1,6 mm, zimní pro zimní provoz 4 mm) a doporučení. Je to jen odhad z fotky – přesně to změří měrka.")


# ------------------------------------------------------------------ hooks and the minute look
def on_driving(rt: Any, on: bool, odo: float | None = None, place: str = "") -> None:
    """(404, 409) the phone joined / left the car's Bluetooth: a logbook trip starts / ends; at the end the phone sends
    where you parked (when it may use the location in the background)."""
    try:
        if on:
            trip_start(rt, place, odo)
        else:
            trip_end(rt, place, odo)
            rt.phone_push("where", why="parking")
    except Exception as e:  # noqa: BLE001
        log.debug("car trip: %s", e)


async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now()
    said = []
    t = parking_due(rt, now.timestamp())
    if t:
        said.append(t)
        rt.notify("Parkování", t, speak=False)
        rt.phone_push("notify", title="Parkování", body=t)
    from .proactiveplus import due_today

    if due_today(rt, "cx_daily", "08:45", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("cx_daily", now.date().isoformat()))
        try:
            from .proactx import weather

            d = (weather(rt) or {}).get("daily") or {}
            adv = tyre_advice([float(x) for x in d.get("temperature_2m_max") or []], now.month, str(getattr(rt.cfg.carx, "tyres", "") or ""))
            key = f"cx_tyres:{now.year}:{now.month}"
            if adv and not rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
                said.append(adv)
                rt.notify("Pneumatiky", adv, speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("tyres: %s", e)
        for t in insurance_due(rt, now.date()):
            said.append(t)
            rt.notify("Pojištění auta", t, speak=False)
    return said

