"""3.20 Paměť+ (nápady 41–60 ze stránky „Nápady pro JARVISe“).

- osobní wiki: co o tobě JARVIS ví jako stránky po oblastech, každá věta upravitelná (41)
- zapomeň i ze záloh: fakt zmizí z paměti, z kopií databáze v zálohách a po obnovení zálohy se nevrátí (42)
- přání blízkých → tipy na dárky (43), časová osa života (44), původ každé vzpomínky (45)
- výročí a jubilea (46), kam jsem to dal (47), doporučení od lidí (48), vzpomínka s fotkou (49)
- fakta starší než rok: „platí to ještě?“ (50), sdílená rodinná paměť (51), rok v kostce (52), deník (53)
- fotky s pamětí: datum, místo z GPS, lidé – hledání slovy (54), oblíbené odpovědi (55)
- dočasné vzpomínky „do pátku“ (56), citlivé údaje v paměti (57), sdílení vzpomínky (58)
- soukromé vzpomínky pod PINem (59), paměť přes víc PC šifrovaně (60)
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import logging
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_wishes (id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, item TEXT, ts REAL, source TEXT, done INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS mem_places (item TEXT PRIMARY KEY, place TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS mem_recs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, by TEXT, ts REAL, done INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS mem_dates (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, month INT, day INT, year INT, kind TEXT,
  person TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS mem_diary (day TEXT PRIMARY KEY, text TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS mem_favs (msg_id TEXT PRIMARY KEY, text TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS mem_tombstones (h TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS mem_photos (path TEXT PRIMARY KEY, taken REAL, lat REAL, lon REAL, place TEXT, people TEXT, words TEXT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_memx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            cols = {r[1] for r in rt.db.conn.execute("PRAGMA table_info(facts)")}
            for col, typ in (("source", "TEXT DEFAULT ''"), ("category", "TEXT DEFAULT ''"), ("project", "TEXT DEFAULT ''"),
                             ("expires", "REAL"), ("shared", "INT DEFAULT 0"), ("locked", "INT DEFAULT 0"), ("confirmed", "REAL")):
                if col not in cols:
                    rt.db.conn.execute(f"ALTER TABLE facts ADD COLUMN {col} {typ}")
            rt.db.conn.commit()
        rt._memx_ready = True
    return rt.db


def _add_fact(rt: Any, text: str, source: str = "") -> int:
    know = getattr(rt, "knowledge", None)
    if know is not None:
        r = know.add_fact(text, source=source)
        if r.get("id"):
            return int(r["id"])
    cur = db(rt).exec("INSERT INTO facts(text, created, source) VALUES (?,?,?)", (text, time.time(), source[:200]))
    return int(cur.lastrowid)


# ------------------------------------------------------------------ (41) osobní wiki
def wiki_pages(rt: Any) -> dict[str, list[dict]]:
    from .knowledge import category

    pages: dict[str, list[dict]] = {}
    for f in db(rt).all("SELECT id, text, created, source, category, locked FROM facts ORDER BY id"):
        if f["locked"] and not unlocked(rt):
            continue
        pages.setdefault(f["category"] or category(f["text"]), []).append(dict(f))
    return pages


def wiki_html(rt: Any) -> str:
    pages = wiki_pages(rt)
    nav = "".join(f'<a href="#{html.escape(k)}">{html.escape(k)} ({len(v)})</a>' for k, v in sorted(pages.items()))
    secs = []
    for k, items in sorted(pages.items()):
        rows = "".join(f'<li><span>{html.escape(i["text"])}</span><small>#{i["id"]} · {dt.date.fromtimestamp(i["created"]):%d. %m. %Y}'
                       f'{" · " + html.escape(i["source"]) if i["source"] else ""}</small></li>' for i in items)
        secs.append(f'<section id="{html.escape(k)}"><h2>{html.escape(k)}</h2><ul>{rows}</ul></section>')
    return ("<!doctype html><meta charset=utf-8><title>Co o mně JARVIS ví</title>"
            "<style>body{font:15px system-ui;max-width:860px;margin:auto;padding:16px;color:#1b1f27;background:#f7f8fa}"
            "nav a{margin-right:10px}li{margin:6px 0;list-style:none;padding:8px 10px;background:#fff;border-radius:8px}"
            "small{display:block;color:#6b7280}@media(prefers-color-scheme:dark){body{background:#12151b;color:#e6e8ec}"
            "li{background:#1b1f27}small{color:#9aa3b2}}</style>"
            f"<h1>Co o mně JARVIS ví</h1><p>Opravíš řeknutím „oprav fakt #12 na …“ nebo „zapomeň #12“.</p><nav>{nav}</nav>{''.join(secs)}")


def write_wiki(rt: Any) -> Path:
    from .pcreport import reports_dir

    p = reports_dir().parent / "Paměť" / "co-o-mne-vi.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(wiki_html(rt), encoding="utf-8")
    return p


def edit_fact(rt: Any, fid: int, text: str) -> bool:
    return db(rt).exec("UPDATE facts SET text=?, confirmed=? WHERE id=?", (text.strip(), time.time(), int(fid))).rowcount > 0


# ------------------------------------------------------------------ (42) zapomeň i ze záloh
def _h(text: str) -> str:
    return hashlib.sha256(fold(text).encode()).hexdigest()


def backup_dbs(rt: Any) -> list[Path]:
    """Copies of JARVIS's database inside your backups (the destinations of the automatic backups)."""
    out: list[Path] = []
    try:
        jobs = [j for j in rt.scheduler.list() if j and j.get("kind") == "backup"]
    except Exception:  # noqa: BLE001
        jobs = []
    for j in jobs:
        dest = Path(str((j.get("payload") or {}).get("destination") or ""))
        if dest.is_dir():
            out += [p for p in dest.rglob("jarvis*.db") if p.is_file()][:50]
    return out


def forget_everywhere(rt: Any, needle: str) -> dict:
    """Delete the facts with these words here, in the database copies in your backups, and remember a tombstone so a
    restored older backup does not bring them back."""
    n = fold(needle)
    if len(n) < 3:
        raise ValueError("Napiš aspoň pár slov, co mám zapomenout.")
    hits = [f for f in db(rt).all("SELECT id, text FROM facts") if n in fold(f["text"]) or str(f["id"]) == needle.strip("# ")]
    for f in hits:
        db(rt).exec("DELETE FROM facts WHERE id=?", (f["id"],))
        db(rt).exec("INSERT OR REPLACE INTO mem_tombstones VALUES (?,?)", (_h(f["text"]), time.time()))
    cleaned = 0
    for p in backup_dbs(rt):
        try:
            con = sqlite3.connect(str(p))
            for f in hits:
                cleaned += con.execute("DELETE FROM facts WHERE text=?", (f["text"],)).rowcount
            con.commit()
            con.close()
        except sqlite3.Error as e:
            log.info("backup %s: %s", p, e)
    return {"deleted": [f["text"] for f in hits], "in_backups": cleaned}


def apply_tombstones(rt: Any) -> int:
    """After a backup was restored: what you asked to forget is gone again."""
    dead = {r["h"] for r in db(rt).all("SELECT h FROM mem_tombstones")}
    if not dead:
        return 0
    n = 0
    for f in db(rt).all("SELECT id, text FROM facts"):
        if _h(f["text"]) in dead:
            db(rt).exec("DELETE FROM facts WHERE id=?", (f["id"],))
            n += 1
    return n


# ------------------------------------------------------------------ (43) přání blízkých
WISH = re.compile(r"^(?P<who>[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+)\s+(by\s+)?(chtěl[a]?|chce|si\s+přeje|by\s+se\s+hodil[aoy]?|se\s+líbil[aoy]?|"
                  r"sní\s+o|touží\s+po|potřebuje)\s+(?P<item>.{3,80}?)[.!]?$", re.I)


def detect_wish(text: str) -> tuple[str, str] | None:
    m = WISH.match((text or "").strip())
    if not m or fold(m.group("who")) in ("jarvis", "jarvisi", "ja", "on", "ona", "to", "kdo", "co"):
        return None
    item = re.sub(r"^(by |si |mu |jí |ji )", "", m.group("item").strip(), flags=re.I)
    return m.group("who"), item


def add_wish(rt: Any, person: str, item: str, source: str = "") -> int:
    cur = db(rt).exec("INSERT INTO mem_wishes(person, item, ts, source) VALUES (?,?,?,?)", (person.strip(), item.strip(), time.time(), source))
    return int(cur.lastrowid)


def wishes(rt: Any, person: str = "") -> list[dict]:
    rows = db(rt).all("SELECT * FROM mem_wishes WHERE done=0 ORDER BY ts DESC")
    p = fold(person)[:4]
    return [dict(r) for r in rows if not p or fold(r["person"]).startswith(p)]


# ------------------------------------------------------------------ (44) časová osa života
def timeline(rt: Any, year: int | None = None) -> list[dict]:
    """Facts with a date in them, trips, diary days, notes – by month."""
    ev: list[dict] = []
    for f in db(rt).all("SELECT text, created FROM facts"):
        m = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b", f["text"])
        if m:
            try:
                d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                ev.append({"date": d.isoformat(), "kind": "fakt", "text": f["text"]})
            except ValueError:
                pass
    try:
        for b in rt.db.all("SELECT name, city, start FROM bookings"):
            ev.append({"date": str(b["start"])[:10], "kind": "cesta", "text": f"{b['name']}, {b['city']}"})
    except sqlite3.Error:
        pass
    for d in db(rt).all("SELECT day, text FROM mem_diary"):
        ev.append({"date": d["day"], "kind": "deník", "text": d["text"][:160]})
    for p in db(rt).all("SELECT taken, place FROM mem_photos WHERE taken IS NOT NULL"):
        ev.append({"date": dt.date.fromtimestamp(p["taken"]).isoformat(), "kind": "fotky", "text": p["place"] or "fotka"})
    if year:
        ev = [e for e in ev if e["date"].startswith(str(year))]
    ev.sort(key=lambda e: e["date"])
    photos: dict[str, dict] = {}
    out = []
    for e in ev:                                   # photos of one day as one line
        if e["kind"] == "fotky":
            k = e["date"]
            if k in photos:
                photos[k]["n"] += 1
                continue
            photos[k] = {**e, "n": 1}
            out.append(photos[k])
        else:
            out.append(e)
    for e in out:
        if e["kind"] == "fotky":
            e["text"] = f"{e.pop('n')} fotek" + (f" – {e['text']}" if e["text"] != "fotka" else "")
    return out


# ------------------------------------------------------------------ (45) původ
def origin(rt: Any, query: str) -> list[dict]:
    """Where a remembered fact came from: the conversation (and the words said then), or a file / photo."""
    q = fold(query)
    out = []
    for f in db(rt).all("SELECT id, text, created, source FROM facts"):
        if q and q not in fold(f["text"]) and str(f["id"]) != query.strip("# "):
            continue
        said = rt.db.one("SELECT content, created FROM messages WHERE role='user' AND created BETWEEN ? AND ? ORDER BY ABS(created-?) LIMIT 1",
                         (f["created"] - 300, f["created"] + 60, f["created"]))
        out.append({"id": f["id"], "text": f["text"], "when": dt.datetime.fromtimestamp(f["created"]).strftime("%d. %m. %Y %H:%M"),
                    "source": f["source"] or ("rozhovor" if said else "neznámý"), "said": (said["content"][:200] if said else "")})
    return out[:10]


# ------------------------------------------------------------------ (46) výročí, (71) narozeniny
DATE_FACT = re.compile(r"(?P<what>.{3,60}?)\s*(?:je|bylo|byl|byla|mám|máme|slavíme|má)?\s*(?:dne\s+|od\s+)?"
                       r"(?P<d>\d{1,2})\.\s?(?P<m>\d{1,2})\.(?:\s?(?P<y>\d{4}))?", re.I)


def add_date(rt: Any, title: str, day: int, month: int, year: int | None = None, kind: str = "výročí", person: str = "") -> int:
    dt.date(2000, month, day)                     # raises on 31. 2.
    cur = db(rt).exec("INSERT INTO mem_dates(title, month, day, year, kind, person) VALUES (?,?,?,?,?,?)",
                      (title.strip(), month, day, year, kind, person))
    return int(cur.lastrowid)


def dates_from_facts(rt: Any) -> int:
    """Birthdays and anniversaries found in what JARVIS remembers ("Jana má narozeniny 3. 5.", "svatba 12. 6. 2015")."""
    have = {(r["title"], r["month"], r["day"]) for r in db(rt).all("SELECT title, month, day FROM mem_dates")}
    n = 0
    for f in db(rt).all("SELECT text FROM facts"):
        t = f["text"]
        if not re.search(r"narozenin|vyroc|svatb|jubile|nastoupil|v praci od|seznamili|zasnub", fold(t)):
            continue
        m = DATE_FACT.search(t)
        if not m:
            continue
        kind = "narozeniny" if "narozenin" in fold(t) else "výročí"
        person = ""
        pm = re.match(r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+)", t)
        if kind == "narozeniny" and pm:
            person = pm.group(1)
        title = re.sub(r"\s+", " ", m.group("what")).strip(" ,:-") or t[:40]
        key = (title, int(m.group("m")), int(m.group("d")))
        if key in have:
            continue
        try:
            add_date(rt, title, int(m.group("d")), int(m.group("m")), int(m.group("y")) if m.group("y") else None, kind, person)
            n += 1
        except ValueError:
            continue
    return n


def upcoming_dates(rt: Any, days: int = 7, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    out = []
    for r in db(rt).all("SELECT * FROM mem_dates"):
        try:
            d = dt.date(today.year, r["month"], r["day"])
        except ValueError:
            continue
        if d < today:
            d = d.replace(year=today.year + 1)
        left = (d - today).days
        if left <= days:
            years = d.year - r["year"] if r["year"] else None
            out.append({**dict(r), "date": d.isoformat(), "in_days": left, "years": years})
    return sorted(out, key=lambda x: x["in_days"])


def date_line(e: dict, rt: Any) -> str:
    when = "dnes" if e["in_days"] == 0 else "zítra" if e["in_days"] == 1 else f"za {e['in_days']} dní"
    yrs = f" ({e['years']}.)" if e.get("years") else ""
    line = f"{when.capitalize()}: {e['title']}{yrs}."
    if e["kind"] == "narozeniny" and e.get("person"):
        w = wishes(rt, e["person"])
        if w:
            line += f" Tip na dárek – {e['person']} chtěl(a): " + ", ".join(x["item"] for x in w[:3]) + "."
    return line


# ------------------------------------------------------------------ (47) kam jsem to dal
PUT = re.compile(r"^(?P<item>.{2,60}?)\s+(?:jsou|je|leží|leží|mám|dal jsem|dala jsem|schoval jsem|uložil jsem)\s+(?P<place>(?:v|ve|na|pod|za|u|do|mezi)\s.{2,80}?)[.!]?$", re.I)
PUT2 = re.compile(r"^(?:dal jsem|dala jsem|schoval jsem|schovala jsem|uložil jsem|uložila jsem)\s+(?P<item>.{2,60}?)\s+(?P<place>(?:do|na|pod|za|k|ke|v|ve)\s.{2,80}?)[.!]?$", re.I)
WHERE = re.compile(r"^(?:kde (?:jsou|je|mám|najdu|leží)|kam jsem (?:dal|dala|schoval|uložil)\w*)\s+(?P<item>.{2,60}?)\??$", re.I)


def put(rt: Any, text: str) -> tuple[str, str] | None:
    t = (text or "").strip()
    m = PUT2.match(t) or PUT.match(t)
    if not m:
        return None
    item, place = m.group("item").strip(), m.group("place").strip()
    if fold(item) in ("to", "ono", "tohle", "venku", "pocasi"):
        return None
    db(rt).exec("INSERT OR REPLACE INTO mem_places VALUES (?,?,?)", (fold(item), place, time.time()))
    return item, place


def where_is(rt: Any, text: str) -> str | None:
    m = WHERE.match((text or "").strip())
    if not m:
        return None
    q = fold(m.group("item"))
    best = None
    for r in db(rt).all("SELECT * FROM mem_places"):
        words = set(r["item"].split())
        hit = len(words & set(q.split()))
        if hit and (best is None or hit > best[0]):
            best = (hit, r)
    if not best:
        return f"Nevím, kde je „{m.group('item')}“ – řekni mi to, až to někam dáš."
    r = best[1]
    return f"{m.group('item')[0].upper() + m.group('item')[1:]}: {r['place']} (řekl jsi mi to {dt.date.fromtimestamp(r['ts']):%d. %m. %Y})."


# ------------------------------------------------------------------ (48) doporučení
REC = re.compile(r"^(?P<by>[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+)\s+(?:mi\s+)?(?:doporučil[a]?|radil[a]?|říkal[a]?,? (?:že )?(?:je )?dobr\w*)\s+"
                 r"(?P<kind>film|knihu|knížku|seriál|restauraci|podcast|hru|album|písničku|kavárnu|hospodu|appku|aplikaci)?\s*(?P<title>.{2,80}?)[.!]?$", re.I)
KINDS = {"knizku": "kniha", "knihu": "kniha", "film": "film", "serial": "seriál", "restauraci": "restaurace", "podcast": "podcast",
         "hru": "hra", "album": "hudba", "pisnicku": "hudba", "kavarnu": "restaurace", "hospodu": "restaurace", "appku": "aplikace",
         "aplikaci": "aplikace"}


def add_rec(rt: Any, text: str) -> dict | None:
    m = REC.match((text or "").strip())
    if not m:
        return None
    kind = KINDS.get(fold(m.group("kind") or ""), "tip")
    title = m.group("title").strip(" „“\"")
    db(rt).exec("INSERT INTO mem_recs(kind, title, by, ts) VALUES (?,?,?,?)", (kind, title, m.group("by"), time.time()))
    return {"kind": kind, "title": title, "by": m.group("by")}


def recs(rt: Any, kind: str = "") -> list[dict]:
    rows = db(rt).all("SELECT * FROM mem_recs WHERE done=0 ORDER BY ts DESC")
    k = fold(kind)
    return [dict(r) for r in rows if not k or fold(r["kind"]).startswith(k[:4])]


# ------------------------------------------------------------------ (49) vzpomínka s fotkou
def photo_memory(rt: Any, text: str, attachment: str, place: str = "") -> int:
    if not place:
        loc = getattr(rt, "phone_location", None) or {}
        place = str(loc.get("place") or loc.get("name") or "")
    body = text.strip() or "Vzpomínka"
    full = body + (f" (místo: {place})" if place else "")
    return _add_fact(rt, full, source=f"fotka:{attachment}")


# ------------------------------------------------------------------ (50) fakta starší než rok
def stale_facts(rt: Any, days: int = 365, now: float | None = None, limit: int = 3) -> list[dict]:
    now = now or time.time()
    cut = now - days * 86400
    rows = db(rt).all("SELECT id, text, created, confirmed FROM facts WHERE COALESCE(confirmed, created) < ? AND locked=0 "
                      "ORDER BY created LIMIT ?", (cut, limit))
    return [dict(r) for r in rows]


def confirm_fact(rt: Any, fid: int) -> bool:
    return db(rt).exec("UPDATE facts SET confirmed=? WHERE id=?", (time.time(), int(fid))).rowcount > 0


def drop_fact(rt: Any, fid: int) -> bool:
    return db(rt).exec("DELETE FROM facts WHERE id=?", (int(fid),)).rowcount > 0


# ------------------------------------------------------------------ (51) sdílená rodinná paměť
def share_fact(rt: Any, needle: str, on: bool = True) -> int:
    n = fold(needle)
    rows = [f for f in db(rt).all("SELECT id, text FROM facts") if n in fold(f["text"]) or str(f["id"]) == needle.strip("# ")]
    for f in rows:
        db(rt).exec("UPDATE facts SET shared=? WHERE id=?", (1 if on else 0, f["id"]))
    return len(rows)


def shared_facts(rt: Any) -> list[str]:
    return [r["text"] for r in db(rt).all("SELECT text FROM facts WHERE shared=1 AND locked=0 ORDER BY id")]


def facts_for_speaker(rt: Any, facts: list[str], speaker_is_household: bool) -> list[str]:
    """A household member (not the owner) speaking: only what is shared with the family. Locked ones never."""
    locked = {r["text"] for r in db(rt).all("SELECT text FROM facts WHERE locked=1")}
    if speaker_is_household:
        return shared_facts(rt)
    if unlocked(rt):
        return facts
    return [f for f in facts if f not in locked]


# ------------------------------------------------------------------ (52) rok v kostce
def year_data(rt: Any, year: int) -> dict:
    tl = timeline(rt, year)
    by_kind: dict[str, int] = {}
    for e in tl:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    months: dict[str, int] = {}
    for e in tl:
        months[e["date"][:7]] = months.get(e["date"][:7], 0) + 1
    busiest = max(months, key=lambda k: months[k]) if months else ""
    diary = [e["text"] for e in tl if e["kind"] == "deník"]
    return {"year": year, "events": tl, "counts": by_kind, "busiest_month": busiest, "diary_days": len(diary),
            "trips": [e["text"] for e in tl if e["kind"] == "cesta"]}


YEAR_PROMPT = ("Z těchto záznamů napiš krátký osobní příběh roku (6–10 vět), česky, vlídně, bez vymýšlení: co se dělo, "
               "kam uživatel cestoval, co ho bavilo, nejrušnější měsíc. Jen z toho, co je v datech.")


async def year_story(rt: Any, year: int) -> str:
    d = year_data(rt, year)
    if not d["events"]:
        return f"Z roku {year} nemám skoro žádné záznamy – deník, cesty a fotky mi dají víc."
    lines = "\n".join(f"{e['date']} {e['kind']}: {e['text']}" for e in d["events"][:200])
    try:
        return (await rt.router.complete([{"role": "system", "content": YEAR_PROMPT},
                                          {"role": "user", "content": f"Rok {year}\n{lines}"}])).strip()
    except Exception as e:  # noqa: BLE001 – no AI: the numbers alone
        log.info("year story: %s", e)
        c = d["counts"]
        return (f"Rok {year}: {c.get('cesta', 0)} cest, {d['diary_days']} dní v deníku, {c.get('fotky', 0)} dní s fotkami. "
                f"Nejrušnější měsíc: {d['busiest_month']}.")


# ------------------------------------------------------------------ (53) deník
def diary_add(rt: Any, text: str, day: dt.date | None = None) -> str:
    day = day or dt.date.today()
    old = db(rt).one("SELECT text FROM mem_diary WHERE day=?", (day.isoformat(),))
    body = (old["text"] + " " if old else "") + text.strip()
    db(rt).exec("INSERT OR REPLACE INTO mem_diary VALUES (?,?,?)", (day.isoformat(), body, time.time()))
    return body


def diary(rt: Any, query: str = "", limit: int = 10) -> list[dict]:
    rows = db(rt).all("SELECT day, text FROM mem_diary ORDER BY day DESC")
    q = fold(query)
    return [dict(r) for r in rows if not q or q in fold(r["text"]) or r["day"].startswith(query)][:limit]


DIARY_ASK = "Jak ses dnes měl? Řekni mi dvě tři věty – zapíšu je do deníku."
DIARY_WINDOW = 20 * 60


def diary_waiting(rt: Any) -> bool:
    return time.time() - float(getattr(rt, "memx_diary_asked", 0) or 0) < DIARY_WINDOW


# ------------------------------------------------------------------ (54) fotky s pamětí
def _exif(path: Path) -> dict:
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return {}
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
            gps = ex.get_ifd(0x8825) if hasattr(ex, "get_ifd") else {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    raw = tags.get("DateTimeOriginal") or tags.get("DateTime")
    if raw:
        try:
            out["taken"] = dt.datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    if gps and 2 in gps and 4 in gps:
        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        try:
            out["lat"], out["lon"] = deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return out


async def place_name(rt: Any, lat: float, lon: float) -> str:
    """The town for a GPS point (OpenStreetMap Nominatim; cached by ~1 km)."""
    key = f"geo_{round(lat, 2)}_{round(lon, 2)}"
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
    if row:
        return row["v"]
    try:
        async with rt.http() as c:
            r = await c.get("https://nominatim.openstreetmap.org/reverse", params={"lat": lat, "lon": lon, "format": "jsonv2",
                                                                                   "zoom": 10, "accept-language": "cs"},
                            headers={"User-Agent": "JARVIS-desktop/3.20"}, timeout=15)
        a = r.json().get("address", {}) if r.status_code == 200 else {}
    except Exception as e:  # noqa: BLE001
        log.info("place name: %s", e)
        return ""
    name = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county") or ""
    if a.get("country") and a.get("country") != "Česko":
        name = f"{name}, {a['country']}" if name else a["country"]
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, name))
    return name


async def index_photos(rt: Any, folder: Path, limit: int = 2000) -> dict:
    """Date and place (from the photo's own GPS) for each photo, and the people JARVIS knows by face."""
    import asyncio

    n = new = 0
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".heic", ".png") or not p.is_file():
            continue
        n += 1
        if n > limit:
            break
        if db(rt).one("SELECT path FROM mem_photos WHERE path=?", (str(p),)):
            continue
        ex = await asyncio.to_thread(_exif, p)
        place = await place_name(rt, ex["lat"], ex["lon"]) if "lat" in ex else ""
        people = ""
        try:
            from . import faces

            if hasattr(faces, "people_in"):
                people = ", ".join(await asyncio.to_thread(faces.people_in, rt, p))
        except Exception:  # noqa: BLE001
            people = ""
        taken = ex.get("taken") or p.stat().st_mtime
        words = fold(f"{place} {people} {p.parent.name} {dt.date.fromtimestamp(taken):%Y %m} {MONTHS[dt.date.fromtimestamp(taken).month - 1]}")
        db(rt).exec("INSERT OR REPLACE INTO mem_photos VALUES (?,?,?,?,?,?,?)",
                    (str(p), taken, ex.get("lat"), ex.get("lon"), place, people, words))
        new += 1
    return {"seen": min(n, limit), "new": new}


MONTHS = ["leden", "unor", "brezen", "duben", "kveten", "cerven", "cervenec", "srpen", "zari", "rijen", "listopad", "prosinec"]
MONTH_STEMS = {"led": 1, "uno": 2, "bre": 3, "dub": 4, "kve": 5, "cerven": 6, "cervenc": 7, "srp": 8, "zar": 9, "rij": 10, "lis": 11, "pro": 12}


def search_photos(rt: Any, query: str, limit: int = 30) -> list[dict]:
    q = [w for w in fold(query).split() if w not in ("fotky", "fotka", "fotek", "z", "ze", "s", "se", "v", "ve", "na", "kde", "je", "jsou", "moje",
                                                       "najdi", "ukaz", "a")]
    out = []
    for r in db(rt).all("SELECT * FROM mem_photos ORDER BY taken DESC"):
        w = r["words"]
        ok = True
        for x in q:
            if x.isdigit() and len(x) == 4:
                ok &= f" {x} " in f" {w} "
            elif any(x.startswith(k) for k in MONTH_STEMS):
                mo = next(v for k, v in sorted(MONTH_STEMS.items(), key=lambda kv: -len(kv[0])) if x.startswith(k))
                ok &= MONTHS[mo - 1] in w
            else:
                ok &= x[: max(3, len(x) - 2)] in w
        if ok:
            out.append(dict(r))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ (55) oblíbené odpovědi
def star(rt: Any, msg_id: str, on: bool = True) -> bool:
    if not on:
        row = rt.db.one("SELECT meta FROM messages WHERE id=?", (msg_id,))
        if row:
            _star_meta(rt, msg_id, row["meta"], False)
        return db(rt).exec("DELETE FROM mem_favs WHERE msg_id=?", (msg_id,)).rowcount > 0
    m = rt.db.one("SELECT content, meta FROM messages WHERE id=?", (msg_id,))
    if not m:
        return False
    db(rt).exec("INSERT OR REPLACE INTO mem_favs VALUES (?,?,?)", (msg_id, m["content"], time.time()))
    _star_meta(rt, msg_id, m["meta"], True)
    return True


def _star_meta(rt: Any, msg_id: str, meta: str | None, on: bool) -> None:
    """The ★ stays on the message after a reload."""
    try:
        d = json.loads(meta or "{}")
    except ValueError:
        d = {}
    d["starred"] = on
    rt.db.exec("UPDATE messages SET meta=? WHERE id=?", (json.dumps(d, ensure_ascii=False), msg_id))


def favorites(rt: Any, query: str = "") -> list[dict]:
    q = fold(query)
    return [dict(r) for r in db(rt).all("SELECT * FROM mem_favs ORDER BY ts DESC") if not q or q in fold(r["text"])]


# ------------------------------------------------------------------ (56) dočasné vzpomínky
UNTIL = re.compile(r"^(?:pamatuj si|zapamatuj si|zapamatuj)\s+(?:do|az do)\s+(?P<when>.+?)\s*(?:,\s*(?:ze\s+)?|\s+ze\s+)(?P<what>.{3,})$")


def remember_until(rt: Any, text: str, until: dt.datetime) -> int:
    fid = _add_fact(rt, text.strip(), source="dočasné")
    end = until.replace(hour=23, minute=59, second=0) if until.hour == 9 and until.minute == 0 else until
    db(rt).exec("UPDATE facts SET expires=? WHERE id=?", (end.timestamp(), fid))
    return fid


def parse_until(text: str, now: dt.datetime | None = None) -> tuple[str, dt.datetime] | None:
    m = UNTIL.match(fold(text))
    if not m:
        return None
    from .voicex import parse_when

    at = parse_when(m.group("when"), now)
    if at is None:
        return None
    # the words as you said them (with accents): cut the same number of words off the front
    lead = len(fold(text)) - len(m.group("what"))
    return text[lead:].strip(" ,"), at


# ------------------------------------------------------------------ (57) citlivé údaje
def _luhn(num: str) -> bool:
    d = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        s += x
    return s % 10 == 0


SENSITIVE = [
    ("karta", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")),
    ("heslo", re.compile(r"\b(heslo|password|pin|pinkod|kód|kod)\b[^\n]{0,30}?(?:\bje\b|=|:)\s*\S{3,}", re.I)),
    ("rodné číslo", re.compile(r"\b\d{6}/\d{3,4}\b")),
    ("číslo účtu", re.compile(r"\b(?:\d{1,6}-)?\d{2,10}/\d{4}\b")),
]


def sensitive_scan(rt: Any) -> list[dict]:
    out = []
    for f in db(rt).all("SELECT id, text FROM facts"):
        for kind, rx in SENSITIVE:
            m = rx.search(f["text"])
            if not m:
                continue
            if kind == "karta" and not _luhn(m.group(0)):
                continue
            if kind == "číslo účtu" and SENSITIVE[3][1].search(f["text"]):
                continue
            out.append({"id": f["id"], "kind": kind, "text": mask(f["text"])})
            break
    return out


def mask(text: str) -> str:
    t = re.sub(r"\b(\d[ -]?){9,15}(\d{4})\b", lambda m: "•••• " + m.group(2), text)
    return re.sub(r"\b(heslo|password|pin|pinkód|pinkod|kód|kod)\b([^\n]{0,30}?(?:\bje\b|=|:)\s*)\S{3,}", r"\1\2••••", t, flags=re.I)


# ------------------------------------------------------------------ (59) soukromé vzpomínky pod PINem
UNLOCK_S = 600


def set_pin(rt: Any, pin: str) -> None:
    if not re.fullmatch(r"\d{4,8}", pin or ""):
        raise ValueError("PIN musí mít 4–8 číslic.")
    salt = base64.b64encode(hashlib.sha256(str(time.time()).encode()).digest()[:12]).decode()
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('memx_pin', ?)", (json.dumps({"salt": salt, "h": h}),))


def check_pin(rt: Any, pin: str) -> bool:
    row = rt.db.one("SELECT v FROM kv WHERE k='memx_pin'")
    if not row:
        return False
    d = json.loads(row["v"])
    import hmac

    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", (pin or "").encode(), d["salt"].encode(), 200_000).hex(), d["h"])


def unlock(rt: Any, pin: str) -> bool:
    if check_pin(rt, pin):
        rt.memx_unlocked = time.time() + UNLOCK_S
        return True
    return False


def unlocked(rt: Any) -> bool:
    return time.time() < float(getattr(rt, "memx_unlocked", 0) or 0)


def lock_fact(rt: Any, needle: str, on: bool = True) -> int:
    if not rt.db.one("SELECT v FROM kv WHERE k='memx_pin'"):
        raise ValueError("Nejdřív si nastav PIN (řekni „nastav PIN pro soukromou paměť 1234“).")
    n = fold(needle)
    rows = [f for f in db(rt).all("SELECT id, text FROM facts") if n in fold(f["text"]) or str(f["id"]) == needle.strip("# ")]
    for f in rows:
        db(rt).exec("UPDATE facts SET locked=? WHERE id=?", (1 if on else 0, f["id"]))
    return len(rows)


# ------------------------------------------------------------------ (60) paměť přes víc PC
def _key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(("jarvis-memsync:" + secret).encode()).digest())


def export_facts(rt: Any, secret: str) -> str:
    """Every shareable fact (not locked), encrypted with the key both PCs share."""
    from cryptography.fernet import Fernet

    rows = [{"text": r["text"], "created": r["created"], "category": r["category"] or "", "shared": r["shared"] or 0}
            for r in db(rt).all("SELECT text, created, category, shared FROM facts WHERE locked=0")]
    dead = [r["h"] for r in db(rt).all("SELECT h FROM mem_tombstones")]
    return Fernet(_key(secret)).encrypt(json.dumps({"facts": rows, "tombstones": dead}).encode()).decode()


def import_facts(rt: Any, blob: str, secret: str) -> dict:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        d = json.loads(Fernet(_key(secret)).decrypt(blob.encode()))
    except (InvalidToken, ValueError) as e:
        raise ValueError("Data nejdou rozšifrovat – jiný klíč spojení?") from e
    for h in d.get("tombstones", []):
        db(rt).exec("INSERT OR IGNORE INTO mem_tombstones VALUES (?,?)", (h, time.time()))
    have = {fold(r["text"]) for r in db(rt).all("SELECT text FROM facts")}
    dead = {r["h"] for r in db(rt).all("SELECT h FROM mem_tombstones")}
    added = 0
    for f in d.get("facts", []):
        if fold(f["text"]) in have or _h(f["text"]) in dead:
            continue
        db(rt).exec("INSERT INTO facts(text, created, category, source, shared) VALUES (?,?,?,?,?)",
                    (f["text"], f.get("created") or time.time(), f.get("category", ""), "jiný počítač", int(f.get("shared") or 0)))
        added += 1
    removed = apply_tombstones(rt)
    return {"added": added, "removed": removed}


# ------------------------------------------------------------------ quick commands (no AI in between)
OBJECTS = re.compile(r"\b(klic\w*|pas\b|pasy|doklad\w*|obcansk\w*|ridicak\w*|nabijec\w*|ovladac\w*|bryle|brejle|penezenk\w*|kart\w*|"
                     r"kabel\w*|bateri\w*|naradi|sroubovak\w*|vrtack\w*|deštnik|destnik\w*|sluchatk\w*|hodink\w*|prsten\w*|sperk\w*|"
                     r"dokument\w*|smlouv\w*|zaruk\w*|uctenk\w*|flash\w*|disk\w*|hesl\w*|krabic\w*|kufr\w*|lyze|kolo|helm\w*|"
                     r"muj|moje|moji|nase|naseho|svoje)\b")
FORGET_ALL = re.compile(r"^zapomen\w*\b.*\b(i|uplne|vsude)\b.*\b(zaloh\w*|vsude|uplne)\b")


def quick(rt: Any, text: str) -> tuple[str, dict] | None:
    t = (text or "").strip()
    f = fold(t).strip(" .!?")
    if not f:
        return None
    if WHERE.match(t):
        return "memory_kit", {"action": "where", "text": t}
    if (PUT2.match(t) or (PUT.match(t) and OBJECTS.search(f))) and not f.startswith(("kde", "kam", "co ", "jak")):
        return "memory_kit", {"action": "put", "text": t}
    if REC.match(t):
        return "memory_kit", {"action": "rec_add", "text": t}
    w = detect_wish(t)
    if w and len(t.split()) <= 12 and not re.match(r"^\w+(t|ct)\b", fold(w[1])):
        return "memory_kit", {"action": "wish_add", "person": w[0], "text": w[1]}
    if UNTIL.match(f):
        return "memory_kit", {"action": "until", "text": t}
    if FORGET_ALL.match(f):
        thing = re.sub(r"^\S+\s+(?:i\s+ze\s+zaloh\w*|uplne|vsude)?\s*,?\s*(?:ze\s+)?", "", t, flags=re.I).strip()
        return "memory_kit", {"action": "forget_all", "text": thing or t}
    from .proactx import CONTACTED

    if CONTACTED.match(f) and len(f.split()) <= 8:
        return "day_kit", {"action": "friend_contact", "name": CONTACTED.match(f).group("name")}
    if diary_waiting(rt) and len(f.split()) >= 3 and not re.match(r"^(jarvis\w*|otevri|pust|zapni|vypni|kolik|kdy|jak|co|kde|proc|nastav)\b", f):
        from .instant import plan

        if plan(t) is None:
            rt.memx_diary_asked = 0
            return "memory_kit", {"action": "diary_add", "text": t}
    return None


async def sync_node(rt: Any, node: dict, connect=None, timeout: float = 30.0) -> dict:
    """(60) Both PCs end up with the same memory: ours goes there encrypted with its pairing key, its memory comes back."""
    import asyncio

    from . import nodes

    key = nodes.token_for(node)
    if not key:
        raise ValueError(f"Pro {node['name']} nemám párovací klíč.")
    if connect is None:
        from websockets.asyncio.client import connect as ws_connect

        conn = ws_connect(nodes.ws_url(node), open_timeout=8, max_size=2**24)
    else:
        conn = connect(nodes.ws_url(node))
    async with conn as ws:
        await ws.send(json.dumps({"type": "hello", "client": "node", "name": "JARVIS"}))
        await ws.send(json.dumps({"type": "mem_sync", "blob": export_facts(rt, key)}))
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.1, end - loop.time())))
            if msg.get("type") == "mem_sync_done":
                if msg.get("error"):
                    raise ValueError(str(msg["error"]))
                back = import_facts(rt, str(msg.get("blob") or ""), key) if msg.get("blob") else {"added": 0, "removed": 0}
                return {"sent_added": int(msg.get("added") or 0), "got_added": back["added"], "removed": back["removed"]}
