"""OMEGA wave 23 by voice: the smart home – rooms and control by room, energy per meter, low batteries, firmware updates,
device history, and a simulator for JARVIS's "Když … tak …" rules."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool

NOT_SET = ToolResult(False, "Chytrá domácnost není připojená – Nastavení → Domov (adresa Home Assistantu a token).")


def _ready(ctx) -> bool:
    from .. import home

    return home.configured(ctx)


async def _guard(coro):
    try:
        return await coro, None
    except PermissionError as e:
        return None, ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – Home Assistant unreachable
        return None, ToolResult(False, f"Home Assistant neodpovídá: {type(e).__name__}")


@tool("home_rooms", "Místnosti domácnosti (z Home Assistantu) a co v nich je: kolik svítí světel, teplota, zařízení.",
      category="domácnost", perm="home")
async def home_rooms(ctx) -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    r, err = await _guard(homeplus.rooms(ctx))
    if err:
        return err
    if not r:
        return ToolResult(True, "V Home Assistantu nejsou nastavené žádné místnosti (oblasti).", data=[])
    return ToolResult(True, "; ".join(f"{x['name']}: {len(x['devices'])} zařízení" + (f", svítí {x['lights_on']}" if x["lights_on"] else "") +
                                      (f", {x['temperature']} °C" if x["temperature"] else "") for x in r) + ".", data=r)


@tool("room_control", "Ovládne celou místnost najednou: zhasni / rozsviť v obýváku (světla), vypni v ložnici všechno (světla, "
      "zásuvky, přehrávače). Zámky, vrata a alarm se takhle neovládají.", category="domácnost", perm="home")
async def room_control(ctx, room: str, action: Annotated[str, "on / off"], what: Annotated[str, "lights / all"] = "lights") -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    if action not in ("on", "off"):
        return ToolResult(False, "Akce: on nebo off.")
    rs, err = await _guard(homeplus.rooms(ctx))
    if err:
        return err
    r = homeplus.find_room(rs, room)
    if not r:
        return ToolResult(False, f"Místnost „{room}“ neznám. Mám: {', '.join(x['name'] for x in rs) or 'žádné'}.")
    domains = ("light",) if what == "lights" else ("light", "switch", "fan", "media_player")
    targets = [d for d in r["devices"] if d["domain"] in domains]
    if not targets:
        return ToolResult(False, f"V místnosti {r['name']} nic takového není.")
    done = []
    for d in targets:
        try:
            await ctx.home.service(d["domain"], f"turn_{action}", {"entity_id": d["id"]})
            done.append(d["name"])
        except Exception:  # noqa: BLE001 – one device off-line does not stop the rest
            continue
    return ToolResult(bool(done), f"{r['name']}: {'zapnuto' if action == 'on' else 'vypnuto'} {len(done)} z {len(targets)} ({', '.join(done[:6])}).",
                      data={"room": r["name"], "done": done})


@tool("home_energy", "Spotřeba energie za posledních N dní podle měřičů v Home Assistantu: kolik kWh který spotřebič / okruh, "
      "po dnech, a kolik to stojí.", category="domácnost", perm="home")
async def home_energy(ctx, days: int = 7, price_kwh: float = 6.0) -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    r, err = await _guard(homeplus.energy(ctx, max(1, min(days, 90))))
    if err:
        return err
    if not r["meters"]:
        return ToolResult(True, "Home Assistant nemá žádný měřič energie (kWh).", data=r)
    return ToolResult(True, f"Za {days} dní {r['total_kwh']} kWh ≈ {round(r['total_kwh'] * price_kwh)} Kč: " +
                      "; ".join(f"{m['name']} {m['kwh']} kWh" for m in r["meters"][:6]) + ".", data=r)


@tool("home_batteries", "Které chytré zařízení má slabou baterii (čidla, zámky, ovladače) – ať nepřestanou fungovat.",
      category="domácnost", perm="home")
async def home_batteries(ctx, threshold: int = 20) -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    st, err = await _guard(homeplus.raw_states(ctx))
    if err:
        return err
    b = homeplus.low_batteries(st, threshold)
    low = [x for x in b if x["low"]]
    if not b:
        return ToolResult(True, "Žádné zařízení s baterií nevidím.", data=[])
    return ToolResult(True, ("Slabá baterie: " + ", ".join(f"{x['name']} {x['level']:.0f} %" for x in low) if low else
                             f"Všech {len(b)} baterií je nad {threshold} %, nejslabší {b[0]['name']} {b[0]['level']:.0f} %") + ".", data=b)


@tool("home_firmware", "Které chytré zařízení nebo doplněk čeká na aktualizaci firmwaru (verze nainstalovaná → nová).",
      category="domácnost", perm="home")
async def home_firmware(ctx) -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    st, err = await _guard(homeplus.raw_states(ctx))
    if err:
        return err
    fw = homeplus.firmware(st)
    pend = [x for x in fw if x["pending"]]
    if not fw:
        return ToolResult(True, "Home Assistant nesleduje žádné aktualizace.", data=[])
    return ToolResult(True, (f"Čeká {len(pend)} aktualizací: " + "; ".join(f"{x['name']} {x['installed']} → {x['latest']}" for x in pend[:8])
                             if pend else f"Vše aktuální ({len(fw)} položek)") + ".", data=fw)


@tool("home_history", "Co se doma dělo: historie událostí zařízení (dveře, pohyb, světla, alarm) za posledních N hodin, "
      "volitelně jen pro jedno zařízení.", category="domácnost", perm="home")
async def home_history(ctx, hours: int = 24, device: str = "") -> ToolResult:
    from .. import homeplus

    if not _ready(ctx):
        return NOT_SET
    ent = ""
    if device:
        hits, err = await _guard(ctx.home.find(device, ("light", "switch", "lock", "cover", "binary_sensor", "sensor", "alarm_control_panel",
                                                        "climate", "media_player", "person", "fan", "vacuum")))
        if err:
            return err
        if not hits:
            return ToolResult(False, f"Zařízení „{device}“ nevidím.")
        ent = hits[0]["id"]
    ev, err = await _guard(homeplus.logbook(ctx, max(1, min(hours, 24 * 14)), ent))
    if err:
        return err
    if not ev:
        return ToolResult(True, "Za tu dobu se nic nestalo.", data=[])
    return ToolResult(True, "; ".join(f"{e['when'][11:16]} {e['name']} {e['message'] or e['state']}" for e in ev[-15:]) + ".", data=ev)


@tool("simulate_automations", "Vyzkouší pravidla „Když … tak …“ nanečisto na vymyšlených událostech (nic se neprovede): "
      "„po 7:00; e-mail od šéf: Porada; baterie 15; odejdu 20“ → které pravidlo by se spustilo a co by udělalo.", category="automatizace")
async def simulate_automations(ctx, events: Annotated[str, "události oddělené středníkem"]) -> ToolResult:
    from .. import homeplus

    try:
        evs = homeplus.parse_events(events)
    except ValueError as e:
        return ToolResult(False, str(e))
    r = homeplus.simulate(list(ctx.cfg.automations.items), evs)
    lines = []
    for f in r["events"]:
        what = ", ".join(f"{h['rule']} ({'; '.join(h['steps'][:2])})" for h in f["rules"]) or "nic"
        lines.append(f"{f['n']}. {f['event']['type']} → {what}")
    msg = " | ".join(lines)
    if r["never_fired"]:
        msg += f". Nespustilo se: {', '.join(r['never_fired'][:6])}"
    if r["multiple"]:
        msg += f". Víc pravidel najednou u události {', '.join(str(m['n']) for m in r['multiple'])}"
    return ToolResult(True, msg + ".", data=r)
