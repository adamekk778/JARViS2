"""3.14 JARVIS v celém domě: speakers, satellites, presence, other PCs, electricity prices."""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


@tool("house_announce", "Řekne zprávu do reproduktorů v domě – všude, nebo v jedné místnosti („večeře je hotová“, "
      "„řekni dětem v pokoji, ať jdou spát“). Hlasem JARVISe přes Home Assistant.", category="domácnost", perm="home")
async def house_announce(ctx, text: Annotated[str, "co říct"], where: Annotated[str, "místnost nebo prázdné = celý dům"] = "") -> ToolResult:
    from .. import house

    try:
        r = await house.announce(ctx, text, where or "all")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Do reproduktorů to nešlo: {e}")
    return ToolResult(bool(r["ok"]), r["message"], data=r)


@tool("house_where", "Kde je uživatel a kdo je doma: u PC, v místnosti se satelitem, nebo pryč s telefonem; kdy odešel.",
      category="domácnost")
async def house_where(ctx) -> ToolResult:
    from .. import house

    h = house.of(ctx)
    w = h.where()
    text = {"pc": "Jsi u počítače.", "phone": "Jsi pryč z domu (podle telefonu).", "": "Nevím přesně, kde jsi."}.get(
        w, f"Jsi v místnosti {w.split(':', 1)[-1]}." if w.startswith("room:") else "")
    return ToolResult(True, text, data={"where": w, "home": h.home, "left_at": h.left_at})


@tool("satellite_setup", "Jak připojit hlasové satelity v místnostech (ESP32, Home Assistant Voice): vrátí adresu, kterou "
      "zadáš v Home Assistantu do integrace Ollama – JARVIS pak odpovídá z reproduktoru v té místnosti.", category="domácnost")
async def satellite_setup(ctx, room: Annotated[str, "místnost, např. kuchyň"] = "obyvak") -> ToolResult:
    from .. import house
    from ..server.houseroutes import satellite_key

    import re
    import unicodedata

    slug = re.sub(r"[^a-z0-9]+", "-", "".join(c for c in unicodedata.normalize("NFKD", room.lower())
                                                if not unicodedata.combining(c))).strip("-") or "dum"
    url = f"http://{house.lan_ip()}:{ctx.cfg.phone.port}/ha/{satellite_key(ctx)}/{slug}"
    return ToolResult(True, f"V Home Assistantu: Nastavení → Zařízení a služby → Přidat integraci → Ollama → URL {url} → model "
                      "jarvis. Pak u hlasového asistenta (Nastavení → Hlasoví asistenti) vyber jako konverzačního agenta tuto "
                      "Ollamu a přiřaď ho satelitu v té místnosti.", data={"url": url, "room": slug})


@tool("node_ask", "Pošle požadavek JARVISovi na jiném počítači (notebook, herní PC, domácí server) a vrátí jeho odpověď – "
      "„zeptej se herního PC, kolik má místa na disku“, „pošli na notebook, ať otevře prezentaci“, „vypni herní PC“. "
      "Potvrzení z druhého PC přijdou sem.", category="zařízení", perm="network")
async def node_ask(ctx, node: Annotated[str, "jméno počítače z Nastavení → Domov → Počítače"],
                   request: Annotated[str, "co má ten JARVIS udělat nebo říct"]) -> ToolResult:
    from .. import nodes

    n = nodes.find(ctx, node)
    if n is None:
        names = ", ".join(x["name"] for x in nodes.nodes(ctx)) or "žádné"
        return ToolResult(False, f"Počítač „{node}“ neznám. Mám: {names}. Přidáš je v Nastavení → Domov → Počítače.")
    r = await nodes.ask(ctx, n, request)
    return ToolResult(bool(r["ok"]), f"{n['name']}: {r['answer']}", data=r)


@tool("node_wake", "Zapne jiný počítač v domě přes síť (Wake-on-LAN) – „zapni herní PC“.", category="zařízení", perm="network")
async def node_wake(ctx, node: str) -> ToolResult:
    from .. import nodes

    n = nodes.find(ctx, node)
    if n is None:
        return ToolResult(False, f"Počítač „{node}“ neznám.")
    if not nodes.wake(n):
        return ToolResult(False, f"U {n['name']} chybí MAC adresa síťové karty (Nastavení → Domov → Počítače).")
    return ToolResult(True, f"Budím {n['name']}. Za chvilku by měl naběhnout.")


@tool("electricity_prices", "Spotová cena elektřiny (OTE) dnes a zítra: kolik je teď, nejlevnější a nejdražší hodiny. "
      "Na „kdy je nejlevnější elektřina“, „kolik je teď elektřina“.", category="domácnost")
async def electricity_prices(ctx) -> ToolResult:
    from .. import energy

    try:
        items = await energy.prices(ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Ceny elektřiny teď nejdou zjistit: {e}")
    now = dt.datetime.now()
    s = energy.summary(items, now)
    parts = []
    if s["now"]:
        parts.append(f"Teď {s['now']['czk_kwh']:.2f} Kč/kWh".replace(".", ","))
    if s["cheapest"]:
        parts.append("nejlevněji " + ", ".join(energy.say_hour(x, now) for x in s["cheapest"]))
    if s["dearest"]:
        parts.append("nejdráž " + energy.say_hour(s["dearest"][0], now))
    return ToolResult(True, "; ".join(parts) + ". (Tržní cena bez distribuce a DPH.)", data={**s, "items": len(items)})


@tool("energy_plan", "Naplánuje něco na nejlevnější hodiny elektřiny: „pusť pračku v nejlevnější 2 hodiny do 7:00“, "
      "„nabij auto přes noc nejlevněji“. JARVIS v ten čas sám provede `what` (třeba zapne zásuvku pračky).",
      category="domácnost", perm="home")
async def energy_plan(ctx, what: Annotated[str, "co v ten čas udělat, např. „zapni zásuvku pračky“"],
                      hours: Annotated[int, "kolik hodin to potřebuje"] = 1,
                      before: Annotated[str, "do kdy to má být hotové (HH:MM), prázdné = kdykoli do zítřka"] = "") -> ToolResult:
    from .. import energy
    from .timers import parse_when

    try:
        items = await energy.prices(ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Ceny elektřiny teď nejdou zjistit: {e}")
    now = dt.datetime.now()
    end = parse_when(before) if before else None
    if end is not None and end <= now:
        end += dt.timedelta(days=1)
    w = energy.cheapest_window(items, hours, now, end)
    if w is None:
        return ToolResult(False, "Na tu dobu nemám ceny (zítřejší vycházejí kolem 13:00).")
    job = ctx.scheduler.add({"type": "once", "at": w["start"].timestamp()}, "prompt", {"prompt": what}, f"Nejlevnější elektřina: {what[:40]}")
    when = w["start"].strftime("%H:%M") + ("" if w["start"].date() == now.date() else " zítra")
    return ToolResult(True, f"Naplánováno na {when} – průměr {w['avg']:.2f} Kč/kWh za {hours} h.".replace(".", ",", 1), data={**job, "window": {
        "start": w["start"].isoformat(), "end": w["end"].isoformat(), "avg": w["avg"]}})
