"""3.18 Cesty: hotels and flights by your description, compared, booked and paid only after your confirmation.

"Najdi hotel v Římě na 3 noci od pátku do 150 € za noc, blízko centra, se snídaní" → hotel_search → 3–5 offers with
why, the total, the cancellation terms (a card in the chat). "Beru dvojku" → travel_book: asks twice (the second time
with the exact amount; to the phone with the fingerprint), checks the price again right before paying, then books.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Annotated, Any

from .base import ToolResult, tool
from .. import clock


def _money(amount: float, cur: str) -> str:
    return f"{float(amount):,.2f} {cur}".replace(",", " ").replace(".00 ", " ")


def _provider(ctx: Any, want: str = "") -> str:
    from .. import booking

    want = (want or getattr(ctx.cfg.booking, "provider", "") or "").lower()
    if want in ("browser", "prohlížeč"):
        return "browser"
    if want == "liteapi" and booking.lite_key():
        return "liteapi"
    if want == "duffel" and booking.duffel_key():
        return "duffel"
    return "liteapi" if booking.lite_key() else "duffel" if booking.duffel_key() else "browser"


async def _open_site(ctx: Any, site: str, c: dict) -> ToolResult:
    """Without a key: the booking site in JARVIS' browser with everything filled in – it stops before paying."""
    from .. import travelsearch
    from . import call

    url = travelsearch.site_url(site, c)
    r = await call("browser_open", {"url": url}, ctx)
    how = ("Otevřel jsem to v prohlížeči JARVISe s vyplněným hledáním. Vyber, já vyplním údaje – a před tlačítkem "
           "Zaplatit / Rezervovat se vždycky zastavím a zeptám.")
    if not r.ok:
        r = await call("open_url", {"url": url}, ctx)
        how = "Otevřel jsem hledání v prohlížeči. (Rychlejší je klíč LiteAPI nebo Duffel – Nastavení → Propojení.)"
    return ToolResult(r.ok, how if r.ok else f"Stránku jsem neotevřel: {r.summary}", data={"url": url, "criteria": c})


def _criteria_line(c: dict) -> str:
    bits = [c.get("city") or "", f"{c.get('checkin', '')} – {c.get('checkout', '')}", f"{c.get('adults', 2)} dosp."]
    if c.get("max_per_night"):
        bits.append(f"do {c['max_per_night']:g} {c.get('currency', '')}/noc")
    if c.get("must"):
        bits.append(", ".join(c["must"]))
    return " · ".join(b for b in bits if b.strip(" –·"))


async def _center(ctx: Any, c: dict) -> tuple[float, float] | None:
    from .. import travel

    near = (c.get("near") or "").strip()
    q = c["city"] if not near or "centr" in near.lower() else f"{near}, {c['city']}"
    return await travel.geocode(ctx, q)


async def _hotels(ctx: Any, c: dict, provider: str, transport: Any = None) -> list[dict]:
    from .. import booking

    if provider == "liteapi":
        return await booking.lite_search(ctx, c, transport)
    return await booking.duffel_stays_search(ctx, c, transport)


def _with_dates(offers: list[dict], c: dict) -> list[dict]:
    for o in offers:
        o.setdefault("checkin", c.get("checkin", ""))
        o.setdefault("checkout", c.get("checkout", ""))
        if not o.get("city"):
            o["city"] = c.get("city", "")
        o["criteria"] = {k: c.get(k) for k in ("city", "country", "checkin", "checkout", "adults", "children", "rooms", "must",
                                                "currency", "with")}
    return offers


def _card(offers: list[dict], title: str) -> dict:
    return {"title": title, "offers": [{k: o.get(k) for k in (
        "n", "kind", "name", "stars", "rating", "total", "currency", "per_night", "nights", "km", "why", "refundable",
        "free_cancel_until", "pay_at_property", "breakfast", "legs", "photo", "lat", "lon")} for o in offers]}


# ------------------------------------------------------------------------------------------ search
@tool("hotel_search", "Najde hotel podle popisu („Řím, 3 noci od pátku, do 150 € za noc, blízko centra, snídaně, zrušení "
      "zdarma, jako minule“): vybere 3–5 nejlepších nabídek s důvodem, celkovou cenou a podmínkami zrušení. Rezervace pak "
      "travel_book s číslem nabídky. Bez klíče otevře Booking.com / Airbnb s vyplněným hledáním.", category="cesty", perm="network")
async def hotel_search(ctx, description: Annotated[str, "popis vlastními slovy uživatele (kam, kdy, kolik, co musí mít)"],
                       provider: Annotated[str, "liteapi / duffel / browser / airbnb (prázdné = co je nastavené)"] = "") -> ToolResult:
    from .. import booking, money, travelsearch

    await money.ensure_rates(ctx)
    c, missing = await travelsearch.understand(ctx, description)
    c["kind"] = "hotel"
    missing = [m for m in missing if m in ("kam (město)", "od kdy", "do kdy")]
    if missing:
        return ToolResult(True, "Ještě potřebuju vědět: " + ", ".join(missing) + ".", data={"criteria": c, "missing": missing})
    prov = "airbnb" if (provider or "").lower() == "airbnb" else _provider(ctx, provider)
    if prov in ("browser", "airbnb"):
        return await _open_site(ctx, "airbnb" if prov == "airbnb" else "booking", c)
    try:
        found = await _hotels(ctx, c, prov)
    except booking.BookingError as e:
        return ToolResult(False, str(e))
    if not found:
        return ToolResult(True, f"Pro {_criteria_line(c)} jsem nic volného nenašel. Zkus jiné datum nebo vyšší cenu.", data={"criteria": c})
    p = travelsearch.prefs(ctx)
    b = ctx.cfg.booking
    best = travelsearch.rank(found, c, p, await _center(ctx, c), b.prefer_free_cancel, b.prefer_pay_at_hotel)
    if not best:
        return ToolResult(True, f"Našel jsem {len(found)} hotelů, ale žádný nesplní všechno ({_criteria_line(c)}). Mám povolit "
                                "vyšší cenu nebo horší hodnocení?", data={"criteria": c})
    booking.remember(ctx, _with_dates(best, c))
    lines = [travelsearch.line(o) for o in best]
    test = " (zkušební klíč – nic se nezaplatí)" if prov == "liteapi" and booking.sandbox() else ""
    from .. import entryreq

    entry = entryreq.warn(ctx, c.get("country") or "")
    return ToolResult(True, f"{_criteria_line(c)}{test}:\n" + "\n".join(lines) + "\nKterou chceš? Řekni číslo."
                      + (f"\n{entry}" if entry else ""),
                      data={"criteria": c, "offers": best, "card": _card(best, c.get("city", ""))})


@tool("flight_search", "Najde letenky podle popisu („z Prahy do Lisabonu 12. 3., zpátky 16. 3., jen přímé“): nejlevnější a "
      "nejrychlejší, přestupy, zavazadla podle aerolinky. Rezervace pak travel_book. Bez klíče Duffel otevře Google Flights.",
      category="cesty", perm="network")
async def flight_search(ctx, description: Annotated[str, "popis vlastními slovy (odkud, kam, kdy, zpátky, přímé)"]) -> ToolResult:
    from .. import booking, money, travelsearch

    await money.ensure_rates(ctx)
    c, missing = await travelsearch.understand(ctx, description)
    c["kind"] = "flight"
    missing = [m for m in missing if m in ("odkud letíš", "kam letíš", "kdy letíš")]
    if missing:
        return ToolResult(True, "Ještě potřebuju vědět: " + ", ".join(missing) + " (stačí město).", data={"criteria": c, "missing": missing})
    if not booking.duffel_key():
        return await _open_site(ctx, "google_flights", c)
    try:
        found = await booking.flight_search(ctx, c)
    except booking.BookingError as e:
        return ToolResult(False, str(e))
    if c.get("direct"):
        found = [o for o in found if all(lg["stops"] == 0 for lg in o["legs"])] or found
    if not found:
        return ToolResult(True, f"Let {c['origin']}→{c['destination']} {c['date']} jsem nenašel.", data={"criteria": c})

    def hours(o: dict) -> float:
        try:
            return sum((dt.datetime.fromisoformat(lg["arr"][:19]) - dt.datetime.fromisoformat(lg["dep"][:19])).total_seconds()
                       for lg in o["legs"]) / 3600
        except (TypeError, ValueError, KeyError):
            return 99.0
    cheapest = min(found, key=lambda o: o["total"])
    fastest = min(found, key=hours)
    pick = [cheapest] + [o for o in [fastest] + sorted(found, key=lambda o: (o["total"], hours(o))) if o is not cheapest]
    best: list[dict] = []
    for o in pick:
        if o not in best:
            best.append(o)
        if len(best) == 4:
            break
    for o in best:
        why = (["nejlevnější"] if o is cheapest else []) + (["nejrychlejší"] if o is fastest else [])
        o["why"] = ", ".join(why + (["lze vrátit"] if o.get("refundable") else []))
        o.setdefault("checkin", c["date"])
        o.setdefault("checkout", c.get("return_date") or c["date"])
        o["city"] = c["destination"]
        o["criteria"] = {k: c.get(k) for k in ("origin", "destination", "date", "return_date", "adults", "children", "with")}
    booking.remember(ctx, best)
    from .. import entryreq

    entry = entryreq.warn(ctx, best[0].get("country") or "")
    return ToolResult(True, "\n".join(travelsearch.line(o) for o in best) + "\nKterý chceš? Řekni číslo." + (f"\n{entry}" if entry else ""),
                      data={"criteria": c, "offers": best, "card": _card(best, f"{c['origin']} → {c['destination']}")})


@tool("travel_offers", "Ukáže znovu nabídky z posledního hledání hotelu nebo letu (platí 30 minut).", category="cesty", perm="network")
async def travel_offers(ctx) -> ToolResult:
    from .. import booking, travelsearch

    offers = sorted(booking._offers(ctx).values(), key=lambda o: o["n"])
    if not offers:
        return ToolResult(True, "Žádné aktuální nabídky nemám – řekni, co mám najít.")
    return ToolResult(True, "\n".join(travelsearch.line(o) for o in offers), data={"offers": offers, "card": _card(offers, "Nabídky")})


# ------------------------------------------------------------------------------------------ book (asks twice, always)
def _book_details(a: dict, ctx: Any = None) -> list[str]:
    """What the confirmation shows in full: the hotel or flight, dates, the total, the terms, the limits."""
    if ctx is None:
        return []
    from .. import booking, travelsearch

    off = booking.offer(ctx, a.get("option"))
    if not off:
        return ["Tahle nabídka už neplatí – hledej znovu."]
    out = [f"{'Let' if off['kind'] == 'flight' else 'Hotel'}: {off.get('name', '')}"]
    if off["kind"] == "flight":
        out += [f"{lg['from']} → {lg['to']}: {str(lg['dep'])[:16].replace('T', ' ')}"
                + (f", {lg['stops']}× přestup" if lg["stops"] else ", přímý") for lg in off.get("legs") or []]
    else:
        out.append(f"{off.get('checkin', '')} – {off.get('checkout', '')} ({off.get('nights', 1)} noci), {off.get('room') or 'pokoj'}"
                   + (f", {off['board']}" if off.get("board") else ""))
        if off.get("address"):
            out.append(off["address"])
    from ..money import rate_note

    czk = "" if off["currency"].upper() == "CZK" else \
        f" (~{booking.to_czk(off['total'], off['currency']):,.0f} Kč, {rate_note()})".replace(",", " ")
    out.append(f"Celkem: {_money(off['total'], off['currency'])}{czk}")
    if off.get("refundable"):
        out.append("Zrušení zdarma" + (f" do {travelsearch.fmt_when(off['free_cancel_until'])}" if off.get("free_cancel_until") else ""))
    else:
        out.append("NEVRATNÉ – po rezervaci peníze nevrátí.")
    out.append("Platí se na hotelu." if off.get("pay_at_property") else
               ("Platba: zůstatek v Duffel." if off["provider"] == "duffel" else
                f"Platba: {'karta uložená v LiteAPI' if ctx.cfg.booking.liteapi_payment == 'ACC_CREDIT_CARD' else 'peněženka LiteAPI'}."))
    why = booking.limit_problem(ctx, off["total"], off["currency"])
    out.append(f"Limit: {why}" if why else "Limit a měsíční rozpočet: v pořádku.")
    out.append("Těsně před platbou cenu ověřím znovu – když se změní, nic nezaplatím.")
    if booking.sandbox() and off["provider"] == "liteapi":
        out.append("Zkušební klíč – nic se nezaplatí.")
    return out


@tool("travel_book", "Zarezervuje a ZAPLATÍ nabídku z hotel_search / flight_search podle čísla. Vždy se ptá dvakrát (podruhé s "
      "přesnou částkou), na telefonu s otiskem prstu; těsně před platbou ověří cenu znovu. expected_total = celková cena té "
      "nabídky, jak ji uživatel slyšel. Jen na výslovný pokyn uživatele („beru dvojku“, „rezervuj to“).",
      category="cesty", perm="network", danger=True, details=_book_details)
async def travel_book(ctx, option: Annotated[int, "číslo nabídky (1, 2, 3…)"],
                      expected_total: Annotated[float, "celková cena té nabídky"],
                      currency: Annotated[str, "měna té ceny (EUR, CZK…)"],
                      business: Annotated[bool, "služební cesta (náklady pro účetní)"] = False) -> ToolResult:
    from .. import booking, travelsearch, tripcare

    off = booking.offer(ctx, option)
    if not off:
        return ToolResult(False, "Tahle nabídka už neplatí (nabídky vydrží 30 minut) – řekni, ať hledám znovu.")
    if (currency or "").upper() != off["currency"].upper() or booking.price_changed(off["total"], off["currency"],
                                                                                    float(expected_total or 0), currency):
        return ToolResult(False, f"Částka nesouhlasí: nabídka {option} stojí {_money(off['total'], off['currency'])}, ne "
                                 f"{_money(expected_total, currency)}. NEPROVEDENO – řekni uživateli správnou cenu.")
    try:
        res = await booking.book(ctx, off, business=business)
    except booking.BookingError as e:
        return ToolResult(False, f"Nerezervováno: {e}.")
    except Exception as e:  # noqa: BLE001 – an unknown answer from the provider: say so, never guess it went through
        return ToolResult(False, f"Rezervace skončila chybou ({e}). Nevím jistě, jestli proběhla – podívej se do e-mailu "
                                 "nebo do účtu poskytovatele, než to zkusíš znovu.")
    b = {"kind": off["kind"], "name": off.get("name", ""), "city": off.get("city", ""), "start": off.get("checkin", ""),
         "end": off.get("checkout", ""), "total": res["total"], "currency": res["currency"], "ref": res["ref"],
         "free_cancel_until": off.get("free_cancel_until", ""), "pay_at_property": off.get("pay_at_property"), "business": business}
    if off.get("legs"):
        b["start"], b["end"] = off["legs"][0]["dep"], off["legs"][-1]["arr"]
    travelsearch.learn(ctx, off, off.get("criteria") or {})
    done = await tripcare.after_booking(ctx, b, res, off)
    booking._offers(ctx).clear()                       # one booking per search: no second payment by repeating it
    head = "ZKUŠEBNÍ rezervace hotová (nic se nezaplatilo)" if res.get("sandbox") else "Hotovo, rezervováno"
    return ToolResult(True, f"{head}: {off.get('name', '')}, {_money(res['total'], res['currency'])}, číslo "
                            f"{res.get('confirmation') or res['ref']}. Zapsal jsem: {', '.join(done)}.",
                      data={"booking": {**b, "id": res.get("id"), "confirmation": res.get("confirmation")}})


# ------------------------------------------------------------------------------------------ after
@tool("booking_list", "Moje rezervace hotelů a letů od JARVISe: kdy, kde, cena, do kdy zrušení zdarma.", category="cesty", perm="network")
async def booking_list(ctx, past: Annotated[bool, "i proběhlé"] = False) -> ToolResult:
    from .. import booking, travelsearch

    rows = [b for b in booking.bookings(ctx, include_past=past) if b["status"] != "cancelled" or past]
    if not rows:
        return ToolResult(True, "Žádnou rezervaci od JARVISe nemáš.", data={"bookings": []})
    lines = [f"{b['id']}) {'let' if b['kind'] == 'flight' else 'hotel'} {b['name']} {str(b['start'])[:10]} – "
             f"{_money(b['total'], b['currency'])}" + (" (zrušeno)" if b["status"] == "cancelled" else "")
             + (f", zrušení zdarma do {travelsearch.fmt_when(b['free_cancel_until'])}" if b.get("free_cancel_until") and
                b["status"] != "cancelled" else "") + (" – zkušební" if b["sandbox"] else "") for b in rows]
    return ToolResult(True, "\n".join(lines), data={"bookings": rows})


@tool("booking_cancel_check", "Zjistí, za kolik jde rezervace zrušit (zdarma do kdy, poplatek, co se vrátí) – nic neruší.",
      category="cesty", perm="network")
async def booking_cancel_check(ctx, booking_ref: Annotated[str, "číslo z booking_list, název hotelu nebo město"]) -> ToolResult:
    from .. import booking, travelsearch

    b = booking.find_booking(ctx, booking_ref)
    if not b:
        return ToolResult(False, "Takovou rezervaci nenacházím (booking_list ukáže všechny).")
    if b["provider"] == "email":
        free = f" Zdarma jde zrušit do {travelsearch.fmt_when(b['free_cancel_until'])}." if b.get("free_cancel_until") else ""
        return ToolResult(True, f"{b['name']} jsi rezervoval jinde (mám ji z e-mailu) – zrušíš ji tam, kde jsi ji udělal.{free}",
                          data={"booking": b})
    if b["kind"] == "flight":
        try:
            q = await booking.flight_cancel_quote(ctx, b["ref"])
        except booking.BookingError as e:
            return ToolResult(False, str(e))
        ctx.travel_cancel = {"booking": b["id"], "id": q["id"]}
        return ToolResult(True, f"Při zrušení letu {b['name']} vrátí {q['refund'] or 0} {q['currency'] or b['currency']}. "
                                "Mám ho zrušit?", data={"booking": b, "quote": q})
    free = b.get("free_cancel_until") or ""
    if b["refundable"] and free and free > clock.now().isoformat()[:16]:
        say = f"{b['name']}: zrušení je zdarma do {travelsearch.fmt_when(free)}."
    elif b["refundable"]:
        say = f"{b['name']}: zrušení zdarma už skončilo – hotel si může vzít poplatek (řekne ho až při zrušení)."
    else:
        say = f"{b['name']} je nevratná rezervace – zrušením peníze nejspíš nevrátí."
    return ToolResult(True, say + " Mám ji zrušit?", data={"booking": b})


@tool("booking_cancel", "Zruší rezervaci hotelu nebo letu. Vždy se ptá dvakrát; u letu nejdřív booking_cancel_check.",
      category="cesty", perm="network", danger=True)
async def booking_cancel(ctx, booking_ref: Annotated[str, "číslo z booking_list, název hotelu nebo město"]) -> ToolResult:
    from .. import booking

    b = booking.find_booking(ctx, booking_ref)
    if not b:
        return ToolResult(False, "Takovou rezervaci nenacházím.")
    q = getattr(ctx, "travel_cancel", None) or {}
    try:
        res = await booking.cancel(ctx, b, q.get("id", "") if q.get("booking") == b["id"] else "")
    except booking.BookingError as e:
        return ToolResult(False, f"Nezrušeno: {e}.")
    ctx.travel_cancel = None
    fee = f", poplatek {res['fee']} {res.get('currency') or ''}" if res.get("fee") else ""
    back = f", vrátí {res['refund']} {res.get('currency') or ''}" if res.get("refund") else ""
    ok = "cancel" in (res.get("status") or "").lower()
    return ToolResult(ok, (f"Zrušeno: {b['name']}{fee}{back}." if ok else f"Poskytovatel zrušení nepotvrdil (stav {res.get('status')})."),
                      data={"booking": b, "result": res})


@tool("booking_change", "Změna termínu hotelu („posuň Řím o den“): najde stejný hotel na nové termíny; když je volno, nabídne "
      "ho jako nabídku 1 (travel_book), starou rezervaci pak zrušíš (zdarma do…).", category="cesty", perm="network")
async def booking_change(ctx, booking_ref: Annotated[str, "která rezervace"],
                         checkin: Annotated[str, "nový příjezd YYYY-MM-DD"], checkout: Annotated[str, "nový odjezd YYYY-MM-DD"]) -> ToolResult:
    from .. import booking, travelsearch

    b = booking.find_booking(ctx, booking_ref)
    if not b or b["kind"] != "hotel":
        return ToolResult(False, "Měnit umím rezervace hotelů (let = zrušit a najít nový).")
    row = ctx.db.one("SELECT data FROM bookings WHERE id=?", (b["id"],))
    old = (json.loads(row["data"]) or {}).get("offer", {}) if row else {}
    c = {**(old.get("criteria") or {}), "city": b["city"] or old.get("city", ""), "checkin": checkin[:10], "checkout": checkout[:10],
         "currency": b["currency"], "nationality": ctx.cfg.booking.nationality or "CZ"}
    c.setdefault("adults", 2)
    if b["provider"] != "liteapi":
        return ToolResult(True, "U tohohle poskytovatele změnu udělám jako nové hledání: řekni „najdi hotel …“ s novými termíny.")
    try:
        found = await booking.lite_search(ctx, {**c, "city": c["city"]})
    except booking.BookingError as e:
        return ToolResult(False, str(e))
    same = [o for o in found if o.get("hotel_id") == old.get("hotel_id")]
    if not same:
        return ToolResult(True, f"{b['name']} na {checkin} – {checkout} volno nemá. Mám najít jiný hotel?")
    booking.remember(ctx, _with_dates(same[:1], c))
    o = same[0]
    free = f" Starou rezervaci zrušíš zdarma do {travelsearch.fmt_when(b['free_cancel_until'])}." if b.get("free_cancel_until") else ""
    return ToolResult(True, f"{b['name']} {checkin} – {checkout}: {_money(o['total'], o['currency'])} (nabídka 1). Mám ji "
                            f"zarezervovat a pak zrušit tu starou?{free}", data={"offers": [o], "old": b})


@tool("hotel_message", "Napíše hotelu zprávu k rezervaci (pozdní příjezd, postýlka, parkování, tichý pokoj) – jen koncept; "
      "pošle se až po potvrzení přes email_send.", category="cesty", perm="network")
async def hotel_message(ctx, booking_ref: Annotated[str, "která rezervace"],
                        request: Annotated[str, "co hotelu napsat, vlastními slovy"]) -> ToolResult:
    from .. import booking

    b = booking.find_booking(ctx, booking_ref)
    if not b:
        return ToolResult(False, "Takovou rezervaci nenacházím.")
    row = ctx.db.one("SELECT data FROM bookings WHERE id=?", (b["id"],))
    data = json.loads(row["data"]) if row else {}
    g = ctx.cfg.booking
    text = str(await ctx.router.complete([
        {"role": "system", "content": "Napiš krátký zdvořilý e-mail hotelu v angličtině (bez úvodu a vysvětlování, jen předmět "
                                      "na prvním řádku 'Subject: …' a pak text)."},
        {"role": "user", "content": f"Hotel {b['name']}, rezervace {data.get('confirmation') or b['ref']}, {b['start'][:10]} – "
                                    f"{b['end'][:10]}, jméno {g.first_name} {g.last_name}. Požadavek: {request[:500]}"}]) or "").strip()
    subject, _, body = text.partition("\n")
    subject = subject.replace("Subject:", "").strip() or f"Reservation {b['ref']}"
    from ..tripcare import hotel_email

    to = hotel_email(str(data.get("hotel_email") or ""))
    where = (f"Mám ho poslat na {to} (adresa hotelu z potvrzení)? Pošle se až po tvém potvrzení." if to else
             "Mám ho poslat? Adresu hotelu najdeš v potvrzení – řekni mi ji.")
    return ToolResult(True, f"Koncept pro {b['name']}:\nPředmět: {subject}\n{body.strip()}\n{where}",
                      data={"subject": subject, "body": body.strip(), "booking": b, "to": to})


# ------------------------------------------------------------------------------------------ the whole trip, tickets, watches, spend
@tool("trip_plan", "Celá cesta z popisu („víkend v Barceloně z Prahy 12.–15. 3., hotel blízko pláže“): let tam a zpět + hotel, "
      "celková cena a nabídky k rezervaci (každá se potvrzuje zvlášť).", category="cesty", perm="network")
async def trip_plan(ctx, description: Annotated[str, "popis celé cesty vlastními slovy"]) -> ToolResult:
    from .. import booking, travelsearch

    c, missing = await travelsearch.understand(ctx, description)
    if missing:
        return ToolResult(True, "Ještě potřebuju vědět: " + ", ".join(missing) + ".", data={"criteria": c, "missing": missing})
    parts, offers = [], []
    if c.get("origin") and booking.duffel_key():
        try:
            fl = sorted(await booking.flight_search(ctx, {**c, "date": c.get("date") or c["checkin"],
                                                          "return_date": c.get("return_date") or c["checkout"]}),
                        key=lambda o: o["total"])[:1]
        except booking.BookingError as e:
            fl = []
            parts.append(f"Lety: {e}")
        for o in fl:
            o["why"], o["city"] = "nejlevnější let", c.get("destination") or c.get("city")
            o.setdefault("checkin", c.get("date") or c["checkin"])
            o.setdefault("checkout", c.get("return_date") or c["checkout"])
            offers.append(o)
    prov = _provider(ctx)
    if prov != "browser" and c.get("city"):
        try:
            hot = travelsearch.rank(await _hotels(ctx, c, prov), c, travelsearch.prefs(ctx), await _center(ctx, c),
                                    ctx.cfg.booking.prefer_free_cancel, ctx.cfg.booking.prefer_pay_at_hotel, limit=2)
            offers += _with_dates(hot, c)
        except booking.BookingError as e:
            parts.append(f"Hotely: {e}")
    if not offers:
        return await _open_site(ctx, "booking", c)
    booking.remember(ctx, offers)
    total = sum(booking.to_czk(o["total"], o["currency"]) for o in offers if o["kind"] == "flight") + \
        min((booking.to_czk(o["total"], o["currency"]) for o in offers if o["kind"] == "hotel"), default=0)
    return ToolResult(True, "\n".join([travelsearch.line(o) for o in offers] + parts) +
                      f"\nCelkem zhruba {total:,.0f} Kč (let + nejlevnější hotel). Každou část potvrdíš zvlášť – řekni čísla."
                      .replace(",", " "), data={"criteria": c, "offers": offers, "card": _card(offers, c.get("city") or "Cesta")})


@tool("experiences", "Vstupenky a zážitky v cíli (muzea, výlety, koncerty): otevře GetYourGuide s hledáním v prohlížeči "
      "JARVISe; nákup se vždy zastaví před platbou a zeptá se.", category="cesty", perm="network")
async def experiences(ctx, city: str, what: Annotated[str, "co (Vatikánská muzea, výlet lodí…)"] = "") -> ToolResult:
    return await _open_site(ctx, "getyourguide", {"city": city, "what": what})


@tool("travel_watch", "Hlídání ceny: „dej vědět, až bude Řím 12.–15. 3. pod 4 000 Kč“ (hotel nebo let); kontroluje dvakrát "
      "denně a ozve se. action = add / list / stop.", category="cesty", perm="network")
async def travel_watch(ctx, action: Annotated[str, "add / list / stop"] = "list",
                       description: Annotated[str, "co hlídat (u add)"] = "",
                       max_price: Annotated[float, "pod kolik (u add)"] = 0, currency: str = "CZK",
                       watch_id: Annotated[int, "které hlídání zastavit"] = 0) -> ToolResult:
    from .. import travelsearch, tripcare

    a = (action or "list").lower()
    if a == "stop":
        return ToolResult(tripcare.stop_watch(ctx, watch_id), "Hlídání zastaveno." if watch_id else "Řekni které (číslo).")
    if a == "add":
        if max_price <= 0:
            return ToolResult(False, "Řekni, pod kolik má cena klesnout.")
        c, missing = await travelsearch.understand(ctx, description)
        if missing:
            return ToolResult(True, "Ještě potřebuju vědět: " + ", ".join(missing) + ".", data={"missing": missing})
        kind = "flight" if c["kind"] == "flight" else "hotel"
        wid = tripcare.add_watch(ctx, kind, c, max_price, currency)
        what = c.get("city") or f"{c.get('origin')}→{c.get('destination')}"
        return ToolResult(True, f"Hlídám {what} pod {max_price:,.0f} {currency.upper()} – ozvu se.".replace(",", " "), data={"id": wid})
    ws = tripcare.watches(ctx)
    if not ws:
        return ToolResult(True, "Nic nehlídám.", data={"watches": []})
    return ToolResult(True, "; ".join(f"{w['id']}) {w['criteria'].get('city') or w['criteria'].get('destination')} pod "
                                      f"{w['max_price']:,.0f} {w['currency']}".replace(",", " ") +
                                      (f" (naposled {w['last_price']:,.0f})".replace(",", " ") if w["last_price"] else "")
                                      for w in ws), data={"watches": ws})


@tool("travel_spend", "Kolik stály cesty: tento měsíc, letos po měsících, služební zvlášť (rezervace přes JARVISe).",
      category="cesty", perm="network")
async def travel_spend(ctx, year: Annotated[int, "rok (0 = letos)"] = 0) -> ToolResult:
    from .. import money, tripcare

    await money.ensure_rates(ctx)
    s = tripcare.spend(ctx, year or None)
    if not s["trips"]:
        return ToolResult(True, f"V roce {s['year']} jsem přes JARVISe nic nerezervoval.", data=s)
    months = ", ".join(f"{int(m)}. {v:,.0f} Kč".replace(",", " ") for m, v in s["by_month"].items())
    biz = f", z toho služebně {s['business_czk']:,.0f} Kč".replace(",", " ") if s["business_czk"] else ""
    return ToolResult(True, f"Cesty {s['year']}: celkem {s['total_czk']:,.0f} Kč{biz} ({months}).".replace(",", " "), data=s)


# ------------------------------------------------------------------------------------------ 3.19 Cesty 2
@tool("train_search", "Vlak nebo autobus („vlakem z Prahy do Brna v pátek ráno“): RegioJet živě s cenou a volnými místy, "
      "koupě na jeho webu v prohlížeči JARVISe (před platbou se zastaví); ČD, Leo Express a další přes IDOS.",
      category="cesty", perm="network")
async def train_search(ctx, src: Annotated[str, "odkud (město)"], dst: Annotated[str, "kam (město)"],
                       date: Annotated[str, "den YYYY-MM-DD (prázdné = dnes)"] = "",
                       after: Annotated[str, "od kolika hodin HH:MM (prázdné = celý den)"] = "") -> ToolResult:
    from .. import bridges, groundtravel

    day = (date or clock.today().isoformat())[:10]
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return ToolResult(False, "Den zadej jako RRRR-MM-DD.")
    try:
        r = await groundtravel.search(src, dst, day)
    except Exception as e:  # noqa: BLE001
        r = {"error": f"RegioJet teď neodpovídá ({str(e)[:80]})"}
    idos = bridges.idos_link(src, dst, dt.datetime.fromisoformat(f"{day}T{(after or '06:00')[:5]}"), "", "vlakyautobusy")
    if r.get("error"):
        return ToolResult(True, f"{r['error']} Ostatní dopravce (ČD, Leo Express…) najdeš v IDOS: {idos}", data={"idos": idos})
    routes = [x for x in r["routes"] if not after or x["dep"][11:16] >= after[:5]][:6]
    if not routes:
        return ToolResult(True, f"RegioJet {r['from']} → {r['to']} {day}{' po ' + after if after else ''} nic nejede. IDOS: {idos}",
                          data={"idos": idos, **r})
    return ToolResult(True, f"RegioJet {r['from']} → {r['to']} {day}:\n" + "\n".join(groundtravel.line(x) for x in routes)
                      + f"\nKoupit: řekni a otevřu RegioJet (před zaplacením se zastavím). ČD a další: {idos}",
                      data={**r, "routes": routes, "idos": idos})


@tool("entry_requirements", "Co potřebuju do země (pas, občanka, vízum, UK ETA, ESTA, eTA…) jako občan ČR – shrnutí s odkazem "
      "na MZV k ověření.", category="cesty", perm="network")
async def entry_requirements(ctx, country: Annotated[str, "země jako ISO-2 kód (GB, US, TR…)"]) -> ToolResult:
    from .. import entryreq

    r = entryreq.check(country)
    if r["known"] and r.get("ok_with_id") and not r["line"]:
        return ToolResult(True, "V EU a Schengenu ti stačí platný občanský průkaz.", data=r)
    return ToolResult(True, r["line"] or "Řekni zemi.", data=r)


@tool("trip_pack", "Cestovní karta do telefonu, která funguje i bez internetu: kde, kdy, číslo rezervace, adresa s mapou, "
      "storno podmínky, lety a tísňová čísla.", category="cesty", perm="files_write")
async def trip_pack(ctx, booking_ref: Annotated[str, "která rezervace (číslo, hotel nebo město)"]) -> ToolResult:
    from .. import booking, tripcare

    b = booking.find_booking(ctx, booking_ref)
    if not b:
        return ToolResult(False, "Takovou rezervaci nenacházím.")
    p = tripcare.trip_card(ctx, b)
    att = []
    store = getattr(ctx, "store", None)
    if store is not None:
        try:
            att = [(await store.save_path(p, "text/html")).id]
        except Exception:  # noqa: BLE001
            att = []
    ctx.phone_push("notify", title="Cestovní karta", body=f"{b['name']}: karta je v chatu JARVISe – stáhni si ji, funguje i offline.")
    return ToolResult(True, f"Cestovní karta pro {b['name']} je hotová (i ve složce cesty) – v telefonu ji stáhni z chatu.",
                      data={"path": str(p)}, attachments=att)


@tool("travel_allowance", "Cestovní náhrady (stravné) za služební cestu podle zákoníku práce: po dnech, se zkrácením za jídla "
      "zdarma; zapíše je i do tabulky pro účetní.", category="cesty", perm="files_write")
async def travel_allowance(ctx, start: Annotated[str, "začátek YYYY-MM-DDTHH:MM"], end: Annotated[str, "konec YYYY-MM-DDTHH:MM"],
                           country: Annotated[str, "země ISO-2 (CZ = tuzemsko)"] = "CZ",
                           meals: Annotated[int, "kolik jídel denně bylo zdarma (snídaně v hotelu = 1)"] = 0,
                           save: Annotated[bool, "zapsat do naklady.csv"] = True) -> ToolResult:
    import csv

    from .. import tripcare

    r = tripcare.per_diem(ctx, start, end, country, meals)
    if not r["ok"]:
        return ToolResult(False, r["why"].capitalize() + ".")
    days = "; ".join(f"{d['day'][8:10]}. {d['day'][5:7]}. {d['hours']:g} h → {d['amount']:g}".replace(".0 ", " ") for d in r["days"])
    if save:
        p = tripcare.travel_dir() / "naklady.csv"
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            if new:
                w.writerow(["datum", "co", "kde", "od", "do", "castka", "mena", "cislo"])
            w.writerow([clock.today().isoformat(), "stravné", r["country"], start, end, f"{r['total']:.2f}".replace(".", ","),
                        r["currency"], ""])
    return ToolResult(True, f"Stravné celkem {r['total']:g} {r['currency']} ({days}). Sazby si hlídej podle aktuální vyhlášky."
                      + (" Zapsáno do naklady.csv." if save else ""), data=r)


@tool("travel_companions", "Spolucestující (partner, děti, kolegové) pro rezervace – jméno, příjmení, datum narození. "
      "action = list / add / remove. Údaje zůstávají jen v tomhle PC.", category="cesty", perm="files_write")
async def travel_companions(ctx, action: Annotated[str, "list / add / remove"] = "list", first_name: str = "", last_name: str = "",
                            born_on: Annotated[str, "YYYY-MM-DD"] = "", relation: str = "",
                            gender: Annotated[str, "m / f"] = "m") -> ToolResult:
    comp = [c.model_dump() for c in ctx.cfg.booking.companions]
    a = (action or "list").lower()
    if a == "add":
        if not first_name.strip():
            return ToolResult(False, "Řekni aspoň křestní jméno.")
        if born_on:
            try:
                dt.date.fromisoformat(born_on[:10])
            except ValueError:
                return ToolResult(False, "Datum narození zadej jako RRRR-MM-DD.")
        comp = [c for c in comp if c["first_name"].lower() != first_name.strip().lower()] + [{
            "first_name": first_name.strip(), "last_name": last_name.strip(), "born_on": born_on[:10], "relation": relation.strip(),
            "gender": "f" if gender.lower().startswith(("f", "z", "ž")) else "m",
            "title": "ms" if gender.lower().startswith(("f", "z", "ž")) else "mr"}]
        ctx.update_config({"booking": {"companions": comp}})
        return ToolResult(True, f"Zapsáno: {first_name} {last_name}".strip() + ". Údaje zůstávají jen v PC.")
    if a == "remove":
        left = [c for c in comp if c["first_name"].lower() != first_name.strip().lower()]
        ctx.update_config({"booking": {"companions": left}})
        return ToolResult(len(left) < len(comp), "Odebráno." if len(left) < len(comp) else "Takového spolucestujícího nemám.")
    if not comp:
        return ToolResult(True, "Spolucestující nemám – řekni „přidej spolucestující Janu Novákovou, narozená 1990-05-01“.")
    return ToolResult(True, "; ".join(f"{c['first_name']} {c['last_name']}".strip() + (f" ({c['relation']})" if c["relation"] else "")
                                      + ("" if c["born_on"] else " – chybí datum narození") for c in comp), data={"companions": comp})


@tool("trip_share", "Odkaz na cestu pro rodinu jen pro čtení (kam, kdy, stav letu) – bez ceny a čísla rezervace, platí do konce "
      "cesty. action = create / stop. Vytvoření odkazu se vždy zeptá (prozradí, kdy nejsi doma).", category="cesty", perm="network",
      danger_if=lambda a: str(a.get("action") or "create").lower() != "stop")
async def trip_share(ctx, booking_ref: Annotated[str, "která rezervace"], action: Annotated[str, "create / stop"] = "create") -> ToolResult:
    from .. import booking, tripshare

    b = booking.find_booking(ctx, booking_ref)
    if not b:
        return ToolResult(False, "Takovou rezervaci nenacházím.")
    if (action or "").lower() == "stop":
        n = tripshare.stop(ctx, b["id"])
        return ToolResult(True, "Sdílení zrušeno – odkaz už nefunguje." if n else "Tahle cesta sdílená nebyla.")
    r = tripshare.create(ctx, b)
    where = "" if r["public"] else (" Funguje jen u tebe doma – pro sdílení odkudkoli nastav veřejnou adresu (Tailscale nebo "
                                    "Cloudflare, E-mail a telefon → Veřejná adresa).")
    return ToolResult(True, f"Odkaz pro rodinu: {r['url']} (platí do {dt.datetime.fromtimestamp(r['until']):%d. %m.}, jen pro čtení, "
                            f"bez ceny a čísla rezervace).{where}", data=r)
