"""3.20 Cesty+ (nápady 221–240 ze stránky „Nápady pro JARVISe“).

- plán výletu na den (221), plán proti jet lagu (222), výluky na tvých trasách (223 – z tebou zadaných zdrojů)
- kavárny se zásuvkou a Wi-Fi (224), vyhlídky a příroda (225), jízdenka offline v telefonu (226)
- sdílená kola a koloběžky ze standardu GBFS (228), cestovní deník (229), tísňová čísla v zemi (230)
- překlad jídelního lístku s alergeny (231), dálniční známky a mýto (232), změna času (233)
- náhrada za zpoždění letu podle EU 261 (234), cesta s dětmi (235), věrnostní body (236 – v moneyx)
- cestovní pojištění (237), offline mapy (238), sdílený plán s přáteli (239), místní zvyklosti (240)
Místa a trasy z OpenStreetMap (Overpass, OSRM), počasí z Open-Meteo – bez klíčů.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import math
import re
import secrets as pysecrets
import time
import unicodedata
from typing import Any, Callable

log = logging.getLogger(__name__)

OVERPASS = "https://overpass-api.de/api/interpreter"
OSRM = "https://router.project-osrm.org/route/v1/driving"
SCHEMA = """
CREATE TABLE IF NOT EXISTS tx_plan (token TEXT PRIMARY KEY, title TEXT, items TEXT, ts REAL, until REAL);
CREATE TABLE IF NOT EXISTS tx_insured (trip TEXT PRIMARY KEY, ts REAL);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_tripx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._tripx_ready = True
    return rt.db


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


# ------------------------------------------------------------------ OpenStreetMap places (224, 225, 235, 221)
KINDS = {
    "cafe_work": ('node["amenity"="cafe"]["internet_access"~"wlan|yes"]', "kavárna s Wi-Fi"),
    "viewpoint": ('node["tourism"="viewpoint"]', "vyhlídka"),
    "nature": ('node["natural"~"peak|waterfall|cave_entrance|spring"]', "příroda"),
    "playground": ('node["leisure"="playground"]', "hřiště"),
    "food": ('node["amenity"~"restaurant|fast_food"]', "jídlo"),
    "fuel": ('node["amenity"="fuel"]', "pumpa"),
    "charger": ('node["amenity"="charging_station"]', "nabíječka"),
}


def overpass_query(kind: str, lat: float, lon: float, radius_m: int = 2000, limit: int = 30) -> str:
    sel, _ = KINDS[kind]
    return f"[out:json][timeout:20];({sel}(around:{int(radius_m)},{lat:.5f},{lon:.5f}););out body {int(limit)};"


def parse_places(data: dict, near: tuple[float, float], kind: str) -> list[dict]:
    out = []
    for e in data.get("elements") or []:
        if "lat" not in e:
            continue
        tags = e.get("tags") or {}
        p = (float(e["lat"]), float(e["lon"]))
        item = {"name": tags.get("name") or KINDS[kind][1], "lat": p[0], "lon": p[1], "km": round(km(near, p), 2), "kind": kind}
        if kind == "cafe_work":
            item["socket"] = "ano" if tags.get("socket") or tags.get("power_supply") in ("yes", "socket") else "?"
            item["hours"] = tags.get("opening_hours", "")
        if kind == "nature":
            item["what"] = {"peak": "vrchol", "waterfall": "vodopád", "cave_entrance": "jeskyně", "spring": "pramen"}.get(tags.get("natural", ""), "")
        out.append(item)
    return sorted(out, key=lambda x: x["km"])


async def places(rt: Any, kind: str, lat: float, lon: float, radius_m: int = 2000, fetch: Callable[..., Any] | None = None) -> list[dict]:
    q = overpass_query(kind, lat, lon, radius_m)
    if fetch is None:
        async with rt.http() as c:
            r = await c.post(OVERPASS, data={"data": q}, timeout=25)
        r.raise_for_status()
        data = r.json()
    else:
        data = await fetch(q)
    return parse_places(data, (lat, lon), kind)


def nature_walk(start: tuple[float, float], spots: list[dict], max_stops: int = 4) -> list[dict]:
    """(225) a loop through the nearest nice places (nearest-neighbour order), back to the start."""
    left = [s for s in spots if s["kind"] in ("viewpoint", "nature")][: max_stops * 3]
    order: list[dict] = []
    here = start
    while left and len(order) < max_stops:
        nxt = min(left, key=lambda s: km(here, (s["lat"], s["lon"])))
        order.append(nxt)
        left.remove(nxt)
        here = (nxt["lat"], nxt["lon"])
    return order


def walk_km(start: tuple[float, float], stops: list[dict]) -> float:
    pts = [start] + [(s["lat"], s["lon"]) for s in stops] + [start]
    return round(sum(km(a, b) for a, b in zip(pts, pts[1:])) * 1.3, 1)     # paths are not straight lines


async def day_trip(rt: Any, dest: str) -> dict:
    """(221) a day out: the drive, what to see, where to eat and the weather."""
    from .phonex import geocode

    to = await geocode(rt, dest)
    if not to:
        return {"ok": False, "message": f"Místo „{dest}“ jsem nenašel."}
    home = await _home(rt)
    drive = None
    if home:
        try:
            drive = await route_summary(rt, home, to)
        except Exception as e:  # noqa: BLE001
            log.info("day trip route: %s", e)
    see = (await places(rt, "viewpoint", *to, radius_m=6000))[:3] + (await places(rt, "nature", *to, radius_m=6000))[:2]
    eat = (await places(rt, "food", *to, radius_m=1500))[:3]
    weather = await _weather_day(rt, to)
    lines = [f"Výlet: {dest}"]
    if drive:
        lines.append(f"Cesta autem {drive['km']} km, asi {drive['minutes']} min – vyraz v 9:00, budeš tam {_add(9 * 60, drive['minutes'])}.")
    if weather:
        lines.append(weather)
    if see:
        lines.append("Co vidět: " + ", ".join(f"{s['name']} ({s['km']} km)" for s in see))
    if eat:
        lines.append("Jídlo: " + ", ".join(e["name"] for e in eat))
    return {"ok": True, "lines": lines, "see": see, "eat": eat, "drive": drive}


def _add(minutes_from_midnight: int, extra: int) -> str:
    t = minutes_from_midnight + extra
    return f"{t // 60 % 24}:{t % 60:02d}"


async def _home(rt: Any) -> tuple[float, float] | None:
    lat, lon = getattr(rt.cfg.general, "home_lat", None), getattr(rt.cfg.general, "home_lon", None)
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    try:
        from .proactx import weather

        w = weather(rt) or {}
        if w.get("lat") is not None:
            return float(w["lat"]), float(w["lon"])
    except Exception:  # noqa: BLE001
        pass
    return None


async def _weather_day(rt: Any, p: tuple[float, float]) -> str:
    try:
        async with rt.http() as c:
            r = await c.get("https://api.open-meteo.com/v1/forecast", params={"latitude": p[0], "longitude": p[1], "timezone": "auto",
                            "daily": "temperature_2m_max,precipitation_probability_max", "forecast_days": 1}, timeout=10)
        d = r.json().get("daily") or {}
        return f"Počasí: do {round(d['temperature_2m_max'][0])} °C, déšť {d['precipitation_probability_max'][0]} %."
    except Exception:  # noqa: BLE001
        return ""


async def route_summary(rt: Any, a: tuple[float, float], b: tuple[float, float], fetch: Callable[..., Any] | None = None) -> dict:
    url = f"{OSRM}/{a[1]},{a[0]};{b[1]},{b[0]}"
    if fetch is None:
        async with rt.http() as c:
            r = await c.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    else:
        data = await fetch(url)
    rt0 = (data.get("routes") or [{}])[0]
    coords = ((rt0.get("geometry") or {}).get("coordinates") or [])
    return {"km": round(float(rt0.get("distance") or 0) / 1000), "minutes": round(float(rt0.get("duration") or 0) / 60),
            "points": [(c[1], c[0]) for c in coords]}


def stops_along(points: list[tuple[float, float]], total_minutes: int, every_min: int) -> list[tuple[float, float]]:
    """(235, 419) where you will be every `every_min` minutes of driving (by the route's shape)."""
    if not points or total_minutes <= every_min:
        return []
    n = total_minutes // every_min
    return [points[min(len(points) - 1, round(len(points) * (k * every_min) / total_minutes))] for k in range(1, n + 1)]


# ------------------------------------------------------------------ (222) jet lag
def jetlag_plan(shift_h: float, depart: dt.date, days_before: int = 3) -> list[str]:
    """shift_h > 0 = flying east (the day starts earlier), < 0 = west. ~1 hour a day; light in the morning going east,
    in the evening going west."""
    if abs(shift_h) < 2:
        return ["Posun je malý – stačí po příletu dodržovat místní čas."]
    east = shift_h > 0
    steps = min(days_before, int(abs(shift_h)))
    out = []
    for k in range(steps, 0, -1):
        day = depart - dt.timedelta(days=k)
        h = steps - k + 1
        out.append(f"{day:%d. %m.}: spát o {h} h {'dřív' if east else 'později'}, " + ("ráno hned na světlo, večer tlumit." if east
                                                                                    else "večer co nejdéle světlo, ráno přítmí."))
    out.append(f"{depart:%d. %m.} v letadle: přepni hodinky na cílový čas, spi podle něj, pij vodu, ne alkohol.")
    out.append("Po příletu: jídlo a spánek podle místního času, " + ("dopoledne ven na světlo." if east else "odpoledne ven na světlo."))
    left = abs(shift_h) - steps
    if left > 0:
        out.append(f"Zbylé {left:g} h dožene tělo asi za {math.ceil(left)} dní na místě.")
    return out


# ------------------------------------------------------------------ (223) výluky
def closures_in(text: str, lines: list[str], places_: list[str] | None = None) -> list[str]:
    """Paragraphs of an operator's notice page that mention your lines (S7, R9…) or stations."""
    t = re.sub(r"<[^>]+>", " ", text)
    t = html.unescape(re.sub(r"\s+", " ", t))
    out = []
    for chunk in re.split(r"(?<=[.!?])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9])", t):
        f = fold(chunk)
        if not re.search(r"vyluk|omezen|nahradni doprav|zmena|preruseni|zrusen", f):
            continue
        if any(re.search(rf"\b{re.escape(fold(x))}\b", f) for x in lines) or any(fold(p) in f for p in places_ or []):
            out.append(chunk.strip()[:240])
    return list(dict.fromkeys(out))[:8]


# ------------------------------------------------------------------ (228) GBFS sdílená vozidla
def gbfs_nearby(stations: dict | None, status: dict | None, free: dict | None, near: tuple[float, float], radius_km: float = 0.6) -> list[dict]:
    out = []
    st_by = {s["station_id"]: s for s in ((stations or {}).get("data") or {}).get("stations", [])}
    for s in ((status or {}).get("data") or {}).get("stations", []):
        info = st_by.get(s.get("station_id"))
        if not info:
            continue
        d = km(near, (float(info["lat"]), float(info["lon"])))
        if d <= radius_km and int(s.get("num_bikes_available") or 0) > 0:
            out.append({"kind": "stanice", "name": info.get("name", ""), "km": round(d, 2), "count": int(s["num_bikes_available"])})
    for b in ((free or {}).get("data") or {}).get("bikes", []) + ((free or {}).get("data") or {}).get("vehicles", []):
        if b.get("is_reserved") or b.get("is_disabled"):
            continue
        d = km(near, (float(b["lat"]), float(b["lon"])))
        if d <= radius_km:
            out.append({"kind": "volné", "name": b.get("vehicle_type_id") or "kolo/koloběžka", "km": round(d, 2), "count": 1,
                        "battery": b.get("current_range_meters")})
    return sorted(out, key=lambda x: x["km"])


def ride_cost(minutes: float, unlock: float, per_min: float) -> float:
    return round(unlock + per_min * minutes, 2)


# ------------------------------------------------------------------ (230) tísňová čísla, (240) zvyklosti, (232) známky
EMERGENCY = {  # police, ambulance, fire
    "cz": ("158", "155", "150"), "sk": ("158", "155", "150"), "de": ("110", "112", "112"), "at": ("133", "144", "122"),
    "pl": ("997", "999", "998"), "hu": ("107", "104", "105"), "hr": ("192", "194", "193"), "it": ("113", "118", "115"),
    "es": ("091", "061", "080"), "fr": ("17", "15", "18"), "gr": ("100", "166", "199"), "pt": ("112", "112", "112"),
    "gb": ("999", "999", "999"), "ch": ("117", "144", "118"), "us": ("911", "911", "911"), "tr": ("155", "112", "110"),
    "eg": ("122", "123", "180"), "th": ("191", "1669", "199"), "jp": ("110", "119", "119"), "nl": ("112", "112", "112"),
    "si": ("113", "112", "112"), "me": ("122", "124", "123"), "al": ("129", "127", "128"),
}


def emergency_text(cc: str) -> str:
    cc = (cc or "").lower()
    p = EMERGENCY.get(cc)
    base = "Všude v EU funguje 112 (i bez SIM, mluví anglicky)." if cc not in ("us", "eg", "th", "jp", "tr") else ""
    if not p:
        return "Tísňová čísla pro tuhle zemi nemám – zkus 112. Kontakty na české velvyslanectví: mzv.gov.cz → Zastupitelské úřady."
    tourist = " Turistická policie: 1155." if cc == "th" else ""
    return (f"Policie {p[0]}, záchranka {p[1]}, hasiči {p[2]}. {base}{tourist} České velvyslanectví: mzv.gov.cz → Zastupitelské "
            "úřady; aplikace Cestujte bezpečně.").replace("  ", " ")


CUSTOMS = {
    "de": "Dýško 5–10 % se zaokrouhluje při placení („stimmt so“). Zdravit „Guten Tag“, v neděli jsou obchody zavřené.",
    "at": "Dýško 5–10 %, zaokrouhlit. „Grüß Gott“. V neděli je zavřeno, na lyžích ohleduplnost ve frontě.",
    "it": "Coperto (poplatek za stůl) je běžný, dýško není nutné. Cappuccino jen ráno, v kostelech zakrytá ramena.",
    "hr": "Dýško 10 % v restauraci. Na plážích s plavkami ne do města (pokuty ve Splitu, Hvaru).",
    "es": "Dýško 5–10 % jen za dobrou obsluhu. Večeře od 21:00, siesta odpoledne.",
    "fr": "Obsluha je v ceně, drobné navíc za dobrou obsluhu. Vždy pozdravit „Bonjour“ při vstupu do obchodu.",
    "gr": "Dýško 5–10 %. Mávnutí otevřenou dlaní (moutza) je urážka.",
    "gb": "Dýško 10–12,5 % pokud není „service charge“. Fronta je svatá, jezdí se vlevo.",
    "us": "Dýško 18–20 % v restauraci je povinnost, i u taxi a kadeřníka. Ceny jsou bez daně.",
    "tr": "Dýško 5–10 %. Do mešit zakrytá ramena a kolena, ženy šátek, boty dolů.",
    "eg": "Bakšiš se čeká skoro za vše (drobné). Smlouvání na trzích je normální, zakrytá ramena mimo pláž.",
    "th": "Nedotýkat se hlavy, nemluvit špatně o královské rodině, do chrámů zakrytě a bez bot. Dýško malé.",
    "jp": "Dýško se nedává (urazí). Ticho ve vlaku, boty dolů v domě, nejíst za chůze.",
    "pl": "Dýško 10 %, „dziękuję“ při placení může znamenat „drobné si nechte“.",
}

VIGNETTES = {
    "cz": ("e-známka", "edalnice.cz", "dálnice a rychlostní silnice"), "sk": ("e-známka", "eznamka.sk", "dálnice"),
    "at": ("digitální dálniční známka (+ mýto tunely)", "asfinag.at", "dálnice a rychlostní silnice"),
    "si": ("e-vinjeta", "evinjeta.dars.si", "dálnice"), "hu": ("e-matrica", "nemzetiutdij.hu", "dálnice"),
    "ch": ("Vignette (40 CHF, rok)", "via.admin.ch", "dálnice"), "bg": ("e-vinetka", "bgtoll.bg", "dálnice a hlavní silnice"),
    "ro": ("rovinieta", "roviniete.ro", "všechny státní silnice"),
}
TOLL_ROADS = {"it": "mýto na dálnici podle úseku (karta/hotovost u brány)", "fr": "mýto podle úseku (péage)",
              "hr": "mýto podle úseku (od 2026 bezbariérové ENC/registrace SZK)", "es": "některé dálnice placené (AP)",
              "pl": "e-TOLL na úsecích A1, A2, A4", "pt": "elektronické mýto – zaregistruj SPZ", "gr": "mýto u bran",
              "de": "pro osobní auta zdarma", "nl": "zdarma (kromě několika tunelů)", "be": "zdarma"}


def vignette_text(countries: list[str]) -> list[str]:
    out = []
    for cc in [c.lower() for c in countries]:
        if cc in VIGNETTES:
            name, web, where = VIGNETTES[cc]
            out.append(f"{cc.upper()}: {name} na {where} – kup jen na {web} (pozor na předražené weby).")
        elif cc in TOLL_ROADS:
            out.append(f"{cc.upper()}: {TOLL_ROADS[cc]}.")
    return out or ["Na téhle cestě známku nepotřebuješ (nebo zemi neznám)."]


# ------------------------------------------------------------------ (233) změna času
def dst_change(year: int, tz: str = "Europe/Prague") -> list[dt.date]:
    from zoneinfo import ZoneInfo

    z = ZoneInfo(tz)
    out = []
    d = dt.date(year, 1, 1)
    prev = dt.datetime(year, 1, 1, 12, tzinfo=z).utcoffset()
    while d.year == year:
        cur = dt.datetime(d.year, d.month, d.day, 12, tzinfo=z).utcoffset()
        if cur != prev:
            out.append(d)
            prev = cur
        d += dt.timedelta(days=1)
    return out


def dst_notice(today: dt.date, tz: str = "Europe/Prague") -> str:
    for d in dst_change(today.year, tz):
        if (d - today).days == 1:
            summer = d.month < 7
            return (f"Zítra v noci se mění čas – {'posouvá se o hodinu dopředu (spíš o hodinu kratší noc)' if summer else 'posouvá se o hodinu zpět (hodina spánku navíc)'}."
                    " Budíky JARVISe se posunou samy; hodiny v autě a troubě ručně.")
    return ""


# ------------------------------------------------------------------ (234) EU 261
def eu261(distance_km: float, delay_h: float, from_eu: bool = True, eu_carrier: bool = True, extraordinary: bool = False) -> dict:
    """The EU's flight compensation: arrival ≥ 3 h late → 250 / 400 / 600 € by distance."""
    if not (from_eu or eu_carrier):
        return {"eligible": False, "eur": 0, "why": "Let z mimo EU s neevropskou aerolinkou pod EU 261 nespadá."}
    if extraordinary:
        return {"eligible": False, "eur": 0, "why": "Mimořádné okolnosti (počasí, stávka letiště, bezpečnost) náhradu ruší."}
    if delay_h < 3:
        return {"eligible": False, "eur": 0, "why": "Zpoždění v cíli je kratší než 3 hodiny."}
    eur = 250 if distance_km <= 1500 else 400 if distance_km <= 3500 else 600
    return {"eligible": True, "eur": eur, "why": f"Zpoždění {delay_h:g} h na {round(distance_km)} km → {eur} € na osobu."}


def eu261_letter(name: str, flight: str, date: str, route: str, delay_h: float, eur: int, booking: str = "") -> str:
    return (f"Dobrý den,\n\nžádám o náhradu podle nařízení (ES) č. 261/2004 za zpoždění letu {flight} dne {date} ({route}). "
            f"Do cíle jsem dorazil(a) se zpožděním {delay_h:g} hodin, náhrada činí {eur} EUR na cestujícího."
            + (f" Rezervace: {booking}." if booking else "") +
            "\n\nProsím o úhradu na můj bankovní účet do 30 dnů. Přikládám palubní vstupenku a potvrzení rezervace."
            f"\n\nS pozdravem\n{name}")


# ------------------------------------------------------------------ (237) pojištění, (238) offline mapy
def insurance_due(rt: Any, trips: list[dict], today: dt.date) -> list[str]:
    out = []
    for t in trips:
        cc = str(t.get("country") or "").lower()
        if not cc or cc == "cz":
            continue
        start = dt.date.fromisoformat(str(t["start"])[:10])
        if 0 <= (start - today).days <= 7 and not db(rt).one("SELECT trip FROM tx_insured WHERE trip=?", (str(t["id"]),)):
            key = f"tx_ins:{t['id']}"
            if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
                continue
            rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
            ehic = " Evropský průkaz pojištěnce (EHIC) kryje jen základní péči, ne převoz domů." if cc in EUISH else ""
            out.append(f"Za {(start - today).days} dní jedeš do {t.get('title') or cc.upper()} – máš cestovní pojištění?{ehic}")
    return out


EUISH = set("at be bg hr cy dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se is li no ch".split())


def insured(rt: Any, trip: str) -> None:
    db(rt).exec("INSERT OR REPLACE INTO tx_insured VALUES (?,?)", (str(trip), time.time()))


def offline_map_links(lat: float, lon: float, name: str = "") -> dict:
    return {"organic": f"om://map?ll={lat:.5f},{lon:.5f}&n={name}", "mapy": f"https://mapy.com/?x={lon:.5f}&y={lat:.5f}&z=12",
            "how": "Mapy.com → Offline mapy → stáhni oblast; Organic Maps stáhne region sám po otevření odkazu. Stahuj na Wi-Fi."}


# ------------------------------------------------------------------ (239) sdílený plán
def plan_create(rt: Any, title: str, days: int = 30) -> str:
    token = pysecrets.token_urlsafe(12)
    db(rt).exec("INSERT INTO tx_plan VALUES (?,?,?,?,?)", (token, title[:80], "[]", time.time(), time.time() + days * 86400))
    return token


def plan_get(rt: Any, token: str) -> dict | None:
    row = db(rt).one("SELECT * FROM tx_plan WHERE token=?", (token,))
    if not row or float(row["until"]) < time.time():
        return None
    return {"title": row["title"], "items": json.loads(row["items"])}


def plan_add(rt: Any, token: str, who: str, text: str) -> bool:
    p = plan_get(rt, token)
    if p is None or not text.strip():
        return False
    items = (p["items"] + [{"who": who.strip()[:30] or "někdo", "text": text.strip()[:200], "ts": time.time()}])[-100:]
    db(rt).exec("UPDATE tx_plan SET items=? WHERE token=?", (json.dumps(items, ensure_ascii=False), token))
    return True


def plan_page(token: str, p: dict) -> str:
    esc = html.escape
    rows = "".join(f"<li><b>{esc(i['who'])}</b>: {esc(i['text'])} <small>{dt.datetime.fromtimestamp(i['ts']):%d. %m. %H:%M}</small></li>"
                   for i in p["items"]) or "<li>Zatím nic – přidej první bod.</li>"
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv=refresh content=30><title>{esc(p['title'])}</title><style>body{{font:16px system-ui;margin:20px;"
            "background:#0b0f14;color:#e8eef5}input,button{font:inherit;padding:8px;border-radius:8px;border:1px solid #334}"
            "button{background:#4fc3ff;border:0}li{margin:6px 0}small{color:#789}</style>"
            f"<h1>{esc(p['title'])}</h1><ul>{rows}</ul><form method=post action='/plan/{esc(token)}'>"
            "<input name=who placeholder='Jméno' maxlength=30> <input name=text placeholder='Co přidat' maxlength=200 required> "
            "<button>Přidat</button></form>")


# ------------------------------------------------------------------ (231) jídelní lístek, (229) deník
ALLERGENS = ["lepek", "korýši", "vejce", "ryby", "arašídy", "sója", "mléko", "ořechy", "celer", "hořčice", "sezam", "oxid siřičitý",
             "vlčí bob", "měkkýši"]


def menu_prompt(allergies: list[str]) -> str:
    al = ", ".join(allergies) if allergies else "žádné zadané"
    return ("Přelož tento jídelní lístek do češtiny: každé jídlo na řádek – původní název, český překlad, cena. Ke každému jídlu "
            f"uveď pravděpodobné alergeny ze 14 EU alergenů ({', '.join(ALLERGENS)}). Moje alergie: {al} – jídla, která je "
            "pravděpodobně obsahují, označ ⚠ na začátku. Když si nejsi jistý, napiš „zeptej se obsluhy“.")


def diary_html(title: str, days: list[dict], spend_czk: float = 0) -> str:
    """(229) the trip as a story: each day its places, photos and notes; the spend at the end."""
    esc = html.escape
    body = ""
    for d in days:
        pics = "".join(f"<img src='{esc(p)}' alt=''>" for p in d.get("photos", [])[:6])
        body += (f"<section><h2>{esc(d['date'])}</h2><p>{esc(', '.join(d.get('places', [])))}</p>"
                 f"<p>{esc(d.get('note', ''))}</p><div class=g>{pics}</div></section>")
    return ("<!doctype html><meta charset=utf-8><title>" + esc(title) + "</title><style>body{font:16px Georgia,serif;max-width:860px;"
            "margin:auto;padding:24px}h1{font-size:34px}.g{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.g img{width:100%;"
            "border-radius:8px}</style>" + f"<h1>{esc(title)}</h1>{body}" + (f"<p>Celkem utraceno: {spend_czk:,.0f} Kč</p>".replace(",", " ") if spend_czk else ""))


# ------------------------------------------------------------------ the daily look
async def closures_check(rt: Any, fetch: Callable[[str], Any] | None = None) -> list[str]:
    c = rt.cfg.tripx
    if not c.closure_feeds or not c.closure_lines:
        return []
    found: list[str] = []
    for url in c.closure_feeds[:6]:
        try:
            if fetch is None:
                async with rt.http() as cl:
                    r = await cl.get(url, timeout=20, follow_redirects=True)
                text = r.text
            else:
                text = await fetch(url)
        except Exception as e:  # noqa: BLE001
            log.info("closures %s: %s", url, e)
            continue
        found += closures_in(text, c.closure_lines)
    new = []
    for f in found:
        key = "tx_cl:" + str(abs(hash(f)) % 10**12)
        if not rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
            rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
            new.append(f)
    return new


async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    if not due_today(rt, "tx_daily", "18:30", now):
        return said
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("tx_daily", now.date().isoformat()))
    t = dst_notice(now.date())
    if t:
        said.append(t)
        rt.notify("Změna času", t, speak=False)
    try:
        from . import booking

        trips = [{"id": b.get("id"), "title": b.get("city") or b.get("name") or "", "start": b.get("checkin") or b.get("start"),
                  "country": b.get("country", "")} for b in booking.bookings(rt) if (b.get("checkin") or b.get("start"))]
        for t in insurance_due(rt, trips, now.date()):
            said.append(t)
            rt.notify("Cestovní pojištění", t, speak=False)
    except Exception as e:  # noqa: BLE001
        log.debug("insurance: %s", e)
    for t in await closures_check(rt):
        said.append(t)
        rt.notify("Výluka na tvé trase", t, speak=False)
    return said
