from __future__ import annotations

import asyncio
from typing import Annotated, Literal

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


@tool("media_seek", "Přetočí právě hrající píseň nebo video na daný čas (v sekundách od začátku).", category="média")
async def media_seek(ctx, seconds: Annotated[float, "kam přetočit, sekundy od začátku"]) -> ToolResult:
    import sys
    import time

    if sys.platform != "win32":
        return ToolResult(False, "Přetáčení umí jen Windows.")
    from ..desktop import media as desk_media

    try:
        ok = await desk_media.seek(float(seconds))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Přetočit nejde: {e}")
    if not ok:
        return ToolResult(False, "Přehrávač přetočení nedovolil.")
    st = getattr(ctx, "media_state", None)
    if isinstance(st, dict) and st.get("title"):              # the notch moves at once, the player confirms later
        st.update(position=float(seconds), at=time.time())
        ctx.bus.publish("media", **st)
    return ToolResult(True, f"Přetočeno na {int(seconds) // 60}:{int(seconds) % 60:02d}")
