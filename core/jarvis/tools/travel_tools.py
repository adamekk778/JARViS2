"""3.14 Auto, cesty, svět: the car through Home Assistant, trips from e-mail, parcels, the world map in the HUD."""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from .base import ToolResult, tool


# ---------------------------------------------------------------------------------------------- the car
@tool("car_status", "Stav auta přes Home Assistant: baterie nebo palivo, dojezd, zamčeno, kde stojí, nabíjí se, topí – "
      "„jak je na tom auto“, „kde je auto“, „kolik mám dojezd“.", category="domácnost", perm="home")
async def car_status(ctx) -> ToolResult:
    from .. import car

    try:
        text, data = await car.status(ctx)
    except LookupError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Home Assistant teď neodpovídá: {e}")
    return ToolResult(True, text, data=data)


@tool("car_setup", "Najde auto v Home Assistantu (integrace výrobce – Škoda, VW, Tesla, BMW, Kia/Hyundai… – nebo OBD adaptér) "
      "a zapamatuje si jeho baterii, dojezd, polohu, zámek a topení.", category="domácnost", perm="home")
async def car_setup(ctx, name: Annotated[str, "jak autu říkáš, např. Enyaq"] = "") -> ToolResult:
    from .. import car

    try:
        found = car.discover(await ctx.home.states(fresh=True))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Home Assistant teď neodpovídá: {e} (adresa a token: Nastavení → Domov).")
    if not found:
        return ToolResult(False, "V Home Assistantu jsem auto nenašel. Přidej tam integraci výrobce (Nastavení → Zařízení a služby → "
                          "Přidat integraci → např. MySkoda, Volkswagen, Tesla, BMW Connected Drive, Kia Uvo) nebo OBD adaptér "
                          "přes ESPHome / Torque Pro, a řekni mi to znovu.")
    ctx.update_config({"home": {"car": {**found, "name": name.strip() or "Auto"}}})
    parts = ", ".join(car.LABEL[r] for r in car.ROLES if r in found)
    return ToolResult(True, f"Auto propojené: {parts}. Zkus „jak je na tom auto“ nebo „připrav auto na 7:30“.", data=found)


@tool("car_climate", "Zapne nebo vypne v autě topení / klimatizaci (předehřátí) přes Home Assistant.", category="domácnost",
      perm="home")
async def car_climate(ctx, on: Annotated[bool, "true = zapnout, false = vypnout"] = True) -> ToolResult:
    from .. import car

    try:
        return ToolResult(True, await car.climate(ctx, on))
    except LookupError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Auto teď neodpovídá: {e}")


@tool("car_lock", "Zamkne nebo odemkne auto přes Home Assistant. Odemčení se vždy nejdřív zeptá.", category="domácnost",
      perm="home", danger_if=lambda a: a.get("lock") is False)
async def car_lock(ctx, lock: Annotated[bool, "true = zamknout, false = odemknout"] = True) -> ToolResult:
    from .. import car

    try:
        return ToolResult(True, await car.lock(ctx, lock))
    except LookupError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Auto teď neodpovídá: {e}")


@tool("car_ready", "„Připrav auto na 7:30“: topení / klimatizace se zapne 15 minut předem, na telefon přijde zpráva "
      "(i s varováním, když je slabá baterie).", category="domácnost", perm="home")
async def car_ready(ctx, time: Annotated[str, "kdy má být auto připravené, např. 7:30"]) -> ToolResult:
    from .. import car

    if not car.entities(ctx).get("climate"):
        return ToolResult(False, "U auta nemám ovládání topení – řekni nejdřív „najdi auto v Home Assistantu“.")
    try:
        job = car.ready_at(ctx, time)
    except ValueError as e:
        return ToolResult(False, str(e))
    start = dt.datetime.fromtimestamp(job["next_run"])
    return ToolResult(True, f"Dobře, v {start:%H:%M} začnu auto předehřívat, aby bylo v {time.strip()} připravené.", data=job)


# ---------------------------------------------------------------------------------------------- trips
@tool("trips_list", "Moje cesty: lety a vlaky z rezervací v e-mailu (nebo přidané hlasem) – kdy, odkud kam, zpoždění, gate "
      "a kdy vyrazit z domu. „Kdy letím?“, „v kolik mi jede vlak?“", category="kalendář")
async def trips_list(ctx, scan: Annotated[bool, "nejdřív projít nové e-maily"] = True) -> ToolResult:
    from .. import travel

    if scan:
        try:
            await travel.scan_mail(ctx)
        except Exception:  # noqa: BLE001 – mail offline: show what is known
            pass
    trips = travel.upcoming(ctx)
    if not trips:
        return ToolResult(True, "Žádnou cestu v plánu nevidím. Až přijde rezervace e-mailem, zapíšu si ji sám – nebo řekni "
                          "„přidej let FR 1234 12. 12. v 14:35“.", data={"trips": []})
    lines = []
    for t in trips[:6]:
        p = await travel.leave_plan(ctx, t)
        lines.append(f"{travel.describe(t)} – vyrazit v {dt.datetime.fromtimestamp(p['leave']):%H:%M}"
                     + (" (odhad)" if p["guess"] else ""))
    return ToolResult(True, "; ".join(lines) + ".", data={"trips": trips})


@tool("trip_add", "Zapíše let nebo vlak ručně („přidej let FR 1234 12. 12. v 14:35 z Prahy do Barcelony“); JARVIS pak hlídá "
      "zpoždění a připomene, kdy vyrazit.", category="kalendář")
async def trip_add(ctx, number: Annotated[str, "číslo letu (FR 1234) nebo vlaku (RJ 1031)"],
                   date: Annotated[str, "den odjezdu, např. 12. 12. 2026 nebo 2026-12-12"],
                   time: Annotated[str, "čas odjezdu, např. 14:35"],
                   origin: Annotated[str, "odkud (kód letiště PRG nebo nádraží)"] = "",
                   dest: Annotated[str, "kam"] = "") -> ToolResult:
    from .. import travel

    num = re.sub(r"\s+", " ", number.strip().upper())
    m = re.match(r"^([A-Z0-9]{2})\s?(\d{1,4})$", num)
    flight = bool(m and m.group(1) in travel.AIRLINES)
    days = travel.dates_in(date if re.search(r"20\d{2}", date) else f"{date.strip().rstrip('.')}. {dt.date.today().year}")
    times = travel.times_in(time)
    if not days or not times:
        return ToolResult(False, "Napiš den (12. 12. 2026) a čas (14:35).")
    dep = dt.datetime.combine(days[0][1], times[0][1])
    if dep < dt.datetime.now() - dt.timedelta(hours=3):
        dep = dep.replace(year=dep.year + 1)
    code = lambda s: s.strip().upper() if s.strip().upper() in travel.AIRPORTS else s.strip()  # noqa: E731
    trip = {"kind": "flight" if flight else "train", "number": f"{m.group(1)} {int(m.group(2))}" if flight and m else num,
            "dep": dep.timestamp(), "arr": None, "origin": code(origin), "dest": code(dest)}
    tid = travel.add(ctx, trip, "hlas")
    if tid is None:
        return ToolResult(True, "Tuhle cestu už mám zapsanou.")
    trip["id"] = tid
    p = await travel.leave_plan(ctx, trip)
    return ToolResult(True, f"Zapsáno: {travel.describe(trip)}. Vyrazit v {dt.datetime.fromtimestamp(p['leave']):%H:%M}.",
                      data={**trip, **p})


@tool("trip_remove", "Smaže cestu ze seznamu (zrušený let, omyl).", category="kalendář")
async def trip_remove(ctx, number: Annotated[str, "číslo letu nebo vlaku"]) -> ToolResult:
    from .. import travel

    want = re.sub(r"\s+", "", number.upper())
    hit = [t for t in travel.upcoming(ctx, days=400) if re.sub(r"\s+", "", t["number"].upper()) == want]
    for t in hit:
        travel.remove(ctx, t["id"])
    return ToolResult(bool(hit), f"Smazáno: {', '.join(t['number'] for t in hit)}." if hit else "Takovou cestu nemám.")


@tool("flight_status", "Stav letu: skutečný odlet, zpoždění, terminál a gate (s klíčem AeroDataBox v Propojení), a kde letadlo "
      "právě je (OpenSky). „Má můj let zpoždění?“, „kde je teď letadlo FR 1234?“", category="info", perm="network")
async def flight_status(ctx, number: Annotated[str, "číslo letu; prázdné = můj nejbližší let"] = "") -> ToolResult:
    from .. import connectors, travel

    trips = [t for t in travel.upcoming(ctx) if t["kind"] == "flight"]
    want = re.sub(r"\s+", "", number.upper())
    t = next((x for x in trips if re.sub(r"\s+", "", x["number"].upper()) == want), None) if want else (trips[0] if trips else None)
    num = t["number"] if t else number.strip().upper()
    if not num:
        return ToolResult(False, "Žádný let v plánu nemám – řekni číslo letu.")
    bits = []
    if t:
        try:
            res = await travel.check_flight(ctx, t)
            t["info"] = res["info"]
        except Exception as e:  # noqa: BLE001
            bits.append(f"AeroDataBox teď neodpovídá ({e})")
        bits.insert(0, travel.describe(t))
        if not connectors.configured("aerodatabox"):
            bits.append("zpoždění a gate uvidím s klíčem AeroDataBox (Nastavení → Propojení → Cesty a zásilky)")
    try:
        pos = await travel.live(ctx, num)
    except Exception:  # noqa: BLE001
        pos = {}
    if pos:
        where = "stojí na zemi" if pos["on_ground"] else f"letí ve výšce {round((pos['alt_m'] or 0) / 1000, 1)} km rychlostí {pos['speed_kmh']} km/h"
        if t and t.get("dest") in travel.AIRPORTS and not pos["on_ground"]:
            a = travel.AIRPORTS[t["dest"]]
            where += f", {round(travel._km((pos['lat'], pos['lon']), (a[1], a[2])))} km od cíle ({a[0]})"
        bits.append(f"Letadlo {pos['callsign']} {where}")
    elif not t:
        bits.append(f"Let {num} teď ve vzduchu nevidím")
    return ToolResult(True, ". ".join(bits).replace("..", ".") + ".", data={"trip": t, "live": pos})


# ---------------------------------------------------------------------------------------------- parcels
@tool("parcels_list", "Kde mám balík: zásilky z e-mailů (Česká pošta, Balíkovna, Zásilkovna, PPL, DPD, GLS, Alza…) a jejich stav.",
      category="info")
async def parcels_list(ctx, refresh: Annotated[bool, "zjistit aktuální stav u dopravců"] = True) -> ToolResult:
    from .. import parcels, travel

    try:
        await travel.scan_mail(ctx)
    except Exception:  # noqa: BLE001
        pass
    if refresh:
        try:
            await parcels.refresh(ctx, notify=False)
        except Exception:  # noqa: BLE001
            pass
    return ToolResult(True, parcels.summary(ctx), data={"parcels": parcels.listing(ctx)})


@tool("parcel_add", "Začne hlídat zásilku podle čísla („hlídej balík RR123456789CZ“).", category="info")
async def parcel_add(ctx, number: Annotated[str, "číslo zásilky"], carrier: Annotated[str, "dopravce, prázdné = poznat podle čísla"] = "",
                     shop: Annotated[str, "odkud (obchod), nepovinné"] = "") -> ToolResult:
    from .. import parcels

    words = {"posta": "cpost", "pošta": "cpost", "balikovna": "cpost", "balíkovna": "cpost", "zasilkovna": "zasilkovna",
             "zásilkovna": "zasilkovna", "packeta": "zasilkovna", "ppl": "ppl", "dpd": "dpd", "gls": "gls", "alza": "alzabox"}
    c = words.get(carrier.strip().lower(), "") or parcels.guess_carrier(number)
    if not parcels.add(ctx, c, number, shop.strip()):
        return ToolResult(True, "Tuhle zásilku už hlídám." if number.strip() else "Chybí číslo zásilky.")
    try:
        await parcels.refresh(ctx, notify=False)
    except Exception:  # noqa: BLE001
        pass
    return ToolResult(True, "Hlídám ji. " + parcels.summary(ctx))


@tool("parcel_remove", "Přestane hlídat zásilku (už ji mám, omyl).", category="info")
async def parcel_remove(ctx, number: Annotated[str, "číslo zásilky"]) -> ToolResult:
    from .. import parcels

    ok = parcels.remove(ctx, number)
    return ToolResult(ok, "Hotovo, už ji nehlídám." if ok else "Takovou zásilku nehlídám.")


# ---------------------------------------------------------------------------------------------- the world map
@tool("world_map", "Ukáže v HUD mapu světa: radar srážek, domov, auto, cíle tvých cest a letadla nad domem.", category="info")
async def world_map(ctx, focus: Annotated[str, "co ukázat: radar / auto / cesty / letadla (prázdné = vše)"] = "") -> ToolResult:
    ctx.bus.publish("hud_map", focus=focus.strip().lower())
    return ToolResult(True, "Mapa světa je v HUD (Stark HUD, tlačítko se zeměkoulí).")
