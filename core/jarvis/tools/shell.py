from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("run_shell", "Spustí příkaz v PowerShellu na PC a vrátí výstup. Pro pokročilé věci, které jiné nástroje neumí.",
      danger=True, category="systém")
async def run_shell(ctx, command: Annotated[str, "PowerShell příkaz"], timeout: int = 60) -> ToolResult:
    code, out = await asyncio.to_thread(ctx.platform.run_shell, command, timeout)
    return ToolResult(code == 0, f"exit {code}", data=out[-8000:])
