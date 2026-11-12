"""3.12 Poslech zařízení as a tool – so "poslouchej, co se říká" / "hotovo, udělej z toho prompt" work by voice."""
from __future__ import annotations

import asyncio
from typing import Literal

from .base import ToolResult, tool


@tool("device_listen", "Poslouchej, co hraje z počítače (video, hovor, přednáška), a piš všechno, co se říká – přepis "
      "zvuku zařízení. start = začni poslouchat; stop = přestaň; prompt / summary / notes = přestaň a udělej z přepisu "
      "prompt pro AI, shrnutí nebo poznámky; copy = zkopíruj přepis. Nikdy ne mikrofon, jen zvuk z PC.",
      category="média", perm="screen")
async def device_listen(ctx, action: Literal["start", "stop", "prompt", "summary", "notes", "copy"] = "start") -> ToolResult:
    from .. import devicelisten

    dl = devicelisten.get(ctx)
    if action == "start":
        r = dl.start()
        return ToolResult(bool(r.get("ok")), r.get("message", ""))
    if dl.on:
        dl.stop()
        await asyncio.sleep(2.0)              # the last piece is still being written down
    if action == "stop":
        w = (dl.last or {}).get("words", 0)
        return ToolResult(True, f"Přestal jsem poslouchat – {w} slov. Mám z toho udělat prompt, shrnutí, nebo poznámky?")
    r = await devicelisten.act(ctx, action)
    return ToolResult(bool(r.get("ok")), r.get("text", "")[:6000] + ("\n\n(Zkopírováno do schránky.)" if r.get("copied") else ""))
