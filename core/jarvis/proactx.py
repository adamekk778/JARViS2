"""3.20 Proaktivita+ (nápady 61–80 ze stránky „Nápady pro JARVISe“).

- ranní souhrn podle dne: pracovní den, víkend / svátek, dovolená (61)
- den na sušení prádla podle předpovědi po hodinách (63), pitný režim podle horka (68)
- hlídání termínů: STK, pojištění, pas, faktury – týden a den předem (64)
- nemocenský den (65), kontrola před dovolenou (66), uzávěrka měsíce (67)
- příprava na schůzku 30 min předem (69), návrh týdne v neděli (70), narozeniny s tipem na dárek (71)
- sezónní úkoly (72), ozvi se kamarádovi (73), pauza ve hře po 2 hodinách (74)
- státní svátky a zavřené obchody den předem (75), rutiny s podmínkou počasí a dne (76)
- uvolněný čas po zrušené schůzce (77), konec pracovního dne (78), přehled používaných rutin (79)
- čtvrteční předpověď na víkend (80); večerní deník, výročí, fakta k ověření, rok v kostce (z Paměti+)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import time
import unicodedata
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS px_deadlines (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, day TEXT, kind TEXT, told7 INT DEFAULT 0,
  told1 INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS px_friends (name TEXT PRIMARY KEY, every_days INT, last REAL);
CREATE TABLE IF NOT EXISTS px_seasonal (key TEXT, year INT, state TEXT, PRIMARY KEY (key, year));
CREATE TABLE IF NOT EXISTS auto_stats (id TEXT PRIMARY KEY, fires INT DEFAULT 0, last REAL, month_fires INT DEFAULT 0, month TEXT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_px_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._px_ready = True
    return rt.db


def once(rt: Any, key: str, period: str) -> bool:
    """True the first time for this key in this period (a day, a year…) – then never again in it."""
    k = f"px_once_{key}"
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (k,))
    if row and row["v"] == period:
        return False
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, period))
    return True


# ------------------------------------------------------------------ (75) státní svátky
def easter(year: int) -> dt.date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    return dt.date(year, month, day)


def cz_holidays(year: int) -> dict[dt.date, str]:
    e = easter(year)
    fixed = {(1, 1): "Nový rok a Den obnovy samostatného českého státu", (5, 1): "Svátek práce", (5, 8): "Den vítězství",
             (7, 5): "Den slovanských věrozvěstů Cyrila a Metoděje", (7, 6): "Den upálení mistra Jana Husa",
             (9, 28): "Den české státnosti", (10, 28): "Den vzniku samostatného československého státu",
             (11, 17): "Den boje za svobodu a demokracii", (12, 24): "Štědrý den", (12, 25): "1. svátek vánoční",
             (12, 26): "2. svátek vánoční"}
    out = {dt.date(year, m, d): n for (m, d), n in fixed.items()}
    out[e - dt.timedelta(days=2)] = "Velký pátek"
    out[e + dt.timedelta(days=1)] = "Velikonoční pondělí"
    return out


def shops_closed(day: dt.date) -> str:
    """Zákon č. 223/2016 Sb.: shops over 200 m² are closed on these holidays (24. 12. from noon)."""
    if day == dt.date(day.year, 12, 24):
        return "od 12:00"
    closed = {(1, 1), (5, 8), (9, 28), (10, 28), (12, 25), (12, 26)}
    if (day.month, day.day) in closed or day == easter(day.year) + dt.timedelta(days=1):
        return "celý den"
    return ""


def holiday_notice(day: dt.date) -> str:
    """For the day before a holiday: what it is and what is closed."""
    hol = cz_holidays(day.year).get(day)
    if not hol:
        return ""
    shops = shops_closed(day)
    s = f"Zítra je svátek – {hol}."
    if shops == "celý den":
        s += " Velké obchody (nad 200 m²) budou celý den zavřené, pošta a úřady taky – nakup a vyřiď to dnes."
    elif shops:
        s += " Velké obchody zavřou ve 12:00."
    else:
        s += " Obchody mají otevřeno, pošta a úřady ne."
    return s


# ------------------------------------------------------------------ (61) ranní souhrn podle dne
def day_kind(rt: Any, day: dt.date | None = None) -> str:
    day = day or dt.date.today()
    try:
        for b in rt.db.all("SELECT start, end FROM bookings WHERE status != 'cancelled'"):
            if str(b["start"])[:10] <= day.isoformat() <= str(b["end"])[:10]:
                return "vacation"
    except Exception:  # noqa: BLE001
        pass
    if getattr(rt.cfg, "day", None) is not None and getattr(rt.cfg.day, "vacation_until", "") >= day.isoformat():
        return "vacation"
    if day.weekday() >= 5 or day in cz_holidays(day.year):
        return "weekend"
    return "work"


def morning_lead(rt: Any, day: dt.date | None = None) -> str:
    day = day or dt.date.today()
    k = day_kind(rt, day)
    if k == "vacation":
        try:
            b = next((b for b in rt.db.all("SELECT name, city, start, end FROM bookings WHERE status != 'cancelled'")
                      if str(b["start"])[:10] <= day.isoformat() <= str(b["end"])[:10]), None)
        except Exception:  # noqa: BLE001
            b = None
        where = f" ({b['name']}, {b['city']}, do {str(b['end'])[8:10]}. {str(b['end'])[5:7]}.)" if b else ""
        return f"Jsi na dovolené{where} – pracovní věci nechávám stranou, doma hlídám, co je potřeba."
    if k == "weekend":
        hol = cz_holidays(day.year).get(day)
        return (f"Dnes je svátek – {hol}." if hol else "Je víkend.") + " Pracovní pošta počká, tady je jen to podstatné."
    return ""


# ------------------------------------------------------------------ weather (one cached fetch for several checks)
WEATHER_TTL = 1800


async def refresh_weather(rt: Any) -> dict | None:
    if os.environ.get("JARVIS_NO_NET"):
        return None
    city = rt.cfg.general.city or "Praha"
    try:
        async with rt.http() as c:
            g = (await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "cs"},
                             timeout=15)).json()
            loc = (g.get("results") or [None])[0]
            if not loc:
                return None
            w = (await c.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
                "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto", "forecast_days": 4,
                "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,wind_speed_10m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})).json()
    except Exception as e:  # noqa: BLE001
        log.debug("px weather: %s", e)
        return None
    data = {"ts": time.time(), "hourly": w.get("hourly", {}), "daily": w.get("daily", {})}
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_weather', ?)", (json.dumps(data),))
    return data


def weather(rt: Any) -> dict:
    row = rt.db.one("SELECT v FROM kv WHERE k='px_weather'")
    try:
        return json.loads(row["v"]) if row else {}
    except ValueError:
        return {}


def today_max(rt: Any, day: dt.date | None = None) -> float | None:
    d = weather(rt).get("daily") or {}
    key = (day or dt.date.today()).isoformat()
    for t, mx in zip(d.get("time", []), d.get("temperature_2m_max", [])):
        if t == key:
            return mx
    return None


RAIN_CODES = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}
SNOW_CODES = set(range(71, 78)) | {85, 86}


def now_hour(rt: Any, at: dt.datetime | None = None) -> dict:
    h = weather(rt).get("hourly") or {}
    key = (at or dt.datetime.now()).strftime("%Y-%m-%dT%H:00")
    times = h.get("time", [])
    if key not in times:
        return {}
    i = times.index(key)
    return {k: (h.get(k) or [None] * (i + 1))[i] for k in ("temperature_2m", "relative_humidity_2m", "precipitation_probability",
                                                              "wind_speed_10m", "weather_code")}


# ------------------------------------------------------------------ (63) sušení prádla
def laundry_window(rt: Any, day: dt.date | None = None) -> str:
    h = weather(rt).get("hourly") or {}
    day = day or dt.date.today()
    good: list[int] = []
    for t, temp, hum, rain, wind in zip(h.get("time", []), h.get("temperature_2m", []), h.get("relative_humidity_2m", []),
                                         h.get("precipitation_probability", []), h.get("wind_speed_10m", [])):
        if not t.startswith(day.isoformat()):
            continue
        hour = int(t[11:13])
        if 8 <= hour <= 19 and temp is not None and temp >= 8 and (hum or 100) < 75 and (rain or 0) < 20 and (wind or 0) < 40:
            good.append(hour)
    best: list[int] = []
    run: list[int] = []
    for x in good:
        run = run + [x] if run and x == run[-1] + 1 else [x]
        if len(run) > len(best):
            best = list(run)
    if len(best) < 4:
        return ""
    return f"Dnes je dobré počasí na sušení prádla venku – od {best[0]}:00 do {best[-1] + 1}:00 (sucho, bez deště)."


# ------------------------------------------------------------------ (68) pitný režim podle horka
def water_minutes(rt: Any, mins: int) -> int:
    mx = today_max(rt)
    if mins and mx is not None and mx >= 28:
        return max(20, int(mins * 0.66))
    return mins


# ------------------------------------------------------------------ (64) hlídání termínů
DEADLINE_WORDS = {"stk": "STK", "pojist": "pojištění", "pas": "pas", "obcansk": "občanka", "op ": "občanka", "ridicak": "řidičák",
                  "faktur": "faktura", "smlouv": "smlouva", "dalnicni": "dálniční známka", "znamk": "dálniční známka",
                  "dan": "daně", "prohlidk": "prohlídka", "revize": "revize", "kotel": "kotel"}


def parse_deadline(text: str, today: dt.date | None = None) -> tuple[str, dt.date, str] | None:
    """"STK do 3. 4. 2027", "pojištění auta končí 15. 6.", "faktura Alza splatná 30. 11." → (title, day, kind)."""
    today = today or dt.date.today()
    m = re.search(r"(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?", text) or re.search(r"\b(\d{1,2})/(\d{4})\b", text)
    if not m:
        return None
    try:
        if m.lastindex == 2 and len(m.group(2)) == 4:          # "3/2027" = the end of that month
            mo, y = int(m.group(1)), int(m.group(2))
            day = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1))
        else:
            y = int(m.group(3)) if m.group(3) else today.year
            day = dt.date(y, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and day < today:
                day = day.replace(year=y + 1)
    except ValueError:
        return None
    f = fold(text) + " "
    kind = next((v for k, v in DEADLINE_WORDS.items() if k in f), "termín")
    title = re.sub(r"\s*(do|konci|končí|splatn\w*|plati|platí|vyprsi|vyprší|je|ma|má)?\s*(\d{1,2}\.\s?\d{1,2}\.(\s?\d{4})?|\d{1,2}/\d{4}).*$",
                   "", text, flags=re.I).strip(" ,:-") or kind
    return title, day, kind


def add_deadline(rt: Any, title: str, day: dt.date, kind: str = "termín") -> int:
    return int(db(rt).exec("INSERT INTO px_deadlines(title, day, kind) VALUES (?,?,?)", (title, day.isoformat(), kind)).lastrowid)


def deadlines(rt: Any, include_past: bool = False) -> list[dict]:
    rows = db(rt).all("SELECT * FROM px_deadlines ORDER BY day")
    today = dt.date.today().isoformat()
    return [dict(r) for r in rows if include_past or r["day"] >= today]


def deadlines_due(rt: Any, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    out = []
    for r in db(rt).all("SELECT * FROM px_deadlines WHERE day >= ?", (today.isoformat(),)):
        left = (dt.date.fromisoformat(r["day"]) - today).days
        if left <= 1 and not r["told1"]:
            db(rt).exec("UPDATE px_deadlines SET told1=1, told7=1 WHERE id=?", (r["id"],))
            out.append(f"{'Dnes' if left == 0 else 'Zítra'} končí: {r['title']} ({dt.date.fromisoformat(r['day']):%d. %m. %Y}).")
        elif left <= 7 and not r["told7"]:
            db(rt).exec("UPDATE px_deadlines SET told7=1 WHERE id=?", (r["id"],))
            out.append(f"Za {left} dní končí: {r['title']} ({dt.date.fromisoformat(r['day']):%d. %m. %Y}).")
    return out


def deadlines_from_facts(rt: Any) -> int:
    have = {(r["title"], r["day"]) for r in db(rt).all("SELECT title, day FROM px_deadlines")}
    n = 0
    for f in rt.db.all("SELECT text FROM facts"):
        if not re.search(r"\b(stk|pojist\w*|pas\w*|obcansk\w*|ridicak\w*|splatn\w*|plati do|konci|vyprsi|znamk\w*)\b", fold(f["text"])):
            continue
        p = parse_deadline(f["text"])
        if p and (p[0], p[1].isoformat()) not in have:
            add_deadline(rt, *p)
            n += 1
    return n


# ------------------------------------------------------------------ (65) nemocenský den
async def sick_day(rt: Any, day: dt.date | None = None) -> dict:
    day = day or dt.date.today()
    events = []
    try:
        events = [e for e in await rt.calendar.day(day) if not e.get("all_day")]
    except Exception:  # noqa: BLE001
        pass
    try:
        rt.attention.focus(8 * 60)                  # quiet: notices wait, nothing loud
    except Exception:  # noqa: BLE001
        pass
    if not getattr(rt.cfg.health, "water_minutes", 0):
        rt.update_config({"health": {"water_minutes": 60}})
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_sick', ?)", (day.isoformat(),))
    moves = [f"{dt.datetime.fromtimestamp(e['start']).strftime('%H:%M') if isinstance(e.get('start'), (int, float)) else str(e.get('start', ''))[11:16]} "
             f"{e.get('title', '')}" for e in events]
    return {"events": moves, "quiet": True}


# ------------------------------------------------------------------ (66) kontrola před dovolenou
async def vacation_check(rt: Any) -> list[tuple[str, str]]:
    """(stav, co) – ✓ done, ! needs you, ? JARVIS cannot see it."""
    out: list[tuple[str, str]] = []
    try:
        from . import home

        if home.configured(rt):
            hm = getattr(rt, "home", None) or home.Home(rt)
            states = await hm.states()
            on = [s.get("attributes", {}).get("friendly_name") or s["entity_id"] for s in states
                  if s["entity_id"].startswith(("light.", "switch.")) and s.get("state") == "on"]
            opened = [s.get("attributes", {}).get("friendly_name") or s["entity_id"] for s in states
                      if s["entity_id"].startswith("binary_sensor.") and s.get("attributes", {}).get("device_class") in ("window", "door")
                      and s.get("state") == "on"]
            out.append(("!" if on else "✓", "Svítí / je zapnuté: " + ", ".join(on[:6]) if on else "Světla a zásuvky jsou vypnuté."))
            out.append(("!" if opened else "✓", "Otevřené: " + ", ".join(opened[:6]) if opened else "Okna a dveře jsou zavřené."))
        else:
            out.append(("?", "Světla, spotřebiče a okna nevidím (chytrá domácnost není připojená) – projdi je sám."))
    except Exception as e:  # noqa: BLE001
        out.append(("?", f"Chytrou domácnost se nepodařilo projít ({e})."))
    until = getattr(rt.cfg.booking, "passport_until", "") if getattr(rt.cfg, "booking", None) else ""
    out.append(("✓" if until and until > (dt.date.today() + dt.timedelta(days=180)).isoformat() else "?",
                f"Pas platí do {until}." if until else "Platnost pasu neznám (Nastavení → Cesty)."))
    out += [("!", "Automatická odpověď v e-mailu („jsem na dovolené do …“)."),
            ("!", "Pošta: úložní služba na poště nebo soused, ať schránka nepřetéká."),
            ("!", "Kytky: zalít, nebo domluvit zalévání."),
            ("!", "Topení na úsporný režim, bojler a lednice podle délky pobytu."),
            ("!", "Cestovní pojištění a kopie dokladů v telefonu.")]
    return out


# ------------------------------------------------------------------ (67) uzávěrka měsíce
MONTH_TOOLS = (("fakturoid_invoices", {}), ("idoklad_invoices", {}), ("subscriptions_overview", {"months": 2}),
               ("toggl_report", {}), ("cashflow_report", {}))


def last_day_of_month(day: dt.date) -> bool:
    return (day + dt.timedelta(days=1)).month != day.month


async def month_close(rt: Any) -> str:
    from . import tools

    parts = []
    for name, args in MONTH_TOOLS:
        if name not in tools.REGISTRY:
            continue
        try:
            r = await tools.call(name, args, rt)
        except Exception as e:  # noqa: BLE001
            log.debug("month close %s: %s", name, e)
            continue
        if r.ok and r.summary:
            parts.append(f"• {tools.REGISTRY[name].description.split('.')[0][:40]}: {r.summary.splitlines()[0][:220]}")
    try:
        from . import money

        ov = money.overview(rt)
        parts.append(f"• Peníze tento měsíc: {ov.get('summary') or ov.get('text') or ''}"[:260])
    except Exception:  # noqa: BLE001
        pass
    return "Uzávěrka měsíce:\n" + ("\n".join(parts) if parts else "Nemám napojené účetnictví ani výkazy – připoj Fakturoid, iDoklad nebo Toggl.")


# ------------------------------------------------------------------ (69) příprava na schůzku, (77) uvolněný čas
def upcoming_events(rt: Any, start: float, end: float) -> list[dict]:
    if not rt.db.one("SELECT name FROM sqlite_master WHERE name='cal_events'"):
        return []
    return [dict(r) for r in rt.db.all("SELECT id, title, start, end, location FROM cal_events WHERE start >= ? AND start <= ? ORDER BY start",
                                       (start, end))]


async def prep_due(rt: Any, now: float | None = None, minutes: int = 30) -> list[str]:
    now = now or time.time()
    out = []
    for e in upcoming_events(rt, now + (minutes - 5) * 60, now + (minutes + 5) * 60):
        if not once(rt, f"prep_{e['id']}", "1"):
            continue
        from . import tools

        r = await tools.call("meeting_prep", {"title": e["title"]}, rt) if "meeting_prep" in tools.REGISTRY else None
        when = dt.datetime.fromtimestamp(e["start"]).strftime("%H:%M")
        body = (r.summary[:600] if r is not None and r.ok else "Podklady jsem nenašel.")
        out.append(f"V {when} „{e['title']}“. {body}")
    return out


def freed_time(rt: Any, now: float | None = None) -> list[str]:
    """Meetings of the next 8 hours that disappeared from the calendar since the last look."""
    now = now or time.time()
    cur = {e["id"]: e for e in upcoming_events(rt, now, now + 8 * 3600)}
    row = rt.db.one("SELECT v FROM kv WHERE k='px_cal_seen'")
    before = json.loads(row["v"]) if row else {}
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_cal_seen', ?)", (json.dumps({k: [v["title"], v["start"], v["end"]] for k, v in cur.items()}),))
    out = []
    for eid, (title, start, end) in before.items():
        if eid not in cur and start > now:
            mins = int((end - start) // 60)
            tip = ""
            try:
                pin = rt.db.one("SELECT text FROM pinned ORDER BY created LIMIT 1")
                tip = f" Třeba: {pin['text']}." if pin else ""
            except Exception:  # noqa: BLE001
                pass
            out.append(f"„{title}“ v {dt.datetime.fromtimestamp(start):%H:%M} odpadla – máš {mins} min volna.{tip}")
    return out


# ------------------------------------------------------------------ (70) návrh týdne
async def week_plan(rt: Any, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    tasks: list[str] = []
    for q in ("SELECT text FROM pinned ORDER BY created", "SELECT item AS text FROM lists WHERE list IN ('úkoly', 'ukoly', 'todo') ORDER BY ts"):
        try:
            tasks += [r["text"] for r in rt.db.all(q)]
        except Exception:  # noqa: BLE001
            pass
    soon = [f"{r['title']} ({dt.date.fromisoformat(r['day']):%d. %m.})" for r in deadlines(rt)
            if (dt.date.fromisoformat(r["day"]) - today).days <= 9]
    slots: list[str] = []
    start = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)        # the coming Monday
    for i in range(5):
        d = start + dt.timedelta(days=i)
        day_s = dt.datetime.combine(d, dt.time(8)).timestamp()
        busy = [(e["start"], e["end"]) for e in upcoming_events(rt, day_s, day_s + 10 * 3600)]
        free = 10 * 60 - sum(int((b - a) // 60) for a, b in busy)
        slots.append(f"{['Po', 'Út', 'St', 'Čt', 'Pá'][i]} {d:%d. %m.}: {len(busy)} schůzek, volno ~{max(0, free) // 60} h")
    plan = []
    for i, t in enumerate(tasks[:10]):
        plan.append(f"{['Po', 'Út', 'St', 'Čt', 'Pá'][i % 5]}: {t}")
    s = "Návrh týdne:\n" + "\n".join(slots)
    if soon:
        s += "\nTermíny: " + ", ".join(soon)
    if plan:
        s += "\nÚkoly do volných chvil:\n" + "\n".join(plan)
    return s


# ------------------------------------------------------------------ (72) sezónní úkoly
SEASONAL = [("pneu_zima", "Přezout na zimní pneumatiky (od 1. 11. podle počasí povinné)", (10, 10), (11, 15)),
            ("pneu_leto", "Přezout na letní pneumatiky", (3, 25), (4, 30)),
            ("dane", "Daňové přiznání (papírově do 1. 4., elektronicky do 4. 5.)", (2, 15), (4, 1)),
            ("okapy", "Vyčistit okapy od listí", (11, 1), (11, 30)),
            ("kotel", "Servis kotle před topnou sezónou", (9, 1), (9, 30)),
            ("komin", "Kontrola komína (u kotle na tuhá paliva 3× ročně)", (9, 1), (10, 15)),
            ("klima", "Vyčistit klimatizaci a filtry", (5, 1), (5, 31)),
            ("voda_zahrada", "Vypustit venkovní vodu před mrazy", (10, 20), (11, 10)),
            ("hasicak", "Zkontrolovat hasicí přístroj a hlásiče kouře", (1, 10), (1, 31))]


def seasonal_due(rt: Any, today: dt.date | None = None) -> list[tuple[str, str]]:
    today = today or dt.date.today()
    out = []
    for key, title, (m1, d1), (m2, d2) in SEASONAL:
        if dt.date(today.year, m1, d1) <= today <= dt.date(today.year, m2, d2):
            st = db(rt).one("SELECT state FROM px_seasonal WHERE key=? AND year=?", (key, today.year))
            if not st:
                out.append((key, title))
    return out


def seasonal_mark(rt: Any, key: str, state: str = "done", year: int | None = None) -> None:
    db(rt).exec("INSERT OR REPLACE INTO px_seasonal VALUES (?,?,?)", (key, year or dt.date.today().year, state))


# ------------------------------------------------------------------ (73) ozvi se kamarádovi
def friend_add(rt: Any, name: str, every_days: int = 60) -> None:
    db(rt).exec("INSERT OR REPLACE INTO px_friends VALUES (?,?,COALESCE((SELECT last FROM px_friends WHERE name=?), ?))",
                (name.strip(), max(7, int(every_days)), name.strip(), time.time()))


def friend_contact(rt: Any, name: str, when: float | None = None) -> bool:
    n = fold(name)
    for r in db(rt).all("SELECT name FROM px_friends"):
        if fold(r["name"]).startswith(n[:4]) or n.startswith(fold(r["name"])[:4]):
            db(rt).exec("UPDATE px_friends SET last=? WHERE name=?", (when or time.time(), r["name"]))
            return True
    return False


def friends_overdue(rt: Any, now: float | None = None) -> list[str]:
    now = now or time.time()
    out = []
    for r in db(rt).all("SELECT * FROM px_friends"):
        days = int((now - (r["last"] or now)) // 86400)
        if days >= r["every_days"]:
            out.append(f"S {r['name']} jsi nemluvil {days} dní.")
    return out


CONTACTED = re.compile(r"^(?:mluvil|mluvila|volal|volala|psal|psala|byl|byla|videl|videla)\s+(?:jsem\s+)?(?:s|se)\s+"
                       r"(?P<name>[\wáčďéěíňóřšťúůýž]{3,})", re.I)


# ------------------------------------------------------------------ (74) pauza ve hře
def game_break(rt: Any, playing: bool, now: float | None = None, after_min: int = 120) -> str:
    now = now or time.time()
    since = getattr(rt, "px_game_since", None)
    if not playing:
        rt.px_game_since = None
        rt.px_game_told = 0
        return ""
    if since is None:
        rt.px_game_since = now
        return ""
    played = (now - since) / 60
    told = int(getattr(rt, "px_game_told", 0) or 0)
    nxt = after_min + 60 * told
    if played >= nxt:
        rt.px_game_told = told + 1
        h = int(played // 60)
        return f"Hraješ už {h} {'hodinu' if h == 1 else 'hodiny' if h < 5 else 'hodin'} – co takhle pět minut pauza, voda a protáhnout se?"
    return ""


# ------------------------------------------------------------------ (76) podmínky rutin
def conditions_ok(rt: Any, conds: list[str], at: dt.datetime | None = None) -> bool:
    """Every condition holds: "prší", "sněží", "jasno", "teplo>25", "zima<0", "víkend", "všední den", "svátek",
    "mezi 7:00-9:00". Unknown weather = the condition does not hold (no surprise routines)."""
    at = at or dt.datetime.now()
    hour = None
    for c in conds or []:
        f = fold(c).replace(" ", "")
        if f in ("vikend",):
            if at.weekday() < 5 and at.date() not in cz_holidays(at.year):
                return False
            continue
        if f in ("vsednıden", "vsedniden", "pracovniden"):
            if at.weekday() >= 5 or at.date() in cz_holidays(at.year):
                return False
            continue
        if f == "svatek":
            if at.date() not in cz_holidays(at.year):
                return False
            continue
        m = re.match(r"mezi(\d{1,2}):?(\d{2})?-(\d{1,2}):?(\d{2})?", f)
        if m:
            a = int(m.group(1)) * 60 + int(m.group(2) or 0)
            b = int(m.group(3)) * 60 + int(m.group(4) or 0)
            if not a <= at.hour * 60 + at.minute <= b:
                return False
            continue
        hour = hour if hour is not None else now_hour(rt, at)
        if not hour:
            return False
        code = hour.get("weather_code") or 0
        temp = hour.get("temperature_2m")
        if f in ("prsi", "dest", "deszt"):
            if code not in RAIN_CODES and (hour.get("precipitation_probability") or 0) < 60:
                return False
        elif f in ("snezi", "snih"):
            if code not in SNOW_CODES:
                return False
        elif f in ("jasno", "slunecno", "svitislunce"):
            if code > 2:
                return False
        elif (m2 := re.match(r"(teplo|tepl|teplota)?([<>])(-?\d+)", f.replace("zima", "teplota").replace("teplo", "teplota"))):
            if temp is None:
                return False
            v = int(m2.group(3))
            if (m2.group(2) == ">" and not temp > v) or (m2.group(2) == "<" and not temp < v):
                return False
        else:
            return False
    return True


def record_fire(rt: Any, aid: str) -> None:
    month = dt.date.today().strftime("%Y-%m")
    r = db(rt).one("SELECT * FROM auto_stats WHERE id=?", (aid,))
    if r is None:
        db(rt).exec("INSERT INTO auto_stats VALUES (?,?,?,?,?)", (aid, 1, time.time(), 1, month))
    else:
        mf = (r["month_fires"] + 1) if r["month"] == month else 1
        db(rt).exec("UPDATE auto_stats SET fires=fires+1, last=?, month_fires=?, month=? WHERE id=?", (time.time(), mf, month, aid))


# ------------------------------------------------------------------ (79) přehled rutin
def routines_report(rt: Any, now: float | None = None) -> dict:
    now = now or time.time()
    stats = {r["id"]: dict(r) for r in db(rt).all("SELECT * FROM auto_stats")}
    used, idle, off = [], [], []
    for a in rt.cfg.automations.items:
        s = stats.get(a.id)
        if not a.enabled:
            off.append(a.name)
        elif s and now - (s["last"] or 0) <= 30 * 86400:
            used.append(f"{a.name} ({s['fires']}×, naposledy {dt.date.fromtimestamp(s['last']):%d. %m.})")
        else:
            idle.append(a.name)
    return {"used": used, "idle": idle, "off": off}


# ------------------------------------------------------------------ (78) konec pracovního dne
async def end_of_day(rt: Any) -> str:
    from . import tools

    done = []
    if "workspace_save" in tools.REGISTRY:
        r = await tools.call("workspace_save", {"name": "Konec práce " + dt.date.today().strftime("%d. %m.")}, rt)
        if r.ok:
            done.append("rozložení oken uložené")
    closed = []
    for app in getattr(rt.cfg.day, "work_apps", []) or []:
        r = await tools.call("close_app", {"name": app}, rt)
        if r.ok:
            closed.append(app)
    if closed:
        done.append("zavřeno: " + ", ".join(closed))
    try:
        rt.attention.focus(0)
    except Exception:  # noqa: BLE001
        pass
    summ = ""
    if "day_summary" in tools.REGISTRY:
        r = await tools.call("day_summary", {}, rt)
        summ = r.summary.splitlines()[0][:240] if r.ok and r.summary else ""
    return "Konec práce. " + ("; ".join(done) + ". " if done else "") + summ


# ------------------------------------------------------------------ (80) víkendová předpověď
def weekend_forecast(rt: Any, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    d = weather(rt).get("daily") or {}
    sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
    rows = {t: (mx, mn, rp, code) for t, mx, mn, rp, code in zip(d.get("time", []), d.get("temperature_2m_max", []),
                                                                 d.get("temperature_2m_min", []), d.get("precipitation_probability_max", []),
                                                                 d.get("weather_code", []))}
    days = [(sat, "sobota"), (sat + dt.timedelta(days=1), "neděle")]
    have = [(n, rows[x.isoformat()]) for x, n in days if x.isoformat() in rows]
    if not have:
        return ""
    parts = [f"{n}: {mn:.0f}–{mx:.0f} °C, déšť {rp or 0} %" for n, (mx, mn, rp, _c) in have]
    best = min(have, key=lambda x: ((x[1][2] or 0), -(x[1][0] or 0)))
    tip = f" Na výlet vychází líp {best[0]}." if len(have) == 2 and (best[1][2] or 0) < 50 else \
        " Spíš počasí na kino, bazén nebo muzeum." if all((x[1][2] or 0) >= 60 for x in have) else ""
    return "Víkend: " + "; ".join(parts) + "." + tip


# ------------------------------------------------------------------ the loop
def _setting(rt: Any, name: str, default: Any) -> Any:
    return getattr(getattr(rt.cfg, "day", None), name, default)


async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    """One look (every minute): what is due now. Returns the titles of what was said (for tests)."""
    from . import memx
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    today = now.date()

    def tell(key: str, at: str, title: str, body: str, actions: list[dict] | None = None) -> None:
        if not body or not due_today(rt, f"px_{key}", at, now):
            return
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (f"px_{key}", today.isoformat()))
        rt.notify(title, body, speak=False, actions=actions)
        said.append(title)

    w = weather(rt)
    if (not w or time.time() - float(w.get("ts", 0)) > WEATHER_TTL) and not os.environ.get("JARVIS_NO_NET"):
        await refresh_weather(rt)
    if _setting(rt, "laundry", True):
        tell("laundry", "08:30", "Sušení prádla", laundry_window(rt, today))
    if _setting(rt, "deadlines", True):
        due = deadlines_due(rt, today)
        if due:
            rt.notify("Termíny", " ".join(due), speak=False)
            said.append("Termíny")
    if _setting(rt, "dates", True):
        memx.dates_from_facts(rt)
        lines = [memx.date_line(e, rt) for e in memx.upcoming_dates(rt, 7, today) if e["in_days"] in (0, 1, 7)]
        tell("dates", "08:00", "Výročí a narozeniny", " ".join(lines))
    if _setting(rt, "holidays", True):
        tell("holiday", "17:00", "Zítra je svátek", holiday_notice(today + dt.timedelta(days=1)))
    if _setting(rt, "seasonal", True) and today.weekday() == 5:
        due_s = seasonal_due(rt, today)
        tell("seasonal", "10:00", "Sezónní úkoly", "Je čas na: " + "; ".join(t for _, t in due_s) + "." if due_s else "")
    if _setting(rt, "friends", True) and today.weekday() == 4:
        tell("friends", "18:00", "Ozvi se", " ".join(friends_overdue(rt)))
    if _setting(rt, "weekend_forecast", True) and today.weekday() == 3:
        tell("weekend", "18:00", "Předpověď na víkend", weekend_forecast(rt, today))
    if _setting(rt, "month_close", True) and last_day_of_month(today) and due_today(rt, "px_month", "15:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_month', ?)", (today.isoformat(),))
        rt.notify("Uzávěrka měsíce", await month_close(rt), speak=False)
        said.append("Uzávěrka měsíce")
    if _setting(rt, "week_plan", True) and today.weekday() == 6 and due_today(rt, "px_week", "18:30", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_week', ?)", (today.isoformat(),))
        rt.notify("Návrh týdne", await week_plan(rt, today), speak=False)
        said.append("Návrh týdne")
    dtime = _setting(rt, "diary_time", "21:30")
    if dtime and due_today(rt, "px_diary", dtime, now) and not memx.diary(rt, today.isoformat()):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_diary', ?)", (today.isoformat(),))
        rt.memx_diary_asked = time.time()
        rt.notify("Deník", memx.DIARY_ASK, speak=False)
        said.append("Deník")
    if today.weekday() == 0:
        stale = memx.stale_facts(rt, now=now.timestamp(), limit=1)
        if stale:
            f = stale[0]
            tell("stale", "10:00", "Platí to ještě?", f"Pamatuju si: „{f['text']}“ – platí to pořád?",
                 actions=[{"label": "Platí", "action": "fact_confirm", "args": {"id": f["id"]}},
                          {"label": "Neplatí", "action": "fact_drop", "args": {"id": f["id"]}}])
    if today.month == 12 and today.day == 31 and due_today(rt, "px_year", "17:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_year', ?)", (today.isoformat(),))
        rt.notify(f"Rok {today.year} v kostce", await memx.year_story(rt, today.year), speak=False)
        said.append("Rok v kostce")
    end = _setting(rt, "workday_end", "")
    if end and day_kind(rt, today) == "work" and due_today(rt, "px_end", end, now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_end', ?)", (today.isoformat(),))
        rt.notify("Konec pracovního dne", await end_of_day(rt), speak=False)
        said.append("Konec pracovního dne")
    mins = int(_setting(rt, "meeting_prep_min", 30) or 0)
    if mins:
        for line in await prep_due(rt, now.timestamp(), mins):
            rt.notify("Za chvíli schůzka", line, speak=False)
            said.append("Za chvíli schůzka")
    for line in freed_time(rt, now.timestamp()):
        rt.notify("Volná chvíle", line, speak=False)
        said.append("Volná chvíle")
    try:
        playing = (rt.attention.reason() == "hra") if hasattr(rt.attention, "reason") else False
    except Exception:  # noqa: BLE001
        playing = False
    msg = game_break(rt, playing, now.timestamp(), int(_setting(rt, "game_break_min", 120) or 120))
    if msg:
        rt.notify("Pauza", msg, speak=False)
        said.append("Pauza")
    return said


async def loop(rt: Any) -> None:
    from . import lookx

    await asyncio.sleep(30)
    while True:
        try:
            await tick(rt)
        except Exception as e:  # noqa: BLE001
            log.warning("proactx tick: %s", e)
        try:
            await lookx.tick(rt)                       # 3.20 Vzhled+: countdown, timeline, weather, photo, wallpaper tasks
        except Exception as e:  # noqa: BLE001
            log.debug("lookx tick: %s", e)
        burst = getattr(rt, "_burst", None)
        if burst is not None and burst.due():          # 3.20 (119) the held notices as one line
            title, body = burst.summary()
            rt.notify(title, body, speak=False, kind="burst")
        await asyncio.sleep(60)
