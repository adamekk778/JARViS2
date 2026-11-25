"""3.20 Zdraví+ (nápady 241–260 ze stránky „Nápady pro JARVISe“). Nic z toho není lékařské zařízení ani rada lékaře.

- léky s potvrzením a zásobou (241), dechové cvičení v notchi (242), hluk nad 70 dB (243 – jen hlasitost, nic se nenahrává)
- zdravotní deník (244), pravidlo 20-20-20 (245), teplejší obrazovka večer (246), jídelníček (247 → familyx)
- prevence a očkování celé rodiny (248), lékárnička s expirací (249), horečka a léky u dítěte (250), cviky u stolu (251)
- kofein (252), pyl tvých alergenů (253), příprava na lékaře (254), světlo u stolu (255), večerní omezení aplikací (256)
- citlivý režim s kontakty na pomoc (257), sklenice vody v notchi (258), karta pro nouzi na zamčeném telefonu (259)
- budík ve vhodné chvíli podle spánkových cyklů (260)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import time
import unicodedata
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hl_meds (name TEXT PRIMARY KEY, dose TEXT, times TEXT, stock REAL, per_dose REAL, person TEXT);
CREATE TABLE IF NOT EXISTS hl_med_log (ts REAL, name TEXT, person TEXT);
CREATE TABLE IF NOT EXISTS hl_symptoms (ts REAL, person TEXT, symptom TEXT, severity INT, note TEXT);
CREATE TABLE IF NOT EXISTS hl_prevent (person TEXT, kind TEXT, last TEXT, every_months INT, PRIMARY KEY (person, kind));
CREATE TABLE IF NOT EXISTS hl_pharmacy (name TEXT PRIMARY KEY, expires TEXT, qty INT);
CREATE TABLE IF NOT EXISTS hl_fever (ts REAL, child TEXT, temp REAL, med TEXT, dose_mg REAL);
CREATE TABLE IF NOT EXISTS hl_coffee (ts REAL, mg REAL);
CREATE TABLE IF NOT EXISTS hl_water (day TEXT PRIMARY KEY, n INT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_healthx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._healthx_ready = True
    return rt.db


def _cfg(rt: Any) -> Any:
    return getattr(rt.cfg, "healthx", None)


def _get(rt: Any, name: str, default: Any = None) -> Any:
    c = _cfg(rt)
    return getattr(c, name, default) if c is not None else default


def _once(rt: Any, key: str) -> bool:
    if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
        return False
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
    return True


# ------------------------------------------------------------------ (241) léky
def med_set(rt: Any, name: str, times: list[str], dose: str = "", stock: float = 0, per_dose: float = 1, person: str = "") -> None:
    for t in times:
        if not re.fullmatch(r"\d{1,2}:\d{2}", t):
            raise ValueError("Časy napiš jako 8:00, 20:00.")
    db(rt).exec("INSERT OR REPLACE INTO hl_meds VALUES (?,?,?,?,?,?)", (name, dose, json.dumps(times), float(stock), float(per_dose), person))


def med_taken(rt: Any, name: str, ts: float | None = None) -> dict:
    row = db(rt).one("SELECT * FROM hl_meds WHERE name=?", (name,))
    if not row:
        raise ValueError(f"Lék {name} nemám v seznamu.")
    stock = max(0.0, float(row["stock"]) - float(row["per_dose"])) if row["stock"] else 0.0
    db(rt).exec("UPDATE hl_meds SET stock=? WHERE name=?", (stock, name))
    db(rt).exec("INSERT INTO hl_med_log VALUES (?,?,?)", (ts or time.time(), name, row["person"] or ""))
    per_day = len(json.loads(row["times"] or "[]")) * float(row["per_dose"] or 1)
    days = int(stock / per_day) if per_day and row["stock"] else None
    return {"stock": stock, "days_left": days}


def meds_due(rt: Any, clock: dt.datetime) -> list[dict]:
    """The medicines due at this minute (and the ones with a week of stock left, once)."""
    out = []
    hm = f"{clock.hour}:{clock.minute:02d}"
    for r in db(rt).all("SELECT * FROM hl_meds"):
        times = [t.lstrip("0") if not t.startswith("0:") else t for t in json.loads(r["times"] or "[]")]
        if hm in times and _once(rt, f"hl_med:{r['name']}:{clock:%Y-%m-%d}:{hm}"):
            who = f" ({r['person']})" if r["person"] else ""
            out.append({"kind": "dose", "name": r["name"], "text": f"Čas na {r['name']}{who}" + (f" – {r['dose']}" if r["dose"] else "") + "."})
        per_day = len(times) * float(r["per_dose"] or 1)
        if r["stock"] and per_day and float(r["stock"]) / per_day <= 7 and _once(rt, f"hl_stock:{r['name']}:{clock:%Y-%m}"):
            out.append({"kind": "stock", "name": r["name"], "text": f"{r['name']}: zbývá na {int(float(r['stock']) / per_day)} dní – kup nebo si řekni o recept."})
    return out


def adherence(rt: Any, name: str, days: int = 14, now: float | None = None) -> dict:
    now = now or time.time()
    row = db(rt).one("SELECT times FROM hl_meds WHERE name=?", (name,))
    want = len(json.loads(row["times"])) * days if row else 0
    got = db(rt).one("SELECT COUNT(*) n FROM hl_med_log WHERE name=? AND ts >= ?", (name, now - days * 86400))["n"]
    return {"taken": got, "planned": want, "pct": round(got / want * 100) if want else None}


# ------------------------------------------------------------------ (242) dýchání, (251) cviky
BREATHING = {"4-7-8": [("nádech", 4), ("zadrž", 7), ("výdech", 8)], "box": [("nádech", 4), ("zadrž", 4), ("výdech", 4), ("zadrž", 4)],
             "klid": [("nádech", 4), ("výdech", 6)]}


def breathing(kind: str = "klid", minutes: float = 2) -> dict:
    steps = BREATHING.get(kind, BREATHING["klid"])
    cycle = sum(s for _, s in steps)
    rounds = max(1, int(minutes * 60 // cycle))
    return {"kind": kind, "steps": [{"say": a, "s": s} for a, s in steps], "rounds": rounds, "seconds": rounds * cycle}


EXERCISES = [("Krk", "Pomalu ukloň hlavu k rameni, 15 s na každou stranu. Ramena dole."),
             ("Ramena", "10× zakrouž rameny dozadu, pak 10× dopředu."),
             ("Hrudník", "Spoj ruce za zády, vypni hrudník a 20 s dýchej."),
             ("Záda", "Vsedě se předkloň k nohám, ruce volně dolů, 20 s."),
             ("Zápěstí", "Natáhni ruku dlaní ven a druhou jemně přitáhni prsty, 15 s na každou ruku."),
             ("Boky", "Vstaň, ruce v bok, 10× zakrouž pánví na každou stranu."),
             ("Lýtka", "Vstaň a 15× se zvedni na špičky."),
             ("Oči", "Zavři oči na 10 s, pak 10× pomalu pohleď nahoru, dolů, doleva, doprava.")]


def exercise_set(n: int = 3, seed: int | None = None) -> list[dict]:
    seed = seed if seed is not None else dt.date.today().toordinal()
    k = seed % len(EXERCISES)
    return [{"name": EXERCISES[(k + i) % len(EXERCISES)][0], "how": EXERCISES[(k + i) % len(EXERCISES)][1]} for i in range(n)]


# ------------------------------------------------------------------ (243) hluk, (255) světlo
def noise_db(samples: list[float], offset: float = 90.0) -> float:
    """dBFS of float samples (−1…1) shifted by a calibration offset → roughly dB(A) in the room (not a calibrated meter)."""
    if not samples:
        return 0.0
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    return round(20 * math.log10(max(rms, 1e-9)) + offset, 1)


class NoiseWatch:
    """Above 70 dB for 10 minutes → one quiet notice (then again after an hour at most)."""

    def __init__(self, limit: float = 70, minutes: float = 10):
        self.limit, self.minutes = limit, minutes
        self.since: float | None = None
        self.told: float | None = None

    def feed(self, db_value: float, now: float) -> str:
        if db_value < self.limit:
            self.since = None
            return ""
        if self.since is None:
            self.since = now
        if now - self.since >= self.minutes * 60 and (self.told is None or now - self.told > 3600):
            self.told = now
            return f"Už {int((now - self.since) // 60)} minut je kolem tebe hluk přes {int(self.limit)} dB – sluchu prospěje pauza nebo chrániče."
        return ""


def luminance(rgb_mean: tuple[float, float, float]) -> float:
    r, g, b = rgb_mean
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def light_advice(lum: float) -> str:
    if lum < 45:
        return "Pracuješ v šeru – rozsviť lampu, oči se míň unaví."
    return ""


# ------------------------------------------------------------------ (246) teplejší obrazovka
def gamma_ramp(kelvin: int) -> list[list[int]]:
    """A warmer screen in the evening (Windows SetDeviceGammaRamp): 3 × 256 values for the colour temperature."""
    k = max(1900, min(6500, kelvin)) / 100
    r = 255.0 if k <= 66 else 329.7 * ((k - 60) ** -0.1332)
    g = 99.47 * math.log(k) - 161.12 if k <= 66 else 288.12 * ((k - 60) ** -0.0755)
    b = 255.0 if k >= 66 else (0.0 if k <= 19 else 138.52 * math.log(k - 10) - 305.04)
    mult = [max(0.0, min(255.0, c)) / 255 for c in (r, g, b)]
    return [[min(65535, int(i * 257 * m)) for i in range(256)] for m in mult]


def apply_gamma(kelvin: int) -> bool:
    import sys

    if sys.platform != "win32":
        return False
    import ctypes

    ramp = gamma_ramp(kelvin)
    arr = (ctypes.c_ushort * 768)(*[v for ch in ramp for v in ch])
    hdc = ctypes.windll.user32.GetDC(0)  # type: ignore[attr-defined]
    try:
        return bool(ctypes.windll.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(arr)))  # type: ignore[attr-defined]
    finally:
        ctypes.windll.user32.ReleaseDC(0, hdc)  # type: ignore[attr-defined]


def evening_kelvin(clock: dt.datetime, start: str = "21:00") -> int:
    h, m = (int(x) for x in start.split(":"))
    mins = clock.hour * 60 + clock.minute - (h * 60 + m)
    if mins < 0 and clock.hour >= 6:
        return 6500
    if clock.hour < 6:
        return 3400
    return max(3400, 6500 - mins * 50)                 # a slow fade over an hour


# ------------------------------------------------------------------ (244, 254) deník a lékař
def symptom_add(rt: Any, symptom: str, severity: int = 3, note: str = "", person: str = "", ts: float | None = None) -> None:
    db(rt).exec("INSERT INTO hl_symptoms VALUES (?,?,?,?,?)", (ts or time.time(), person, symptom[:80], max(1, min(10, int(severity))), note[:200]))


def doctor_brief(rt: Any, person: str = "", days: int = 60, questions: list[str] | None = None, now: float | None = None) -> str:
    now = now or time.time()
    rows = [dict(r) for r in db(rt).all("SELECT * FROM hl_symptoms WHERE ts >= ? AND person=? ORDER BY ts", (now - days * 86400, person))]
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(fold(r["symptom"]), []).append(r)
    lines = ["Shrnutí pro lékaře" + (f" – {person}" if person else "")]
    for _k, rs in by.items():
        first, last = dt.datetime.fromtimestamp(rs[0]["ts"]), dt.datetime.fromtimestamp(rs[-1]["ts"])
        sev = [r["severity"] for r in rs]
        trend = "zhoršuje se" if sev[-1] > sev[0] else "zlepšuje se" if sev[-1] < sev[0] else "stejné"
        lines.append(f"• {rs[0]['symptom']}: {len(rs)}× od {first:%d. %m.} do {last:%d. %m.}, síla {min(sev)}–{max(sev)}/10, {trend}"
                     + (f" ({rs[-1]['note']})" if rs[-1]["note"] else ""))
    meds = [r["name"] + (f" {r['dose']}" if r["dose"] else "") for r in db(rt).all("SELECT * FROM hl_meds WHERE person=?", (person,))]
    if meds:
        lines.append("Užívám: " + ", ".join(meds) + ".")
    if questions:
        lines.append("Otázky: " + " ".join(f"{i}) {q}" for i, q in enumerate(questions, 1)))
    if len(lines) == 1:
        lines.append("Za posledních 60 dní nic zapsaného – řekni třeba „bolí mě hlava, síla 6“.")
    return "\n".join(lines)


# ------------------------------------------------------------------ (248) prevence, (249) lékárnička
PREVENT = {"prohlidka": ("Preventivní prohlídka u praktika", 24), "zubar": ("Zubař", 6), "gynekolog": ("Gynekolog", 12),
           "tetanus": ("Očkování proti tetanu", 120), "oci": ("Oční vyšetření", 24), "kuze": ("Kontrola znamének", 12),
           "detska": ("Preventivní prohlídka u pediatra", 24)}


def prevent_set(rt: Any, person: str, kind: str, last: str, every_months: int | None = None) -> None:
    dt.date.fromisoformat(last)
    months = every_months or PREVENT.get(kind, ("", 12))[1]
    db(rt).exec("INSERT OR REPLACE INTO hl_prevent VALUES (?,?,?,?)", (person, kind, last, int(months)))


def prevent_due(rt: Any, today: dt.date, within_days: int = 30) -> list[str]:
    out = []
    for r in db(rt).all("SELECT * FROM hl_prevent"):
        last = dt.date.fromisoformat(r["last"])
        due = last + dt.timedelta(days=int(r["every_months"] * 30.44))
        left = (due - today).days
        if left <= within_days:
            label = PREVENT.get(r["kind"], (r["kind"], 0))[0]
            out.append(f"{r['person']}: {label} {'byla potřeba už před ' + str(-left) + ' dny' if left < 0 else f'za {left} dní'} – objednej se.")
    return out


BASICS = ["paracetamol", "ibuprofen", "náplasti", "dezinfekce", "obvaz", "teploměr", "elektrolyty", "antihistaminikum", "nosní kapky"]


def pharmacy_set(rt: Any, name: str, expires: str, qty: int = 1) -> None:
    dt.date.fromisoformat(expires)
    db(rt).exec("INSERT OR REPLACE INTO hl_pharmacy VALUES (?,?,?)", (name, expires, int(qty)))


def pharmacy_check(rt: Any, today: dt.date) -> dict:
    rows = [dict(r) for r in db(rt).all("SELECT * FROM hl_pharmacy")]
    expired = [r["name"] for r in rows if dt.date.fromisoformat(r["expires"]) < today]
    soon = [r["name"] for r in rows if 0 <= (dt.date.fromisoformat(r["expires"]) - today).days <= 30]
    have = {fold(r["name"]) for r in rows if r["qty"] > 0 and r["name"] not in expired}
    missing = [b for b in BASICS if not any(fold(b) in h for h in have)]
    return {"expired": expired, "soon": soon, "missing": missing}


# ------------------------------------------------------------------ (250) horečka u dítěte
DOSING = {"paracetamol": {"mg_per_kg": 15, "every_h": 6, "max_per_day": 4}, "ibuprofen": {"mg_per_kg": 10, "every_h": 8, "max_per_day": 3}}


def fever_log(rt: Any, child: str, temp: float, med: str = "", dose_mg: float = 0, ts: float | None = None) -> None:
    if not 34 <= temp <= 43:
        raise ValueError("Teplota mimo rozsah.")
    db(rt).exec("INSERT INTO hl_fever VALUES (?,?,?,?,?)", (ts or time.time(), child, float(temp), fold(med), float(dose_mg)))


def next_dose(rt: Any, child: str, med: str, weight_kg: float = 0, now: float | None = None) -> dict:
    """When the next dose is allowed (by the usual interval and the daily maximum) – check the leaflet / ask a doctor."""
    now = now or time.time()
    med = fold(med)
    rule = DOSING.get(med)
    if rule is None:
        raise ValueError("Znám paracetamol a ibuprofen.")
    rows = [float(r["ts"]) for r in db(rt).all("SELECT ts FROM hl_fever WHERE child=? AND med=? AND ts >= ? ORDER BY ts",
                                               (child, med, now - 86400))]
    nxt = rows[-1] + rule["every_h"] * 3600 if rows else now
    if len(rows) >= rule["max_per_day"]:
        nxt = max(nxt, rows[-rule["max_per_day"]] + 86400)
    out = {"med": med, "doses_24h": len(rows), "next_ts": nxt, "now_ok": nxt <= now,
           "note": "Orientačně podle obvyklého dávkování – řiď se příbalovým letákem a lékařem. Při teplotě nad 40 °C, u kojenců do 3 měsíců "
                   "nebo při zhoršení volej lékaře."}
    if weight_kg:
        out["dose_mg"] = round(rule["mg_per_kg"] * weight_kg)
    return out


# ------------------------------------------------------------------ (252) kofein, (258) voda
CAFFEINE = {"espresso": 65, "kava": 80, "cappuccino": 80, "presso": 65, "caj": 40, "zeleny caj": 30, "energetak": 80, "cola": 35}


def coffee(rt: Any, kind: str = "kava", ts: float | None = None) -> dict:
    mg = next((v for k, v in CAFFEINE.items() if k in fold(kind)), 80)
    ts = ts or time.time()
    db(rt).exec("INSERT INTO hl_coffee VALUES (?,?)", (ts, float(mg)))
    day0 = dt.datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0).timestamp()
    total = float(db(rt).one("SELECT SUM(mg) s FROM hl_coffee WHERE ts >= ?", (day0,))["s"] or 0)
    hour = dt.datetime.fromtimestamp(ts).hour
    warn = ""
    if total > 400:
        warn = f"Dnes už {int(total)} mg kofeinu – nad doporučených 400 mg."
    elif hour >= 15:
        warn = "Káva po 15:00 může zkrátit hluboký spánek – zvaž bezkofeinovou."
    return {"mg": mg, "today": total, "warn": warn}


def water_add(rt: Any, day: dt.date | None = None, n: int = 1) -> int:
    day = day or dt.date.today()
    row = db(rt).one("SELECT n FROM hl_water WHERE day=?", (day.isoformat(),))
    cnt = (int(row["n"]) if row else 0) + n
    db(rt).exec("INSERT OR REPLACE INTO hl_water VALUES (?,?)", (day.isoformat(), cnt))
    goal = int(_get(rt, "water_goal", 8) or 8)
    rt.bus.publish("water_glass", n=cnt, goal=goal)                     # the notch fills its glass
    return cnt


def water_week(rt: Any, today: dt.date | None = None) -> list[tuple[str, int]]:
    today = today or dt.date.today()
    out = []
    for k in range(6, -1, -1):
        d = today - dt.timedelta(days=k)
        row = db(rt).one("SELECT n FROM hl_water WHERE day=?", (d.isoformat(),))
        out.append((f"{d:%d. %m.}", int(row["n"]) if row else 0))
    return out


# ------------------------------------------------------------------ (253) pyl
POLLEN = {"briza": "birch_pollen", "bříza": "birch_pollen", "olse": "alder_pollen", "olše": "alder_pollen", "travy": "grass_pollen",
          "trávy": "grass_pollen", "pelyněk": "mugwort_pollen", "pelynek": "mugwort_pollen", "ambrozie": "ragweed_pollen",
          "ambrózie": "ragweed_pollen", "oliva": "olive_pollen"}


def pollen_alert(hourly: dict, allergens: list[str], limit: float = 50) -> str:
    """Open-Meteo pollen (grains/m³): today's max for your allergens above the limit → a warning."""
    out = []
    for a in allergens:
        key = POLLEN.get(a.lower()) or POLLEN.get(fold(a))
        vals = [v for v in (hourly.get(key) or [])[:24] if v is not None] if key else []
        if vals and max(vals) >= limit:
            out.append(f"{a} {int(max(vals))} zrn/m³")
    return ("Vysoký pyl: " + ", ".join(out) + ". Větrej brzy ráno, venku brýle, po návratu sprcha.") if out else ""


async def pollen(rt: Any, lat: float, lon: float) -> dict:
    keys = ",".join(sorted(set(POLLEN.values())))
    async with rt.http() as c:
        r = await c.get("https://air-quality-api.open-meteo.com/v1/air-quality", params={"latitude": lat, "longitude": lon,
                        "hourly": keys, "forecast_days": 1, "timezone": "auto"}, timeout=12)
    r.raise_for_status()
    return r.json().get("hourly") or {}


# ------------------------------------------------------------------ (256) večerní detox
def detox_block(app: str, clock: dt.datetime, apps: list[str], start: str) -> bool:
    if not apps or not start:
        return False
    h, m = (int(x) for x in start.split(":"))
    late = clock.hour * 60 + clock.minute >= h * 60 + m or clock.hour < 5
    return late and any(fold(a) in fold(app) for a in apps if a)


# ------------------------------------------------------------------ (257) citlivý režim
CRISIS = re.compile(r"(nechci (uz )?zit|chci umrit|zabit se|sebevrazd|skoncit se zivotem|nema to cenu zit|ublizit si|sebeposkoz|"
                    r"nikdo by mi nechybel|vsem bude lip beze mne)")
CRISIS_RULE = ("Uživatel možná prožívá velmi těžké chvíle. Odpovídej klidně, laskavě a bez poučování, zeptej se, jak mu je, a "
               "nabídni pomoc: Linka první psychické pomoci 116 123 (nonstop, zdarma), pro děti a studenty Linka bezpečí 116 111, "
               "v ohrožení života 155 nebo 112. Nabídni, že můžeš někomu blízkému napsat. Nic nediagnostikuj.")


def crisis_signal(text: str) -> bool:
    return bool(CRISIS.search(fold(text)))


# ------------------------------------------------------------------ (259) karta pro nouzi
def ice_card(rt: Any) -> str:
    c = _cfg(rt)
    if c is None:
        return ""
    bits = []
    if c.blood_type:
        bits.append(f"Krevní skupina {c.blood_type}")
    if c.allergies:
        bits.append("Alergie: " + ", ".join(c.allergies))
    meds = [r["name"] for r in db(rt).all("SELECT name FROM hl_meds WHERE person=''")]
    if meds:
        bits.append("Léky: " + ", ".join(meds))
    if c.ice_contact:
        bits.append(f"Kontakt: {c.ice_contact}")
    return " · ".join(bits)


# ------------------------------------------------------------------ (260) budík podle cyklů
def cycle_alarm(bed: dt.datetime, window_start: dt.datetime, window_end: dt.datetime, fall_asleep_min: int = 15,
                cycle_min: int = 90) -> dt.datetime:
    """The latest end of a whole 90-minute sleep cycle inside the window (you wake from light sleep); else the window's end."""
    t = bed + dt.timedelta(minutes=fall_asleep_min)
    best = None
    while t <= window_end:
        if t >= window_start:
            best = t
        t += dt.timedelta(minutes=cycle_min)
    return best or window_end


# ------------------------------------------------------------------ the minute look
class State:
    def __init__(self) -> None:
        self.work = 0.0
        self.last = 0.0
        self.kelvin = 6500
        self.noise = NoiseWatch()


def state(rt: Any) -> State:
    s = getattr(rt, "healthx_state", None)
    if s is None:
        s = rt.healthx_state = State()
    return s


async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now()
    said: list[str] = []
    s = state(rt)
    for m in meds_due(rt, now):
        acts = [{"label": "Vzal jsem", "action": "ask", "args": {"text": f"vzal jsem lék {m['name']}"}}] if m["kind"] == "dose" else None
        rt.notify("Léky", m["text"], speak=m["kind"] == "dose", actions=acts)
        said.append(m["text"])
    try:
        idle = float(rt.platform.idle_seconds())
    except Exception:  # noqa: BLE001
        idle = 1e9
    ts = now.timestamp()
    step = min(ts - s.last, 120) if s.last else 0
    s.last = ts
    s.work = s.work + step if idle < 60 else 0.0
    if _get(rt, "eyes_202020", True) and s.work >= 20 * 60:
        s.work = 0.0
        rt.bus.publish("notice_hint", text="20-20-20: podívej se 20 s do dálky", icon="eye")
        said.append("202020")
    if _get(rt, "warm_screen", False):
        k = evening_kelvin(now, str(_get(rt, "warm_from", "21:00")))
        if abs(k - s.kelvin) >= 200:
            s.kelvin = k
            try:
                apply_gamma(k)
            except Exception as e:  # noqa: BLE001
                log.debug("gamma: %s", e)
    apps = _get(rt, "detox_apps", []) or []
    if apps:
        try:
            front = (rt.platform.foreground_info() or {}).get("app", "")
        except Exception:  # noqa: BLE001
            front = ""
        if front and detox_block(front, now, apps, str(_get(rt, "detox_from", "22:00"))):
            try:
                rt.platform.close_app(front)
            except Exception:  # noqa: BLE001
                pass
            rt.notify("Večerní detox", f"{front} je po {_get(rt, 'detox_from', '22:00')} zavřený (vypneš v Nastavení → Zdraví).", speak=False)
            said.append("detox")
    from .proactiveplus import due_today

    if due_today(rt, "hl_daily", "09:05", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("hl_daily", now.date().isoformat()))
        for t in prevent_due(rt, now.date(), 14):
            rt.notify("Prevence", t, speak=False)
            said.append(t)
        ph = pharmacy_check(rt, now.date())
        if ph["expired"] or ph["soon"]:
            t = "Lékárnička: " + ", ".join([f"{x} prošlé" for x in ph["expired"]] + [f"{x} brzy projde" for x in ph["soon"]]) + "."
            rt.notify("Lékárnička", t, speak=False)
            said.append(t)
        allergens = _get(rt, "pollen", []) or []
        if allergens:
            try:
                from .proactx import weather

                w = weather(rt) or {}
                if w.get("lat") is not None:
                    t = pollen_alert(await pollen(rt, float(w["lat"]), float(w["lon"])), allergens)
                    if t:
                        rt.notify("Pyl", t, speak=False)
                        said.append(t)
            except Exception as e:  # noqa: BLE001
                log.debug("pollen: %s", e)
    return said
