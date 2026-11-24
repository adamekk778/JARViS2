"""3.14 Zásilky (návrh 48): parcels from your e-mails – Česká pošta, Zásilkovna, PPL, DPD, GLS, Balíkovna, Alza…

A "shipped" e-mail from a shop or a carrier → the tracking number and the carrier, kept here. Česká pošta (and
Balíkovna) tell where the parcel is through their public tracking (no key needed); Zásilkovna too when you have its
API password in Propojení. For the others JARVIS keeps the tracking link. Every 30 minutes the open parcels are
checked; "připraveno k vyzvednutí" / "doručeno" comes as a notice. "Kde mám balík?" lists them.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

log = logging.getLogger("jarvis.parcels")

SUBJECT = re.compile(r"(zásilk|zasilk|balík|balik|odeslán|odeslan|expedov|na cestě|na ceste|tracking|sledov|shipped|"
                     r"dispatched|doruč|doruc|vyzvednut|parcel|package|packeta|ppl|dpd|gls|balíkovn)", re.I)
LINKS = {
    "cpost": "https://www.postaonline.cz/trackandtrace/-/zasilka/cislo?parcelNumbers={n}",
    "zasilkovna": "https://tracking.packeta.com/cs/?id={n}",
    "ppl": "https://www.ppl.cz/vyhledat-zasilku?shipmentId={n}",
    "dpd": "https://tracking.dpd.de/status/cs_CZ/parcel/{n}",
    "gls": "https://gls-group.com/CZ/cs/sledovani-zasilek?match={n}",
    "alzabox": "https://www.alza.cz/muj-ucet/objednavky.htm",
}
NAMES = {"cpost": "Česká pošta", "zasilkovna": "Zásilkovna", "ppl": "PPL", "dpd": "DPD", "gls": "GLS", "alzabox": "Alza"}
SHOPS = ("alza", "mall", "czc", "datart", "notino", "zalando", "about you", "temu", "aliexpress", "amazon", "rohlik", "kosik",
         "lidl", "ikea", "decathlon", "sportisimo", "mironet", "electroworld", "okay", "kasa", "dr.max", "pilulka", "vinted")
DONE_WORDS = ("doručen", "dodán", "vydán", "převzat", "delivered")
READY_WORDS = ("připraven", "k vyzvednutí", "uložen", "ready for pick", "čeká na vyzvednutí")


def _db(rt: Any) -> Any:
    rt.db.exec("CREATE TABLE IF NOT EXISTS parcels (id INTEGER PRIMARY KEY AUTOINCREMENT, carrier TEXT, number TEXT UNIQUE, "
               "shop TEXT, source TEXT, status TEXT, status_at TEXT, state TEXT, added REAL, checked REAL)")
    return rt.db


def subject_hit(subject: str) -> bool:
    return bool(SUBJECT.search(subject or ""))


def _near(text: str, pos: int, words: tuple[str, ...], span: int = 160) -> bool:
    win = text[max(0, pos - span): pos + span].lower()
    return any(w in win for w in words)


def find(text: str, sender: str = "", sender_name: str = "") -> list[dict]:
    """[{carrier, number, shop}] in a shipping e-mail."""
    text = text or ""
    who = f"{sender} {sender_name}".lower()
    low = text.lower() + " " + who
    shop = next((s.title() for s in SHOPS if s in who), "") or next((s.title() for s in SHOPS if s in low[:400]), "")
    out: list[dict] = []
    seen: set[str] = set()

    def put(carrier: str, number: str) -> None:
        if number not in seen:
            seen.add(number)
            out.append({"carrier": carrier, "number": number, "shop": shop})

    for m in re.finditer(r"(?<![A-Z0-9])([A-Z]{2}\d{9}[A-Z]{2})(?![A-Z0-9])", text):        # UPU S10: RR123456789CZ
        put("cpost", m.group(1))
    for m in re.finditer(r"(?<![A-Z0-9])(D[A-Z]\d{10}[A-Z])(?![A-Z0-9])", text):           # domestic: DR0123456789M
        put("cpost", m.group(1))
    for m in re.finditer(r"(?<![A-Za-z0-9])Z\s?(\d{3})\s?(\d{4})\s?(\d{3})(?!\d)", text):  # Zásilkovna: Z 123 4567 890
        put("zasilkovna", "Z" + "".join(m.groups()))
    carriers = (("ppl", ("ppl",), r"\d{11}"), ("dpd", ("dpd",), r"\d{14}"), ("gls", ("gls",), r"\d{11}"))
    for carrier, words, rx in carriers:
        if not any(w in low for w in words):
            continue
        for m in re.finditer(rf"(?<!\d)({rx})(?!\d)", text):
            if _near(text, m.start(), words + ("sledov", "track", "zásilk", "zasilk", "číslo", "cislo"), 300):
                put(carrier, m.group(1))
    return out


def add(rt: Any, carrier: str, number: str, shop: str = "", source: str = "") -> bool:
    number = re.sub(r"\s+", "", number or "").upper()
    if not number:
        return False
    db = _db(rt)
    if db.one("SELECT id FROM parcels WHERE number=?", (number,)):
        return False
    db.exec("INSERT INTO parcels (carrier, number, shop, source, status, status_at, state, added, checked) VALUES (?,?,?,?,?,?,?,?,?)",
            (carrier, number, shop, source, "", "", "open", time.time(), 0))
    return True


def remove(rt: Any, number: str) -> bool:
    number = re.sub(r"\s+", "", number or "").upper()
    db = _db(rt)
    had = db.one("SELECT id FROM parcels WHERE number=?", (number,)) is not None
    db.exec("DELETE FROM parcels WHERE number=?", (number,))
    return had


def guess_carrier(number: str) -> str:
    n = re.sub(r"\s+", "", number or "").upper()
    if re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}|D[A-Z]\d{10}[A-Z]", n):
        return "cpost"
    if re.fullmatch(r"Z\d{10}", n):
        return "zasilkovna"
    if re.fullmatch(r"\d{14}", n):
        return "dpd"
    if re.fullmatch(r"\d{11}", n):
        return "ppl"
    return ""


def listing(rt: Any, include_done: bool = False) -> list[dict]:
    rows = _db(rt).all("SELECT * FROM parcels " + ("" if include_done else "WHERE state!='done' ") + "ORDER BY added DESC")
    out = []
    for r in rows:
        d = dict(r)
        d["link"] = LINKS.get(d["carrier"], "").format(n=d["number"])
        d["carrier_name"] = NAMES.get(d["carrier"], d["carrier"] or "neznámý dopravce")
        out.append(d)
    return out


def state_of(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in DONE_WORDS):
        return "done"
    if any(w in t for w in READY_WORDS):
        return "ready"
    return "open"


def cpost_status(data: Any) -> tuple[str, str]:
    """(text, date) of the newest state in Česká pošta's answer; ("", "") when it does not know the parcel."""
    try:
        states = data[0]["states"]["state"]
    except (KeyError, IndexError, TypeError):
        return "", ""
    states = [s for s in states if str(s.get("id")) not in ("-3", "-4")]       # -3: "není v evidenci"
    if not states:
        return "", ""
    s = states[-1]
    where = f" ({s['postoffice']})" if s.get("postoffice") else ""
    return f"{s.get('text', '').strip()}{where}", str(s.get("date") or "")


async def track(rt: Any, p: dict) -> tuple[str, str]:
    """(status text, date) from the carrier, or ("", "") when it cannot tell (then the link is the way)."""
    if p["carrier"] == "cpost":
        async with rt.http() as c:
            r = await c.get("https://b2c.cpost.cz/services/ParcelHistory/getDataAsJson",
                            params={"idParcel": p["number"], "language": "cs"}, timeout=15)
        return cpost_status(r.json()) if r.status_code == 200 else ("", "")
    if p["carrier"] == "zasilkovna":
        from . import connectors

        if connectors.configured("zasilkovna"):
            from .connectors import zasilkovna as z

            rec = z._record(await z.rest("packetStatus", packetId=z.packet_id(p["number"])))
            return str(rec.get("statusText") or rec.get("codeText") or ""), str(rec.get("dateTime", ""))[:16].replace("T", " ")
    return "", ""


async def refresh(rt: Any, notify: bool = True) -> list[dict]:
    """Check the open parcels; returns the ones whose state changed."""
    changed = []
    for p in listing(rt):
        try:
            text, when = await track(rt, p)
        except Exception as e:  # noqa: BLE001
            log.debug("parcel %s: %s", p["number"], e)
            continue
        _db(rt).exec("UPDATE parcels SET checked=? WHERE id=?", (time.time(), p["id"]))
        if not text or text == p["status"]:
            continue
        st = state_of(text)
        _db(rt).exec("UPDATE parcels SET status=?, status_at=?, state=? WHERE id=?", (text, when, st, p["id"]))
        p.update(status=text, status_at=when, state=st)
        changed.append(p)
        if notify and st in ("ready", "done"):
            what = f"Balík{' z ' + p['shop'] if p['shop'] else ''} ({p['carrier_name']})"
            rt.notify("Zásilka", f"{what}: {text}.", target="all", speak=st == "ready")
    return changed


def summary(rt: Any) -> str:
    items = listing(rt)
    if not items:
        return "Žádné zásilky na cestě nevidím."
    parts = []
    for p in items[:8]:
        who = (p["shop"] + ", " if p["shop"] else "") + p["carrier_name"]
        parts.append(f"{who}: {p['status'] or 'zatím bez stavu – ' + (p['link'] or p['number'])}")
    return f"Na cestě {len(items)} {'zásilka' if len(items) == 1 else 'zásilky' if len(items) < 5 else 'zásilek'}: " + "; ".join(parts) + "."


async def loop(rt: Any) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await refresh(rt)
            _db(rt).exec("DELETE FROM parcels WHERE state='done' AND added<?", (time.time() - 30 * 86400,))
        except Exception as e:  # noqa: BLE001
            log.debug("parcels: %s", e)
        await asyncio.sleep(30 * 60)
