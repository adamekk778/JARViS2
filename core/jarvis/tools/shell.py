from __future__ import annotations

import asyncio
import re
from typing import Annotated

from .base import ToolResult, tool

# OMEGA 297 / 704: commands that can wipe a disk or the ability to recover are never run by JARVIS, even when approved.
# The user does these themselves, in Windows, if they really mean it.
NEVER = re.compile(r"(?ix)(?:^|[\s;|&(])(?:format(?:\.com)?\s+[a-z]:|format-volume|clear-disk|initialize-disk|remove-partition"
                   r"|diskpart|cipher(?:\.exe)?\s+/w|vssadmin(?:\.exe)?\s+(?:delete|resize)|wbadmin(?:\.exe)?\s+delete"
                   r"|bcdedit(?:\.exe)?\s+/delete|remove-computerrestorepoint|wmic\s+shadowcopy\s+delete|mkfs|dd\s+if=)")


def never_reason(command: str) -> str:
    m = NEVER.search(command or "")
    return m.group(0).strip(" ;|&(") if m else ""


@tool("run_shell", "Spustí příkaz v PowerShellu na PC a vrátí výstup. Pro pokročilé věci, které jiné nástroje neumí.",
      danger=True, category="systém")
async def run_shell(ctx, command: Annotated[str, "PowerShell příkaz"], timeout: int = 60) -> ToolResult:
    bad = never_reason(command)
    if bad:
        return ToolResult(False, f"Tohle JARVIS nikdy nespouští ({bad}): může to nevratně smazat disk nebo zálohy. "
                                 "Pokud to opravdu chceš, udělej to sám ve Windows (Správa disků).")
    code, out = await asyncio.to_thread(ctx.platform.run_shell, command, timeout)
    return ToolResult(code == 0, f"exit {code}", data=out[-8000:])
