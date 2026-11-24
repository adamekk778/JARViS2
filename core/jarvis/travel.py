"""3.14 Cestovní režim (návrh 47): flights and trains from your booking e-mails, the flight's real state, when to leave.

- A booking / boarding-pass e-mail (airline, Kiwi, Booking, eSky, ČD, RegioJet, Leo Express…) → a trip: the flight
  or train number, when it leaves, from where to where. Found by itself in new e-mail (only the subject decides which
  e-mails it opens) or added by voice ("přidej let FR 1234 12. 12. v 14:35").
- The flight: with an AeroDataBox key the real departure, delay, terminal and gate; without one where the plane is
  right now (OpenSky, free) once it flies.
- When to leave: the departure minus the time at the airport (2 hours; a train 10 minutes) minus the drive from home
  (OpenStreetMap's router). A notice 20 minutes before that, the day's trips in the morning briefing, and a notice when
  the delay or the gate changes.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import re
import time
import unicodedata
from typing import Any

log = logging.getLogger("jarvis.travel")

# IATA → (Czech name, latitude, longitude) – the airports people from Czechia fly to most
AIRPORTS: dict[str, tuple[str, float, float]] = {
    "PRG": ("Praha", 50.1008, 14.2600), "BRQ": ("Brno", 49.1513, 16.6944), "OSR": ("Ostrava", 49.6963, 18.1111),
    "PED": ("Pardubice", 50.0134, 15.7386), "KLV": ("Karlovy Vary", 50.2030, 12.9150), "VIE": ("Vídeň", 48.1103, 16.5697),
    "BTS": ("Bratislava", 48.1702, 17.2127), "KTW": ("Katovice", 50.4743, 19.0800), "KRK": ("Krakov", 50.0777, 19.7848),
    "WAW": ("Varšava", 52.1657, 20.9671), "BUD": ("Budapešť", 47.4298, 19.2611), "MUC": ("Mnichov", 48.3538, 11.7861),
    "FRA": ("Frankfurt", 50.0379, 8.5622), "BER": ("Berlín", 52.3667, 13.5033), "DRS": ("Drážďany", 51.1328, 13.7672),
    "NUE": ("Norimberk", 49.4987, 11.0669), "LEJ": ("Lipsko", 51.4324, 12.2416), "HAM": ("Hamburk", 53.6304, 9.9882),
    "DUS": ("Düsseldorf", 51.2895, 6.7668), "ZRH": ("Curych", 47.4582, 8.5555), "GVA": ("Ženeva", 46.2381, 6.1089),
    "AMS": ("Amsterdam", 52.3105, 4.7683), "BRU": ("Brusel", 50.9014, 4.4844), "CDG": ("Paříž", 49.0097, 2.5479),
    "ORY": ("Paříž Orly", 48.7262, 2.3652), "LHR": ("Londýn Heathrow", 51.4700, -0.4543), "LGW": ("Londýn Gatwick", 51.1537, -0.1821),
    "STN": ("Londýn Stansted", 51.8860, 0.2389), "LTN": ("Londýn Luton", 51.8747, -0.3683), "DUB": ("Dublin", 53.4264, -6.2499),
    "EDI": ("Edinburgh", 55.9500, -3.3725), "MAN": ("Manchester", 53.3537, -2.2750), "CPH": ("Kodaň", 55.6180, 12.6508),
    "OSL": ("Oslo", 60.1976, 11.1004), "ARN": ("Stockholm", 59.6498, 17.9238), "HEL": ("Helsinky", 60.3172, 24.9633),
    "BCN": ("Barcelona", 41.2974, 2.0833), "MAD": ("Madrid", 40.4983, -3.5676), "AGP": ("Málaga", 36.6749, -4.4991),
    "ALC": ("Alicante", 38.2822, -0.5582), "PMI": ("Mallorca", 39.5517, 2.7388), "TFS": ("Tenerife", 28.0445, -16.5725),
    "LPA": ("Gran Canaria", 27.9319, -15.3866), "LIS": ("Lisabon", 38.7742, -9.1342), "OPO": ("Porto", 41.2481, -8.6814),
    "FCO": ("Řím", 41.8003, 12.2389), "CIA": ("Řím Ciampino", 41.7994, 12.5949), "MXP": ("Milán", 45.6306, 8.7281),
    "BGY": ("Bergamo", 45.6739, 9.7042), "VCE": ("Benátky", 45.5053, 12.3519), "NAP": ("Neapol", 40.8860, 14.2908),
    "CTA": ("Catania", 37.4668, 15.0664), "ATH": ("Atény", 37.9364, 23.9445), "HER": ("Heraklion", 35.3397, 25.1803),
    "RHO": ("Rhodos", 36.4054, 28.0862), "CFU": ("Korfu", 39.6019, 19.9117), "SPU": ("Split", 43.5389, 16.2980),
    "DBV": ("Dubrovník", 42.5614, 18.2682), "ZAG": ("Záhřeb", 45.7429, 16.0688), "IST": ("Istanbul", 41.2753, 28.7519),
    "SAW": ("Istanbul Sabiha", 40.8986, 29.3092), "AYT": ("Antalya", 36.8987, 30.8005), "HRG": ("Hurghada", 27.1783, 33.7994),
    "SSH": ("Šarm aš-Šajch", 27.9773, 34.3950), "DXB": ("Dubaj", 25.2532, 55.3657), "DOH": ("Dauhá", 25.2731, 51.6081),
    "TLV": ("Tel Aviv", 32.0114, 34.8867), "JFK": ("New York", 40.6413, -73.7781), "EWR": ("New York Newark", 40.6895, -74.1745),
    "MLA": ("Malta", 35.8575, 14.4775), "LCA": ("Larnaka", 34.8751, 33.6249), "PFO": ("Pafos", 34.7180, 32.4857),
    "BKK": ("Bangkok", 13.6900, 100.7501), "SIN": ("Singapur", 1.3644, 103.9915),
}
# IATA airline code → ICAO (the plane's callsign in the air: FR 1234 flies as RYR1234)
AIRLINES: dict[str, str] = {
    "OK": "CSA", "QS": "TVS", "FR": "RYR", "RK": "RUK", "W6": "WZZ", "W4": "WMT", "U2": "EZY", "EC": "EJU", "LH": "DLH",
    "LX": "SWR", "OS": "AUA", "EW": "EWG", "KL": "KLM", "AF": "AFR", "BA": "BAW", "EI": "EIN", "IB": "IBE", "VY": "VLG",
    "TP": "TAP", "AZ": "ITY", "LO": "LOT", "SN": "BEL", "SK": "SAS", "AY": "FIN", "DY": "NOZ", "D8": "NSZ", "A3": "AEE",
    "TK": "THY", "PC": "PGT", "EK": "UAE", "QR": "QTR", "EY": "ETD", "LY": "ELY", "JU": "ASL", "RO": "ROT", "OU": "CTN",
    "KM": "KMM", "BT": "BTI", "HV": "TRA", "TO": "TVF", "X3": "TUI", "BY": "TOM", "DE": "CFG", "UA": "UAL", "DL": "DAL",
    "AA": "AAL", "AC": "ACA", "LS": "EXS", "V7": "VOE", "HG": "NLY", "4U": "GWI", "6B": "BLX", "XQ": "SXS", "SM": "MSC",
}
TRAIN = r"(?:EC|IC|EN|Ex|Rx|R|Sp|Os|RJX|RJ|LE|ICE|SC|NJ|Nightjet|railjet|rj)"
MONTHS = {"jan": 1, "led": 1, "feb": 2, "uno": 2, "mar": 3, "bre": 3, "apr": 4, "dub": 4, "may": 5, "kve": 5, "jun": 6,
          "cerven": 6, "cervna": 6, "jul": 7, "cervenec": 7, "cervence": 7, "aug": 8, "srp": 8, "sep": 9, "zar": 9,
          "oct": 10, "rij": 10, "nov": 11, "lis": 11, "dec": 12, "pro": 12}
SUBJECT = re.compile(r"(rezervac|booking|potvrzen|confirmation|letenk|flight|let |boarding|palubn|itinerar|e-?ticket|"
                     r"jizdenk|jízdenk|vlak|regiojet|leo express|ceske drahy|české dráhy|cd\.cz|check-?in|odbaven)", re.I)
TRAIN_WORDS = re.compile(r"(jizdenk|jízdenk|vlak|regiojet|leo express|českých drah|ceske drahy|české dráhy|cd\.cz|odjezd|train)", re.I)
FLIGHT_BUFFER_DEFAULT, TRAIN_BUFFER = 120, 10
NOTIFY_BEFORE_MIN = 20


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))


def _db(rt: Any) -> Any:
    rt.db.exec("CREATE TABLE IF NOT EXISTS trips (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, number TEXT, dep REAL, arr REAL, "
               "origin TEXT, dest TEXT, source TEXT, info TEXT, created REAL, UNIQUE(number, dep))")
    return rt.db


# ---------------------------------------------------------------------------------------------- reading e-mails
_DATES = [
    (re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d{2})\b"), "dmy"),
    (re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})\.?\s+([a-zA-Zá-žÁ-Ž]{3,9})\.?,?\s+(20\d{2})\b"), "dMy"),
    (re.compile(r"\b([a-zA-Z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b"), "Mdy"),
]
_TIME = re.compile(r"(?<![\d.:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")


def _month(word: str) -> int | None:
    w = _fold(word)
    for k in sorted(MONTHS, key=len, reverse=True):
        if w.startswith(k):
            return MONTHS[k]
    return None


def dates_in(text: str) -> list[tuple[int, dt.date]]:
    """(position, date) of every date in the text, in order."""
    out = []
    for rx, kind in _DATES:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                elif kind == "ymd":
                    d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif kind == "dMy":
                    mo = _month(m.group(2))
                    if not mo:
                        continue
                    d = dt.date(int(m.group(3)), mo, int(m.group(1)))
                else:
                    mo = _month(m.group(1))
                    if not mo:
                        continue
                    d = dt.date(int(m.group(3)), mo, int(m.group(2)))
            except ValueError:
                continue
            out.append((m.start(), d))
    return sorted(out)


def times_in(text: str) -> list[tuple[int, dt.time]]:
    return [(m.start(), dt.time(int(m.group(1)), int(m.group(2)))) for m in _TIME.finditer(text)]


def _date_near(text: str, pos: int, dates: list[tuple[int, dt.date]]) -> dt.date | None:
    after = [d for p, d in dates if pos <= p <= pos + 400]
    if after:
        return after[0]
    before = [d for p, d in dates if pos - 400 <= p < pos]
    if before:
        return before[-1]
    return dates[0][1] if dates else None


def parse(text: str, now: dt.datetime | None = None) -> list[dict]:
    """Trips in a booking e-mail: [{kind, number, dep, arr, origin, dest}] (dep/arr local timestamps)."""
    now = now or dt.datetime.now()
    text = re.sub(r"[ \t ]+", " ", text or "")
    dates = dates_in(text)
    out: list[dict] = []
    seen = set()
    codes = "|".join(sorted((re.escape(c) for c in AIRLINES), key=len, reverse=True))
    for m in re.finditer(rf"(?<![A-Z0-9])({codes})\s?(\d{{1,4}})(?![\d:])", text):
        if 1990 <= int(m.group(2)) <= 2100:            # "LS 2026" is a year, not a flight
            continue
        number = f"{m.group(1)} {int(m.group(2))}"
        win = text[m.end(): m.end() + 400]
        d = _date_near(text, m.start(), dates)
        ts = [t for _, t in times_in(win)]
        if not d or not ts:
            continue
        dep = dt.datetime.combine(d, ts[0])
        if dep < now - dt.timedelta(days=2) or (number, dep) in seen:
            continue
        seen.add((number, dep))
        arr = None
        if len(ts) > 1:
            arr = dt.datetime.combine(d, ts[1])
            if arr <= dep:
                arr += dt.timedelta(days=1)
        iata = r"(?<![A-Z])([A-Z]{3})(?![A-Z])"
        after = [c for c in re.findall(iata, text[m.end(): m.end() + 250]) if c in AIRPORTS]
        before = [c for c in re.findall(iata, text[max(0, m.start() - 200): m.start()]) if c in AIRPORTS]
        ports = list(dict.fromkeys(after + before[::-1]))          # the airports right after the number first
        out.append({"kind": "flight", "number": number, "dep": dep.timestamp(), "arr": arr.timestamp() if arr else None,
                    "origin": ports[0] if ports else "", "dest": ports[1] if len(ports) > 1 else ""})
    if TRAIN_WORDS.search(text):
        for m in re.finditer(rf"(?<![A-Za-z0-9]){TRAIN}\s?(\d{{1,5}})(?![\d:.])", text):
            number = re.sub(r"\s+", " ", m.group(0)).strip()
            win = text[m.end(): m.end() + 300]
            d = _date_near(text, m.start(), dates)
            ts = [t for _, t in times_in(win)] or [t for _, t in times_in(text[max(0, m.start() - 150): m.start()])]
            if not d or not ts:
                continue
            dep = dt.datetime.combine(d, ts[0])
            if dep < now - dt.timedelta(days=2) or (number, dep) in seen:
                continue
            seen.add((number, dep))
            route = re.search(r"([A-ZÁ-Ž][\w.áčďéěíňóřšťúůýž ]{2,40}?)\s*(?:→|->|–|—| - )\s*([A-ZÁ-Ž][\w.áčďéěíňóřšťúůýž ]{2,40})",
                              text[max(0, m.start() - 300): m.end() + 300])
            arr = dt.datetime.combine(d, ts[1]) if len(ts) > 1 else None
            if arr and arr <= dep:
                arr += dt.timedelta(days=1)
            out.append({"kind": "train", "number": number, "dep": dep.timestamp(), "arr": arr.timestamp() if arr else None,
                        "origin": route.group(1).strip() if route else "", "dest": route.group(2).strip() if route else ""})
    return out


def add(rt: Any, trip: dict, source: str = "") -> int | None:
    """Store a trip (the same number at the same time only once); returns its id (None when it was there already)."""
    db = _db(rt)
    if db.one("SELECT id FROM trips WHERE number=? AND dep=?", (trip["number"], trip["dep"])):
        return None
    db.exec("INSERT INTO trips (kind, number, dep, arr, origin, dest, source, info, created) VALUES (?,?,?,?,?,?,?,?,?)",
            (trip["kind"], trip["number"], trip["dep"], trip.get("arr"), trip.get("origin", ""), trip.get("dest", ""), source,
             json.dumps(trip.get("info") or {}), time.time()))
    row = db.one("SELECT id FROM trips WHERE number=? AND dep=?", (trip["number"], trip["dep"]))
    return int(row["id"]) if row else None


def remove(rt: Any, tid: int) -> bool:
    db = _db(rt)
    had = db.one("SELECT id FROM trips WHERE id=?", (int(tid),)) is not None
    db.exec("DELETE FROM trips WHERE id=?", (int(tid),))
    return had


def upcoming(rt: Any, now: float | None = None, days: int = 60) -> list[dict]:
    now = time.time() if now is None else now
    rows = _db(rt).all("SELECT * FROM trips WHERE dep>=? AND dep<=? ORDER BY dep", (now - 3 * 3600, now + days * 86400))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["info"] = json.loads(d.get("info") or "{}")
        except ValueError:
            d["info"] = {}
        out.append(d)
    return out


def place(code: str) -> str:
    return AIRPORTS[code][0] if code in AIRPORTS else code


def describe(t: dict) -> str:
    when = dt.datetime.fromtimestamp(t["dep"])
    what = ("let " if t["kind"] == "flight" else "vlak ") + t["number"]
    route = ""
    if t.get("origin") or t.get("dest"):
        route = f" {place(t.get('origin', ''))} → {place(t.get('dest', ''))}".replace(" →  ", " ").rstrip(" →")
    info = t.get("info") or {}
    extra = []
    if info.get("delay_min"):
        extra.append(f"zpoždění {info['delay_min']} min")
    if info.get("gate"):
        extra.append(f"gate {info['gate']}")
    if info.get("terminal"):
        extra.append(f"terminál {info['terminal']}")
    return f"{what}{route} {when.day}. {when.month}. v {when:%H:%M}" + (f" ({', '.join(extra)})" if extra else "")


def _subject_hit(subject: str) -> bool:
    return bool(SUBJECT.search(subject or ""))


async def scan_mail(rt: Any, limit: int = 40) -> list[dict]:
    """Look at the last e-mails whose subject smells like a booking (once each) and keep the trips (and parcels) in them."""
    mail = getattr(rt, "mail", None)
    if mail is None or not rt.cfg.mail.accounts:
        return []
    from . import parcels

    db = rt.db
    row = db.one("SELECT v FROM kv WHERE k='travel_seen_mail'")
    seen: list[str] = json.loads(row["v"]) if row else []
    found: list[dict] = []
    acc = mail.account()
    heads = await asyncio.to_thread(acc.list, False, limit)
    for h in heads:
        if h["id"] in seen or h.get("newsletter"):
            continue
        trip_like, parcel_like = _subject_hit(h["subject"]), parcels.subject_hit(h["subject"])
        if not (trip_like or parcel_like):
            continue
        seen.append(h["id"])
        try:
            m = await asyncio.to_thread(acc.read, h["uid"], False)
        except Exception as e:  # noqa: BLE001
            log.debug("travel read: %s", e)
            continue
        body = f"{m.get('subject', '')}\n{m.get('text', '')}"
        if trip_like:
            for t in parse(body):
                if add(rt, t, h["id"]):
                    found.append(t)
        if parcel_like:
            for p in parcels.find(body, m.get("from", ""), m.get("from_name", "")):
                parcels.add(rt, p["carrier"], p["number"], p.get("shop", ""), h["id"])
    db.exec("INSERT OR REPLACE INTO kv VALUES ('travel_seen_mail', ?)", (json.dumps(seen[-500:]),))
    return found


# ---------------------------------------------------------------------------------------------- when to leave
def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


async def drive_minutes(rt: Any, frm: tuple[float, float], to: tuple[float, float]) -> int | None:
    """The drive by OpenStreetMap's router (OSRM); None when it cannot say."""
    try:
        async with rt.http() as c:
            r = await c.get(f"https://router.project-osrm.org/route/v1/driving/{frm[1]},{frm[0]};{to[1]},{to[0]}",
                            params={"overview": "false"}, timeout=12)
        j = r.json()
        if j.get("code") == "Ok" and j.get("routes"):
            return max(1, round(float(j["routes"][0]["duration"]) / 60))
    except Exception as e:  # noqa: BLE001
        log.debug("osrm: %s", e)
    return None


async def geocode(rt: Any, name: str) -> tuple[float, float] | None:
    try:
        async with rt.http() as c:
            r = await c.get("https://nominatim.openstreetmap.org/search", params={"q": name, "format": "json", "limit": 1},
                            headers={"User-Agent": "JARVIS-assistant/3.14"}, timeout=12)
        j = r.json()
        if j:
            return float(j[0]["lat"]), float(j[0]["lon"])
    except Exception as e:  # noqa: BLE001
        log.debug("geocode: %s", e)
    return None


async def leave_plan(rt: Any, t: dict) -> dict:
    """{leave: timestamp, drive_min, buffer_min}: when to set off from home for this trip."""
    flight = t["kind"] == "flight"
    buffer = int(getattr(rt.cfg.home, "travel_buffer_min", FLIGHT_BUFFER_DEFAULT) or FLIGHT_BUFFER_DEFAULT) if flight else TRAIN_BUFFER
    info = t.get("info") or {}
    drive = info.get("drive_min")
    if drive is None:
        target: tuple[float, float] | None = None
        if flight and t.get("origin") in AIRPORTS:
            a = AIRPORTS[t["origin"]]
            target = (a[1], a[2])
        elif t.get("origin"):
            target = await geocode(rt, t["origin"] + (" nádraží" if not flight else ""))
        try:
            from .eyes import home_coords

            lat, lon, _ = await home_coords(rt)
            home: tuple[float, float] | None = (lat, lon)
        except Exception:  # noqa: BLE001
            home = None
        if target and home:
            drive = 0 if _km(home, target) < 1 else await drive_minutes(rt, home, target)
        if drive is not None:
            info["drive_min"] = drive
            if t.get("id"):
                _db(rt).exec("UPDATE trips SET info=? WHERE id=?", (json.dumps(info), t["id"]))
    dep = float(t["dep"]) + 60 * int(info.get("delay_min") or 0)
    d = int(drive if drive is not None else (45 if flight else 30))
    return {"leave": dep - 60 * (buffer + d), "drive_min": d, "buffer_min": buffer, "guess": drive is None}


# ---------------------------------------------------------------------------------------------- the flight's state
def callsign(number: str) -> str:
    m = re.match(r"^\s*([A-Z0-9]{2})\s?(\d{1,4})\s*$", (number or "").upper())
    if not m or m.group(1) not in AIRLINES:
        return ""
    return f"{AIRLINES[m.group(1)]}{int(m.group(2))}"


async def live(rt: Any, number: str) -> dict:
    """Where the plane is now (OpenSky, free): {} when it is not in the air."""
    cs = callsign(number)
    if not cs:
        return {}
    async with rt.http() as c:
        r = await c.get("https://opensky-network.org/api/states/all", timeout=20)
    if r.status_code != 200:
        return {}
    for s in (r.json() or {}).get("states") or []:
        if (s[1] or "").strip().upper() == cs and s[5] is not None and s[6] is not None:
            return {"callsign": cs, "lon": s[5], "lat": s[6], "alt_m": s[7] or s[13], "on_ground": bool(s[8]),
                    "speed_kmh": round((s[9] or 0) * 3.6)}
    return {}


async def check_flight(rt: Any, t: dict) -> dict:
    """The flight's real state from AeroDataBox (with a key): changes saved; returns {changed: [...], info}."""
    from . import connectors

    if t["kind"] != "flight" or not connectors.configured("aerodatabox"):
        return {"changed": [], "info": t.get("info") or {}}
    from .connectors import aerodatabox

    day = dt.datetime.fromtimestamp(t["dep"]).date().isoformat()
    s = await aerodatabox.flight(t["number"], day)
    info = dict(t.get("info") or {})
    changed = []
    if s:
        delay = 0
        try:
            sched = dt.datetime.fromisoformat(s["dep_sched"][:16].replace(" ", "T"))
            rev = dt.datetime.fromisoformat(s["dep_revised"][:16].replace(" ", "T")) if s.get("dep_revised") else sched
            delay = max(0, round((rev - sched).total_seconds() / 60))
        except (ValueError, KeyError):
            pass
        for k, v in (("delay_min", delay), ("gate", s.get("gate", "")), ("terminal", s.get("terminal", "")), ("status", s.get("status", ""))):
            if v and info.get(k) != v:
                if k in ("delay_min", "gate") and (k != "delay_min" or abs(int(v) - int(info.get(k) or 0)) >= 10):
                    changed.append(k)
                info[k] = v
        if not t.get("origin") and s.get("from"):
            _db(rt).exec("UPDATE trips SET origin=?, dest=? WHERE id=?", (s["from"], s.get("to", ""), t["id"]))
        _db(rt).exec("UPDATE trips SET info=? WHERE id=?", (json.dumps(info), t["id"]))
    return {"changed": changed, "info": info}


def briefing_line(rt: Any, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    end = now.replace(hour=23, minute=59).timestamp()
    today = [t for t in upcoming(rt, now.timestamp()) if t["dep"] <= end]
    if not today:
        return ""
    return "Dnes cestujete: " + "; ".join(describe(t) for t in today) + "."


class Watch:
    """Every 5 minutes: new booking e-mails, the flight's delay / gate, "time to leave"."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.last_scan = 0.0
        self.last_check: dict[int, float] = {}
        self.told: set[tuple[int, str]] = set()

    async def step(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        said = []
        if now - self.last_scan >= 15 * 60:
            self.last_scan = now
            try:
                for t in await scan_mail(self.rt):
                    said.append(f"new:{t['number']}")
                    self.rt.notify("Nová cesta", f"Z e-mailu jsem si zapsal {describe(t)}. Dám vědět, kdy vyrazit.", target="all")
            except Exception as e:  # noqa: BLE001
                log.debug("travel scan: %s", e)
        for t in upcoming(self.rt, now, days=2):
            tid = int(t["id"])
            if t["kind"] == "flight" and t["dep"] - now <= 8 * 3600 and now - self.last_check.get(tid, 0) >= 15 * 60:
                self.last_check[tid] = now
                try:
                    res = await check_flight(self.rt, t)
                    t["info"] = res["info"]
                    for k in res["changed"]:
                        said.append(f"{k}:{t['number']}")
                        self.rt.notify("Let " + t["number"], ("Zpoždění: " if k == "delay_min" else "Změna gate: ") + describe(t) + ".",
                                       target="all", speak=True)
                except Exception as e:  # noqa: BLE001
                    log.debug("flight check: %s", e)
            if (tid, "leave") not in self.told and t["dep"] > now:
                plan = await leave_plan(self.rt, t)
                if plan["leave"] - NOTIFY_BEFORE_MIN * 60 <= now:
                    self.told.add((tid, "leave"))
                    at = dt.datetime.fromtimestamp(max(now, plan["leave"]))
                    where = "na letiště" if t["kind"] == "flight" else "na nádraží"
                    self.rt.notify("Čas vyrazit", f"{describe(t)}: vyrazte {where} v {at:%H:%M} (cesta asi {plan['drive_min']} min, "
                                   f"rezerva {plan['buffer_min']} min).", target="all", speak=True)
                    said.append(f"leave:{t['number']}")
        return said

    async def run(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                await self.step()
            except Exception as e:  # noqa: BLE001
                log.debug("travel: %s", e)
            await asyncio.sleep(5 * 60)


def watch(rt: Any) -> Watch:
    w = getattr(rt, "_travel", None)
    if w is None:
        w = rt._travel = Watch(rt)
    return w
