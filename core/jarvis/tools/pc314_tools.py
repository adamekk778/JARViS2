"""3.14 tools: the PC (návrhy 81–83, 86–89)."""
from __future__ import annotations

import asyncio
import time
from typing import Annotated, Literal

from .. import paths
from .base import ToolResult, tool


@tool("disk_treemap", "Mapa, co zabírá místo ve složce nebo na disku – obdélníky podle velikosti (obrázek) a seznam "
      "největších položek. Bez cesty: domovská složka.", category="soubory", perm="files_read")
async def disk_treemap(ctx, path: str = "") -> ToolResult:
    from pathlib import Path

    from .. import pcplus

    root = Path(path).expanduser() if path else Path.home()
    try:
        items = await asyncio.to_thread(pcplus.folder_sizes, root)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not items:
        return ToolResult(True, "Složka je prázdná.")
    svg = pcplus.treemap_svg(items, f"{root} – {pcplus.human(sum(i['bytes'] for i in items))}")
    out = paths.sub("grafy") / f"mista-{time.strftime('%Y%m%d-%H%M%S')}.svg"
    out.write_text(svg, encoding="utf-8")
    att = await ctx.store.save(out.name, svg.encode(), "image/svg+xml", conv_id=ctx.memory.current_conversation) \
        if getattr(ctx, "store", None) else None
    top = ", ".join(f"{i['name']} {pcplus.human(i['bytes'])}" for i in items[:6])
    return ToolResult(True, f"Nejvíc zabírá: {top}.", data=items[:20], attachments=[att.id] if att else [])


def _inst_details(a: dict) -> list[str]:
    return [f"Program: {a.get('package_id', '')}", "Nainstaluje se přes winget (Microsoft) tiše a bez reklamních doplňků.",
            "Půjde zase odebrat: „odinstaluj, co jsi nainstaloval“."]


@tool("app_search", "Najde program k instalaci ve winget (katalog Microsoftu): přesné ID, verzi a zdroj. Nic neinstaluje.",
      category="aplikace", perm="apps")
async def app_search(ctx, query: str) -> ToolResult:
    from .. import pcplus

    try:
        r = await asyncio.to_thread(pcplus.winget, ["search", query, "--accept-source-agreements"])
    except (RuntimeError, OSError) as e:
        return ToolResult(False, str(e))
    found = pcplus.parse_winget_search(r.stdout or "")[:10]
    if not found:
        return ToolResult(True, f"Ve winget jsem „{query}“ nenašel.")
    return ToolResult(True, "; ".join(f"{f['name']} ({f['id']} {f['version']})" for f in found), data=found)


@tool("app_install", "Nainstaluje program přes winget podle PŘESNÉHO ID z app_search. Vždy s potvrzením; JARVIS si pamatuje, "
      "co nainstaloval, a umí to zase odebrat.", danger=True, details=_inst_details, category="aplikace", perm="system")
async def app_install(ctx, package_id: str) -> ToolResult:
    from .. import pcplus

    try:
        r = await asyncio.to_thread(pcplus.install, ctx, package_id)
    except (RuntimeError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(r["ok"], f"Nainstalováno: {package_id}." if r["ok"] else f"Instalace se nepovedla: {r['output'][-200:]}")


@tool("app_uninstall", "Odinstaluje program přes winget (přesné ID). Bez ID: seznam programů, které nainstaloval JARVIS.",
      danger_if=lambda a: bool(a.get("package_id")), category="aplikace", perm="system",
      details=lambda a: [f"Odinstalovat: {a.get('package_id', '')}"])
async def app_uninstall(ctx, package_id: str = "") -> ToolResult:
    from .. import pcplus

    if not package_id:
        led = pcplus.ledger(ctx)
        return ToolResult(True, ("JARVIS nainstaloval: " + ", ".join(x["id"] for x in led)) if led else "JARVIS zatím nic neinstaloval.",
                          data=led)
    try:
        r = await asyncio.to_thread(pcplus.uninstall, ctx, package_id)
    except (RuntimeError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(r["ok"], f"Odinstalováno: {package_id}." if r["ok"] else f"Nepovedlo se: {r['output'][-200:]}")


@tool("service_start_type", "Změní, jak se spouští služba Windows (Automatic / Manual / Disabled). Původní stav si pamatuje "
      "a service_revert ho vrátí. Bezpečnostní a systémové služby nemění.", danger=True, category="systém", perm="system",
      details=lambda a: [f"Služba: {a.get('name', '')} → {a.get('start_type', '')}", "Původní nastavení jde vrátit."])
async def service_start_type(ctx, name: str, start_type: Literal["Automatic", "Manual", "Disabled"]) -> ToolResult:
    from .. import pcplus

    try:
        r = await asyncio.to_thread(pcplus.set_service, ctx, name, start_type)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Služba {r['name']}: {r['was']} → {r['now']}.", data=r)


@tool("service_revert", "Vrátí službě Windows typ spuštění, který měla, než ho JARVIS změnil.", danger=True, category="systém",
      perm="system")
async def service_revert(ctx, name: str) -> ToolResult:
    from .. import pcplus

    try:
        r = await asyncio.to_thread(pcplus.revert_service, ctx, name)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Služba {r['name']} je zpátky, jak byla.")


@tool("pc_baseline", "Před / po: action=save uloží stav PC (paměť v klidu, místo na disku, procesy, programy po startu) před "
      "úpravou; action=compare ho porovná s tím, jak je teď – důkaz, že úprava pomohla.", category="systém")
async def pc_baseline(ctx, action: Literal["save", "compare"] = "save", label: str = "") -> ToolResult:
    from .. import pcplus

    if action == "save":
        s = await asyncio.to_thread(pcplus.save_baseline, ctx, label)
        return ToolResult(True, f"Uloženo: paměť {s['ram_used_gb']} GB, volno {s['disk_free_gb']} GB, {s['processes']} procesů.", data=s)
    try:
        c = await asyncio.to_thread(pcplus.compare, ctx)
    except ValueError as e:
        return ToolResult(False, str(e))
    names = {"ram_used_gb": "paměť", "disk_free_gb": "volno na disku (GB)", "processes": "procesy", "startup_apps": "programy po startu",
             "ram_used_pct": "paměť %"}
    lines = [f"{names.get(r['what'], r['what'])}: {r['before']} → {r['after']}{'' if r['same'] else (' ✓' if r['better'] else ' ✗')}"
             for r in c["rows"]]
    return ToolResult(True, "; ".join(lines), data=c)


@tool("gpu_driver_check", "Zjistí verzi a stáří ovladače grafické karty; když je starší než půl roku, dá odkaz na stránku "
      "výrobce. Nic nestahuje ani neinstaluje.", category="systém")
async def gpu_driver_check(ctx) -> ToolResult:
    from .. import pcplus

    if not pcplus.WIN:
        return ToolResult(False, "Ovladače grafiky kontroluju jen ve Windows.")
    rows = await asyncio.to_thread(pcplus.gpu_drivers)
    if not rows:
        return ToolResult(False, "Grafickou kartu jsem nenašel.")
    parts = [f"{r['name']}: ovladač {r['version']} z {r['date']}" + (f" ({r['age_days']} dní) – je starší, novější najdeš na "
             f"{r['page']}" if r["old"] and r["page"] else "") for r in rows]
    return ToolResult(True, "; ".join(parts), data=rows)


@tool("device_conflicts", "Zařízení s problémem (Správce zařízení) a prostředky, o které se dělí s jinými – mapa konfliktů, "
      "s vysvětlením kódu chyby. Jen čte.", category="systém")
async def device_conflicts(ctx) -> ToolResult:
    from .. import pcplus

    if not pcplus.WIN:
        return ToolResult(False, "Správce zařízení čtu jen ve Windows.")
    c = await asyncio.to_thread(pcplus.conflicts)
    if not c["problems"]:
        return ToolResult(True, "Žádné zařízení nehlásí problém.", data=c)
    return ToolResult(True, "; ".join(f"{p['name']}: {p['meaning']} (kód {p['code']})" for p in c["problems"][:8])
                      + (f". Sdílené prostředky: {len(c['shared'])}." if c["shared"] else ""), data=c)


@tool("game_fps", "Měří FPS hry živě v notchi přes PresentMon (zdarma od Intelu, musí být nainstalovaný). exe = název "
      "procesu hry, např. VALORANT-Win64-Shipping.exe; on=false měření ukončí.", category="hry")
async def game_fps(ctx, exe: Annotated[str, "proces hry"] = "", on: bool = True) -> ToolResult:
    from .. import pcplus

    fw = getattr(ctx, "fpswatch", None)
    if fw is None:
        fw = ctx.fpswatch = pcplus.FpsWatch(ctx)
    if not on:
        fw.stop()
        return ToolResult(True, "Měření FPS vypnuto.")
    if not exe:
        return ToolResult(False, "Řekni, jaká hra (název procesu).")
    r = fw.start(exe)
    return ToolResult(r["ok"], r["message"])


@tool("dynamic_lock", "Dynamický zámek Windows: PC se samo zamkne, když od něj odejdeš se spárovaným telefonem (Bluetooth). "
      "on=true zapne a otevře spárování Bluetooth.", danger=True, category="zabezpečení", perm="system",
      details=lambda a: ["Zapne Dynamický zámek Windows (EnableGoodbye)." if a.get("on", True) else "Vypne Dynamický zámek Windows."])
async def dynamic_lock(ctx, on: bool = True) -> ToolResult:
    from .. import phoneplus

    r = await asyncio.to_thread(phoneplus.dynamic_lock, on)
    return ToolResult(r["ok"], r["message"])
