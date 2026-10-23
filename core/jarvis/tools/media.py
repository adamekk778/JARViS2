from __future__ import annotations

import asyncio
from typing import Literal

from .base import ToolResult, tool


@tool("media_control", "Ovládá právě hrající hudbu/video (Spotify, YouTube…): play/pauza, další, předchozí, stop.", category="média")
async def media_control(ctx, action: Literal["play_pause", "next", "previous", "stop"]) -> ToolResult:
    await asyncio.to_thread(ctx.platform.media_key, action)
    names = {"play_pause": "Play/pauza", "next": "Další", "previous": "Předchozí", "stop": "Stop"}
    return ToolResult(True, names[action])


@tool("volume", "Hlasitost PC: nastavit na úroveň (0–100), zesílit, zeslabit, ztlumit, zrušit ztlumení, zjistit.", category="média")
async def volume(ctx, action: Literal["set", "up", "down", "mute", "unmute", "get"], level: int | None = None) -> ToolResult:
    p = ctx.platform
    if action == "get":
        v = await asyncio.to_thread(p.get_volume)
        return ToolResult(True, f"Hlasitost je {v} %", data=v)
    if action == "mute":
        await asyncio.to_thread(p.set_mute, True)
        return ToolResult(True, "Ztlumeno")
    if action == "unmute":
        await asyncio.to_thread(p.set_mute, False)
        return ToolResult(True, "Zvuk zapnut")
    cur = await asyncio.to_thread(p.get_volume)
    step = level if level is not None else 10
    new = {"set": level if level is not None else cur, "up": cur + step, "down": cur - step}[action]
    new = max(0, min(100, int(new)))
    await asyncio.to_thread(p.set_volume, new)
    if new > 0:
        await asyncio.to_thread(p.set_mute, False)
    return ToolResult(True, f"Hlasitost {new} %", data=new)
