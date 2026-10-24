"""3.2 Stark tools: "brífink", "spusť protokol párty", "ukaž HUD"."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("briefing", "Ranní brífink jako JARVIS z filmu: den, počasí, dnešní plány, stav PC a hlavní zprávy. "
      "Použij na „brífink“, „co mě dnes čeká“, „dobré ráno“.", category="info")
async def briefing(ctx) -> ToolResult:
    from .. import stark

    b = await stark.briefing(ctx)
    stark.briefing_done(ctx)
    ctx.bus.publish("briefing", **b)
    return ToolResult(True, b["text"], data={k: v for k, v in b.items() if k in ("news", "jobs", "timers")})


@tool("run_protocol", "Spustí protokol (uloženou sérii akcí), např. „spusť protokol párty“, „dobrou noc“, "
      "„pracovní režim“, „herní režim“. Spustí se hned po této odpovědi; odpověz jen krátce, že ho spouštíš.",
      category="systém", perm="apps")
async def run_protocol(ctx, name: Annotated[str, "název protokolu"]) -> ToolResult:
    from .. import stark

    p = stark.find_protocol(ctx, name)
    names = ", ".join(x.name for x in ctx.cfg.stark.protocols) or "žádné"
    if p is None:
        return ToolResult(False, f"Protokol „{name}“ neznám. Mám: {names}. Nové si uživatel vytvoří v Nastavení → Protokoly.")
    stark.start_protocol(ctx, p)
    return ToolResult(True, f"Spouštím protokol {p.name}.", data={"id": p.id, "steps": len(p.steps)})


@tool("list_protocols", "Seznam protokolů (uložených sérií akcí), které umím spustit.", category="systém", perm="apps")
async def list_protocols(ctx) -> ToolResult:
    items = ctx.cfg.stark.protocols
    return ToolResult(True, ", ".join(p.name for p in items) or "Žádné protokoly.",
                      data=[{"id": p.id, "name": p.name, "steps": len(p.steps)} for p in items])


@tool("show_hud", "Otevře nebo zavře Stark HUD: holografický přehled přes celou obrazovku (systémy, počasí, "
      "časovače, protokoly). Na „ukaž HUD“, „ukaž systémy“, „zavři HUD“.", category="systém", perm="apps")
async def show_hud(ctx, close: bool = False) -> ToolResult:
    if not ctx.ui_hook:
        return ToolResult(False, "HUD jde otevřít jen v aplikaci na PC.")
    ctx.ui_hook("hud-close" if close else "hud")
    return ToolResult(True, "HUD zavřen." if close else "Zobrazuji HUD.")
