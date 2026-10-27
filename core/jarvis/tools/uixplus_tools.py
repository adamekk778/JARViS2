"""Wave 46 by voice: a quiet focus mode, the data lens for any text and the window map."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("focus_mode", "Režim soustředění: na zadanou dobu ztiší a zprůhlední rozhraní a nedůležitá upozornění podrží – po skončení "
      "je shrne. Budíky, časovače a věci, o které sis řekl, projdou vždy.", category="rozhraní")
async def focus_mode(ctx, minutes: Annotated[int, "na jak dlouho (0 = vypnout)"] = 50) -> ToolResult:
    ctx.attention.focus(minutes)
    if minutes <= 0:
        s = ctx.attention.flush()
        if s:
            ctx.notify(s["title"], s["body"], speak=False, urgent=True)
        return ToolResult(True, "Režim soustředění vypnut." + (f" Mezitím přišlo {len(s['titles'])} upozornění." if s else ""))
    return ToolResult(True, f"Soustředění na {minutes} min – nebudu rušit, upozornění ti dám potom najednou.")


@tool("data_lens", "Datová lupa: co je v textu na první pohled – částky v Kč, převody jednotek, kolik dní do data, součet a "
      "průměr čísel, barvy, kontrola IČO a IBAN, počet slov. Bez AI, hned.", category="info")
async def data_lens(ctx, text: str) -> ToolResult:
    from .. import uixplus

    items = uixplus.lens(text)
    if not items:
        return ToolResult(True, "V textu nevidím nic k přepočtu ani kontrole.", data=[])
    return ToolResult(True, "; ".join(f"{i['text']} → {i['value']}" for i in items[:8]), data=items)


@tool("window_switch", "Přepne na okno v daném směru od toho aktuálního (vlevo / vpravo / nahoru / dolů) – jako navigace po "
      "mapě oken na obrazovce.", category="okna", perm="input")
async def window_switch(ctx, direction: Annotated[str, "left / right / up / down"]) -> ToolResult:
    import asyncio

    from .. import uixplus

    d = {"vlevo": "left", "doleva": "left", "vpravo": "right", "doprava": "right", "nahoru": "up", "nahoře": "up", "dolů": "down"}.get(direction.lower(), direction.lower())
    if d not in ("left", "right", "up", "down"):
        return ToolResult(False, "Směr: vlevo, vpravo, nahoru, dolů.")
    wins = uixplus.window_map(await asyncio.to_thread(ctx.platform.window_layout), ctx.platform.screen_size())
    fg = (await asyncio.to_thread(ctx.platform.foreground_info) or {}).get("hwnd", 0)
    nb = uixplus.neighbour(wins, fg, d)
    if not nb:
        return ToolResult(False, "Tím směrem žádné okno není.")
    await asyncio.to_thread(ctx.platform.focus_window, nb["hwnd"])
    return ToolResult(True, f"Přepnuto na {nb['app'] or nb['title']}.", data=nb)
