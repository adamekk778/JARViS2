"""3.20 Rodina+ (nápady 381–400 ze stránky „Nápady pro JARVISe“) a jídelníček (247).

- rodinný kalendář s barvou pro každého (381), úkoly dětí za body (382), jídelníček na týden a nákupní seznam z něj (383, 247)
- recept krok za krokem hlasem s minutkami (384), lednice s datem spotřeby (385), zalévání podle druhu rostliny (386)
- mazlíček – krmení, očkování, veterinář (387), údržba domu (388), rozvrh a kroužky dětí (389), pohádka na dobrou noc (390)
- rodičovská pravidla bez špehování (391), úklidový plán (392), Wi-Fi pro hosty jako QR (393), kdo jde pro děti (394)
- rodinné dokumenty (395 – tresor z Bezpečnosti), narozeniny celé rodiny (396), karta pro hlídání (397)
- péče o starší rodiče (398), rodinná kronika (399), svoz odpadu (400)
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time
import unicodedata
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS fm_members (name TEXT PRIMARY KEY, color TEXT, kid INT DEFAULT 0, born TEXT);
CREATE TABLE IF NOT EXISTS fm_chores (id INTEGER PRIMARY KEY AUTOINCREMENT, kid TEXT, task TEXT, points INT, done REAL);
CREATE TABLE IF NOT EXISTS fm_fridge (item TEXT PRIMARY KEY, until TEXT, qty TEXT);
CREATE TABLE IF NOT EXISTS fm_plants (name TEXT PRIMARY KEY, species TEXT, every_days INT, last TEXT);
CREATE TABLE IF NOT EXISTS fm_care (id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT, kind TEXT, what TEXT, every_days INT, last TEXT,
  at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS fm_schedule (id INTEGER PRIMARY KEY AUTOINCREMENT, kid TEXT, weekday INT, start TEXT, what TEXT, driver TEXT);
CREATE TABLE IF NOT EXISTS fm_waste (bin TEXT PRIMARY KEY, weekday INT, every_weeks INT, parity INT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_familyx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._familyx_ready = True
    return rt.db


def _once(rt: Any, key: str) -> bool:
    if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
        return False
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
    return True


WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def weekday_of(word: str) -> int:
    f = fold(word)[:2]                       # po, ut, st, ct, pa, so, ne – the first two letters are unique
    for i, d in enumerate(WEEKDAYS):
        if fold(d)[:2] == f:
            return i
    raise ValueError("Den napiš jako pondělí, úterý…")


# ------------------------------------------------------------------ (381) rodinný kalendář
COLORS = ["#4fc3ff", "#ff9f0a", "#30d158", "#bf5af2", "#ff375f", "#ffd60a"]


def member_add(rt: Any, name: str, kid: bool = False, color: str = "", born: str = "") -> str:
    n = db(rt).one("SELECT COUNT(*) n FROM fm_members")["n"]
    color = color or COLORS[n % len(COLORS)]
    db(rt).exec("INSERT OR REPLACE INTO fm_members VALUES (?,?,?,?)", (name, color, int(kid), born))
    return color


def members(rt: Any) -> list[dict]:
    return [dict(r) for r in db(rt).all("SELECT * FROM fm_members ORDER BY name")]


def owner_of(title: str, people: list[dict]) -> dict | None:
    f = fold(title)
    return next((p for p in people if re.search(rf"\b{re.escape(fold(p['name']))}\w{{0,3}}\b", f)), None)


def week_html(rt: Any, start: dt.date) -> str:
    from .proactx import upcoming_events

    people = members(rt)
    a = dt.datetime.combine(start, dt.time()).timestamp()
    evs = upcoming_events(rt, a, a + 7 * 86400)
    cols = []
    for k in range(7):
        d = start + dt.timedelta(days=k)
        items = []
        for e in evs:
            if dt.date.fromtimestamp(float(e["start"])) == d:
                who = owner_of(e["title"], people)
                color = who["color"] if who else "#8e8e93"
                items.append(f"<li style='border-left:4px solid {color}'>{dt.datetime.fromtimestamp(float(e['start'])):%H:%M} "
                             f"{html.escape(str(e['title']))}</li>")
        for s in db(rt).all("SELECT * FROM fm_schedule WHERE weekday=? ORDER BY start", (d.weekday(),)):
            who = next((p for p in people if p["name"] == s["kid"]), None)
            items.append(f"<li style='border-left:4px solid {who['color'] if who else '#8e8e93'}'>{html.escape(s['start'])} "
                         f"{html.escape(s['kid'])}: {html.escape(s['what'])}" + (f" (veze {html.escape(s['driver'])})" if s["driver"] else "") + "</li>")
        cols.append(f"<section><h2>{WEEKDAYS[d.weekday()]} {d:%d. %m.}</h2><ul>{''.join(items) or '<li class=free>volno</li>'}</ul></section>")
    legend = " ".join(f"<span style='color:{p['color']}'>● {html.escape(p['name'])}</span>" for p in people)
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Rodinný kalendář</title>"
            "<style>body{font:14px system-ui;background:#0b0f14;color:#e8eef5;margin:16px}main{display:grid;grid-template-columns:"
            "repeat(auto-fill,minmax(160px,1fr));gap:10px}section{background:#121a23;border-radius:12px;padding:10px}h2{font-size:14px;"
            "margin:0 0 6px;text-transform:capitalize}ul{list-style:none;margin:0;padding:0}li{padding:4px 6px;margin:4px 0;background:#18222d;"
            "border-radius:6px}.free{color:#678}</style>" + f"<h1>Rodinný kalendář</h1><p>{legend}</p><main>{''.join(cols)}</main>")


# ------------------------------------------------------------------ (382) úkoly dětí
def chore_add(rt: Any, kid: str, task: str, points: int = 5) -> int:
    cur = db(rt).exec("INSERT INTO fm_chores (kid, task, points, done) VALUES (?,?,?,NULL)", (kid, task[:80], int(points)))
    return int(getattr(cur, "lastrowid", 0) or 0)


def chore_done(rt: Any, kid: str, task: str) -> dict:
    f = fold(task)
    row = next((r for r in db(rt).all("SELECT * FROM fm_chores WHERE kid=? AND done IS NULL", (kid,)) if f in fold(r["task"])), None)
    if not row:
        raise ValueError(f"{kid} takový úkol nemá.")
    db(rt).exec("UPDATE fm_chores SET done=? WHERE id=?", (time.time(), row["id"]))
    return {"points": points(rt, kid), "task": row["task"]}


def points(rt: Any, kid: str) -> int:
    return int(db(rt).one("SELECT COALESCE(SUM(points),0) s FROM fm_chores WHERE kid=? AND done IS NOT NULL", (kid,))["s"])


# ------------------------------------------------------------------ (383, 247) jídelníček
def menu_prompt(people: int, likes: str = "", avoid: str = "", have: list[str] | None = None, budget: str = "") -> str:
    return ("Navrhni jídelníček na 7 dní (oběd a večeře) pro " + f"{people} lidi" +
            (f", rádi jí: {likes}" if likes else "") + (f", nejí: {avoid}" if avoid else "") +
            (f". Doma už je: {', '.join(have)} – využij to přednostně" if have else "") + (f". Rozpočet: {budget}" if budget else "") +
            ". Jídla obyčejná česká i lehká, opakuj zbytky chytře. Odpověz JEN JSON: {\"days\": [{\"day\": \"pondělí\", \"lunch\": …, "
            "\"dinner\": …}], \"shopping\": [\"položka s množstvím\", …]}.")


def parse_menu(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Jídelníček nepřišel ve správném tvaru.")
    data = json.loads(m.group(0))
    days = [d for d in data.get("days") or [] if isinstance(d, dict)][:7]
    shop = [str(x)[:60] for x in data.get("shopping") or []][:60]
    return {"days": days, "shopping": shop}


# ------------------------------------------------------------------ (384) recept krok za krokem
def recipe_steps(text: str) -> list[dict]:
    """A recipe's method → steps, each with a timer when it says how long ("vař 10 minut")."""
    body = text.split("Postup", 1)[-1] if "Postup" in text else text
    raw = [s.strip(" -•\t") for s in re.split(r"\n+|(?<=\.)\s+(?=\d+[.)]\s)", body) if s.strip()]
    steps = []
    for s in raw:
        s = re.sub(r"^\d+[.)]\s*", "", s)
        if len(s) < 4:
            continue
        m = re.search(r"(\d+)\s*(?:–|-|až)?\s*(\d+)?\s*(min|minut|hod|hodin)", fold(s))
        secs = 0
        if m:
            n = int(m.group(2) or m.group(1))
            secs = n * 3600 if m.group(3).startswith("hod") else n * 60
        steps.append({"text": s, "timer": secs})
    return steps


class Recipe:
    def __init__(self, steps: list[dict]):
        self.steps, self.i = steps, -1

    def next(self) -> dict | None:
        if self.i + 1 >= len(self.steps):
            return None
        self.i += 1
        return {**self.steps[self.i], "n": self.i + 1, "of": len(self.steps)}

    def repeat(self) -> dict | None:
        return {**self.steps[self.i], "n": self.i + 1, "of": len(self.steps)} if self.i >= 0 else None

    def back(self) -> dict | None:
        self.i = max(-1, self.i - 2)
        return self.next()


# ------------------------------------------------------------------ (385) lednice
def fridge_add(rt: Any, item: str, until: str, qty: str = "") -> None:
    dt.date.fromisoformat(until)
    db(rt).exec("INSERT OR REPLACE INTO fm_fridge VALUES (?,?,?)", (item[:60], until, qty[:20]))


def fridge(rt: Any, today: dt.date) -> dict:
    rows = [dict(r) for r in db(rt).all("SELECT * FROM fm_fridge ORDER BY until")]
    soon = [r["item"] for r in rows if 0 <= (dt.date.fromisoformat(r["until"]) - today).days <= 1]
    gone = [r["item"] for r in rows if dt.date.fromisoformat(r["until"]) < today]
    return {"items": rows, "soon": soon, "expired": gone}


def fridge_remove(rt: Any, item: str) -> bool:
    f = fold(item)
    row = next((r for r in db(rt).all("SELECT item FROM fm_fridge") if f in fold(r["item"])), None)
    if row:
        db(rt).exec("DELETE FROM fm_fridge WHERE item=?", (row["item"],))
    return bool(row)


# ------------------------------------------------------------------ (386) rostliny, (387) mazlíček, (388) dům, (398) rodiče
SPECIES = {"kaktus": 21, "sukulent": 14, "monstera": 7, "fikus": 7, "orchidej": 8, "bazalka": 2, "zamiokulkas": 14, "tchynin jazyk": 21,
           "potos": 7, "spathiphyllum": 5, "aloe": 14, "rajce": 1, "bylinky": 3, "palma": 7}


def plant_add(rt: Any, name: str, species: str = "", every_days: int = 0, last: str = "") -> int:
    days = every_days or next((v for k, v in SPECIES.items() if k in fold(species or name)), 7)
    db(rt).exec("INSERT OR REPLACE INTO fm_plants VALUES (?,?,?,?)", (name, species, int(days), last or dt.date.today().isoformat()))
    return int(days)


def plants_due(rt: Any, today: dt.date) -> list[str]:
    out = []
    for r in db(rt).all("SELECT * FROM fm_plants"):
        if (today - dt.date.fromisoformat(r["last"])).days >= int(r["every_days"]):
            out.append(r["name"])
    return out


def plant_watered(rt: Any, name: str, today: dt.date | None = None) -> bool:
    f = fold(name)
    hit = [r["name"] for r in db(rt).all("SELECT name FROM fm_plants") if f in fold(r["name"]) or f in ("vse", "vsechny")]
    for n in hit:
        db(rt).exec("UPDATE fm_plants SET last=? WHERE name=?", ((today or dt.date.today()).isoformat(), n))
    return bool(hit)


HOUSE_TASKS = [("Filtr digestoře", 90), ("Odvápnění kávovaru a konvice", 30), ("Test detektorů kouře", 30), ("Filtr klimatizace", 180),
               ("Revize kotle", 365), ("Kontrola spalinové cesty (komín)", 365), ("Čištění odpadů", 60), ("Těsnění lednice a odmrazení", 180)]


def care_add(rt: Any, who: str, kind: str, what: str, every_days: int, last: str = "", at: str = "") -> int:
    cur = db(rt).exec("INSERT INTO fm_care (who, kind, what, every_days, last, at) VALUES (?,?,?,?,?,?)",
                      (who[:40], kind[:20], what[:80], int(every_days), last or dt.date.today().isoformat(), at))
    return int(getattr(cur, "lastrowid", 0) or 0)


def house_defaults(rt: Any) -> int:
    n = 0
    for what, days in HOUSE_TASKS:
        if not db(rt).one("SELECT id FROM fm_care WHERE kind='dum' AND what=?", (what,)):
            care_add(rt, "dům", "dum", what, days)
            n += 1
    return n


def care_due(rt: Any, today: dt.date, clock: str = "") -> list[dict]:
    """Pets (feeding at a time, vaccinations), the house (filters, chimney), parents (a call, a doctor) – what is due."""
    out = []
    for r in db(rt).all("SELECT * FROM fm_care"):
        if r["at"]:
            if clock and clock == r["at"]:
                out.append({"id": r["id"], "text": f"{r['who']}: {r['what']} ({r['at']})."})
            continue
        left = (dt.date.fromisoformat(r["last"]) + dt.timedelta(days=int(r["every_days"])) - today).days
        if left <= 0:
            out.append({"id": r["id"], "text": f"{r['who']}: {r['what']} – {'dnes' if left == 0 else f'už {-left} dní po termínu'}."})
    return out


def care_done(rt: Any, cid: int, today: dt.date | None = None) -> bool:
    had = db(rt).one("SELECT id FROM fm_care WHERE id=?", (int(cid),))
    db(rt).exec("UPDATE fm_care SET last=? WHERE id=?", ((today or dt.date.today()).isoformat(), int(cid)))
    return bool(had)


def parent_status(rt: Any, who: str, today: dt.date) -> list[str]:
    """(398) one place for a parent: their medicines (Zdraví+), due checks, and when you last called."""
    lines = []
    try:
        from .healthx import db as hdb

        meds = [r["name"] for r in hdb(rt).all("SELECT name FROM hl_meds WHERE person=?", (who,))]
        if meds:
            lines.append("Léky: " + ", ".join(meds))
    except Exception:  # noqa: BLE001
        pass
    for r in db(rt).all("SELECT * FROM fm_care WHERE who=?", (who,)):
        nxt = dt.date.fromisoformat(r["last"]) + dt.timedelta(days=int(r["every_days"]))
        lines.append(f"{r['what']}: příště {nxt:%d. %m.}")
    return lines or [f"Pro {who} zatím nic nesleduji – přidej léky, lékaře nebo „zavolat každý týden“."]


# ------------------------------------------------------------------ (389, 394) rozvrh a vyzvedávání
def schedule_add(rt: Any, kid: str, weekday: int, start: str, what: str, driver: str = "") -> int:
    if not re.fullmatch(r"\d{1,2}:\d{2}", start):
        raise ValueError("Čas napiš jako 15:30.")
    cur = db(rt).exec("INSERT INTO fm_schedule (kid, weekday, start, what, driver) VALUES (?,?,?,?,?)", (kid, int(weekday), start, what[:60], driver[:30]))
    return int(getattr(cur, "lastrowid", 0) or 0)


def pickups(rt: Any, clock: dt.datetime, before_min: int = 30) -> list[dict]:
    out = []
    for r in db(rt).all("SELECT * FROM fm_schedule WHERE weekday=?", (clock.weekday(),)):
        h, m = (int(x) for x in r["start"].split(":"))
        at = clock.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (at - clock).total_seconds() / 60 <= before_min and r["driver"] and _once(rt, f"fm_pick:{r['id']}:{clock:%Y-%m-%d}"):
            out.append({"driver": r["driver"], "text": f"{r['driver']}: v {r['start']} {r['kid']} – {r['what']}."})
    return out


# ------------------------------------------------------------------ (390) pohádka, (391) pravidla, (392) úklid, (393) Wi-Fi
def story_prompt(name: str, age: int, wishes: str = "", minutes: int = 5) -> str:
    words = max(200, minutes * 130)
    return (f"Napiš originální pohádku na dobrou noc pro {name} ({age} let), asi {words} slov, česky. " +
            (f"Přání: {wishes}. " if wishes else "") +
            "Laskavá, bez strašidelných scén a násilí, s jednoduchým ponaučením, krátké věty k předčítání, klidný konec, který "
            "uspává. Nepoužívej postavy ze známých filmů a knih – vymysli vlastní.")


def kid_rules_text(rules: dict) -> str:
    """The rules said openly to the child (no spying: nothing is recorded, only the times are kept)."""
    parts = []
    if rules.get("school_from"):
        parts.append(f"ve všední dny hry až od {rules['school_from']}")
    if rules.get("bed"):
        parts.append(f"obrazovky do {rules['bed']}")
    if rules.get("daily_min"):
        parts.append(f"hry nejvýš {rules['daily_min']} minut denně")
    return ("Pravidla: " + ", ".join(parts) + ". JARVIS nic nenahrává ani nečte – jen hlídá čas a řekne, kolik zbývá.") if parts else ""


def kid_allowed(rules: dict, clock: dt.datetime, used_min: int) -> tuple[bool, str]:
    if rules.get("bed") and clock.strftime("%H:%M") >= rules["bed"]:
        return False, f"Je po {rules['bed']} – obrazovky jdou spát."
    if rules.get("school_from") and clock.weekday() < 5 and clock.strftime("%H:%M") < rules["school_from"]:
        return False, f"Ve všední dny až od {rules['school_from']}."
    if rules.get("daily_min") and used_min >= int(rules["daily_min"]):
        return False, "Dnešní čas na hry je vyčerpaný."
    return True, ""


def chores_rotation(people: list[str], chores: list[str], week: int) -> dict[str, list[str]]:
    """A fair weekly rotation: every week each person moves one chore further."""
    if not people:
        return {}
    plan: dict[str, list[str]] = {p: [] for p in people}
    for i, c in enumerate(chores):
        plan[people[(i + week) % len(people)]].append(c)
    return plan


def wifi_qr_text(ssid: str, password: str, security: str = "WPA") -> str:
    def esc(s: str) -> str:
        return re.sub(r'([\\;,:"])', r"\\\1", s)

    return f"WIFI:T:{security};S:{esc(ssid)};P:{esc(password)};;" if password else f"WIFI:T:nopass;S:{esc(ssid)};;"


# ------------------------------------------------------------------ (397) karta pro hlídání, (399) kronika
def babysitter_html(kids: list[dict], contacts: list[str], rules: list[str], schedule: list[str]) -> str:
    esc = html.escape
    kid_rows = "".join(f"<li><b>{esc(k['name'])}</b> ({esc(str(k.get('age', '')))} let)" +
                       (f" – alergie: <b class=w>{esc(k['allergies'])}</b>" if k.get("allergies") else "") +
                       (f"; léky: {esc(k['meds'])}" if k.get("meds") else "") + "</li>" for k in kids)
    return ("<!doctype html><meta charset=utf-8><title>Karta pro hlídání</title><style>body{font:16px system-ui;max-width:720px;margin:24px auto}"
            "h1{font-size:26px}.w{color:#c00}section{border:2px solid #ddd;border-radius:12px;padding:12px 16px;margin:10px 0}"
            "@media print{section{break-inside:avoid}}</style><h1>Karta pro hlídání</h1>"
            f"<section><h2>Děti</h2><ul>{kid_rows}</ul></section>"
            f"<section><h2>Rozvrh</h2><ul>{''.join(f'<li>{esc(s)}</li>' for s in schedule)}</ul></section>"
            f"<section><h2>Pravidla</h2><ul>{''.join(f'<li>{esc(r)}</li>' for r in rules)}</ul></section>"
            f"<section><h2>Kontakty</h2><ul>{''.join(f'<li>{esc(c)}</li>' for c in contacts)}</ul>"
            "<p><b>Záchranka 155 · Hasiči 150 · Policie 158 · Tísňová linka 112</b></p></section>")


def chronicle_html(family: str, years: dict[int, list[dict]]) -> str:
    esc = html.escape
    body = ""
    for y in sorted(years):
        items = "".join(f"<li><b>{esc(e.get('date', ''))}</b> {esc(e.get('text', ''))}</li>" for e in years[y])
        pics = "".join(f"<img src='{esc(p)}' alt=''>" for e in years[y] for p in e.get("photos", [])[:2])[:4000]
        body += f"<section><h2>{y}</h2><ul>{items}</ul><div class=g>{pics}</div></section>"
    return ("<!doctype html><meta charset=utf-8><title>Kronika</title><style>body{font:17px Georgia,serif;max-width:860px;margin:auto;padding:24px}"
            ".g{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.g img{width:100%;border-radius:6px}</style>"
            f"<h1>Kronika rodiny {esc(family)}</h1>{body}")


# ------------------------------------------------------------------ (400) svoz odpadu
BINS = {"smesny": "Směsný odpad (černá)", "papir": "Papír (modrá)", "plast": "Plast (žlutá)", "bio": "Bioodpad (hnědá)", "sklo": "Sklo (zelená)"}


def waste_set(rt: Any, bin_: str, weekday: int, every_weeks: int = 1, parity: int = 0) -> None:
    db(rt).exec("INSERT OR REPLACE INTO fm_waste VALUES (?,?,?,?)", (bin_, int(weekday), max(1, int(every_weeks)), int(parity)))


def collected_on(row: dict, day: dt.date) -> bool:
    if day.weekday() != int(row["weekday"]):
        return False
    return day.isocalendar()[1] % int(row["every_weeks"]) == int(row["parity"]) % int(row["every_weeks"])


def waste_tomorrow(rt: Any, today: dt.date) -> list[str]:
    tomorrow = today + dt.timedelta(days=1)
    return [BINS.get(r["bin"], r["bin"]) for r in db(rt).all("SELECT * FROM fm_waste") if collected_on(dict(r), tomorrow)]


# ------------------------------------------------------------------ the minute look
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now()
    said: list[str] = []
    for p in pickups(rt, now):
        said.append(p["text"])
        rt.notify("Vyzvedávání", p["text"], speak=False)
        if fold(p["driver"]) in ("ja", "já", fold(str(getattr(rt.cfg.general, "user_name", "") or "").split(" ")[0])):
            rt.phone_push("notify", title="Vyzvedávání", body=p["text"])
    for c in care_due(rt, now.date(), now.strftime("%H:%M")):
        if "(" in c["text"] and _once(rt, f"fm_care:{c['id']}:{now:%Y-%m-%d %H:%M}"):
            said.append(c["text"])
            rt.notify("Péče", c["text"], speak=False)
    from .proactiveplus import due_today

    if due_today(rt, "fm_evening", "19:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("fm_evening", now.date().isoformat()))
        bins = waste_tomorrow(rt, now.date())
        if bins:
            t = "Zítra se vyváží: " + ", ".join(bins) + " – vystav popelnici."
            said.append(t)
            rt.notify("Svoz odpadu", t, speak=False)
        f = fridge(rt, now.date())
        if f["soon"]:
            t = "V lednici brzy projde: " + ", ".join(f["soon"]) + "."
            said.append(t)
            rt.notify("Lednice", t, speak=False)
    if due_today(rt, "fm_morning", "08:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("fm_morning", now.date().isoformat()))
        pl = plants_due(rt, now.date())
        if pl:
            t = "Zalij: " + ", ".join(pl) + "."
            said.append(t)
            rt.notify("Rostliny", t, speak=False)
        for c in care_due(rt, now.date()):
            if "(" not in c["text"] and _once(rt, f"fm_care:{c['id']}:{now:%Y-%m-%d}"):
                said.append(c["text"])
                rt.notify("Péče", c["text"], speak=False)
    return said

