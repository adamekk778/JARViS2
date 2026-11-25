"""3.20 Práce+ (nápady 261–280 ze stránky „Nápady pro JARVISe“).

- hluboké soustředění (261 – rušivé weby přes soubor hosts jen s právy správce), pomodoro v notchi (262)
- automatická odpověď podle dovolené (263 – Gmail / Outlook přes jejich API), ručně psané poznámky z fotky (264)
- rychlá poznámka, která se sama zařadí (265), chybějící příloha (266), odeslání ráno (267), časový výkaz podle oken (268)
- příprava na 1:1 (269), ranní třídění pošty (270), překlad Wordu se zachováním formátu (271), prezentace z poznámek (272)
- psaní bez rozptýlení (273 – stránka /write), hromadná korespondence jen jako koncepty ke kontrole (274)
- společný volný čas pro schůzku (275), nástěnka (276 – /board), „teď jen faktury“ (277), odpovědi na časté dotazy (278)
- konec dne bez rozdělaných věcí (279), podpis PDF obrázkem (280 – kvalifikovaný el. podpis potřebuje certifikát)
"""
from __future__ import annotations

import datetime as dt
import difflib
import html
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wk_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, category TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS wk_time (day TEXT, project TEXT, minutes REAL, PRIMARY KEY (day, project));
CREATE TABLE IF NOT EXISTS wk_board (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, col TEXT, source TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS wk_faq (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT, used INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS wk_focus (start REAL, minutes REAL, kind TEXT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_workx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._workx_ready = True
    return rt.db


# ------------------------------------------------------------------ (261) soustředění, (262) pomodoro, (277) jedna věc
DISTRACTING = ["youtube.com", "www.youtube.com", "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
               "x.com", "twitter.com", "reddit.com", "www.reddit.com", "tiktok.com", "www.tiktok.com", "novinky.cz", "www.idnes.cz"]
HOSTS_MARK = "# JARVIS focus"


def hosts_with_block(current: str, domains: list[str]) -> str:
    keep = [ln for ln in current.splitlines() if not ln.rstrip().endswith(HOSTS_MARK)]
    add = [f"0.0.0.0 {d} {HOSTS_MARK}" for d in domains]
    return "\n".join(keep + add) + "\n"


def hosts_without_block(current: str) -> str:
    return "\n".join(ln for ln in current.splitlines() if not ln.rstrip().endswith(HOSTS_MARK)) + "\n"


def hosts_path() -> Path:
    import os

    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts" if os.name == "nt" else Path("/etc/hosts")


def deep_focus(rt: Any, minutes: int, block: bool = True, domains: list[str] | None = None) -> dict:
    """Do Not Disturb on the phone, quiet notices on the PC, distracting sites blocked (when JARVIS may edit hosts)."""
    until = time.time() + minutes * 60
    rt.focus_until = until
    rt.phone_push("dnd", on=True, why="soustředění")
    blocked = False
    if block:
        p = hosts_path()
        try:
            p.write_text(hosts_with_block(p.read_text(encoding="utf-8", errors="ignore"), domains or DISTRACTING), encoding="utf-8")
            blocked = True
        except OSError:
            blocked = False                      # not an administrator: the sites stay, focusguard still nudges
    db(rt).exec("INSERT INTO wk_focus VALUES (?,?,?)", (time.time(), float(minutes), "focus"))
    return {"until": until, "blocked": blocked}


def focus_end(rt: Any) -> None:
    rt.focus_until = 0
    rt.phone_push("dnd", on=False, why="konec soustředění")
    p = hosts_path()
    try:
        cur = p.read_text(encoding="utf-8", errors="ignore")
        if HOSTS_MARK in cur:
            p.write_text(hosts_without_block(cur), encoding="utf-8")
    except OSError:
        pass


def focus_stats(rt: Any, days: int = 7, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rows = db(rt).all("SELECT kind, SUM(minutes) m, COUNT(*) n FROM wk_focus WHERE start >= ? GROUP BY kind", (now - days * 86400,))
    return {r["kind"]: {"minutes": round(float(r["m"] or 0)), "sessions": int(r["n"])} for r in rows}


class Pomodoro:
    def __init__(self, work: int = 25, rest: int = 5, rounds: int = 4):
        self.work, self.rest, self.rounds = work, rest, rounds
        self.phase, self.n, self.until = "work", 1, 0.0

    def start(self, now: float) -> dict:
        self.phase, self.n, self.until = "work", 1, now + self.work * 60
        return self.state()

    def tick(self, now: float) -> dict | None:
        """The next phase when the current one ends (None while it runs or after the last round)."""
        if not self.until or now < self.until:
            return None
        if self.phase == "work":
            self.phase = "rest"
            self.until = now + (self.rest * 3 if self.n % 4 == 0 else self.rest) * 60
        else:
            if self.n >= self.rounds:
                self.until = 0
                return {"phase": "done", "n": self.n}
            self.n += 1
            self.phase, self.until = "work", now + self.work * 60
        return self.state()

    def state(self) -> dict:
        return {"phase": self.phase, "n": self.n, "until": self.until, "title": f"Pomodoro {self.n}/{self.rounds} – " +
                ("práce" if self.phase == "work" else "pauza")}


def pomodoro(rt: Any) -> Pomodoro | None:
    return getattr(rt, "pomodoro", None)


def focus_topic_holds(topic: str, title: str, body: str) -> bool:
    """(277) "teď jen faktury": notices about anything else wait until you finish."""
    if not topic:
        return False
    words = [w for w in fold(topic).split() if len(w) > 3]
    text = fold(title + " " + body)
    return not any(w[:-1] in text for w in words)


# ------------------------------------------------------------------ (263) automatická odpověď
def vacation_text(until: dt.date, name: str = "", backup: str = "") -> str:
    return (f"Dobrý den, děkuji za zprávu. Do {until:%d. %m. %Y} jsem mimo kancelář s omezeným přístupem k e-mailu. "
            + (f"V naléhavých věcech se obraťte na {backup}. " if backup else "") + "Odpovím po návratu." + (f"\n{name}" if name else ""))


def gmail_vacation_body(on: bool, text: str, start: dt.date, end: dt.date) -> dict:
    to_ms = lambda d: int(dt.datetime.combine(d, dt.time()).timestamp() * 1000)  # noqa: E731
    return {"enableAutoReply": on, "responseSubject": "Mimo kancelář", "responseBodyPlainText": text, "restrictToContacts": False,
            "startTime": to_ms(start), "endTime": to_ms(end + dt.timedelta(days=1))}


def outlook_vacation_body(on: bool, text: str, start: dt.date, end: dt.date) -> dict:
    def stamp(d: dt.date) -> dict:
        return {"dateTime": f"{d.isoformat()}T00:00:00", "timeZone": "Europe/Prague"}

    return {"automaticRepliesSetting": {"status": "scheduled" if on else "disabled", "internalReplyMessage": text,
                                        "externalReplyMessage": text, "scheduledStartDateTime": stamp(start),
                                        "scheduledEndDateTime": stamp(end + dt.timedelta(days=1))}}


async def set_autoreply(rt: Any, on: bool, start: dt.date, end: dt.date, text: str, client: Any = None) -> list[str]:
    from . import secrets

    done = []
    own = client is None
    c = client or rt.http()
    try:
        tok = secrets.get("google_token")
        if tok:
            r = await c.put("https://gmail.googleapis.com/gmail/v1/users/me/settings/vacation", headers={"Authorization": f"Bearer {tok}"},
                            json=gmail_vacation_body(on, text, start, end), timeout=15)
            if r.status_code < 300:
                done.append("Gmail")
        tok = secrets.get("microsoft_token") or secrets.get("onedrive_token")
        if tok:
            r = await c.patch("https://graph.microsoft.com/v1.0/me/mailboxSettings", headers={"Authorization": f"Bearer {tok}"},
                              json=outlook_vacation_body(on, text, start, end), timeout=15)
            if r.status_code < 300:
                done.append("Outlook")
    finally:
        if own:
            await c.aclose()
    return done


# ------------------------------------------------------------------ (265) rychlá poznámka, (264) z fotky
NOTE_CATS = {"úkol": r"\b(udelat|zavolat|napsat|poslat|koupit|objednat|zaridit|nezapomen|musim|todo)\b",
             "nápad": r"\b(napad|co kdyby|idea|zkusit|vymyslet)\b", "schůzka": r"\b(schuzk|meeting|porad|call)\b",
             "peníze": r"\b(faktur|zaplat|cena|kc|eur|rozpocet)\b", "kontakt": r"(\+?\d[\d ]{8,}|@\w)"}


def note_category(text: str) -> str:
    t = fold(text)
    return next((c for c, pat in NOTE_CATS.items() if re.search(pat, t)), "poznámka")


def quick_note(rt: Any, text: str) -> dict:
    cat = note_category(text)
    cur = db(rt).exec("INSERT INTO wk_notes (ts, category, text) VALUES (?,?,?)", (time.time(), cat, text.strip()[:2000]))
    if cat == "úkol":
        board_add(rt, text.strip()[:120], "todo", "poznámka")
    return {"id": int(getattr(cur, "lastrowid", 0) or 0), "category": cat}


HANDWRITING_PROMPT = ("Přepiš ručně psaný text z fotky (tabule, blok, papír) co nejvěrněji do čistého textu. Zachovej odrážky a "
                      "nadpisy, nečitelná místa označ [?]. Pod text napiš 1–3 úkoly, pokud v poznámkách nějaké jsou.")


# ------------------------------------------------------------------ (266) chybějící příloha, (267) odeslání ráno
ATTACH_WORDS = re.compile(r"(v priloze|prikladam|zasilam v priloze|posilam v priloze|attached|in the attachment|enclosed|viz priloha|v prilohach)")


def mentions_attachment(body: str) -> bool:
    return bool(ATTACH_WORDS.search(fold(body)))


def morning_slot(now: dt.datetime, start: str = "08:00", late_from: int = 20) -> dt.datetime | None:
    """Written in the evening, at night or on a weekend → the next working day at 8:00 (None = send now)."""
    h, m = (int(x) for x in start.split(":"))
    if now.weekday() < 5 and h <= now.hour < late_from:
        return None
    d = now.date() + dt.timedelta(days=0 if now.hour < h and now.weekday() < 5 else 1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    from .proactx import cz_holidays

    while d in cz_holidays(d.year) or d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time(h, m))


# ------------------------------------------------------------------ (268) časový výkaz
def project_of(app: str, title: str, rules: dict[str, list[str]]) -> str:
    t = fold(app + " " + title)
    for project, words in rules.items():
        if any(fold(w) in t for w in words if w):
            return project
    return ""


def track_minute(rt: Any, info: dict, rules: dict[str, list[str]], day: dt.date | None = None, minutes: float = 1.0) -> str:
    p = project_of(str(info.get("app", "")), str(info.get("title", "")), rules)
    if not p:
        return ""
    d = (day or dt.date.today()).isoformat()
    db(rt).exec("INSERT INTO wk_time VALUES (?,?,?) ON CONFLICT(day, project) DO UPDATE SET minutes = minutes + excluded.minutes",
                (d, p, minutes))
    return p


def timesheet(rt: Any, start: dt.date, end: dt.date) -> list[dict]:
    rows = db(rt).all("SELECT project, SUM(minutes) m FROM wk_time WHERE day >= ? AND day <= ? GROUP BY project ORDER BY m DESC",
                      (start.isoformat(), end.isoformat()))
    return [{"project": r["project"], "hours": round(float(r["m"]) / 60, 2)} for r in rows]


# ------------------------------------------------------------------ (270) třídění pošty
def triage(mail: dict, me: str = "") -> str:
    """'reply' (someone asks you), 'read' (worth reading), 'archive' (newsletters, notifications)."""
    f = fold(f"{mail.get('subject', '')} {mail.get('snippet', '')}")
    sender = fold(mail.get("from", "") + " " + mail.get("from_name", ""))
    if mail.get("newsletter") or re.search(r"noreply|no-reply|newsletter|notifikace|notification|unsubscribe|odhlasit", sender + " " + f):
        return "archive"
    if "?" in (mail.get("snippet", "") + mail.get("subject", "")) or re.search(r"\b(prosim|muzes|mohl bys|mohla bys|potreb|dej vedet|odpovez|please|could you)\b", f):
        return "reply"
    return "read"


# ------------------------------------------------------------------ (271) překlad Wordu, (272) prezentace, (280) podpis
def translate_docx(src: Path, dst: Path, translate: Any) -> int:
    """Each paragraph and table cell translated in place – the styles, tables and pictures stay as they were."""
    from docx import Document

    doc = Document(str(src))
    paras = list(doc.paragraphs) + [p for t in doc.tables for row in t.rows for cell in row.cells for p in cell.paragraphs]
    n = 0
    for p in paras:
        text = p.text.strip()
        if not text:
            continue
        new = translate(p.text)
        if p.runs:
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
        n += 1
    doc.save(str(dst))
    return n


def outline_to_pptx(outline: list[dict], dst: Path, title: str = "") -> Path:
    """[{title, bullets: […]}] → a simple deck (title slide + one slide per section)."""
    from pptx import Presentation

    prs = Presentation()
    if title:
        s = prs.slides.add_slide(prs.slide_layouts[0])
        s.shapes.title.text = title
    for sec in outline:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = str(sec.get("title", ""))[:120]
        body = s.placeholders[1].text_frame
        bullets = [str(b)[:200] for b in sec.get("bullets", [])][:8]
        body.text = bullets[0] if bullets else ""
        for b in bullets[1:]:
            body.add_paragraph().text = b
    prs.save(str(dst))
    return dst


def parse_outline(text: str) -> list[dict]:
    """Markdown-ish notes → sections: "# Nadpis" / "Nadpis:" starts a slide, "-"/"•"/"*" lines are its bullets."""
    out: list[dict] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or (s.endswith(":") and len(s) < 80):
            out.append({"title": s.lstrip("#").rstrip(":").strip(), "bullets": []})
        elif re.match(r"^[-•*]\s+", s) or not out:
            if not out:
                out.append({"title": "Úvod", "bullets": []})
            out[-1]["bullets"].append(re.sub(r"^[-•*]\s+", "", s))
        else:
            out[-1]["bullets"].append(s)
    return out


def overlay_pdf(w: float, h: float, signature_png: Path, x: float, y: float, width: float, label: str) -> bytes:
    """One PDF page (w×h points) with the signature picture (transparency kept) and a line of text under it – built by
    hand, so no PDF drawing library is needed."""
    import zlib

    from PIL import Image

    im = Image.open(signature_png).convert("RGBA")
    iw, ih = im.size
    height = width * ih / iw
    rgb = zlib.compress(im.convert("RGB").tobytes())
    alpha = zlib.compress(im.getchannel("A").tobytes())
    safe = label.replace("\\", "").replace("(", "").replace(")", "")
    content = (f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {y:.2f} cm /Im0 Do Q "
               f"BT /F1 8 Tf {x:.2f} {y - 10:.2f} Td ({safe}) Tj ET").encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.2f} {h:.2f}] /Resources << /XObject << /Im0 4 0 R >> "
        f"/Font << /F1 6 0 R >> >> /Contents 7 0 R >>".encode(),
        f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        f"/Filter /FlateDecode /SMask 5 0 R /Length {len(rgb)} >>\nstream\n".encode() + rgb + b"\nendstream",
        f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} /ColorSpace /DeviceGray /BitsPerComponent 8 "
        f"/Filter /FlateDecode /Length {len(alpha)} >>\nstream\n".encode() + alpha + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def sign_pdf(src: Path, signature_png: Path, dst: Path, page: int = -1, x: float = 380, y: float = 60, width: float = 160) -> Path:
    """A picture of your signature stamped on a page (a visual signature; a qualified electronic one needs a certificate)."""
    import io

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=str(src))
    idx = page if page >= 0 else len(writer.pages) + page
    pg = writer.pages[idx]
    w, h = float(pg.mediabox.width), float(pg.mediabox.height)
    stamp = overlay_pdf(w, h, signature_png, x, y, width, f"Podepsano {dt.date.today():%d. %m. %Y}")
    pg.merge_page(PdfReader(io.BytesIO(stamp)).pages[0])
    with open(dst, "wb") as f:
        writer.write(f)
    return dst


# ------------------------------------------------------------------ (273) psaní, (274) hromadná korespondence
def write_page(goal: int = 500) -> str:
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Psaní</title>"
            "<style>html,body{margin:0;height:100%;background:#0b0f14;color:#e8eef5}textarea{box-sizing:border-box;width:100%;height:92%;"
            "border:0;outline:0;background:transparent;color:inherit;font:20px/1.7 Georgia,serif;padding:6vh 12vw;resize:none}"
            "footer{position:fixed;bottom:0;left:0;right:0;padding:8px 16px;color:#6f8aa3;font:13px system-ui;display:flex;gap:16px}"
            "progress{flex:1}</style><textarea id=t placeholder='Piš…' autofocus></textarea><footer><span id=c>0 slov</span>"
            f"<progress id=p max={int(goal)} value=0></progress><span>cíl {int(goal)}</span><span>F11 = celá obrazovka</span></footer>"
            "<script>const K='jarvis.write.'+new Date().toISOString().slice(0,10);try{t.value=localStorage.getItem(K)||''}catch(e){}"
            "function u(){const n=(t.value.match(/\\S+/g)||[]).length;c.textContent=n+' slov';p.value=n;try{localStorage.setItem(K,t.value)}catch(e){}}"
            "t.oninput=u;u();</script>")


def merge(template: str, row: dict) -> str:
    """{jméno}, {firma}… from one row of the list; a missing field stays visible as [chybí: pole]."""
    def sub(m: re.Match) -> str:
        key = m.group(1).strip()
        val = next((v for k, v in row.items() if fold(k) == fold(key)), None)
        return str(val) if val not in (None, "") else f"[chybí: {key}]"

    return re.sub(r"\{([^{}]{1,40})\}", sub, template)


def merge_rows(text: str) -> list[dict]:
    import csv
    import io

    return [dict(r) for r in csv.DictReader(io.StringIO(text), delimiter=";" if text.count(";") > text.count(",") else ",")]


# ------------------------------------------------------------------ (275) volný čas pro všechny
def free_slots(busy: list[tuple[dt.datetime, dt.datetime]], day: dt.date, minutes: int, work: tuple[str, str] = ("09:00", "17:00"),
               step: int = 30) -> list[dt.datetime]:
    a = dt.datetime.combine(day, dt.time.fromisoformat(work[0]))
    b = dt.datetime.combine(day, dt.time.fromisoformat(work[1]))
    out = []
    t = a
    while t + dt.timedelta(minutes=minutes) <= b:
        end = t + dt.timedelta(minutes=minutes)
        if not any(s < end and t < e for s, e in busy):
            out.append(t)
        t += dt.timedelta(minutes=step)
    return out


def parse_freebusy(data: dict) -> list[tuple[dt.datetime, dt.datetime]]:
    out = []
    for cal in (data.get("calendars") or {}).values():
        for b in cal.get("busy", []):
            s = dt.datetime.fromisoformat(b["start"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            e = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            out.append((s, e))
    return out


# ------------------------------------------------------------------ (276) nástěnka
COLS = {"todo": "Udělat", "doing": "Dělám", "done": "Hotovo"}


def board_add(rt: Any, title: str, col: str = "todo", source: str = "") -> int:
    cur = db(rt).exec("INSERT INTO wk_board (title, col, source, ts) VALUES (?,?,?,?)", (title[:160], col if col in COLS else "todo", source[:40], time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def board_move(rt: Any, bid: int, col: str) -> bool:
    if col not in COLS:
        return False
    had = db(rt).one("SELECT id FROM wk_board WHERE id=?", (int(bid),))
    db(rt).exec("UPDATE wk_board SET col=?, ts=? WHERE id=?", (col, time.time(), int(bid)))
    return bool(had)


def board_html(rt: Any) -> str:
    cols = []
    for c, label in COLS.items():
        cards = "".join(f"<li draggable=true data-id={r['id']}>{html.escape(r['title'])}<small>{html.escape(r['source'] or '')}</small></li>"
                        for r in db(rt).all("SELECT * FROM wk_board WHERE col=? ORDER BY ts DESC LIMIT 60", (c,)))
        cols.append(f"<section data-col={c}><h2>{label}</h2><ul>{cards}</ul></section>")
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Nástěnka</title>"
            "<style>body{font:14px system-ui;background:#0b0f14;color:#e8eef5;margin:16px}main{display:grid;grid-template-columns:repeat(3,1fr);"
            "gap:12px}section{background:#121a23;border-radius:12px;padding:10px;min-height:60vh}ul{list-style:none;padding:0;margin:0}"
            "li{background:#1b2634;border-radius:8px;padding:8px;margin:6px 0;cursor:grab}small{display:block;color:#6f8aa3}</style>"
            f"<h1>Nástěnka</h1><main>{''.join(cols)}</main><script>let d;document.querySelectorAll('li').forEach(l=>l.ondragstart=()=>d=l);"
            "document.querySelectorAll('section').forEach(s=>{s.ondragover=e=>e.preventDefault();s.ondrop=()=>{if(!d)return;"
            "s.querySelector('ul').prepend(d);fetch('/api/board/move',{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({id:+d.dataset.id,col:s.dataset.col})})}});</script>")


# ------------------------------------------------------------------ (278) časté dotazy, (279) konec dne
def faq_add(rt: Any, question: str, answer: str) -> int:
    cur = db(rt).exec("INSERT INTO wk_faq (question, answer) VALUES (?,?)", (question[:300], answer[:2000]))
    return int(getattr(cur, "lastrowid", 0) or 0)


def faq_find(rt: Any, text: str, cutoff: float = 0.45) -> dict | None:
    t = fold(text)
    best, score = None, 0.0
    for r in db(rt).all("SELECT * FROM wk_faq"):
        q = fold(r["question"])
        s = difflib.SequenceMatcher(None, q, t).ratio()
        words = set(q.split()) & set(t.split())
        s = max(s, len(words) / max(1, len(set(q.split()))))
        if s > score:
            best, score = dict(r), s
    if best and score >= cutoff:
        db(rt).exec("UPDATE wk_faq SET used=used+1 WHERE id=?", (best["id"],))
        return {**best, "score": round(score, 2)}
    return None


def open_items(rt: Any) -> list[str]:
    out = []
    for r in db(rt).all("SELECT * FROM wk_board WHERE col IN ('todo', 'doing') ORDER BY col DESC, ts DESC LIMIT 15"):
        out.append(("▶ " if r["col"] == "doing" else "• ") + r["title"])
    try:
        for t in rt.timers.list():
            out.append(f"⏲ {t.get('label', 'časovač')}")
    except Exception:  # noqa: BLE001
        pass
    try:
        for w in rt.platform.list_windows()[:30]:
            if re.search(r"(\*|neuložen|unsaved|•)", w):
                out.append(f"✎ Neuložený dokument: {w[:60]}")
    except Exception:  # noqa: BLE001
        pass
    return out


def move_to_tomorrow(rt: Any) -> int:
    n = 0
    for r in db(rt).all("SELECT id FROM wk_board WHERE col='doing'"):
        db(rt).exec("UPDATE wk_board SET col='todo' WHERE id=?", (r["id"],))
        n += 1
    return n


# ------------------------------------------------------------------ the minute look
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now()
    said: list[str] = []
    ts = now.timestamp()
    if getattr(rt, "focus_until", 0) and ts >= rt.focus_until:
        focus_end(rt)
        st = focus_stats(rt, 1, ts)
        t = f"Soustředění skončilo – dnes {st.get('focus', {}).get('minutes', 0)} minut hluboké práce."
        rt.notify("Soustředění", t, speak=False)
        said.append(t)
    p = pomodoro(rt)
    if p is not None:
        nxt = p.tick(ts)
        if nxt:
            if nxt["phase"] == "done":
                rt.pomodoro = None
                db(rt).exec("INSERT INTO wk_focus VALUES (?,?,?)", (ts, float(p.work * p.rounds), "pomodoro"))
                t = "Pomodoro hotové – 4 kola. Dej si delší pauzu."
            else:
                rt.bus.publish("countdown", until=nxt["until"], title=nxt["title"])
                t = "Pauza – vstaň a protáhni se." if nxt["phase"] == "rest" else f"Kolo {nxt['n']} – zpátky k práci."
            rt.notify("Pomodoro", t, speak=False)
            said.append(t)
    rules = getattr(getattr(rt.cfg, "workx", None), "projects", {}) or {}
    if rules:
        try:
            idle = float(rt.platform.idle_seconds())
            if idle < 120:
                track_minute(rt, rt.platform.foreground_info() or {}, rules, now.date())
        except Exception as e:  # noqa: BLE001
            log.debug("timesheet: %s", e)
    return said
