"""OMEGA wave 24 by voice: the maker workshop and planning – bill of materials, part compatibility, serial monitor, sensor
chart, robot arm, task dependency plan, formula explorer, learning prerequisites, one search across everything,
search over the user's own workflows, and naming groups of windows."""
from __future__ import annotations

import asyncio
import time
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


@tool("bill_of_materials", "Kusovník (BOM) ze seznamu součástek (CSV, i export z KiCadu): sloučí stejné součástky, spočítá kusy "
      "pro N desek, cenu, a upozorní na chybějící ceny a různá pouzdra.", category="věda", perm="files_read")
async def bill_of_materials(ctx, file: str, boards: int = 1) -> ToolResult:
    from .. import maker

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        r = await asyncio.to_thread(maker.bom, p, max(1, boards))
    except ValueError as e:
        return ToolResult(False, str(e))
    msg = f"{r['unique']} druhů, {r['pieces']:g} kusů pro {boards} desek, cena {r['total']:g}."
    if r["missing_price"]:
        msg += f" Bez ceny: {', '.join(r['missing_price'][:5])}."
    if r["footprint_conflicts"]:
        msg += f" Různá pouzdra: {'; '.join(r['footprint_conflicts'][:3])}."
    return ToolResult(True, msg, data=r)


@tool("parts_compatibility", "Elektrická kompatibilita součástek: napájení v rozsahu, logické úrovně mezi řadičem a moduly "
      "(3,3 V vs 5 V), proud z pinů a celkový odběr proti zdroji.", category="věda")
async def parts_compatibility(ctx, parts: Annotated[list[dict], "[{name, role: mcu/sensor/module/actuator, logic_v, vin_min, vin_max, current_ma, five_v_tolerant}]"],
                              supply_v: float, supply_ma: float = 0) -> ToolResult:
    from .. import maker

    if not parts:
        return ToolResult(False, "Zadej součástky.")
    r = maker.compatibility(parts, supply_v, supply_ma)
    if r["compatible"]:
        return ToolResult(True, "Sedí to: " + "; ".join(r["ok"]) + ".", data=r)
    return ToolResult(True, "Problémy: " + "; ".join(r["issues"]) + ".", data=r)


@tool("serial_monitor", "Sériový monitor (Arduino, ESP32…): seznam portů, nebo přečte port po zadanou dobu (volitelně pošle "
      "jeden řádek) a vrátí výpis i čísla z něj.", category="věda", perm="system")
async def serial_monitor(ctx, port: str = "", baud: int = 115200, seconds: int = 5, send: str = "") -> ToolResult:
    from .. import maker

    try:
        if not port:
            ports = await asyncio.to_thread(maker.serial_ports)
            return ToolResult(True, "; ".join(f"{p['port']} – {p['description']}" for p in ports) or "Žádný sériový port.", data=ports)
        r = await asyncio.to_thread(maker.serial_read, port, baud, max(1, min(seconds, 120)), 2000, send)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – port busy / missing
        return ToolResult(False, f"Port {port} nejde otevřít: {str(e)[:150]}")
    if not r["lines"]:
        return ToolResult(True, f"Za {r['seconds']} s z {port} nic nepřišlo (zkontroluj rychlost {baud}).", data=r)
    return ToolResult(True, f"{len(r['lines'])} řádků ({r['per_second']}/s): " + " | ".join(r["lines"][-8:]), data=r)


@tool("sensor_chart", "Graf dat ze senzorů (CSV se sloupci čísel, nebo seznam hodnot): čárový graf jako obrázek a min / max / "
      "průměr každé řady.", category="věda", perm="files_read")
async def sensor_chart(ctx, file: str = "", columns: list[str] | None = None, values: dict[str, list[float]] | None = None, title: str = "") -> ToolResult:
    from .. import maker

    try:
        series = values or (await asyncio.to_thread(maker.csv_series, resolve(file), columns) if file else {})
        out = paths.data_dir() / "grafy" / f"graf-{time.strftime('%Y%m%d-%H%M%S')}.png"
        r = await asyncio.to_thread(maker.sensor_chart, series, out, None, title)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, "; ".join(f"{k}: {s['min']:g}–{s['max']:g}, průměr {s['mean']:g}" for k, s in r["stats"].items()) + f". Graf: {r['path']}",
                      data=r, attachments=[r["path"]])


@tool("robot_arm", "Dvoukloubové rameno robota: úhly kloubů pro dosažení bodu (inverzní kinematika), nebo dráha přes body "
      "s kontrolou dosahu, rozsahu kloubů a skoků úhlů.", category="věda")
async def robot_arm(ctx, l1: float, l2: float, points: Annotated[list[list[float]], "body [x, y]"], joint_min: float = -180, joint_max: float = 180) -> ToolResult:
    from .. import maker

    pts = [(float(p[0]), float(p[1])) for p in points if len(p) >= 2]
    if not pts:
        return ToolResult(False, "Zadej aspoň jeden bod [x, y].")
    if len(pts) == 1:
        r = maker.arm_ik(l1, l2, *pts[0])
        if not r["reachable"]:
            return ToolResult(True, f"Nedosáhne: {r['why']}.", data=r)
        return ToolResult(True, f"Rameno {r['shoulder_deg']}°, loket {r['elbow_deg']}° (kontrola: {r['check']}).", data=r)
    r = maker.arm_path(l1, l2, pts, 10, (joint_min, joint_max))
    return ToolResult(True, (f"Dráha projde, {len(r['path'])} poloh, největší skok kloubu {r['max_jump_deg']}°." if r["ok"]
                             else "Problémy: " + "; ".join(r["problems"][:5]) + "."), data=r)


@tool("task_plan", "Plán úkolů se závislostmi (co musí být hotové před čím): pořadí, kdy co nejdřív začít, kritická cesta, "
      "rezervy, co jde dělat souběžně, a kruhové závislosti.", category="plánování")
async def task_plan(ctx, tasks: Annotated[list[dict], "[{name, days, after: [názvy]}]"]) -> ToolResult:
    from .. import maker

    if not tasks:
        return ToolResult(False, "Zadej úkoly.")
    r = maker.task_plan(tasks)
    if r.get("cycle"):
        return ToolResult(False, f"Kruhová závislost: {', '.join(r['cycle'])} – na sebe navzájem čekají.", data=r)
    msg = f"Celkem {r['finish_days']:g} dní. Kritická cesta: {' → '.join(r['critical'])}."
    loose = [f"{n} (+{s:g} d)" for n, s in r["slack"].items() if s > 0]
    if loose:
        msg += " Rezerva: " + ", ".join(loose[:6]) + "."
    if r["unknown"]:
        msg += f" Neznámé závislosti: {', '.join(r['unknown'])}."
    return ToolResult(True, msg, data=r)


@tool("formula_explorer", "Prozkoumá vzorec: spočítá ho pro rozsah jedné proměnné (ostatní pevné), najde minimum a maximum a "
      "jak citlivě výsledek reaguje (o kolik % se změní při změně proměnné o 1 %).", category="věda")
async def formula_explorer(ctx, formula: str, variable: str, start: float, stop: float, steps: int = 10,
                           fixed: dict[str, float] | None = None) -> ToolResult:
    from .. import maker

    try:
        r = maker.explore_formula(formula, variable, start, stop, max(2, min(steps, 200)), fixed)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"{variable} {start:g}…{stop:g}: výsledek {r['min']:g} až {r['max']:g}" +
                      (f"; pružnost {r['elasticity']:g} (1 % změny {variable} → {r['elasticity']:g} % výsledku)" if r["elasticity"] is not None else "") + ".", data=r)


@tool("learning_path", "Mapa předpokladů učiva: co se naučit a v jakém pořadí, aby šlo zvládnout cílové téma (a co už umíš, "
      "se přeskočí).", category="učení")
async def learning_path(ctx, topics: Annotated[dict[str, list[str]], "téma → jeho předpoklady"], goal: str, known: list[str] | None = None) -> ToolResult:
    from .. import maker

    try:
        r = maker.prerequisites(topics, goal, known)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"{r['steps']} kroků: " + " → ".join(r["order"]) + "." + (f" Nedefinované: {', '.join(r['undefined'])}." if r["undefined"] else ""), data=r)


@tool("search_everything", "Hledá všude najednou: konverzace a paměť, zaindexované dokumenty, kalendář, seznamy, e-maily a tvé "
      "postupy – na „kde jsem to viděl“.", category="paměť", perm="files_read")
async def search_everything(ctx, query: str) -> ToolResult:
    from .. import maker

    r = await maker.search_everything(ctx, query)
    if not r:
        return ToolResult(True, f"„{query}“ jsem nikde nenašel.", data={})
    return ToolResult(True, " | ".join(f"{k}: " + "; ".join(f"{x['title']}" + (f" – {x['text'][:60]}" if x.get("text") else "") for x in v[:3])
                                       for k, v in r.items()), data=r)


@tool("find_workflow", "Najde tvůj vlastní postup podle slov: protokoly, automatizace, dovednosti a nahrané postupy na webu "
      "(„jak jsem to minule dělal s fakturou?“).", category="paměť")
async def find_workflow(ctx, query: str) -> ToolResult:
    from .. import maker

    hits = maker.workflow_search(ctx, query)
    if not hits:
        return ToolResult(True, "Žádný uložený postup k tomu nemám.", data=[])
    return ToolResult(True, "; ".join(f"{h['kind']} „{h['title']}“ ({h['text']})" for h in hits[:8]) + ".", data=hits)


@tool("name_window_groups", "Pojmenuje skupiny otevřených oken podle toho, na čem pracuješ (stejný projekt / dokument napříč "
      "aplikacemi) – pak je jde uložit jako pracovní prostředí.", category="okna", perm="apps")
async def name_window_groups(ctx) -> ToolResult:
    from .. import maker

    wins = await asyncio.to_thread(ctx.platform.window_layout)
    g = maker.name_window_groups(wins)
    if not g:
        return ToolResult(True, "Otevřená okna spolu nesouvisí – žádná skupina.", data=[])
    return ToolResult(True, "; ".join(f"„{x['name']}“: {len(x['windows'])} oken ({', '.join(a for a in x['apps'] if a)})" for x in g) + ".", data=g)
