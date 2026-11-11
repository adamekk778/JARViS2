from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("open_app", "Spustí aplikaci na PC podle názvu (Spotify, Discord, Steam, Word, kalkulačka…).", category="aplikace")
async def open_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    hit = await asyncio.to_thread(ctx.platform.open_app, name)
    return ToolResult(True, f"Spouštím {hit}")


GAME_HINTS = ("steamapps", "epic games", "riot games", "ubisoft", "ea games", "battle.net", "gog galaxy", "rockstar games",
              "xboxgames", "minecraft", "roblox", "fortnite", "valorant", "leagueoflegends", "cs2", "dota2")


def matching_apps(name: str) -> list[dict]:
    """The running programs close_app would end: [{name, path, count, game}] – shown before anything is closed."""
    try:
        import psutil
    except ImportError:
        return []
    from .platform.windows import ALIASES

    target = ALIASES.get(name.lower(), name).lower().replace(" ", "")
    found: dict[str, dict] = {}
    for p in psutil.process_iter(["name", "exe"]):
        pname = (p.info.get("name") or "").lower().removesuffix(".exe")
        if not pname or pname in ("python", "pythonw", "jarvis") or not (target in pname or (len(pname) >= 4 and pname in target)):
            continue
        exe = (p.info.get("exe") or "").lower()
        it = found.setdefault(pname, {"name": p.info.get("name") or pname, "path": exe, "count": 0, "game": False})
        it["count"] += 1
        it["game"] = it["game"] or any(g in exe or g in pname for g in GAME_HINTS)
    return list(found.values())


def _close_details(a: dict, ctx=None) -> list[str]:
    """What the confirmation shows: which programs end, and a warning for games and unsaved work."""
    apps = matching_apps(str(a.get("name", "")))
    if not apps:
        return [f"„{a.get('name', '')}“ teď neběží – nic se nezavře."]
    out = [f"Zavřu: {x['name']}" + (f" ({x['count']} procesy)" if x["count"] > 1 else "") for x in apps[:6]]
    if any(x["game"] for x in apps):
        out.append("🎮 Je to hra – rozehraná, neuložená hra se ztratí.")
    out.append("Neuložená práce v nich se ztratí.")
    return out


@tool("close_app", "Zavře (ukončí) aplikaci podle názvu. Vždy se nejdřív zeptá uživatele (hry, neuložená práce).",
      danger=True, details=_close_details, category="aplikace")
async def close_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    n = await asyncio.to_thread(ctx.platform.close_app, name)
    return ToolResult(n > 0, f"Zavřeno procesů: {n}" if n else f"{name} neběží")


@tool("list_apps", "Vrátí seznam nainstalovaných aplikací (pro nalezení správného názvu).", category="aplikace")
async def list_apps(ctx, filter: Annotated[str, "volitelný filtr"] = "") -> ToolResult:  # noqa: A002
    apps = await asyncio.to_thread(ctx.platform.list_apps)
    if filter:
        apps = [a for a in apps if filter.lower() in a.lower()]
    return ToolResult(True, f"{len(apps)} aplikací", data=apps[:200])
