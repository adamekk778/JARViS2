"""Wave 35 by voice: the hardware lab – boards, firmware, Raspberry Pi, schematics, PCB, enclosures, camera calibration
and engineering alternatives."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _out(name: str) -> Path:
    return paths.sub("hardware") / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"


@tool("boards_connected", "Jaké vývojové desky (Arduino, ESP32, Raspberry Pi Pico…) jsou připojené přes USB a na jakém portu.",
      category="hardware")
async def boards_connected(ctx) -> ToolResult:
    from .. import hwlab

    boards = await asyncio.to_thread(hwlab.list_boards)
    if not boards:
        return ToolResult(True, "Nevidím žádný sériový port – připoj desku USB kabelem, který přenáší data (ne jen nabíjecí).", data={"boards": []})
    lines = [f"{b['port']}: {b['board'] or b['desc'] or 'neznámé zařízení'}" + ("" if b["sure"] or not b["board"] else " (odhad)") for b in boards]
    cli = "Arduino CLI je nainstalované." if hwlab.arduino_cli() else "Arduino CLI chybí (bez něj nesestavím ani nenahraji sketch)."
    return ToolResult(True, "; ".join(lines) + ". " + cli, data={"boards": boards})


@tool("firmware_project", "Přidá nebo ukáže firmwarový projekt (Arduino / ESP32): složka se sketchem, deska (např. arduino:avr:uno, "
      "esp32:esp32:esp32), port, verze a historie sestavení.", category="hardware")
async def firmware_project(ctx, name: Annotated[str, "název projektu"], path: Annotated[str, "složka se sketchem (při přidání)"] = "",
                           board: Annotated[str, "FQBN desky"] = "", port: Annotated[str, "COM port"] = "") -> ToolResult:
    from .. import hwlab

    if path:
        try:
            p = hwlab.add_project(ctx, name, str(resolve(path)), board, port)
        except FileNotFoundError as e:
            return ToolResult(False, str(e))
    else:
        p = hwlab.get_project(ctx, name)
        if not p:
            names = ", ".join(x["name"] for x in hwlab.list_projects(ctx)) or "žádné"
            return ToolResult(False, f"Projekt „{name}“ neznám. Mám: {names}.")
    last = p["builds"][0] if p.get("builds") else None
    msg = f"{p['name']} v{p['version']} – {p['fqbn'] or 'deska podle připojené'}, {p['path']}."
    if last:
        msg += f" Naposledy: {'OK' if last['ok'] else 'chyba'} ({last['summary'][:80]})"
        if last["flash_pct"] is not None:
            msg += f", flash {last['flash_pct']} %, RAM {last['ram_pct']} %"
    return ToolResult(True, msg, data=p)


@tool("firmware_build", "Sestaví (zkompiluje) firmwarový projekt přes Arduino CLI a vysvětlí chyby česky (chybějící knihovna, "
      "středník, paměť…). Na desku nic nenahrává.", category="hardware", perm="apps")
async def firmware_build(ctx, name: Annotated[str, "název projektu"]) -> ToolResult:
    from .. import hwlab

    try:
        r = await asyncio.to_thread(hwlab.build_project, ctx, name, False)
    except (KeyError, ValueError, FileNotFoundError) as e:
        return ToolResult(False, str(e))
    extra = f" Flash {r['flash']['percent']} %, RAM {r['ram']['percent']} %." if r["ok"] and r["flash"] and r["ram"] else ""
    where = "; ".join(f"{e['file']}:{e['line']} {e['message']}" for e in r["errors"][:3])
    return ToolResult(r["ok"], r["summary"] + extra + (f" ({where})" if where and not r["ok"] else ""), data=r)


def _upload_details(args: dict) -> list[str]:
    return [f"Projekt: {args.get('name')}", "Sestaví firmware a nahraje ho do připojené desky (přepíše program, který v ní je)."]


@tool("firmware_upload", "Sestaví firmwarový projekt a nahraje ho do připojené desky (Arduino / ESP32) přes Arduino CLI. "
      "Přepíše program v desce – vždy se ptá.", category="hardware", perm="apps", danger=True, details=_upload_details)
async def firmware_upload(ctx, name: Annotated[str, "název projektu"], bump: Annotated[str, "zvýšit verzi: patch / minor / major / nic"] = "nic") -> ToolResult:
    from .. import hwlab

    try:
        r = await asyncio.to_thread(hwlab.build_project, ctx, name, True)
    except (KeyError, ValueError, FileNotFoundError) as e:
        return ToolResult(False, str(e))
    if r["ok"] and bump in ("patch", "minor", "major"):
        p = hwlab.get_project(ctx, name)
        ctx.db.exec("UPDATE fw_projects SET version=? WHERE name=?", (hwlab.bump(p["version"], bump), p["name"]))
    return ToolResult(r["ok"], (f"Nahráno do {r['port']}." if r["ok"] else r["summary"]), data=r)


def _flash_details(args: dict) -> list[str]:
    return [f"Port: {args.get('port')}", f"Soubor: {args.get('file')}", f"Adresa: {args.get('address') or '0x0'}",
            "Přepíše firmware v ESP – špatný soubor nebo adresa může desku dočasně „zablokovat“ (jde opravit novým nahráním)."]


@tool("flash_esp32", "Nahraje hotový firmware .bin do ESP32 / ESP8266 přes esptool (musí být nainstalovaný). Vždy se ptá.",
      category="hardware", perm="apps", danger=True, details=_flash_details)
async def flash_esp32(ctx, port: Annotated[str, "COM port"], file: Annotated[str, "soubor .bin"], address: Annotated[str, "adresa, výchozí 0x0"] = "0x0") -> ToolResult:
    from .. import hwlab

    try:
        r = await asyncio.to_thread(hwlab.flash_esp, port, resolve(file), address)
    except (FileNotFoundError, ValueError) as e:
        return ToolResult(False, str(e))
    return ToolResult(r["ok"], "Firmware nahrán." if r["ok"] else ("; ".join(r["hints"]) or r["log"][-300:]), data=r)


@tool("raspberry_pi", "Najde Raspberry Pi v síti, nebo ukáže jeho stav (teplota, zaplnění karty, paměť, jak dlouho běží) přes SSH "
      "s tvým klíčem – jen čte, nic nemění, heslo nezadává.", category="hardware", perm="network")
async def raspberry_pi(ctx, host: Annotated[str, "adresa Pi (prázdné = najít v síti)"] = "", user: Annotated[str, "uživatel"] = "pi") -> ToolResult:
    from .. import hwlab, network

    if not host:
        pis = hwlab.find_pis(await network.devices(ctx))
        if not pis:
            return ToolResult(True, "V síti teď žádné Raspberry Pi nevidím (musí být zapnuté a ve stejné síti).", data={"found": []})
        return ToolResult(True, "Raspberry Pi: " + ", ".join(f"{d.get('name') or 'Pi'} ({d['ip']})" for d in pis) + ".", data={"found": pis})
    try:
        r = await asyncio.to_thread(hwlab.pi_status, host, user)
    except (ValueError, FileNotFoundError) as e:
        return ToolResult(False, str(e))
    if not r["ok"]:
        return ToolResult(False, f"Na {host} se nepřipojím: {r['error']}")
    parts = [f"běží {r.get('uptime', '?')}"]
    if "temp_c" in r:
        parts.append(f"{r['temp_c']} °C")
    if "disk" in r:
        parts.append(f"karta {r['disk']['percent']} % ({r['disk']['used']} z {r['disk']['size']})")
    if "ram_mb" in r:
        parts.append(f"RAM {r['ram_mb']['used']}/{r['ram_mb']['total']} MB")
    return ToolResult(True, f"{host}: " + ", ".join(parts) + ". " + " ".join(r["warnings"]), data=r)


@tool("schematic", "Nakreslí schéma zapojení ze seznamu spojů (např. „Arduino.D9 -> R1.1; R1.2 -> LED1.A; LED1.K -> GND“): obrázek SVG "
      "a netlist pro KiCad.", category="hardware")
async def schematic(ctx, wiring: Annotated[str, "spoje: Součástka.pin -> Součástka.pin; …"], name: Annotated[str, "název"] = "schema") -> ToolResult:
    from .. import hwlab

    w = hwlab.parse_wiring(wiring)
    if not w["nets"]:
        return ToolResult(False, "Ze zadání jsem nevyčetl žádné spoje. Piš třeba „Arduino.D9 -> R1.1; R1.2 -> LED1.A; LED1.K -> GND“.")
    base = _out(name)
    svg, net = base.with_suffix(".svg"), base.with_suffix(".net")
    svg.write_text(hwlab.schematic_svg(w), encoding="utf-8")
    net.write_text(hwlab.kicad_netlist(w), encoding="utf-8")
    return ToolResult(True, f"Schéma: {len(w['components'])} součástek, {len(w['nets'])} spojů ("
                            + ", ".join(f"{n['name']}: {len(n['pins'])}" for n in w["nets"][:6]) + "). Netlist otevřeš v KiCadu (Pcbnew → Import netlistu).",
                      data=w, attachments=[str(svg), str(net)])


@tool("pcb_helper", "Pomoc s plošným spojem: šířka cesty pro daný proud (IPC-2221) a odhad velikosti desky z rozměrů součástek.",
      category="hardware")
async def pcb_helper(ctx, current_a: Annotated[float, "proud cestou v A (0 = jen velikost desky)"] = 0, rise_c: Annotated[float, "dovolené oteplení °C"] = 10,
                     copper_oz: Annotated[float, "tloušťka mědi v oz (1 = 35 µm)"] = 1, inner: Annotated[bool, "vnitřní vrstva"] = False,
                     parts: Annotated[str, "součástky „šířka×výška[×kusů]“ v mm oddělené čárkou"] = "") -> ToolResult:
    import re

    from .. import hwlab

    msg, data = [], {}
    if current_a > 0:
        t = hwlab.trace_width(current_a, rise_c, copper_oz, not inner)
        data["trace"] = t
        msg.append(f"Pro {current_a:g} A (oteplení {rise_c:g} °C, {copper_oz:g} oz, {t['layer']} vrstva) aspoň {t['width_mm']} mm, doporučuji {t['recommended_mm']} mm.")
    items = [re.match(r"\s*([\d.]+)\s*[x×]\s*([\d.]+)(?:\s*[x×]\s*(\d+))?", p) for p in parts.split(",") if p.strip()]
    plist = [{"w": float(m.group(1)), "h": float(m.group(2)), "qty": int(m.group(3) or 1)} for m in items if m]
    if plist:
        b = hwlab.board_size(plist)
        data["board"] = b
        msg.append(f"Deska zhruba {b['board_mm'][0]}×{b['board_mm'][1]} mm (součástky zaberou {b['parts_area_mm2']} mm²).")
    if not msg:
        return ToolResult(False, "Zadej proud cestou nebo rozměry součástek.")
    return ToolResult(True, " ".join(msg), data=data)


@tool("enclosure_design", "Navrhne krabičku s víkem pro 3D tisk podle vnitřních rozměrů (např. pro desku plošného spoje): OpenSCAD "
      "zdroj (i s otvory) a STL k tisku.", category="hardware")
async def enclosure_design(ctx, width: Annotated[float, "vnitřní šířka mm"], depth: Annotated[float, "vnitřní hloubka mm"],
                           height: Annotated[float, "vnitřní výška mm"], wall: Annotated[float, "stěna mm"] = 2.0,
                           holes: Annotated[str, "otvory „x,z,průměr“ na přední stěně, oddělené ;"] = "") -> ToolResult:
    from .. import hwlab

    hl = []
    for part in holes.split(";"):
        nums = [float(x) for x in part.replace(" ", "").split(",") if x]
        if len(nums) == 3:
            hl.append({"x": nums[0] + wall, "z": nums[1] + wall, "d": nums[2], "side": "front"})
    try:
        r = hwlab.enclosure(width, depth, height, wall, holes=hl)
    except ValueError as e:
        return ToolResult(False, str(e))
    base = _out("krabicka")
    scad, stl = base.with_suffix(".scad"), base.with_suffix(".stl")
    scad.write_text(r["scad"], encoding="utf-8")
    stl.write_text(r["stl"], encoding="utf-8")
    note = f" Otvory ({r['holes']}) jsou v .scad – STL je bez nich, vyexportuj ho z OpenSCADu, pokud je chceš." if r["holes"] else ""
    return ToolResult(True, f"Krabička {r['outer_mm'][0]:g}×{r['outer_mm'][1]:g}×{r['outer_mm'][2]:g} mm zvenku, víko vedle ní, "
                            f"asi {r['volume_cm3']} cm³ materiálu.{note}", data={k: v for k, v in r.items() if k not in ('scad', 'stl')},
                      attachments=[str(scad), str(stl)])


@tool("camera_calibrate", "Kalibrace kamery z fotek šachovnice (vytiskni ji, vyfoť 5–15× z různých úhlů): ohnisko, střed, zkreslení "
      "objektivu a přesnost. Výsledek uloží jako JSON.", category="hardware")
async def camera_calibrate(ctx, folder: Annotated[str, "složka s fotkami šachovnice"], cols: Annotated[int, "vnitřních rohů na šířku"] = 9,
                           rows: Annotated[int, "vnitřních rohů na výšku"] = 6, square_mm: Annotated[float, "strana políčka v mm"] = 25) -> ToolResult:
    from .. import hwlab

    d = resolve(folder)
    files = sorted(p for p in (d.iterdir() if d.is_dir() else []) if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))
    if not files:
        return ToolResult(False, f"Ve složce {d} nevidím žádné fotky.")
    try:
        r = await asyncio.to_thread(hwlab.calibrate_photos, files[:40], cols, rows, square_mm)
    except ValueError as e:
        return ToolResult(False, str(e))
    out = hwlab.save_json(r, _out("kalibrace").with_suffix(".json"))
    return ToolResult(True, f"Ohnisko {r['fx']:g} × {r['fy']:g} px, střed {r['cx']:g}, {r['cy']:g}, zkreslení k1 {r['k1']:g}, k2 {r['k2']:g}; "
                            f"zorné pole {r['fov_deg'][0]}° × {r['fov_deg'][1]}°; přesnost {r['rms_px']} px ({r['quality']}). "
                            f"Použito {len(r['used'])} fotek" + (f", nepoužito {len(r['skipped'])}" if r["skipped"] else "") + ".",
                      data=r, attachments=[str(out)])


@tool("beam_alternatives", "Technické alternativy nosníku / držáku: pro zatížení a délku spočítá nejmenší průřez pro různé materiály "
      "(ocel, hliník, dřevo, PLA, PETG) a profily, seřadí podle hmotnosti.", category="hardware")
async def beam_alternatives(ctx, load_kg: Annotated[float, "zatížení v kg"], length_mm: Annotated[float, "délka v mm"],
                            support: Annotated[str, "konzola (držák ve zdi) / prostý nosník (na dvou podporách)"] = "konzola",
                            safety: Annotated[float, "bezpečnost"] = 2.0) -> ToolResult:
    from .. import hwlab

    try:
        r = hwlab.beam_alternatives(load_kg * 9.81, length_mm, support, safety)
    except ValueError as e:
        return ToolResult(False, str(e))
    top = r["options"][:5]
    if not top:
        return ToolResult(False, "Žádný z běžných průřezů do 40 cm to neunese – rozděl zatížení nebo přidej podpěru.")
    lines = [f"{o['material']} {o['profile']} {o['size']} – {o['mass_kg']} kg (průhyb {o['deflection_mm']} mm, rozhoduje {o['governs']})" for o in top]
    return ToolResult(True, f"{r['support']} {length_mm:g} mm, {load_kg:g} kg, bezpečnost {safety:g}: " + "; ".join(lines) + ".", data=r)
