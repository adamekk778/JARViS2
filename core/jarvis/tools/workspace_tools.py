"""OMEGA wave 11 by voice: workspace profiles (save / restore / compare / list / delete), a window to another monitor,
reopen programs that just crashed, keyboard shortcuts for the app in front, and search in the command history."""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


@tool("workspace_save", "Uloží pracovní prostředí pod názvem: které programy jsou otevřené a kde přesně mají okna (i na "
      "kterém monitoru). Na „ulož si tohle rozložení jako Práce“.", category="okna", perm="apps")
async def workspace_save(ctx, name: str, project: str = "") -> ToolResult:
    from .. import workspace

    try:
        ws = await asyncio.to_thread(workspace.save, ctx, name, project)
    except ValueError as e:
        return ToolResult(False, str(e))
    apps = sorted({w.get("app") or w.get("exe") for w in ws["windows"]})
    return ToolResult(True, f"Profil „{name}“ uložen: {len(ws['windows'])} oken ({', '.join(apps[:8])}).", data=ws)


@tool("workspace_restore", "Obnoví uložené pracovní prostředí: spustí programy, které chybí, a rozmístí okna jako minule.",
      category="okna", perm="apps")
async def workspace_restore(ctx, name: str) -> ToolResult:
    from .. import workspace

    try:
        r = await asyncio.to_thread(workspace.restore, ctx, name)
    except ValueError as e:
        return ToolResult(False, str(e))
    msg = f"Profil „{name}“: rozmístěno {r['placed']} z {r['total']} oken" + (f", spuštěno: {', '.join(r['started'])}" if r["started"] else "")
    if r["failed"]:
        msg += f". Nešlo spustit: {'; '.join(r['failed'])}"
    return ToolResult(r["placed"] > 0 or not r["total"], msg + ".", data=r)


@tool("workspace_compare", "Co se změnilo proti uloženému prostředí: co chybí, co přibylo, co se posunulo.", category="okna", perm="apps")
async def workspace_compare(ctx, name: str) -> ToolResult:
    from .. import workspace

    try:
        r = await asyncio.to_thread(workspace.compare, ctx, name)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not (r["missing"] or r["moved"] or r["extra"]):
        return ToolResult(True, "Prostředí odpovídá uloženému profilu.", data=r)
    parts = []
    if r["missing"]:
        parts.append("chybí " + ", ".join(sorted({m.get("app") or m.get("exe") for m in r["missing"]})))
    if r["moved"]:
        parts.append("posunuté " + ", ".join(m["app"] for m in r["moved"]))
    if r["extra"]:
        parts.append("navíc " + ", ".join(sorted({e["app"] for e in r["extra"]})[:6]))
    return ToolResult(True, "; ".join(parts) + ".", data=r)


@tool("workspace_list", "Seznam uložených pracovních prostředí.", category="okna", perm="apps")
async def workspace_list(ctx) -> ToolResult:
    from .. import workspace

    ws = workspace.list_all(ctx)
    return ToolResult(True, ", ".join(f"{w['name']} ({w['windows']} oken)" for w in ws) or "Žádné uložené prostředí.", data=ws)


@tool("workspace_delete", "Smaže uložené pracovní prostředí (jen profil, okna ani programy ne).", category="okna", perm="apps")
async def workspace_delete(ctx, name: str) -> ToolResult:
    from .. import workspace

    return ToolResult(True, f"Profil „{name}“ smazán.") if workspace.delete(ctx, name) else ToolResult(False, f"Profil „{name}“ neexistuje.")


@tool("window_to_monitor", "Přesune okno programu na jiný monitor (1 = hlavní).", category="okna", perm="apps")
async def window_to_monitor(ctx, app: str, monitor: int = 2) -> ToolResult:
    from .. import workspace

    try:
        r = await asyncio.to_thread(workspace.to_monitor, ctx, app, monitor)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(r["ok"], f"{r['app']} je na monitoru {monitor}." if r["ok"] else "Okno nejde přesunout.", data=r)


@tool("reopen_crashed", "Znovu otevře programy, které za poslední hodinu spadly (podle záznamu Windows) a teď neběží.",
      category="okna", perm="apps")
async def reopen_crashed(ctx, minutes: int = 60) -> ToolResult:
    from .. import rescue, workspace

    r = await asyncio.to_thread(rescue.run_probe, "apps")
    if not r["ok"]:
        return ToolResult(False, f"Záznam pádů nejde přečíst: {r['error']}")
    running = await asyncio.to_thread(ctx.platform.running_apps)
    apps = workspace.crashed_recently(rescue.L(r["data"].get("app_errors")), {a.lower() for a in running} | {a.lower().removesuffix(".exe") for a in running}, minutes)
    if not apps:
        return ToolResult(True, "Za tu dobu žádný program nespadl (nebo už zase běží).", data=[])
    opened, failed = [], []
    for a in apps:
        try:
            await asyncio.to_thread(ctx.platform.open_app, a.removesuffix(".exe"))
            opened.append(a)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{a}: {e}")
    return ToolResult(bool(opened), "Znovu otevřeno: " + (", ".join(opened) or "nic") + (f". Nešlo: {'; '.join(failed)}" if failed else "") + ".",
                      data={"opened": opened, "failed": failed})


@tool("shortcuts", "Užitečné klávesové zkratky pro program v popředí (nebo zadaný: Windows, Chrome, Word, Excel, VS Code, "
      "Průzkumník, Outlook, JARVIS).", category="okna")
async def shortcuts(ctx, app: Annotated[str, "program (prázdné = ten v popředí)"] = "") -> ToolResult:
    from .. import workspace

    if not app:
        fg = getattr(ctx.activity, "last_external", {}) if hasattr(ctx, "activity") else {}
        app = fg.get("exe") or fg.get("app") or "windows"
    key, sc = workspace.shortcuts_for(app)
    return ToolResult(True, f"{key.capitalize()}: " + "; ".join(f"{k} = {v}" for k, v in sc), data={"app": key, "shortcuts": sc})


@tool("command_history", "Najde, co jsi kdy JARVISovi řekl nebo co udělal (příkazy a akce), podle slova.", category="paměť")
async def command_history(ctx, query: str) -> ToolResult:
    from .. import workspace

    h = workspace.command_history(ctx, query)
    if not h:
        return ToolResult(True, f"„{query}“ jsem v historii nenašel.", data=[])
    return ToolResult(True, "\n".join(f"{dt.datetime.fromtimestamp(x['ts']):%d. %m. %H:%M} {x['kind']}: {x['text'][:120]}" for x in h[:10]), data=h)
