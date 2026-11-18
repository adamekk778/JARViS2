"""3.13 Hraní za tebe: the tools that start and stop it (autopilot.py does the playing)."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


def _details(a: dict, ctx=None) -> list[str]:
    return [f"Budu hrát {a.get('game', 'hru')} za tebe {a.get('minutes', 30)} min – myší a klávesnicí.",
            "Jakmile sáhneš na myš nebo klávesnici, hru ti hned vrátím. Do chatu nepíšu, nic nekupuji, ze hry neodcházím."]


@tool("play_for_me", "Hraje za uživatele hru, když je pryč od PC (Roblox, Minecraft…): dívá se na obrazovku a ovládá klávesnici "
      "a myš podle toho, co uživatel o hře vysvětlil. Skončí, když se uživatel vrátí k myši/klávesnici, nebo když vyprší čas.",
      danger=True, details=_details, category="ovládání počítače")
async def play_for_me(ctx, game: Annotated[str, "název hry, např. Roblox"],
                      how: Annotated[str, "co uživatel vysvětlil: jak se hra hraje a co v ní dělat (prázdné = co vysvětlil minule)"] = "",
                      minutes: Annotated[int, "jak dlouho hrát (minuty, nejvýš 240)"] = 30) -> ToolResult:
    from .. import autopilot

    try:
        msg = await autopilot.of(ctx).start(game, how, minutes)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, msg)


@tool("play_for_me_stop", "Přestane hrát hru za uživatele (vrátí mu ji).", category="ovládání počítače")
async def play_for_me_stop(ctx) -> ToolResult:
    from .. import autopilot

    ap = autopilot.of(ctx)
    if not ap.on:
        return ToolResult(True, "Teď za tebe nic nehraju.")
    await ap.stop("Zastaveno na tvou žádost.")
    return ToolResult(True, f"Hotovo – {ap.game} je zase tvoje (tahů: {ap.steps}).")
