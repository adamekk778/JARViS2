from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("open_app", "Spustí aplikaci na PC podle názvu (Spotify, Discord, Steam, Word, kalkulačka…).", category="aplikace")
async def open_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    hit = await asyncio.to_thread(ctx.platform.open_app, name)
    return ToolResult(True, f"Spouštím {hit}")


@tool("close_app", "Zavře (ukončí) aplikaci podle názvu.", category="aplikace")
async def close_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    n = await asyncio.to_thread(ctx.platform.close_app, name)
    return ToolResult(n > 0, f"Zavřeno procesů: {n}" if n else f"{name} neběží")


@tool("list_apps", "Vrátí seznam nainstalovaných aplikací (pro nalezení správného názvu).", category="aplikace")
async def list_apps(ctx, filter: Annotated[str, "volitelný filtr"] = "") -> ToolResult:  # noqa: A002
    apps = await asyncio.to_thread(ctx.platform.list_apps)
    if filter:
        apps = [a for a in apps if filter.lower() in a.lower()]
    return ToolResult(True, f"{len(apps)} aplikací", data=apps[:200])
