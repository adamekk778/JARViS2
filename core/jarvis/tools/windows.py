from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from .base import ToolResult, tool


@tool("window_control", "Okna: minimalizovat vše (plocha), obnovit vše, maximalizovat/minimalizovat/zavřít okno, "
      "přepnout na okno podle názvu.", danger_if=lambda a: a.get("action") == "close", category="okna")
async def window_control(ctx, action: Literal["minimize_all", "restore_all", "maximize", "minimize", "focus", "close"],
                         title: Annotated[str, "část názvu okna (prázdné = aktivní okno)"] = "") -> ToolResult:
    name = await asyncio.to_thread(ctx.platform.window_action, action, title)
    return ToolResult(True, f"{action}: {name}")


@tool("list_windows", "Seznam otevřených oken.", category="okna")
async def list_windows(ctx) -> ToolResult:
    w = await asyncio.to_thread(ctx.platform.list_windows)
    return ToolResult(True, f"{len(w)} oken", data=w)


@tool("press_keys", "Stiskne klávesovou zkratku na PC, např. ['ctrl','c'] nebo ['win','d'] nebo ['f5'].", category="okna")
async def press_keys(ctx, keys: list[str]) -> ToolResult:
    await asyncio.to_thread(ctx.platform.hotkey, keys)
    return ToolResult(True, "+".join(keys))


@tool("type_text", "Napíše text do právě aktivního okna (jako by psal uživatel).", category="okna")
async def type_text(ctx, text: str) -> ToolResult:
    await asyncio.to_thread(ctx.platform.type_text, text)
    return ToolResult(True, f"Napsáno {len(text)} znaků")
