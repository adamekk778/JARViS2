"""3.20 Peníze+ (nápady 201–220 ze stránky „Nápady pro JARVISe“).

- zálohy na energie podle skutečné spotřeby (201), měsíční rozpočet po kategoriích (202), kapesné dětí (203)
- hlídač ceny zboží (204), dělení účtu s QR platbami (205), QR platba z PDF faktury (206), spořicí cíle (207)
- Fio banka přes její API jen pro čtení (208 – ostatní banky potřebují placeného zprostředkovatele PSD2)
- poukázky (209), podklady k daňovému přiznání (210), záruky (211), nákup podle zvyku (212), porovnání tarifů (213)
- neobvyklá platba (214), investice z více brokerů jen pro čtení (215), splatnost faktur (216)
- dárky s rozpočtem (218), lhůta na vrácení zboží (219), rok v penězích (220). Výdaje na auto (217) jsou v carx.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import statistics
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mx_budget (category TEXT PRIMARY KEY, limit_czk REAL);
CREATE TABLE IF NOT EXISTS mx_spend (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, category TEXT, amount REAL, note TEXT, source TEXT,
  ref TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS mx_kids (name TEXT PRIMARY KEY, balance REAL, weekly REAL, day INT, last TEXT);
CREATE TABLE IF NOT EXISTS mx_kid_log (ts REAL, name TEXT, amount REAL, note TEXT);
CREATE TABLE IF NOT EXISTS mx_pricewatch (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, title TEXT, target REAL, last REAL,
  best REAL, ts REAL);
CREATE TABLE IF NOT EXISTS mx_goals (name TEXT PRIMARY KEY, target REAL, saved REAL, deadline TEXT);
CREATE TABLE IF NOT EXISTS mx_items (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, value REAL, until TEXT, extra TEXT,
  done INT DEFAULT 0, ts REAL);
CREATE TABLE IF NOT EXISTS mx_tax (id INTEGER PRIMARY KEY AUTOINCREMENT, year INT, kind TEXT, amount REAL, note TEXT, file TEXT);
CREATE TABLE IF NOT EXISTS mx_buys (item TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS mx_portfolio (broker TEXT, symbol TEXT, qty REAL, cost REAL, PRIMARY KEY (broker, symbol));
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_moneyx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._moneyx_ready = True
    return rt.db


def kc(v: float) -> str:
    return f"{v:,.0f} Kč".replace(",", " ")


# ------------------------------------------------------------------ účty, IBAN a QR platby (205, 206, 216)
ACCOUNT_RE = re.compile(r"(?:(\d{1,6})-)?(\d{2,10})/(\d{4})")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b")


def _iban_check(country: str, bban: str) -> str:
    raw = bban + country + "00"
    num = "".join(str(int(c, 36)) for c in raw)
    return f"{98 - int(num) % 97:02d}"


def cz_iban(account: str) -> str:
    """'19-2000145399/0800' → 'CZ6508000000192000145399'."""
    m = ACCOUNT_RE.fullmatch(re.sub(r"\s", "", account))
    if not m:
        raise ValueError("Číslo účtu napiš jako 123456789/0800 nebo 19-123456789/0800.")
    prefix, number, bank = m.group(1) or "0", m.group(2), m.group(3)
    bban = bank + prefix.zfill(6) + number.zfill(10)
    return "CZ" + _iban_check("CZ", bban) + bban


def iban_ok(iban: str) -> bool:
    s = re.sub(r"\s", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", s):
        return False
    num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(num) % 97 == 1


def spayd(iban: str, amount: float, vs: str = "", msg: str = "", due: dt.date | None = None, currency: str = "CZK") -> str:
    """The Czech QR payment (Short Payment Descriptor) every Czech bank app reads."""
    iban = re.sub(r"\s", "", iban).upper()
    if not iban_ok(iban):
        raise ValueError("Neplatný IBAN.")
    parts = ["SPD*1.0", f"ACC:{iban}", f"AM:{amount:.2f}", f"CC:{currency.upper()}"]
    if due:
        parts.append(f"DT:{due:%Y%m%d}")
    if vs:
        parts.append(f"X-VS:{re.sub(r'[^0-9]', '', vs)[:10]}")
    if msg:
        parts.append("MSG:" + unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode().replace("*", " ")[:60])
    return "*".join(parts)


def qr_png(text: str, out: Path) -> Path:
    import qrcode

    out.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(text, box_size=10, border=3).save(out)
    return out


def parse_invoice(text: str) -> dict:
    """From an invoice's text: the account (or IBAN), variable symbol, amount to pay and due date."""
    t = text.replace("\xa0", " ")
    out: dict = {}
    m = IBAN_RE.search(t.upper())
    if m and iban_ok(m.group(1)):
        out["iban"] = re.sub(r"\s", "", m.group(1))
    m = ACCOUNT_RE.search(re.sub(r"(?<=\d) (?=[\d/-])", "", t))
    if m and "iban" not in out:
        try:
            out["iban"] = cz_iban(m.group(0))
            out["account"] = m.group(0)
        except ValueError:
            pass
    m = re.search(r"(?i)(?:variabiln\w*\s*symbol|v\.?\s?s\.?)\s*[:#]?\s*(\d{1,10})", t)
    if m:
        out["vs"] = m.group(1)
    amounts = re.findall(r"(?i)(?:k\s*úhradě|k\s*uhrade|celkem\s*k\s*úhradě|celkem|částka|amount due|total)[^\d\n]{0,25}(\d[\d \.]*[,.]\d{2}|\d[\d ]*)", t)
    if amounts:
        raw = amounts[-1].replace(" ", "")
        raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
        try:
            out["amount"] = float(raw)
        except ValueError:
            pass
    m = re.search(r"(?i)(?:datum\s*splatnosti|splatnost|splatné\s*do|due date)\D{0,10}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})", t)
    if m:
        try:
            out["due"] = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    return out


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:5])


# ------------------------------------------------------------------ (205) dělení účtu
def split(total: float, people: list[str] | int) -> list[tuple[str, float]]:
    names = people if isinstance(people, list) else [f"Osoba {i + 1}" for i in range(int(people))]
    if not names:
        raise ValueError("Na kolik lidí?")
    cents = round(total * 100)
    base, rest = divmod(cents, len(names))
    return [(n, (base + (1 if i < rest else 0)) / 100) for i, n in enumerate(names)]


# ------------------------------------------------------------------ (202) rozpočet a útraty
CATS = {"jidlo": "jídlo", "potraviny": "jídlo", "nakup": "jídlo", "restaurace": "jídlo", "obed": "jídlo", "vecere": "jídlo",
        "zabava": "zábava", "kino": "zábava", "hry": "zábava", "hra": "zábava", "koncert": "zábava",
        "doprava": "doprava", "benzin": "doprava", "nafta": "doprava", "jizdenk": "doprava", "taxi": "doprava",
        "obleceni": "oblečení", "boty": "oblečení", "drogerie": "domácnost", "domacnost": "domácnost", "bydleni": "bydlení",
        "najem": "bydlení", "energie": "bydlení", "zdravi": "zdraví", "lekarn": "zdraví", "leky": "zdraví", "darek": "dárky",
        "darky": "dárky", "predplatne": "předplatné", "deti": "děti", "skola": "děti", "sport": "sport", "posilovn": "sport"}


def category_of(text: str) -> str:
    t = fold(text)
    for k, v in CATS.items():
        if re.search(rf"\b{k}", t):
            return v
    return "ostatní"


def parse_spend(text: str) -> tuple[float, str, str] | None:
    """"utratil jsem 350 za jídlo", "benzín 1 200 Kč" → (amount, category, note)."""
    t = text.replace("\xa0", " ")
    m = re.search(r"(\d[\d ]*(?:[,.]\d{1,2})?)\s*(?:kč|korun|czk|,-)?", t, re.I)
    if not m:
        return None
    amount = float(m.group(1).replace(" ", "").replace(",", "."))
    if amount <= 0:
        return None
    rest = (t[:m.start()] + " " + t[m.end():]).strip()
    rest = re.sub(r"(?i)\b(utratil[a]?|zaplatil[a]?|jsem|za|kč|korun)\b", " ", rest)
    note = " ".join(rest.split())[:80]
    return amount, category_of(note or text), note


def spend_add(rt: Any, amount: float, category: str, note: str = "", source: str = "ručně", ts: float | None = None,
              ref: str | None = None) -> bool:
    cur = db(rt).exec("INSERT OR IGNORE INTO mx_spend (ts, category, amount, note, source, ref) VALUES (?,?,?,?,?,?)",
                      (ts or time.time(), category, float(amount), note[:120], source, ref))
    return bool(getattr(cur, "rowcount", 1))


def budget_set(rt: Any, category: str, limit: float) -> None:
    db(rt).exec("INSERT OR REPLACE INTO mx_budget VALUES (?,?)", (category, float(limit)))


def month_range(day: dt.date) -> tuple[float, float]:
    start = dt.datetime(day.year, day.month, 1)
    end = dt.datetime(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return start.timestamp(), end.timestamp()


def budget_status(rt: Any, day: dt.date | None = None) -> list[dict]:
    day = day or dt.date.today()
    a, b = month_range(day)
    spent = {r["category"]: float(r["s"]) for r in db(rt).all(
        "SELECT category, SUM(amount) s FROM mx_spend WHERE ts >= ? AND ts < ? GROUP BY category", (a, b))}
    out = []
    for r in db(rt).all("SELECT * FROM mx_budget ORDER BY category"):
        s = spent.get(r["category"], 0.0)
        out.append({"category": r["category"], "limit": float(r["limit_czk"]), "spent": s, "left": float(r["limit_czk"]) - s,
                    "pct": round(s / float(r["limit_czk"]) * 100) if r["limit_czk"] else 0})
    return out


def budget_alerts(rt: Any, day: dt.date | None = None) -> list[str]:
    """80 % and 100 % of a category, once a month each."""
    day = day or dt.date.today()
    out = []
    for b in budget_status(rt, day):
        mark = 100 if b["pct"] >= 100 else 80 if b["pct"] >= 80 else 0
        if not mark:
            continue
        key = f"mx_budget:{b['category']}:{day:%Y-%m}:{mark}"
        if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
            continue
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
        out.append(f"{b['category'].capitalize()}: utraceno {kc(b['spent'])} z {kc(b['limit'])}"
                   + (" – rozpočet je vyčerpaný." if mark == 100 else f", zbývá {kc(b['left'])}."))
    return out


# ------------------------------------------------------------------ (203) kapesné
def kid_set(rt: Any, name: str, weekly: float, day: int = 0) -> None:
    row = db(rt).one("SELECT balance FROM mx_kids WHERE name=?", (name,))
    db(rt).exec("INSERT OR REPLACE INTO mx_kids VALUES (?,?,?,?,?)", (name, float(row["balance"]) if row else 0.0, float(weekly), int(day) % 7, ""))


def kid_move(rt: Any, name: str, amount: float, note: str = "") -> float:
    row = db(rt).one("SELECT balance FROM mx_kids WHERE name=?", (name,))
    if not row:
        raise ValueError(f"{name} zatím kapesné nemá – nastav ho: „kapesné {name} 100 Kč týdně“.")
    bal = float(row["balance"]) + float(amount)
    if bal < 0:
        raise ValueError(f"{name} má jen {kc(float(row['balance']))}.")
    db(rt).exec("UPDATE mx_kids SET balance=? WHERE name=?", (bal, name))
    db(rt).exec("INSERT INTO mx_kid_log VALUES (?,?,?,?)", (time.time(), name, float(amount), note[:80]))
    return bal


def kids_payday(rt: Any, today: dt.date) -> list[str]:
    out = []
    for k in db(rt).all("SELECT * FROM mx_kids"):
        if today.weekday() == int(k["day"]) and k["last"] != today.isoformat() and float(k["weekly"]) > 0:
            bal = kid_move(rt, k["name"], float(k["weekly"]), "kapesné")
            db(rt).exec("UPDATE mx_kids SET last=? WHERE name=?", (today.isoformat(), k["name"]))
            out.append(f"{k['name']} dostal(a) kapesné {kc(float(k['weekly']))}, má {kc(bal)}.")
    return out


# ------------------------------------------------------------------ (204) hlídač ceny
def price_from_html(html_text: str) -> tuple[float | None, str]:
    """The price and the name from a shop page: JSON-LD offers first, then meta tags, then a visible "Kč" price."""
    title = ""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html_text, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data, *(data.get("@graph") or [])]:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            title = title or str(item.get("name") or "")
            for off in offers if isinstance(offers, list) else [offers]:
                if isinstance(off, dict):
                    p = off.get("price") or off.get("lowPrice")
                    try:
                        if p is not None:
                            return float(str(p).replace(",", ".").replace(" ", "")), title
                    except ValueError:
                        pass
    m = re.search(r'(?:itemprop="price"|property="product:price:amount")[^>]*content="([\d.,\s]+)"', html_text)
    if not title:
        t = re.search(r"<title>([^<]{1,160})</title>", html_text, re.I)
        title = t.group(1).strip() if t else ""
    if m:
        return float(m.group(1).replace(" ", "").replace(",", ".")), title
    m = re.search(r"(\d{1,3}(?:[\s\xa0.]\d{3})*(?:,\d{2})?)\s*(?:Kč|,-)", html_text)
    if m:
        return float(re.sub(r"[\s\xa0.]", "", m.group(1)).replace(",", ".")), title
    return None, title


def watch_add(rt: Any, url: str, target: float = 0) -> int:
    if not re.match(r"https?://", url):
        raise ValueError("Pošli celý odkaz na zboží (https://…).")
    cur = db(rt).exec("INSERT OR IGNORE INTO mx_pricewatch (url, title, target, last, best, ts) VALUES (?,?,?,?,?,?)",
                      (url, "", float(target or 0), None, None, time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


async def watch_check(rt: Any, fetch: Callable[[str], Any] | None = None) -> list[str]:
    out = []
    for w in db(rt).all("SELECT * FROM mx_pricewatch"):
        try:
            if fetch is None:
                async with rt.http() as c:
                    r = await c.get(w["url"], headers={"User-Agent": "Mozilla/5.0 (JARVIS price watch)"}, timeout=15, follow_redirects=True)
                    page = r.text
            else:
                page = await fetch(w["url"])
        except Exception as e:  # noqa: BLE001
            log.info("price watch %s: %s", w["url"], e)
            continue
        price, title = price_from_html(page)
        if price is None:
            continue
        last, best, target = w["last"], w["best"], float(w["target"] or 0)
        db(rt).exec("UPDATE mx_pricewatch SET last=?, best=?, title=?, ts=? WHERE id=?",
                    (price, min(price, best) if best else price, (title or w["title"] or "")[:120], time.time(), w["id"]))
        name = (title or w["title"] or "Zboží")[:60]
        if target and price <= target and (last is None or last > target):
            out.append(f"{name} stojí {kc(price)} – pod tvou cenou {kc(target)}. {w['url']}")
        elif last and price <= last * 0.95:
            out.append(f"{name} zlevnilo z {kc(last)} na {kc(price)}. {w['url']}")
    return out


# ------------------------------------------------------------------ (207) cíle, (209, 211, 216, 219, 236) věci s datem
def goal_set(rt: Any, name: str, target: float, deadline: str = "") -> None:
    row = db(rt).one("SELECT saved FROM mx_goals WHERE name=?", (name,))
    db(rt).exec("INSERT OR REPLACE INTO mx_goals VALUES (?,?,?,?)", (name, float(target), float(row["saved"]) if row else 0.0, deadline))


def goal_add(rt: Any, name: str, amount: float) -> dict:
    row = db(rt).one("SELECT * FROM mx_goals WHERE name=?", (name,))
    if not row:
        raise ValueError(f"Cíl „{name}“ nemám.")
    saved = float(row["saved"]) + float(amount)
    db(rt).exec("UPDATE mx_goals SET saved=? WHERE name=?", (saved, name))
    return goal_info({**dict(row), "saved": saved})


def goal_info(g: dict, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    pct = min(100, round(float(g["saved"]) / float(g["target"]) * 100)) if g["target"] else 0
    per_month = None
    if g.get("deadline"):
        try:
            d = dt.date.fromisoformat(g["deadline"])
            months = max(1, (d.year - today.year) * 12 + d.month - today.month)
            per_month = max(0.0, (float(g["target"]) - float(g["saved"])) / months)
        except ValueError:
            pass
    return {"name": g["name"], "target": float(g["target"]), "saved": float(g["saved"]), "pct": pct, "per_month": per_month}


def goals(rt: Any) -> list[dict]:
    return [goal_info(dict(r)) for r in db(rt).all("SELECT * FROM mx_goals ORDER BY name")]


KINDS = {"voucher": "poukázka", "warranty": "záruka", "bill": "faktura", "return": "vrácení", "loyalty": "věrnostní body",
         "gift": "dárek"}


def item_add(rt: Any, kind: str, name: str, until: str, value: float = 0, extra: dict | None = None) -> int:
    if kind not in KINDS:
        raise ValueError("Neznámý druh.")
    dt.date.fromisoformat(until)
    cur = db(rt).exec("INSERT INTO mx_items (kind, name, value, until, extra, ts) VALUES (?,?,?,?,?,?)",
                      (kind, name[:120], float(value or 0), until, json.dumps(extra or {}, ensure_ascii=False), time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def warranty_until(bought: dt.date, months: int = 24) -> dt.date:
    y, m = divmod(bought.month - 1 + months, 12)
    import calendar

    year, month = bought.year + y, m + 1
    return dt.date(year, month, min(bought.day, calendar.monthrange(year, month)[1]))


def items(rt: Any, kind: str = "", open_only: bool = True) -> list[dict]:
    q = "SELECT * FROM mx_items WHERE 1=1" + (" AND kind=?" if kind else "") + (" AND done=0" if open_only else "") + " ORDER BY until"
    return [dict(r) for r in db(rt).all(q, (kind,) if kind else ())]


def item_done(rt: Any, iid: int) -> bool:
    had = db(rt).one("SELECT id FROM mx_items WHERE id=?", (int(iid),))
    db(rt).exec("UPDATE mx_items SET done=1 WHERE id=?", (int(iid),))
    return bool(had)


BEFORE = {"voucher": (30, 7, 1), "warranty": (30, 7), "bill": (3, 0), "return": (3, 1), "loyalty": (30, 7), "gift": ()}


def item_reminders(rt: Any, today: dt.date) -> list[str]:
    out = []
    for it in items(rt):
        left = (dt.date.fromisoformat(it["until"]) - today).days
        if left not in BEFORE.get(it["kind"], ()):
            continue
        key = f"mx_item:{it['id']}:{left}"
        if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
            continue
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
        when = "dnes" if left == 0 else "zítra" if left == 1 else f"za {left} dní"
        val = f" ({kc(it['value'])})" if it["value"] else ""
        text = {"voucher": f"Poukázka {it['name']}{val} propadne {when}.",
                "warranty": f"Záruka na {it['name']} končí {when} – jestli něco nefunguje, reklamuj teď.",
                "bill": f"Faktura {it['name']}{val} je splatná {when}.",
                "return": f"Lhůta na vrácení {it['name']} končí {when}.",
                "loyalty": f"Body {it['name']}{val} propadnou {when} – využij je."}[it["kind"]]
        out.append(text)
    return out


# ------------------------------------------------------------------ (201) zálohy na energie, (213) tarify
def advance_check(kwh_year: float, price_kwh: float, fixed_month: float, advance_month: float) -> dict:
    yearly = kwh_year * price_kwh + fixed_month * 12
    fair = yearly / 12
    diff = advance_month - fair
    if abs(diff) < max(100, fair * 0.05):
        verdict = "Zálohy sedí."
    elif diff > 0:
        verdict = f"Platíš o {kc(diff)} měsíčně víc – požádej o snížení záloh na {kc(round(fair, -1))}."
    else:
        verdict = f"Zálohy jsou o {kc(-diff)} měsíčně nízké – ve vyúčtování doplatíš asi {kc(-diff * 12)}. Zvaž {kc(round(fair, -1))}."
    return {"yearly": round(yearly), "fair_month": round(fair), "diff_month": round(diff), "verdict": verdict}


def tariffs(kwh_year: float, offers: list[dict]) -> list[dict]:
    """offers: [{name, price_kwh, fixed_month}] → sorted by the yearly cost for your consumption."""
    rows = [{"name": o["name"], "yearly": round(kwh_year * float(o["price_kwh"]) + 12 * float(o.get("fixed_month", 0)))} for o in offers]
    rows.sort(key=lambda r: r["yearly"])
    if rows:
        for r in rows:
            r["vs_best"] = r["yearly"] - rows[0]["yearly"]
    return rows


# ------------------------------------------------------------------ (208) Fio banka, (214) neobvyklá platba
def parse_fio(data: dict) -> list[dict]:
    out = []
    for t in ((data.get("accountStatement") or {}).get("transactionList") or {}).get("transaction") or []:
        def col(n: int) -> Any:
            c = t.get(f"column{n}")
            return c.get("value") if isinstance(c, dict) else None

        out.append({"id": str(col(22) or ""), "date": str(col(0) or "")[:10], "amount": float(col(1) or 0), "currency": col(14) or "CZK",
                    "counter": str(col(10) or col(2) or ""), "note": str(col(16) or col(25) or col(7) or "")})
    return out


async def fio_sync(rt: Any, days: int = 30, client: Any = None) -> list[dict]:
    from . import secrets

    tok = secrets.get("fio_token")
    if not tok:
        raise ValueError("Chybí token Fio API (internetbanking → Nastavení → API → jen pro čtení) – ulož ho v Nastavení → Klíče.")
    a = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    b = dt.date.today().isoformat()
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get(f"https://fioapi.fio.cz/v1/rest/periods/{tok}/{a}/{b}/transactions.json", timeout=20)
    finally:
        if own:
            await c.aclose()
    if r.status_code == 409:
        raise ValueError("Fio dovolí stáhnout pohyby jednou za 30 s – zkus to za chvíli.")
    r.raise_for_status()
    txs = parse_fio(r.json())
    for t in txs:
        if t["amount"] < 0:
            try:
                ts = dt.datetime.fromisoformat(t["date"]).timestamp()
            except ValueError:
                ts = time.time()
            spend_add(rt, -t["amount"], category_of(t["note"] + " " + t["counter"]), (t["counter"] or t["note"])[:80], "Fio", ts, f"fio:{t['id']}")
    return txs


def unusual(amount: float, history: list[float], new_counterparty: bool = False) -> str:
    """'' or why a payment looks unusual: far above what you normally pay, or a big first payment to someone new."""
    if len(history) >= 8:
        med = statistics.median(history)
        mad = statistics.median([abs(x - med) for x in history]) or max(1.0, med * 0.1)
        if amount > med + 6 * mad and amount > 2 * med and amount >= 1000:
            return f"{kc(amount)} je hodně nad obvyklou platbou ({kc(med)})."
    if new_counterparty and amount >= 5000:
        return f"První platba {kc(amount)} někomu novému."
    return ""


# ------------------------------------------------------------------ (210) daně
TAX_KINDS = {"prijem": "příjem", "penzijni": "penzijní spoření / DIP", "zivotni": "životní pojištění", "hypoteka": "úroky z hypotéky",
             "dar": "dary", "deti": "děti (sleva)", "odbory": "odborové příspěvky", "ostatni": "ostatní"}
PENSION_FREE = 20_400        # penzijní spoření: odečíst jde jen to, co je nad 1 700 Kč měsíčně
SAVINGS_CAP = 48_000         # penzijní + životní pojištění + DIP dohromady za rok
MORTGAGE_CAP = 80_000        # úroky z hypotéky sjednané od 2021 (starší smlouvy 150 000)


def tax_add(rt: Any, year: int, kind: str, amount: float, note: str = "", file: str = "") -> None:
    if kind not in TAX_KINDS:
        raise ValueError("Druh: " + ", ".join(TAX_KINDS))
    db(rt).exec("INSERT INTO mx_tax (year, kind, amount, note, file) VALUES (?,?,?,?,?)", (int(year), kind, float(amount), note[:120], file))


def tax_summary(rt: Any, year: int, old_mortgage: bool = False) -> dict:
    """What was collected during the year and what of it lowers the tax base (orientačně, pravidla od 2024)."""
    sums = {r["kind"]: float(r["s"]) for r in db(rt).all("SELECT kind, SUM(amount) s FROM mx_tax WHERE year=? GROUP BY kind", (int(year),))}
    pension = max(0.0, sums.get("penzijni", 0.0) - PENSION_FREE)
    savings = min(SAVINGS_CAP, pension + sums.get("zivotni", 0.0))
    mortgage = min(sums.get("hypoteka", 0.0), 150_000 if old_mortgage else MORTGAGE_CAP)
    deductible = savings + mortgage + sums.get("dar", 0.0) + sums.get("odbory", 0.0)
    lines = [f"{TAX_KINDS[k]}: {kc(v)}" for k, v in sums.items()]
    if "penzijni" in sums or "zivotni" in sums:
        lines.append(f"Penzijní (nad 1 700 Kč měsíčně) + životní pojištění: odečíst lze {kc(savings)} (strop {kc(SAVINGS_CAP)}).")
    if "hypoteka" in sums:
        lines.append(f"Úroky z hypotéky: odečíst lze {kc(mortgage)}.")
    if "dar" in sums:
        lines.append("Dary: aspoň 2 % základu nebo 1 000 Kč, nejvýš 15 % základu daně.")
    lines.append("Orientační přehled – přiznání podáš přes portál Moje daně; limity si pro daný rok ověř.")
    return {"year": year, "sums": sums, "deductible": round(deductible), "lines": lines}


# ------------------------------------------------------------------ (212) nákup podle zvyku
def bought(rt: Any, item: str, ts: float | None = None) -> None:
    db(rt).exec("INSERT INTO mx_buys VALUES (?,?)", (fold(item)[:60], ts or time.time()))


def due_items(rt: Any, now: float | None = None) -> list[str]:
    now = now or time.time()
    out = []
    by: dict[str, list[float]] = {}
    for r in db(rt).all("SELECT item, ts FROM mx_buys ORDER BY ts"):
        by.setdefault(r["item"], []).append(float(r["ts"]))
    for item, tss in by.items():
        if len(tss) < 3:
            continue
        gaps = [b - a for a, b in zip(tss, tss[1:])]
        every = statistics.median(gaps)
        if every >= 86400 and now - tss[-1] >= every * 0.9:
            out.append(item)
    return sorted(out)


# ------------------------------------------------------------------ (215) investice
def holding_set(rt: Any, broker: str, symbol: str, qty: float, cost: float) -> None:
    db(rt).exec("INSERT OR REPLACE INTO mx_portfolio VALUES (?,?,?,?)", (broker, symbol.upper(), float(qty), float(cost)))


def import_csv(rt: Any, broker: str, text: str) -> int:
    """A broker's positions export (columns like Symbol/Produkt, Quantity/Množství, Cost/Nákupní cena)."""
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(text), delimiter=";" if text.count(";") > text.count(",") else ","))
    n = 0
    for r in rows:
        low = {fold(k): v for k, v in r.items() if k}
        sym = next((low[k] for k in ("symbol", "ticker", "produkt", "product", "isin") if low.get(k)), "")
        qty = next((low[k] for k in ("quantity", "mnozstvi", "pocet", "qty", "units") if low.get(k)), "")
        cost = next((low[k] for k in ("cost", "nakupni cena", "cost basis", "purchase value", "hodnota nakupu") if low.get(k)), "0")
        try:
            holding_set(rt, broker, sym.strip(), float(str(qty).replace(",", ".")), float(str(cost).replace(" ", "").replace(",", ".") or 0))
            n += 1
        except ValueError:
            continue
    return n


async def portfolio(rt: Any, quote: Callable[[str], Any] | None = None) -> dict:
    from . import finance

    rows = [dict(r) for r in db(rt).all("SELECT * FROM mx_portfolio ORDER BY broker, symbol")]
    total = cost = 0.0
    for r in rows:
        try:
            q = await (quote(r["symbol"]) if quote else finance.quote(rt, r["symbol"], "czk"))
            price = float(q.get("price") or q.get("czk") or 0)
        except Exception:  # noqa: BLE001
            price = 0.0
        r["value"] = price * float(r["qty"])
        total += r["value"]
        cost += float(r["cost"])
    return {"rows": rows, "value": round(total), "cost": round(cost), "gain": round(total - cost),
            "gain_pct": round((total - cost) / cost * 100, 1) if cost else None}


# ------------------------------------------------------------------ (218) dárky, (220) rok v penězích
def gifts_status(rt: Any, season: str, budget: float) -> dict:
    gs = [g for g in items(rt, "gift", open_only=False) if json.loads(g["extra"] or "{}").get("season") == season]
    spent = sum(float(g["value"]) for g in gs if json.loads(g["extra"] or "{}").get("bought"))
    planned = sum(float(g["value"]) for g in gs)
    return {"season": season, "budget": budget, "spent": spent, "planned": planned, "left": budget - spent,
            "over": planned > budget, "people": sorted({json.loads(g["extra"] or "{}").get("person", "") for g in gs} - {""})}


def year_summary(rt: Any, year: int) -> dict:
    def by_cat(y: int) -> dict[str, float]:
        a, b = dt.datetime(y, 1, 1).timestamp(), dt.datetime(y + 1, 1, 1).timestamp()
        return {r["category"]: float(r["s"]) for r in db(rt).all(
            "SELECT category, SUM(amount) s FROM mx_spend WHERE ts >= ? AND ts < ? GROUP BY category", (a, b))}

    now_, before = by_cat(year), by_cat(year - 1)
    total = sum(now_.values())
    changes = sorted(((c, now_.get(c, 0) - before.get(c, 0)) for c in set(now_) | set(before)), key=lambda x: -abs(x[1]))
    lines = [f"Za rok {year} jsi utratil {kc(total)}" + (f" (loni {kc(sum(before.values()))})." if before else ".")]
    lines += [f"{c}: {kc(v)} ({round(v / total * 100)} %)" for c, v in sorted(now_.items(), key=lambda x: -x[1])[:6]] if total else []
    lines += [f"Největší změna: {c} {'+' if d > 0 else '−'}{kc(abs(d))}." for c, d in changes[:2] if before and abs(d) >= 500]
    return {"year": year, "total": total, "by_category": now_, "previous": before, "lines": lines}


# ------------------------------------------------------------------ the daily look
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    if not due_today(rt, "mx_daily", "09:15", now):
        return said
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("mx_daily", now.date().isoformat()))
    for t in item_reminders(rt, now.date()) + budget_alerts(rt, now.date()) + kids_payday(rt, now.date()):
        rt.notify("Peníze", t, speak=False)
        said.append(t)
    try:
        for t in await watch_check(rt):
            rt.notify("Hlídač ceny", t, speak=False)
            said.append(t)
    except Exception as e:  # noqa: BLE001
        log.debug("price watch: %s", e)
    return said
