from __future__ import annotations

import asyncio

from .base import ToolResult, tool


@tool("clipboard_get", "Přečte text ze schránky.", category="schránka")
async def clipboard_get(ctx) -> ToolResult:
    t = await asyncio.to_thread(ctx.platform.clipboard_get)
    return ToolResult(True, f"{len(t)} znaků ve schránce", data=t[:10000])


@tool("clipboard_set", "Zkopíruje text do schránky.", category="schránka")
async def clipboard_set(ctx, text: str) -> ToolResult:
    await asyncio.to_thread(ctx.platform.clipboard_set, text)
    return ToolResult(True, "Zkopírováno do schránky")
