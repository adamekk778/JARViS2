"""3.20 Peníze+ (201–220), Cesty+ (221–240) a Auto+ (401–420) tools."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal

from .. import carx, moneyx, tripx
from .base import ToolResult, tool


def _qr_for(ctx, amount: float, msg: str, name: str) -> tuple[str, Path | None]:
    acct = str(getattr(ctx.cfg.moneyx, "my_account", "") or "")
    if not acct:
        return "", None
    iban = acct if acct[:2].isalpha() else moneyx.cz_iban(acct)
    code = moneyx.spayd(iban, amount, msg=msg)
    from .. import paths

    return code, moneyx.qr_png(code, paths.sub("qr") / f"{name}.png")


@tool("money_kit", "Peníze: útrata (spend text=„350 za jídlo“), rozpočet (budget_set category+amount, budget), kapesné (kid_set name+amount, "
      "kid_pay name+amount, kids), hlídač ceny (watch url+amount, watches), rozdělit účet (split amount+text=jména), QR platba z PDF "
      "faktury (invoice_qr path), cíle (goal_set name+amount, goal_add name+amount, goals), věci s datem (item_add kind=voucher/warranty/"
      "bill/return/loyalty/gift name+date+amount, items, item_done id), zálohy na energie (advance kwh+price+fixed+amount), tarify "
      "(tariffs kwh+text=JSON nabídek), Fio banka (bank), neobvyklé platby (unusual), daně (tax_add kind+amount, tax), co dokoupit "
      "(buy text, restock), investice (holding broker+name+qty+amount, import broker+path, portfolio), dárky (gifts), rok (year).",
      category="peníze")
async def money_kit(ctx, action: Literal["spend", "budget_set", "budget", "kid_set", "kid_pay", "kids", "watch", "watches", "split", "invoice_qr",
                                         "goal_set", "goal_add", "goals", "item_add", "items", "item_done", "advance", "tariffs", "bank",
                                         "unusual", "tax_add", "tax", "buy", "restock", "holding", "import", "portfolio", "gifts", "year"],
                    text: str = "", amount: float = 0, category: str = "", name: str = "", url: str = "", path: str = "",
                    kind: str = "", date: str = "", id: int = 0, kwh: float = 0, price: float = 0, fixed: float = 0,  # noqa: A002
                    qty: float = 0, broker: str = "", year: int = 0) -> ToolResult:
    today = dt.date.today()
    if action == "spend":
        sp = moneyx.parse_spend(text) if text and not amount else (amount, category or moneyx.category_of(text), text)
        if not sp or not sp[0]:
            return ToolResult(False, "Kolik a za co? Třeba „350 za jídlo“.")
        moneyx.spend_add(ctx, sp[0], category or sp[1], sp[2])
        st = next((b for b in moneyx.budget_status(ctx) if b["category"] == (category or sp[1])), None)
        left = f" Zbývá {moneyx.kc(st['left'])} z {moneyx.kc(st['limit'])}." if st else ""
        return ToolResult(True, f"Zapsáno {moneyx.kc(sp[0])} – {category or sp[1]}.{left}")
    if action == "budget_set":
        moneyx.budget_set(ctx, category or text, amount)
        return ToolResult(True, f"Rozpočet {category or text}: {moneyx.kc(amount)} měsíčně.")
    if action == "budget":
        st = moneyx.budget_status(ctx)
        return ToolResult(True, "\n".join(f"{b['category']}: {moneyx.kc(b['spent'])} z {moneyx.kc(b['limit'])} ({b['pct']} %)" for b in st)
                          or "Rozpočet zatím nemáš – nastav třeba „jídlo 8000 měsíčně“.", data=st)
    if action == "kid_set":
        moneyx.kid_set(ctx, name, amount, int(kind or 0) if (kind or "").isdigit() else 0)
        return ToolResult(True, f"Kapesné {name}: {moneyx.kc(amount)} týdně.")
    if action == "kid_pay":
        try:
            bal = moneyx.kid_move(ctx, name, -abs(amount) if amount > 0 and "vklad" not in text else abs(amount), text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{name} teď má {moneyx.kc(bal)}.")
    if action == "kids":
        rows = [dict(r) for r in moneyx.db(ctx).all("SELECT * FROM mx_kids")]
        return ToolResult(True, "\n".join(f"{r['name']}: {moneyx.kc(r['balance'])} (týdně {moneyx.kc(r['weekly'])})" for r in rows) or "Kapesné nikdo nemá.")
    if action == "watch":
        try:
            moneyx.watch_add(ctx, url or text, amount)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, "Hlídám cenu – ozvu se při slevě" + (f" pod {moneyx.kc(amount)}." if amount else "."))
    if action == "watches":
        rows = [dict(r) for r in moneyx.db(ctx).all("SELECT * FROM mx_pricewatch")]
        return ToolResult(True, "\n".join(f"{r['title'] or r['url']}: {moneyx.kc(r['last']) if r['last'] else '?'}" for r in rows) or "Nic nehlídám.")
    if action == "split":
        names = [n.strip() for n in text.split(",") if n.strip()] or int(kind or 2)
        parts = moneyx.split(amount, names)
        codes = []
        for n, a in parts:
            code, _png = _qr_for(ctx, a, f"Podil {n}", f"podil-{moneyx.fold(n).replace(' ', '-')}")
            codes.append(code)
        lines = [f"{n}: {moneyx.kc(a) if a == int(a) else f'{a:.2f} Kč'}" for n, a in parts]
        hint = "" if any(codes) else " (QR platby pošlu, až v Nastavení → Peníze zadáš číslo svého účtu.)"
        return ToolResult(True, "\n".join(lines) + hint, data={"parts": parts, "qr": codes})
    if action == "invoice_qr":
        pdf = Path(path)
        if not pdf.is_file():
            return ToolResult(False, "Pošli PDF faktury.")
        info = moneyx.parse_invoice(moneyx.pdf_text(pdf) if pdf.suffix.lower() == ".pdf" else pdf.read_text(encoding="utf-8", errors="ignore"))
        if "iban" not in info or "amount" not in info:
            return ToolResult(False, "Ve faktuře jsem nenašel účet nebo částku.", data=info)
        due = dt.date.fromisoformat(info["due"]) if info.get("due") else None
        code = moneyx.spayd(info["iban"], info["amount"], info.get("vs", ""), f"Faktura {info.get('vs', '')}", due)
        from .. import paths

        png = moneyx.qr_png(code, paths.sub("qr") / f"faktura-{info.get('vs', 'x')}.png")
        if due:
            moneyx.item_add(ctx, "bill", f"VS {info.get('vs', '?')}", due.isoformat(), info["amount"], {"spayd": code})
        att = await ctx.store.save_path(png, "image/png")
        return ToolResult(True, f"QR platba: {moneyx.kc(info['amount'])}, VS {info.get('vs', '–')}" + (f", splatnost {due:%d. %m.}" if due else "")
                          + ". Naskenuj ji v bankovní aplikaci.", data=info, attachments=[att.id])
    if action == "goal_set":
        moneyx.goal_set(ctx, name, amount, date)
        return ToolResult(True, f"Cíl {name}: {moneyx.kc(amount)}" + (f" do {date}" if date else "") + ".")
    if action == "goal_add":
        try:
            g = moneyx.goal_add(ctx, name, amount)
        except ValueError as e:
            return ToolResult(False, str(e))
        ctx.bus.publish("savings_goal", name=g["name"], pct=g["pct"])
        return ToolResult(True, f"{g['name']}: {moneyx.kc(g['saved'])} z {moneyx.kc(g['target'])} ({g['pct']} %).")
    if action == "goals":
        gs = moneyx.goals(ctx)
        return ToolResult(True, "\n".join(f"{g['name']}: {g['pct']} %" + (f", měsíčně odkládej {moneyx.kc(g['per_month'])}" if g["per_month"] else "")
                                          for g in gs) or "Žádné cíle.", data=gs)
    if action == "item_add":
        until = date
        if kind == "warranty" and not until:
            until = moneyx.warranty_until(today, int(qty or 24)).isoformat()
        if kind == "return" and not until:
            until = (today + dt.timedelta(days=14)).isoformat()
        try:
            iid = moneyx.item_add(ctx, kind, name or text, until, amount, json.loads(text) if text.startswith("{") else {})
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Zapsáno ({moneyx.KINDS[kind]}, do {until}). Připomenu se včas.", data={"id": iid})
    if action == "items":
        its = moneyx.items(ctx, kind)
        return ToolResult(True, "\n".join(f"#{i['id']} {moneyx.KINDS[i['kind']]}: {i['name']} do {i['until']}" for i in its) or "Nic.", data=its)
    if action == "item_done":
        return ToolResult(moneyx.item_done(ctx, id), "Hotovo.")
    if action == "advance":
        r = moneyx.advance_check(kwh, price, fixed, amount)
        return ToolResult(True, f"Ročně asi {moneyx.kc(r['yearly'])}, férová záloha {moneyx.kc(r['fair_month'])}. {r['verdict']}", data=r)
    if action == "tariffs":
        try:
            offers = json.loads(text)
        except ValueError:
            return ToolResult(False, "Nabídky pošli jako JSON: [{\"name\":…, \"price_kwh\":…, \"fixed_month\":…}].")
        rows = moneyx.tariffs(kwh, offers)
        return ToolResult(True, "\n".join(f"{r['name']}: {moneyx.kc(r['yearly'])} ročně" + (f" (+{moneyx.kc(r['vs_best'])})" if r["vs_best"] else " – nejlevnější")
                                          for r in rows), data=rows)
    if action == "bank":
        try:
            txs = await moneyx.fio_sync(ctx)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Načteno {len(txs)} pohybů z Fio (jen čtení); výdaje jsou v rozpočtu.")
    if action == "unusual":
        rows = [dict(r) for r in moneyx.db(ctx).all("SELECT * FROM mx_spend ORDER BY ts DESC LIMIT 400")]
        flags = []
        for i, r in enumerate(rows[:30]):
            hist = [x["amount"] for x in rows[i + 1:] if x["category"] == r["category"]]
            new = not any(x["note"] == r["note"] for x in rows[i + 1:])
            why = moneyx.unusual(r["amount"], hist, new)
            if why:
                flags.append(f"{dt.datetime.fromtimestamp(r['ts']):%d. %m.} {r['note'] or r['category']}: {why}")
        return ToolResult(True, "\n".join(flags) or "Žádná neobvyklá platba.")
    if action == "tax_add":
        try:
            moneyx.tax_add(ctx, year or today.year, kind, amount, text, path)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Podklad k dani {year or today.year}: {moneyx.TAX_KINDS[kind]} {moneyx.kc(amount)}.")
    if action == "tax":
        s = moneyx.tax_summary(ctx, year or today.year - 1)
        return ToolResult(True, "\n".join(s["lines"]), data=s)
    if action == "buy":
        moneyx.bought(ctx, text or name)
        return ToolResult(True, f"Zapsáno: {text or name}.")
    if action == "restock":
        due = moneyx.due_items(ctx)
        return ToolResult(True, ("Obvykle by ses už pro tohle stavil: " + ", ".join(due)) if due else "Podle zvyku nic nechybí.", data=due)
    if action == "holding":
        moneyx.holding_set(ctx, broker or "ručně", name or text, qty, amount)
        return ToolResult(True, f"{(name or text).upper()}: {qty:g} ks.")
    if action == "import":
        n = moneyx.import_csv(ctx, broker or "broker", Path(path).read_text(encoding="utf-8-sig", errors="ignore"))
        return ToolResult(n > 0, f"Načteno {n} pozic.")
    if action == "portfolio":
        p = await moneyx.portfolio(ctx)
        return ToolResult(True, f"Hodnota {moneyx.kc(p['value'])}, vloženo {moneyx.kc(p['cost'])}, " +
                          (f"{'zisk' if p['gain'] >= 0 else 'ztráta'} {moneyx.kc(abs(p['gain']))} ({p['gain_pct']} %)." if p["gain_pct"] is not None else "bez nákupních cen."),
                          data=p)
    if action == "gifts":
        c = ctx.cfg.moneyx
        g = moneyx.gifts_status(ctx, c.gift_season or f"Vánoce {today.year}", c.gift_budget or amount)
        return ToolResult(True, f"{g['season']}: koupeno {moneyx.kc(g['spent'])} z {moneyx.kc(g['budget'])}, zbývá {moneyx.kc(g['left'])}"
                          + (" – plánované dárky rozpočet přesahují." if g["over"] else "."), data=g)
    y = moneyx.year_summary(ctx, year or today.year)
    return ToolResult(True, "\n".join(y["lines"]), data=y)


@tool("trip_kit", "Cesty: výlet na den (day_trip text=cíl), jet lag (jetlag amount=posun hodin, date=odlet), kavárny s Wi-Fi a zásuvkou "
      "(work_cafe lat+lon), vyhlídky a příroda (nature lat+lon), hřiště na cestě s dětmi (kids text=cíl), sdílená kola a koloběžky "
      "(bikes lat+lon), tísňová čísla (sos text=země), zvyklosti (customs text=země), dálniční známky (vignettes text=země oddělené "
      "čárkou), změna času (dst), náhrada za zpoždění letu (eu261 amount=km, hours), jídelní lístek (menu attachment), pojištění "
      "zapsáno (insured text), offline mapy (maps lat+lon), sdílený plán s přáteli (plan text=název), jízdenka do telefonu "
      "(ticket attachment), cestovní deník (diary text=název).", category="cestování")
async def trip_kit(ctx, action: Literal["day_trip", "jetlag", "work_cafe", "nature", "kids", "bikes", "sos", "customs", "vignettes", "dst",
                                        "eu261", "menu", "insured", "maps", "plan", "ticket", "diary"],
                   text: str = "", lat: float = 0, lon: float = 0, amount: float = 0, hours: float = 0, date: str = "",
                   attachment: str = "") -> ToolResult:
    if action == "day_trip":
        r = await tripx.day_trip(ctx, text)
        return ToolResult(bool(r.get("ok")), "\n".join(r.get("lines") or [r.get("message", "")]), data=r)
    if action == "jetlag":
        d = dt.date.fromisoformat(date) if date else dt.date.today() + dt.timedelta(days=3)
        return ToolResult(True, "\n".join(tripx.jetlag_plan(amount, d)))
    if action in ("work_cafe", "nature"):
        if not (lat or lon):
            return ToolResult(False, "Kde jsi? Pošli polohu z telefonu.")
        kinds = ["cafe_work"] if action == "work_cafe" else ["viewpoint", "nature"]
        found = []
        for k in kinds:
            found += await tripx.places(ctx, k, lat, lon, 1500 if action == "work_cafe" else 5000)
        if action == "nature":
            stops = tripx.nature_walk((lat, lon), found)
            return ToolResult(bool(stops), (f"Okruh {tripx.walk_km((lat, lon), stops)} km: " + " → ".join(s["name"] for s in stops)) if stops
                              else "Žádné vyhlídky v okolí jsem nenašel.", data=stops)
        return ToolResult(bool(found), "\n".join(f"{c['name']} ({c['km']} km, zásuvka: {c['socket']})" for c in found[:6]) or "Nic poblíž.", data=found)
    if action == "kids":
        from ..phonex import geocode

        home = await tripx._home(ctx)
        to = await geocode(ctx, text)
        if not (home and to):
            return ToolResult(False, "Potřebuju cíl a domov (město v nastavení).")
        r = await tripx.route_summary(ctx, home, to)
        stops = []
        for p in tripx.stops_along(r["points"], r["minutes"], 90):
            pg = await tripx.places(ctx, "playground", p[0], p[1], 3000)
            if pg:
                stops.append(pg[0])
        return ToolResult(True, f"{r['km']} km, asi {r['minutes']} min. Zastávky po 1,5 h: " + (", ".join(f"{s['name']} ({s['km']} km od trasy)" for s in stops) or "hřiště na trase nevím")
                          + ". Pro děti: jídlo a pití po ruce, pauzy aspoň 20 min.", data={"route": {"km": r["km"], "minutes": r["minutes"]}, "stops": stops})
    if action == "bikes":
        feeds = ctx.cfg.tripx.gbfs_feeds
        if not feeds:
            return ToolResult(False, "Zadej v Nastavení → Cesty odkazy GBFS sdílených kol / koloběžek ve tvém městě.")
        out = []
        async with ctx.http() as c:
            for f in feeds[:4]:
                try:
                    root = (await c.get(f, timeout=10)).json()
                    urls = {x["name"]: x["url"] for x in next(iter((root.get("data") or {}).values()))["feeds"]}
                    get = lambda n: (c.get(urls[n], timeout=10) if n in urls else None)  # noqa: E731
                    parts = {}
                    for n in ("station_information", "station_status", "free_bike_status", "vehicle_status"):
                        req = get(n)
                        parts[n] = (await req).json() if req is not None else None
                    out += tripx.gbfs_nearby(parts["station_information"], parts["station_status"],
                                             parts["free_bike_status"] or parts["vehicle_status"], (lat, lon))
                except Exception as e:  # noqa: BLE001
                    out.append({"kind": "chyba", "name": str(e)[:60], "km": 99, "count": 0})
        out = sorted((x for x in out if x["kind"] != "chyba"), key=lambda x: x["km"])
        return ToolResult(True, "\n".join(f"{x['name']}: {x['km']} km ({x['count']})" for x in out[:8]) or "V okolí nic volného.")
    if action == "sos":
        return ToolResult(True, tripx.emergency_text(text))
    if action == "customs":
        return ToolResult(True, tripx.CUSTOMS.get(text.lower()[:2], "Pro tuhle zemi tipy nemám – zeptám se AI, chceš?"))
    if action == "vignettes":
        return ToolResult(True, "\n".join(tripx.vignette_text([c.strip() for c in text.split(",") if c.strip()])))
    if action == "dst":
        d = tripx.dst_change(dt.date.today().year)
        return ToolResult(True, "Změna času letos: " + ", ".join(f"{x:%d. %m.}" for x in d))
    if action == "eu261":
        r = tripx.eu261(amount, hours)
        return ToolResult(r["eligible"], r["why"] + (" Napíšu ti žádost – stačí číslo letu a datum." if r["eligible"] else ""), data=r)
    if action == "menu":
        if not attachment:
            return ToolResult(False, "Vyfoť jídelní lístek a pošli mi ho.")
        parts = await ctx.store.llm_parts(attachment, vision=True)
        out = await ctx.router.complete([{"role": "user", "content": [*parts, {"type": "text", "text": tripx.menu_prompt(ctx.cfg.tripx.allergies)}]}],
                                        need_vision=True)
        return ToolResult(True, str(out).strip())
    if action == "insured":
        tripx.insured(ctx, text)
        return ToolResult(True, "Zapsáno, pojištění máš.")
    if action == "maps":
        m = tripx.offline_map_links(lat, lon, text)
        ctx.phone_push("notify", title="Offline mapa", body=m["how"])
        return ToolResult(True, m["how"], data=m)
    if action == "plan":
        tok = tripx.plan_create(ctx, text or "Výlet")
        base = str(getattr(ctx.cfg.phone_link, "public_url", "") or "").rstrip("/")
        return ToolResult(True, f"Sdílený plán: {base or f'http://localhost:{ctx.cfg.phone.port}'}/plan/{tok} – pošli odkaz kamarádům, každý může přidávat."
                          + ("" if base else " Mimo domácí síť to funguje s veřejnou adresou (Nastavení → Telefon)."))
    if action == "ticket":
        att = ctx.store.get(attachment)
        if not att:
            return ToolResult(False, "Pošli jízdenku (PDF nebo obrázek).")
        ok = ctx.phone_push("save_file", aid=att.id, name=att.name)
        return ToolResult(ok, "Jízdenka je v telefonu i bez internetu." if ok else "Telefon teď není připojený.")
    from .. import memx, tripcare

    rows = [b for b in tripcare.booking_rows(ctx) if not text or tripx.fold(text) in tripx.fold(json.dumps(b, ensure_ascii=False))]
    if not rows:
        return ToolResult(False, "Takovou cestu nemám.")
    b = rows[-1]
    start, end = str(b.get("checkin") or b.get("start") or "")[:10], str(b.get("checkout") or b.get("end") or "")[:10]
    days = []
    try:
        d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        photos = memx.search_photos(ctx, "") if hasattr(memx, "search_photos") else []
        for k in range((d1 - d0).days + 1):
            day = d0 + dt.timedelta(days=k)
            pics = [p["path"] for p in photos if p.get("taken") and dt.date.fromtimestamp(float(p["taken"])) == day][:6]
            days.append({"date": f"{day:%d. %m.}", "places": sorted({p.get("place", "") for p in photos if p.get("path") in pics} - {""}), "photos": pics})
    except Exception:  # noqa: BLE001
        days = [{"date": start, "places": [str(b.get("city", ""))], "photos": []}]
    from .. import paths

    out = paths.sub("travel") / f"denik-{start or 'cesta'}.html"
    out.write_text(tripx.diary_html(f"Cesta {b.get('city') or b.get('name') or ''}".strip(), days, tripcare.spend(ctx).get("total", 0) if isinstance(tripcare.spend(ctx), dict) else 0),
                   encoding="utf-8")
    return ToolResult(True, f"Cestovní deník: {out}", data={"path": str(out)})


@tool("car_kit", "Auto: stav a termíny (status), chybový kód OBD (obd text=P0420), tankování (fuel amount=litry, price=cena, odo, full), "
      "náklad (cost kind+amount), spotřeba a cena za km (consumption), servis (service date+odo+text+amount, services), dálniční známka "
      "(vignette date, text=země), kniha jízd (trips, trip_purpose id+text, logbook date=RRRR-MM), styl jízdy (driving), zaparkoval jsem "
      "(park lat+lon+minutes), kde jsem zaparkoval (where), ceny paliva (fuel_price text=pumpa+price, cheapest), nabíječky (chargers "
      "lat+lon), čas nabíjení (charge_time), doprava teď (traffic), dlouhá cesta (long_trip text=cíl), spolujízda (rideshare amount=km, "
      "odo=lidí), prodej (sell text=JSON), body (points amount+odo=měsíců bez přestupku), dezén z fotky (tread attachment).",
      category="auto")
async def car_kit(ctx, action: Literal["status", "obd", "fuel", "cost", "consumption", "service", "services", "vignette", "trips", "trip_purpose",
                                       "logbook", "driving", "park", "where", "fuel_price", "cheapest", "chargers", "charge_time", "traffic",
                                       "long_trip", "rideshare", "sell", "points", "tread"],
                  text: str = "", amount: float = 0, price: float = 0, odo: float = 0, full: bool = True, kind: str = "",
                  date: str = "", id: int = 0, lat: float = 0, lon: float = 0, minutes: int = 0,  # noqa: A002
                  attachment: str = "") -> ToolResult:
    if action == "status":
        return ToolResult(True, await carx.status_line(ctx))
    if action == "obd":
        try:
            r = carx.obd_explain(text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, r["summary"], data=r)
    if action == "fuel":
        carx.fuel_add(ctx, amount, price, odo, full)
        c = carx.consumption(ctx)
        return ToolResult(True, "Zapsáno." + (f" Spotřeba {c['l_per_100']} l/100 km." if c["l_per_100"] else ""), data=c)
    if action == "cost":
        carx.cost_add(ctx, kind or "jiné", amount, text)
        return ToolResult(True, f"Náklad na auto: {kind or 'jiné'} {carx.kc(amount)}.")
    if action == "consumption":
        c = carx.consumption(ctx)
        if c["avg_l_per_100"] is None:
            return ToolResult(True, "Na spotřebu potřebuju aspoň dvě plné nádrže se stavem tachometru.", data=c)
        return ToolResult(True, f"Průměr {c['avg_l_per_100']} l/100 km (posledně {c['l_per_100']}). Za {c['km']} km palivo {carx.kc(c['fuel_cost'])}, "
                          f"ostatní {carx.kc(c['other_cost'])}" + (f" → {c['per_km']} Kč/km." if c["per_km"] else "."), data=c)
    if action == "service":
        try:
            carx.service_add(ctx, date or dt.date.today().isoformat(), odo, text, amount, attachment)
        except ValueError:
            return ToolResult(False, "Datum servisu napiš jako RRRR-MM-DD.")
        return ToolResult(True, "Servis zapsán.")
    if action == "services":
        rows = [dict(r) for r in carx.db(ctx).all("SELECT * FROM cx_service ORDER BY day DESC")]
        return ToolResult(True, "\n".join(f"{r['day']} ({int(r['km'])} km): {r['what']} – {carx.kc(r['cost'])}" for r in rows) or "Žádný servis zapsaný.")
    if action == "vignette":
        until = carx.vignette(ctx, dt.date.fromisoformat(date) if date else dt.date.today(), text or "CZ")
        return ToolResult(True, f"Známka platí do {until:%d. %m. %Y} – připomenu se týden a den předem.")
    if action == "trips":
        rows = [dict(r) for r in carx.db(ctx).all("SELECT * FROM cx_trips ORDER BY start DESC LIMIT 20")]
        def line(r: dict) -> str:
            dist = "" if r["km"] is None else f"{r['km']:.0f} km "
            return f"#{r['id']} {dt.datetime.fromtimestamp(r['start']):%d. %m. %H:%M} {r['frm'] or ''} → {r['dest'] or ''} {dist}({r['purpose']})"

        return ToolResult(True, "\n".join(line(r) for r in rows) or "Žádné jízdy.")
    if action == "trip_purpose":
        return ToolResult(carx.trip_purpose(ctx, id, text), "Účel jízdy zapsán.")
    if action == "logbook":
        month = date[:7] if date else f"{dt.date.today():%Y-%m}"
        from .. import paths

        out = paths.sub("auto") / f"kniha-jizd-{month}.csv"
        out.write_text(carx.logbook_csv(ctx, month), encoding="utf-8-sig")
        return ToolResult(True, f"Kniha jízd {month}: {out}", data={"path": str(out)})
    if action == "driving":
        s = carx.driving_stats(ctx)
        return ToolResult(True, f"{s['trips']} jízd za 30 dní" + (f", {s['km']} km, {s['hours']} h. " + " ".join(s["tips"]) if s["trips"] else "."), data=s)
    if action == "park":
        p = carx.park(ctx, lat, lon, minutes, text)
        return ToolResult(True, "Zapamatováno, kde stojíš" + (f", parkovné hlídám ({minutes} min)." if minutes else "."), data=p)
    if action == "where":
        p = carx.where_parked(ctx)
        return ToolResult(bool(p), (f"Auto stojí tady: {p['map']}" if p else "Nevím – po vypnutí Bluetooth v autě si polohu zapíšu sám."), data=p)
    if action == "fuel_price":
        carx.price_report(ctx, text, kind or "natural", price, lat or None, lon or None)
        return ToolResult(True, "Cena zapsána.")
    if action == "cheapest":
        rows = carx.cheapest(ctx, kind or "natural")
        return ToolResult(bool(rows), "\n".join(f"{r['station']}: {r['price']:.2f} Kč" for r in rows[:5]) or "Žádné nahlášené ceny za 14 dní.")
    if action == "chargers":
        async with ctx.http() as c:
            from .. import secrets

            params = {"latitude": lat, "longitude": lon, "distance": 15, "distanceunit": "KM", "maxresults": 20, "compact": "true", "verbose": "false"}
            if secrets.get("openchargemap"):
                params["key"] = secrets.get("openchargemap")
            r = await c.get("https://api.openchargemap.io/v3/poi/", params=params, timeout=15)
        rows = carx.parse_ocm(r.json() if r.status_code == 200 else [])
        return ToolResult(bool(rows), "\n".join(f"{x['name']} – {x['kw']:.0f} kW, {x['km']} km" for x in rows[:6]) or "Nabíječky nenalezeny.", data=rows)
    if action == "charge_time":
        c = ctx.cfg.carx
        m = carx.charge_time(c.battery_kwh or 60, amount or 20, price or 80, float(kind or 50))
        return ToolResult(True, f"Asi {m} min.")
    if action == "traffic":
        c = ctx.cfg.carx
        try:
            a = tuple(float(x) for x in c.commute_from.split(","))
            b = tuple(float(x) for x in c.commute_to.split(","))
            t = await carx.traffic(ctx, (a[0], a[1]), (b[0], b[1]))
        except ValueError as e:
            return ToolResult(False, str(e) if "TomTom" in str(e) else "Zadej trasu do práce v Nastavení → Auto (souřadnice).")
        return ToolResult(True, f"Do práce {t['minutes']} min" + (f", z toho zdržení {t['delay_min']} min." if t["delay_min"] else ", bez zdržení."), data=t)
    if action == "long_trip":
        from ..phonex import geocode

        home, to = await tripx._home(ctx), await geocode(ctx, text)
        if not (home and to):
            return ToolResult(False, "Potřebuju cíl a domov.")
        r = await tripx.route_summary(ctx, home, to)
        return ToolResult(True, "\n".join(carx.long_trip_plan(r["km"], r["minutes"], ctx.cfg.carx.ev_range_km or None)))
    if action == "rideshare":
        c = carx.consumption(ctx)
        r = carx.rideshare(amount, c["avg_l_per_100"] or 6.5, price or 38, int(odo or 2))
        return ToolResult(True, f"Cesta stojí asi {carx.kc(r['total'])}, na osobu {carx.kc(r['each'])}.", data=r)
    if action == "sell":
        try:
            info = json.loads(text) if text else {}
        except ValueError:
            return ToolResult(False, "Údaje o autě pošli jako JSON (brand, model, year, km…).")
        est = carx.price_estimate(float(info.get("bought", 0) or 0), int(info.get("year", dt.date.today().year)), float(info.get("km", 0) or 0)) if info.get("bought") else None
        return ToolResult(True, carx.sale_ad(info) + (f"\n\nOdhad ceny: {carx.kc(est['low'])}–{carx.kc(est['high'])}. {est['note']}" if est else ""))
    if action == "points":
        left = carx.points_after(int(amount), int(odo))
        return ToolResult(True, f"Po odečtu za období bez přestupku asi {left} bodů. Přesný stav: Portál dopravy (portal.dopravniinfo.cz) / eDoklady.")
    if not attachment:
        return ToolResult(False, "Vyfoť dezén pneumatiky (ideálně s mincí nebo měrkou) a pošli mi ho.")
    parts = await ctx.store.llm_parts(attachment, vision=True)
    out = await ctx.router.complete([{"role": "user", "content": [*parts, {"type": "text", "text": carx.TREAD_PROMPT}]}], need_vision=True)
    return ToolResult(True, str(out).strip())
