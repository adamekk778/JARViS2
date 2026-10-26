"""OMEGA wave 30 by voice: looking after the PC – service dependencies, drivers to roll back, power plan and battery,
recovery media, frame pacing in games, app launch time and priority profiles."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


async def _probe(name: str):
    from .. import pccare

    return await asyncio.to_thread(pccare.probe, name)


@tool("service_dependencies", "Závislosti služeb Windows: které automatické služby neběží a co tím nefunguje; u zadané služby co "
      "potřebuje a co na ní závisí (i nepřímo). Jen čte.", category="systém", perm="system")
async def service_dependencies(ctx, service: str = "") -> ToolResult:
    from .. import pccare

    try:
        r = pccare.services_graph(await _probe("services"), service)
    except ValueError as e:
        return ToolResult(False, str(e))
    if service:
        f = r["focus"]
        msg = f"{f['display']} ({f['status']}): potřebuje {', '.join(f['needs']) or 'nic'}" + \
              (f" – NEBĚŽÍ: {', '.join(f['needs_not_running'])}" if f["needs_not_running"] else "") + \
              f"; závisí na ní {len(f['all_dependents'])} služeb ({', '.join(f['needed_by'][:5]) or 'žádná'})."
        return ToolResult(True, msg, data=r)
    bad = [b for b in r["stopped_automatic"] if b["breaks"]]
    msg = f"{r['services']} služeb, {len(r['stopped_automatic'])} automatických neběží"
    if bad:
        msg += ". Kvůli tomu nefunguje: " + "; ".join(f"{b['display']} → {', '.join(b['breaks'][:4])}" for b in bad[:4])
    return ToolResult(True, msg + ".", data=r)


@tool("driver_rollback_check", "Najde ovladače nainstalované v posledních 90 dnech, po kterých začal počítač padat, a řekne, jestli "
      "jde vrátit starší verzi (je ještě v systému) a jak. Jen čte; Správce zařízení otevře, když chceš.", category="systém", perm="system")
async def driver_rollback_check(ctx, open_device_manager: bool = False) -> ToolResult:
    from .. import pccare

    try:
        r = pccare.driver_suspects(await _probe("drivers"))
    except ValueError as e:
        return ToolResult(False, str(e))
    if open_device_manager and sys.platform == "win32":
        subprocess.Popen(["mmc.exe", "devmgmt.msc"])
    if not r["drivers"]:
        return ToolResult(True, "Za 90 dní se žádný ovladač neinstaloval.", data=r)
    if not r["suspects"]:
        return ToolResult(True, f"{len(r['drivers'])} nových ovladačů, žádný se s pády neshoduje (pádů za 90 dní: {r['crashes_90d']}).", data=r)
    s = r["suspects"][0]
    msg = (f"Podezřelý: {s['device']} (ovladač {s['version']} od {s['installed']}) – pádů 30 dní před: {s['crashes_before']}, po: {s['crashes_after']}. "
           + (f"Starší verze je v systému ({s['older_in_store'][0]}), jde vrátit: " + " → ".join(r["steps"][:3]) if s["can_roll_back"]
              else "Starší verze v systému není – stáhni předchozí ovladač od výrobce."))
    return ToolResult(True, msg + ".", data=r)


@tool("power_check", "Diagnostika napájení: aktivní plán, omezení výkonu procesoru, uspávání, vypínání obrazovky, uspávání USB a "
      "u notebooku zdraví baterie (kapacita proti nové, cykly) – s radami. Jen čte.", category="systém", perm="system")
async def power_check(ctx) -> ToolResult:
    from .. import pccare

    if sys.platform != "win32":
        return ToolResult(False, "Diagnostika napájení je jen pro Windows.")
    st = await asyncio.to_thread(pccare.power_state)
    r = pccare.power_advice(st)
    msg = f"Plán: {(r['active'] or {}).get('name', '?')}"
    if r["battery"]:
        msg += f"; baterie {r['battery']['health_pct']:g} % původní kapacity" + (f", {r['battery']['cycles']} cyklů" if r["battery"]["cycles"] else "")
    msg += (". " + "; ".join(r["tips"]) if r["tips"] else ". Nastavení je v pořádku")
    return ToolResult(True, msg + ".", data={**r, "plans": st["plans"], "settings": st["settings"]})


def _plan_details(args: dict, ctx=None) -> list[str]:
    return [f"Přepnout plán napájení na „{args.get('plan')}“"]


@tool("power_plan_set", "Přepne plán napájení Windows (Vyvážený, Úsporný, Vysoký výkon nebo vlastní) podle názvu.", category="systém",
      perm="system", danger=True, details=_plan_details)
async def power_plan_set(ctx, plan: str) -> ToolResult:
    from .. import pccare
    from ..comms import fold
    from ..pcreport import run_quiet

    if sys.platform != "win32":
        return ToolResult(False, "Jen pro Windows.")
    _c, out, _e = await asyncio.to_thread(run_quiet, ["powercfg", "/list"], 20)
    plans = pccare.parse_plans(out)
    f = fold(plan)
    hit = next((p for p in plans if fold(p["name"]) == f), None) or next((p for p in plans if f in fold(p["name"])), None)
    if not hit:
        return ToolResult(False, f"Plán „{plan}“ nevidím. Mám: {', '.join(p['name'] for p in plans)}.")
    code, _o, err = await asyncio.to_thread(run_quiet, ["powercfg", "/setactive", hit["guid"]], 20)
    return ToolResult(code == 0, f"Plán napájení: {hit['name']}." if code == 0 else f"Přepnutí selhalo: {err[:150]}", data=hit)


@tool("recovery_media_check", "Příprava záchranného disku Windows: je připojený dost velký flash disk, existuje obnovovací oddíl, "
      "je disk šifrovaný (pak je potřeba klíč BitLockeru) – a postup. Na požádání otevře průvodce Windows.", category="systém",
      perm="system", danger_if=lambda a: bool(a.get("open_tool")))
async def recovery_media_check(ctx, open_tool: bool = False) -> ToolResult:
    from .. import pccare

    try:
        r = pccare.recovery_checklist(await _probe("recovery"))
    except ValueError as e:
        return ToolResult(False, str(e))
    if open_tool:
        subprocess.Popen(["RecoveryDrive.exe"])
    msg = "; ".join(f"{'✓' if i['ok'] else '✗' if i['ok'] is False else '•'} {i['item']}: {i['note']}" for i in r["items"])
    return ToolResult(True, msg + (". Otevřel jsem průvodce." if open_tool else ". Řekni „otevři průvodce“ a spustím ho." if r["ready"] else "."), data=r)


@tool("frame_time_report", "Plynulost hry z logu snímků (PresentMon, CapFrameX, MSI Afterburner export CSV): průměrné FPS, 1% a 0,1% "
      "minima, zaseknutí a kdy, rovnoměrnost – a graf.", category="systém", perm="files_read")
async def frame_time_report(ctx, file: str, target_fps: float = 60) -> ToolResult:
    from .. import maker, paths, pccare
    from ..science import read_csv

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Log neexistuje: {p}")
    header, rows, _, _ = await asyncio.to_thread(read_csv, p)
    try:
        ms = pccare.frame_times(header, rows)
        r = pccare.frame_report(ms, target_fps)
    except ValueError as e:
        return ToolResult(False, str(e))
    chart = paths.data_dir() / "grafy" / f"snimky-{p.stem}.png"
    await asyncio.to_thread(maker.sensor_chart, {"čas snímku (ms)": ms[:5000]}, chart, None, "Časy snímků")
    msg = (f"{r['verdict'].capitalize()}: průměr {r['avg_fps']:g} FPS, 1% minimum {r['low_1pct_fps']:g}, 0,1% {r['low_01pct_fps']:g}, "
           f"zaseknutí {r['stutters']}×" + (f" (v {', '.join(str(t) for t in r['stutter_at_s'][:4])} s)" if r["stutters"] else "") + ".")
    return ToolResult(True, msg, data=r, attachments=[str(chart)])


def _launch_details(args: dict, ctx=None) -> list[str]:
    return [f"Spustit {args.get('app')} {args.get('runs', 3)}× a po každém měření ho zavřít"]


@tool("app_launch_time", "Změří, za jak dlouho se program otevře (čas do zobrazení okna), několikrát – první spuštění „za studena“, "
      "další „za tepla“. Program po každém měření zavře.", category="aplikace", perm="apps", danger=True, details=_launch_details)
async def app_launch_time(ctx, app: Annotated[str, "cesta k .exe nebo název (notepad.exe)"], runs: int = 3) -> ToolResult:
    from .. import pccare

    if sys.platform != "win32":
        return ToolResult(False, "Měření spouštění je jen pro Windows.")
    try:
        r = await asyncio.to_thread(pccare.measure_launch, ctx.platform, app, max(1, min(runs, 6)))
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"{r['app']}: poprvé {r['cold_s']:g} s" + (f", pak {r['warm_s']:g} s" if r["warm_s"] is not None else "") + f" ({r['verdict']}).", data=r)


def _profile_details(args: dict, ctx=None) -> list[str]:
    if args.get("restore"):
        return ["Vrátit priority programů, jak byly"]
    return [f"Profil „{args.get('profile')}“: změnit prioritu běžících programů (jen tvých, ne systémových)"]


@tool("performance_profile", "Profil výkonu: „hra“ (synchronizace a pomocníci do pozadí), „práce“ (herní spouštěče do pozadí), "
      "„tichý“ (méně zátěže), nebo vlastní seznam; „vrátit“ vrátí priority přesně jak byly.", category="systém", perm="system",
      danger=True, details=_profile_details)
async def performance_profile(ctx, profile: Annotated[str, "hra / práce / tichý / vlastní"] = "hra", boost: list[str] | None = None,
                              lower: list[str] | None = None, restore: bool = False) -> ToolResult:
    from .. import pccare

    saved = ctx.__dict__.setdefault("_priority_saved", {})
    if restore:
        r = await asyncio.to_thread(pccare.restore_profile, saved)
        return ToolResult(True, f"Vráceno {len(r['restored'])} programů" + (f", {r['ended']} mezitím skončilo" if r["ended"] else "") + ".", data=r)
    if profile not in pccare.PROFILES and not (boost or lower):
        return ToolResult(False, f"Profil: {', '.join(pccare.PROFILES)} – nebo zadej vlastní seznam programů.")
    r = await asyncio.to_thread(pccare.apply_profile, profile, boost, lower, saved)
    if not r["changed"]:
        return ToolResult(True, "Žádný z programů profilu teď neběží.", data={k: v for k, v in r.items() if k != "saved"})
    msg = f"Profil {profile}: " + ", ".join(f"{c['name']} {'↑' if c['to'] == 'high' else '↓'}" for c in r["changed"][:8])
    if r["denied"]:
        msg += f". Nešlo: {', '.join(r['denied'][:4])}"
    return ToolResult(True, msg + ". „Vrať profil“ vše vrátí.", data={k: v for k, v in r.items() if k != "saved"})
