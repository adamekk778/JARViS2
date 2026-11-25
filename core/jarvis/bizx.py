"""3.20 Firma+ (nápady 281–300 ze stránky „Nápady pro JARVISe“).

- insolvenční rejstřík (281 – veřejné vyhledávání ISIR), hlídání zakázek, změn zákonů a dotačních výzev z tebou zadaných
  zdrojů (282, 296, 300), ARES a spolehlivost plátce DPH (283), rizika ve smlouvách (284), docházka (285)
- cash flow na 3 měsíce (286), směny podle dostupnosti (287), reklamace s 30denní lhůtou (288), žádost podle GDPR (289)
- srovnání dodavatelů (290), cestovní příkaz (291), marže po poplatcích (292), balíček pro účetní (293), malý tým (294)
- smlouva ze šablony (295 – vzor, nech zkontrolovat právníkem), nábor (297), nástup zaměstnance (298), kurzové rozdíly (299)
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import secrets as pysecrets
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bz_attend (id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, t_in REAL, t_out REAL);
CREATE TABLE IF NOT EXISTS bz_claims (id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT, item TEXT, received TEXT, state TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS bz_team (token TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT, task TEXT, done INT DEFAULT 0, ts REAL);
CREATE TABLE IF NOT EXISTS bz_onboard (person TEXT, item TEXT, done INT DEFAULT 0, PRIMARY KEY (person, item));
CREATE TABLE IF NOT EXISTS bz_feeds_seen (h TEXT PRIMARY KEY, ts REAL);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_bizx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._bizx_ready = True
    return rt.db


def kc(v: float) -> str:
    return f"{v:,.0f} Kč".replace(",", " ")


# ------------------------------------------------------------------ (283) ARES, DPH; (281) insolvence
def ico_ok(ico: str) -> bool:
    """The Czech company ID's check digit (mod 11)."""
    d = re.sub(r"\D", "", ico or "").zfill(8)
    if len(d) != 8:
        return False
    s = sum(int(d[i]) * (8 - i) for i in range(7))
    c = (11 - s % 11) % 10
    return c == int(d[7])


def parse_ares(data: dict) -> dict:
    sidlo = data.get("sidlo") or {}
    return {"ico": data.get("ico", ""), "name": data.get("obchodniJmeno", ""), "dic": data.get("dic", ""),
            "address": sidlo.get("textovaAdresa", ""), "since": data.get("datumVzniku", ""), "ended": data.get("datumZaniku", ""),
            "legal_form": data.get("pravniForma", "")}


async def ares(rt: Any, ico: str, client: Any = None) -> dict:
    if not ico_ok(ico):
        raise ValueError("Tohle IČO nemá platný kontrolní součet.")
    d = re.sub(r"\D", "", ico).zfill(8)
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get(f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{d}", timeout=15)
    finally:
        if own:
            await c.aclose()
    if r.status_code == 404:
        raise ValueError("ARES takové IČO nezná.")
    r.raise_for_status()
    return parse_ares(r.json())


VAT_SOAP = ("<soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:roz=\"http://adis.mfcr.cz/rozhraniCRPDPH/\">"
            "<soapenv:Body><roz:StatusNespolehlivyPlatceRequest><roz:dic>{dic}</roz:dic></roz:StatusNespolehlivyPlatceRequest>"
            "</soapenv:Body></soapenv:Envelope>")


def parse_vat(xml: str) -> dict:
    m = re.search(r'nespolehlivyPlatce="(\w+)"', xml)
    accounts = re.findall(r"<(?:\w+:)?(?:standardniUcet|nestandardniUcet)[^>]*?cislo=\"(\d+)\"[^>]*?kodBanky=\"(\d+)\"", xml)
    if not m:
        return {"known": False}
    return {"known": m.group(1) != "NENALEZEN", "unreliable": m.group(1) == "ANO", "accounts": [f"{a}/{b}" for a, b in accounts]}


async def vat_status(rt: Any, dic: str, client: Any = None) -> dict:
    num = re.sub(r"\D", "", dic)
    own = client is None
    c = client or rt.http()
    try:
        r = await c.post("https://adisrws.mfcr.cz/adistc/axis2/services/rozhraniCRPDPH.rozhraniCRPDPHSOAP", content=VAT_SOAP.format(dic=num),
                         headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "getStatusNespolehlivyPlatce"}, timeout=20)
    finally:
        if own:
            await c.aclose()
    return parse_vat(r.text)


def parse_isir(page: str) -> dict:
    t = fold(re.sub(r"<[^>]+>", " ", page))
    if re.search(r"nebyl nalezen zadny|zadne zaznamy|nenalezen", t):
        return {"found": False}
    cases = re.findall(r"\b(INS\s?\d{1,6}/\d{4})\b", re.sub(r"<[^>]+>", " ", page))
    return {"found": bool(cases), "cases": list(dict.fromkeys(c.replace(" ", " ") for c in cases))[:10]}


async def insolvency(rt: Any, ico: str, client: Any = None) -> dict:
    d = re.sub(r"\D", "", ico).zfill(8)
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get("https://isir.justice.cz/isir/ueu/vysledek_lustrace.do", params={"ic": d, "aktualnost": "AKTUALNI_I_UKONCENA"},
                        timeout=20)
    finally:
        if own:
            await c.aclose()
    return {**parse_isir(r.text), "url": f"https://isir.justice.cz/isir/ueu/vysledek_lustrace.do?ic={d}"}


# ------------------------------------------------------------------ (282, 296, 300) zdroje s klíčovými slovy
def parse_feed(xml: str) -> list[dict]:
    items = []
    for block in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", xml, re.S | re.I):
        title = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
        link = re.search(r"<link[^>]*?(?:href=\"([^\"]+)\"[^>]*/?>|>(.*?)</link>)", block, re.S | re.I)
        desc = re.search(r"<(?:description|summary|content)[^>]*>(.*?)</(?:description|summary|content)>", block, re.S | re.I)
        clean = lambda s: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", " ", s or "")).strip()  # noqa: E731
        items.append({"title": " ".join(clean(title.group(1) if title else "").split()),
                      "link": (link.group(1) or link.group(2) or "").strip() if link else "",
                      "text": " ".join(clean(desc.group(1) if desc else "").split())[:400]})
    return items


def feed_hits(items: list[dict], words: list[str], region: str = "") -> list[dict]:
    out = []
    for it in items:
        t = fold(it["title"] + " " + it["text"])
        if any(fold(w) in t for w in words if w) and (not region or fold(region) in t):
            out.append(it)
    return out


async def watch_feeds(rt: Any, feeds: list[str], words: list[str], region: str = "", fetch: Callable[[str], Any] | None = None) -> list[dict]:
    new = []
    for url in feeds[:10]:
        try:
            if fetch is None:
                async with rt.http() as c:
                    xml = (await c.get(url, timeout=20, follow_redirects=True)).text
            else:
                xml = await fetch(url)
        except Exception as e:  # noqa: BLE001
            log.info("feed %s: %s", url, e)
            continue
        for it in feed_hits(parse_feed(xml), words, region):
            h = str(abs(hash(it["link"] or it["title"])) % 10**14)
            if not db(rt).one("SELECT h FROM bz_feeds_seen WHERE h=?", (h,)):
                db(rt).exec("INSERT INTO bz_feeds_seen VALUES (?,?)", (h, time.time()))
                new.append(it)
    return new


# ------------------------------------------------------------------ (284) rizika smluv
CONTRACT_RISKS = [
    (r"smluvni pokut\w*", "Smluvní pokuta", 3), (r"automatick\w* (se )?prodluzuj|prodluzuje se automatick|automaticke prodlouzeni", "Automatické prodloužení", 3),
    (r"jednostrann\w* (zmen|upravi|meni)|(vyhrazuje si|si vyhrazuje) pravo (jednostranne )?(zmenit|upravit)", "Jednostranná změna podmínek", 3),
    (r"vypovedni (lhut|doba)", "Výpovědní lhůta", 1), (r"rozhodci (dolozk|rizeni)|rozhodce", "Rozhodčí doložka", 2),
    (r"omezeni odpovednost|nenese odpovednost|vylucuje odpovednost", "Omezení odpovědnosti", 2),
    (r"urok z prodleni\s*(ve vysi)?\s*(\d+[,.]?\d*)\s*%\s*(denne|za den)", "Vysoký úrok z prodlení", 3),
    (r"zakaz konkurence", "Zákaz konkurence", 2), (r"postoupit pohledavk|postoupeni", "Postoupení pohledávek", 1),
    (r"zaloha\w* (se )?nevrac|nevratn\w* zaloh", "Nevratná záloha", 2), (r"mlcenlivost\w*.{0,80}pokut", "Pokuta za porušení mlčenlivosti", 2),
]


def _fold_map(text: str) -> tuple[str, list[int]]:
    """fold() plus, for every folded character, its index in the original text (to quote the original wording)."""
    out: list[str] = []
    idx: list[int] = []
    space = True
    for i, ch in enumerate(text.lower()):
        if ch.isspace():
            if not space:
                out.append(" ")
                idx.append(i)
            space = True
            continue
        for c in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(c):
                out.append(c)
                idx.append(i)
        space = False
    return "".join(out), idx


def contract_risks(text: str) -> list[dict]:
    t, idx = _fold_map(text or "")
    out = []
    for pat, label, weight in CONTRACT_RISKS:
        m = re.search(pat, t)
        if m:
            a = idx[max(0, m.start() - 90)]
            b = idx[min(len(idx) - 1, m.end() + 120)] + 1
            out.append({"risk": label, "weight": weight, "excerpt": "…" + text[a:b].strip() + "…"})
    return sorted(out, key=lambda r: -r["weight"])


# ------------------------------------------------------------------ (285) docházka
def clock_in(rt: Any, person: str, ts: float | None = None) -> int:
    open_ = db(rt).one("SELECT id FROM bz_attend WHERE person=? AND t_out IS NULL", (person,))
    if open_:
        raise ValueError(f"{person} je už přihlášený(á).")
    cur = db(rt).exec("INSERT INTO bz_attend (person, t_in) VALUES (?,?)", (person, time.time() if ts is None else ts))
    return int(getattr(cur, "lastrowid", 0) or 0)


def clock_out(rt: Any, person: str, ts: float | None = None) -> float:
    row = db(rt).one("SELECT * FROM bz_attend WHERE person=? AND t_out IS NULL ORDER BY t_in DESC LIMIT 1", (person,))
    if not row:
        raise ValueError(f"{person} dnes příchod nemá.")
    t = time.time() if ts is None else ts
    db(rt).exec("UPDATE bz_attend SET t_out=? WHERE id=?", (t, row["id"]))
    return round((t - float(row["t_in"])) / 3600, 2)


def hours(rt: Any, month: str) -> dict[str, float]:
    y, m = (int(x) for x in month.split("-"))
    a = dt.datetime(y, m, 1).timestamp()
    b = dt.datetime(y + (m == 12), m % 12 + 1, 1).timestamp()
    out: dict[str, float] = {}
    for r in db(rt).all("SELECT person, t_in, t_out FROM bz_attend WHERE t_in >= ? AND t_in < ? AND t_out IS NOT NULL", (a, b)):
        out[r["person"]] = round(out.get(r["person"], 0) + (float(r["t_out"]) - float(r["t_in"])) / 3600, 2)
    return out


# ------------------------------------------------------------------ (286) cash flow, (292) marže, (299) kurzové rozdíly
def forecast(balance: float, monthly_in: float, monthly_out: float, one_offs: list[tuple[str, float]] | None = None, months: int = 3,
             start: dt.date | None = None) -> list[dict]:
    """Month by month: the balance with the usual income and spending and the known one-offs (+ income, − payment)."""
    start = start or dt.date.today()
    rows, bal = [], balance
    for k in range(months):
        y, m = start.year + (start.month - 1 + k) // 12, (start.month - 1 + k) % 12 + 1
        extra = sum(v for d, v in (one_offs or []) if d[:7] == f"{y}-{m:02d}")
        bal = bal + monthly_in - monthly_out + extra
        rows.append({"month": f"{m}/{y}", "balance": round(bal), "low": bal < 0})
    return rows


def margin(price: float, cost: float, fee_pct: float = 0, shipping: float = 0, vat_pct: float = 21, price_with_vat: bool = True) -> dict:
    net = price / (1 + vat_pct / 100) if price_with_vat else price
    fees = net * fee_pct / 100
    profit = net - cost - fees - shipping
    return {"net_price": round(net, 2), "fees": round(fees, 2), "profit": round(profit, 2), "margin_pct": round(profit / net * 100, 1) if net else 0,
            "markup_pct": round(profit / cost * 100, 1) if cost else None}


async def cnb_rate(rt: Any, currency: str, day: dt.date, client: Any = None) -> float:
    from .finance import parse_cnb

    own = client is None
    c = client or rt.http()
    try:
        r = await c.get("https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt",
                        params={"date": f"{day:%d.%m.%Y}"}, timeout=15)
    finally:
        if own:
            await c.aclose()
    rates = parse_cnb(r.text)
    if currency.upper() not in rates:
        raise ValueError(f"Kurz {currency} ČNB nevede.")
    return rates[currency.upper()]


def fx_difference(amount: float, rate_issue: float, rate_paid: float) -> dict:
    a, b = amount * rate_issue, amount * rate_paid
    d = round(b - a, 2)
    return {"issued_czk": round(a, 2), "paid_czk": round(b, 2), "difference": d,
            "kind": "kurzový zisk" if d > 0 else "kurzová ztráta" if d < 0 else "bez rozdílu"}


# ------------------------------------------------------------------ (287) směny
def plan_shifts(days: list[str], shifts: list[str], available: dict[str, list[str]], need: int = 1) -> dict:
    """available: person → ["po-ranní", "út-odpolední"…]. Fair: the person with the fewest shifts so far gets the slot."""
    count = {p: 0 for p in available}
    plan: dict[str, list[str]] = {}
    gaps = []
    for d in days:
        for s in shifts:
            slot = f"{d}-{s}"
            cand = sorted((p for p, av in available.items() if slot in av), key=lambda p: (count[p], p))
            pick = cand[:need]
            for p in pick:
                count[p] += 1
            plan[slot] = pick
            if len(pick) < need:
                gaps.append(slot)
    return {"plan": plan, "count": count, "gaps": gaps}


# ------------------------------------------------------------------ (288) reklamace
def claim_add(rt: Any, customer: str, item: str, received: str = "") -> int:
    cur = db(rt).exec("INSERT INTO bz_claims (customer, item, received, state, note) VALUES (?,?,?,?,?)",
                      (customer[:80], item[:120], received or dt.date.today().isoformat(), "přijato", ""))
    return int(getattr(cur, "lastrowid", 0) or 0)


def claims_due(rt: Any, today: dt.date) -> list[dict]:
    out = []
    for r in db(rt).all("SELECT * FROM bz_claims WHERE state != 'vyřízeno'"):
        left = 30 - (today - dt.date.fromisoformat(r["received"])).days
        if left <= 7:
            out.append({**dict(r), "left": left})
    return sorted(out, key=lambda x: x["left"])


def claim_close(rt: Any, cid: int, note: str = "") -> bool:
    had = db(rt).one("SELECT id FROM bz_claims WHERE id=?", (int(cid),))
    db(rt).exec("UPDATE bz_claims SET state='vyřízeno', note=? WHERE id=?", (note[:200], int(cid)))
    return bool(had)


# ------------------------------------------------------------------ (289) GDPR
def gdpr_find(rt: Any, who: str) -> dict:
    """What JARVIS itself keeps about someone (memory, notes, the team board, claims…); other systems are a checklist."""
    f = fold(who)
    found: dict[str, list[str]] = {}
    for table, col in (("facts", "text"), ("wk_notes", "text"), ("bz_claims", "customer"), ("bz_team", "who"), ("mx_spend", "note")):
        try:
            rows = rt.db.all(f"SELECT rowid AS rid, {col} AS v FROM {table}")  # noqa: S608 – fixed table names
        except Exception:  # noqa: BLE001
            continue
        hits = [str(r["v"]) for r in rows if f and f in fold(str(r["v"]))]
        if hits:
            found[table] = hits[:50]
    return {"who": who, "found": found, "deadline_days": 30,
            "elsewhere": ["e-mailová schránka", "účetnictví (doklady se musí uchovat ze zákona)", "CRM / e-shop", "zálohy"]}


def gdpr_delete(rt: Any, who: str) -> int:
    f = fold(who)
    n = 0
    for table, col in (("facts", "text"), ("wk_notes", "text")):
        try:
            rows = rt.db.all(f"SELECT rowid AS rid, {col} AS v FROM {table}")  # noqa: S608
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            if f and f in fold(str(r["v"])):
                rt.db.exec(f"DELETE FROM {table} WHERE rowid=?", (r["rid"],))  # noqa: S608
                n += 1
    return n


# ------------------------------------------------------------------ (290) dodavatelé
def compare_suppliers(rows: list[dict]) -> list[dict]:
    """rows: {item, supplier, price, (delivery_days)} → per item the cheapest and how much the others cost more."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(fold(str(r["item"])), []).append(r)
    out = []
    for _k, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda r: float(r["price"]))
        best = rs[0]
        out.append({"item": best["item"], "best": best["supplier"], "price": float(best["price"]),
                    "others": [{"supplier": r["supplier"], "more_pct": round((float(r["price"]) / float(best["price"]) - 1) * 100, 1)} for r in rs[1:]]})
    return out


# ------------------------------------------------------------------ (291) cestovní příkaz
def travel_order_html(name: str, start: str, end: str, dest: str, purpose: str, transport: str, per_diem: dict, km: float = 0,
                      rate_km: float = 0) -> str:
    esc = html.escape
    km_line = f"<tr><td>Náhrada za km</td><td>{km:.0f} km × {rate_km:.2f} Kč = {km * rate_km:,.0f} Kč</td></tr>".replace(",", " ") if km else ""
    return ("<!doctype html><meta charset=utf-8><title>Cestovní příkaz</title><style>body{font:14px system-ui;max-width:760px;margin:24px auto}"
            "td{border:1px solid #ccc;padding:6px 10px}table{border-collapse:collapse;width:100%}</style><h1>Cestovní příkaz</h1><table>"
            f"<tr><td>Zaměstnanec</td><td>{esc(name)}</td></tr><tr><td>Začátek cesty</td><td>{esc(start)}</td></tr>"
            f"<tr><td>Konec cesty</td><td>{esc(end)}</td></tr><tr><td>Místo jednání</td><td>{esc(dest)}</td></tr>"
            f"<tr><td>Účel</td><td>{esc(purpose)}</td></tr><tr><td>Doprava</td><td>{esc(transport)}</td></tr>"
            f"<tr><td>Stravné</td><td>{esc(str(per_diem.get('text') or per_diem.get('total') or ''))}</td></tr>{km_line}</table>"
            "<p>Podpis zaměstnance: ____________ &nbsp; Schválil: ____________</p>")


# ------------------------------------------------------------------ (293) balíček pro účetní
INVOICE_NAME = re.compile(r"(faktur|invoice|uctenk|doklad|danovy|receipt|dobropis|zalohov)", re.I)


def accountant_pack(rt: Any, month: str, out: Path) -> dict:
    """The month's documents (files named like invoices / receipts) + the logbook and the summary CSV in one ZIP."""
    y, m = (int(x) for x in month.split("-"))
    a = dt.datetime(y, m, 1).timestamp()
    b = dt.datetime(y + (m == 12), m % 12 + 1, 1).timestamp()
    rows = rt.db.all("SELECT * FROM attachments WHERE created >= ? AND created < ?", (a, b)) if rt.db.one(
        "SELECT name FROM sqlite_master WHERE name='attachments'") else []
    files = [r for r in rows if INVOICE_NAME.search(fold(r["name"] or "")) and r["path"] and Path(r["path"]).exists()]
    out.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for r in files:
            name = Path(r["name"]).name or "doklad"
            stem, suf, n = Path(name).stem, Path(name).suffix, 2
            while name in used:                                   # two documents with the same name
                name, n = f"{stem}-{n}{suf}", n + 1
            used.add(name)
            z.write(r["path"], f"doklady/{name}")
        try:
            from .carx import logbook_csv

            z.writestr(f"kniha-jizd-{month}.csv", logbook_csv(rt, month))
        except Exception:  # noqa: BLE001
            pass
        z.writestr("prehled.csv", "soubor;velikost\n" + "\n".join(f"{r['name']};{r['size']}" for r in files))
    return {"path": str(out), "documents": len(files)}


# ------------------------------------------------------------------ (294) malý tým
def team_create(rt: Any) -> str:
    tok = pysecrets.token_urlsafe(12)
    db(rt).exec("INSERT INTO bz_team (token, who, task, done, ts) VALUES (?,?,?,?,?)", (tok, "JARVIS", "Vítejte – přidejte první úkol", 1, time.time()))
    return tok


def team_tasks(rt: Any, tok: str) -> list[dict] | None:
    rows = [dict(r) for r in db(rt).all("SELECT * FROM bz_team WHERE token=? ORDER BY done, ts DESC", (tok,))]
    return rows or None


def team_add(rt: Any, tok: str, who: str, task: str) -> bool:
    if team_tasks(rt, tok) is None or not task.strip():
        return False
    if db(rt).one("SELECT COUNT(*) n FROM bz_team WHERE token=?", (tok,))["n"] >= 300:
        return False
    db(rt).exec("INSERT INTO bz_team (token, who, task, done, ts) VALUES (?,?,?,?,?)", (tok, who.strip()[:30] or "někdo", task.strip()[:200], 0, time.time()))
    return True


def team_done(rt: Any, tok: str, tid: int) -> bool:
    had = db(rt).one("SELECT id FROM bz_team WHERE token=? AND id=?", (tok, int(tid)))
    db(rt).exec("UPDATE bz_team SET done=1, ts=? WHERE token=? AND id=?", (time.time(), tok, int(tid)))
    return bool(had)


def team_page(tok: str, tasks: list[dict]) -> str:
    esc = html.escape
    rows = "".join(f"<li class={'done' if t['done'] else ''}><b>{esc(t['who'])}</b>: {esc(t['task'])}" +
                   ("" if t["done"] else f" <form method=post action='/team/{esc(tok)}/done/{t['id']}' style=display:inline><button>✓</button></form>")
                   + "</li>" for t in tasks)
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Tým</title>"
            "<meta http-equiv=refresh content=60><style>body{font:16px system-ui;margin:20px;background:#0b0f14;color:#e8eef5}.done{opacity:.45;"
            "text-decoration:line-through}button,input{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid #334}</style>"
            f"<h1>Úkoly týmu</h1><ul>{rows}</ul><form method=post action='/team/{esc(tok)}'><input name=who placeholder=Kdo maxlength=30> "
            "<input name=task placeholder='Úkol' maxlength=200 required> <button>Přidat</button></form>")


# ------------------------------------------------------------------ (295) smlouvy ze šablony
TEMPLATES = {
    "nda": ("Dohoda o mlčenlivosti", ["Smluvní strany: {my_name}, IČO {my_ico}, {my_address} (dále jen „Strana A“) a {name}, IČO {ico}, "
                                       "{address} (dále jen „Strana B“).", "1. Předmětem dohody je ochrana důvěrných informací, které si "
                                       "strany sdělí v souvislosti s: {purpose}.", "2. Strany se zavazují důvěrné informace nezpřístupnit "
                                       "třetím osobám a použít je jen k uvedenému účelu.", "3. Povinnost mlčenlivosti trvá {years} let od "
                                       "podpisu.", "4. Dohoda se řídí právem České republiky.", "V {city} dne {date}"]),
    "dilo": ("Smlouva o dílo", ["Objednatel: {name}, IČO {ico}, {address}. Zhotovitel: {my_name}, IČO {my_ico}, {my_address}.",
                                "1. Zhotovitel se zavazuje provést dílo: {purpose}.", "2. Termín dokončení: {deadline}.",
                                "3. Cena díla: {price} Kč, splatná do 14 dnů od předání díla na základě faktury.",
                                "4. Dílo se považuje za předané podpisem předávacího protokolu.", "5. Smlouva se řídí zákonem č. 89/2012 Sb., "
                                "občanský zákoník.", "V {city} dne {date}"]),
}


def contract_from_template(kind: str, data: dict) -> str:
    if kind not in TEMPLATES:
        raise ValueError("Šablony: nda, dilo.")
    title, lines = TEMPLATES[kind]
    vals = {"date": dt.date.today().strftime("%d. %m. %Y"), "years": "3", "city": "Praze", **{k: str(v) for k, v in data.items()}}
    body = "\n\n".join(re.sub(r"\{(\w+)\}", lambda m: vals.get(m.group(1), f"[{m.group(1)}]"), ln) for ln in lines)
    return f"{title}\n\n{body}\n\n______________________          ______________________\n\nVzor – před podpisem nech zkontrolovat právníkem."


# ------------------------------------------------------------------ (297) nábor, (298) nástup
def cv_score(text: str, must: list[str], nice: list[str] | None = None) -> dict:
    t = fold(text)
    have = [w for w in must if fold(w) in t]
    bonus = [w for w in (nice or []) if fold(w) in t]
    score = round((len(have) / max(1, len(must))) * 80 + (len(bonus) / max(1, len(nice or [1]))) * 20)
    years = re.findall(r"(\d{1,2})\s*(?:\+\s*)?(?:let|roky|roku|years)", t)
    return {"score": score, "has": have, "missing": [w for w in must if w not in have], "bonus": bonus,
            "years": max((int(y) for y in years), default=None)}


ONBOARD = ["Pracovní smlouva a prohlášení k dani podepsané", "Přihláška na zdravotní pojišťovnu a ČSSZ", "Vstupní lékařská prohlídka",
           "Školení BOZP", "Notebook a telefon připravené", "E-mail a přístupy (účty, VPN, sdílené disky)", "Klíče / karta do budovy",
           "Představení týmu a mentor", "Plán prvních 30 dní", "Kontrola po prvním týdnu"]


def onboard_start(rt: Any, person: str) -> int:
    for item in ONBOARD:
        db(rt).exec("INSERT OR IGNORE INTO bz_onboard VALUES (?,?,0)", (person, item))
    return len(ONBOARD)


def onboard_tick(rt: Any, person: str, item: str) -> dict:
    f = fold(item)
    row = next((r for r in db(rt).all("SELECT * FROM bz_onboard WHERE person=?", (person,)) if f in fold(r["item"])), None)
    if row:
        db(rt).exec("UPDATE bz_onboard SET done=1 WHERE person=? AND item=?", (person, row["item"]))
    left = [r["item"] for r in db(rt).all("SELECT item FROM bz_onboard WHERE person=? AND done=0", (person,))]
    return {"ticked": row["item"] if row else "", "left": left}


# ------------------------------------------------------------------ the daily look
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    if not due_today(rt, "bz_daily", "08:20", now):
        return said
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("bz_daily", now.date().isoformat()))
    for c in claims_due(rt, now.date()):
        t = f"Reklamace #{c['id']} ({c['customer']}, {c['item']}): " + ("lhůta 30 dní už uplynula!" if c["left"] < 0 else f"zbývá {c['left']} dní.")
        rt.notify("Reklamace", t, speak=False)
        said.append(t)
    cfg = getattr(rt.cfg, "bizx", None)
    if cfg is not None and cfg.feeds and cfg.feed_words:
        try:
            for it in await watch_feeds(rt, cfg.feeds, cfg.feed_words, cfg.region):
                t = f"{it['title']} {it['link']}".strip()
                rt.notify("Nové ve tvém oboru", t, speak=False)
                said.append(t)
        except Exception as e:  # noqa: BLE001
            log.debug("feeds: %s", e)
    return said

