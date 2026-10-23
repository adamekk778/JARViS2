from __future__ import annotations

from .base import ToolResult, tool


@tool("remember", "Zapamatuje si trvale fakt o uživateli (jméno, preference, důležité věci).", category="paměť")
async def remember(ctx, fact: str) -> ToolResult:
    from ..redact import looks_secret

    if looks_secret(fact):
        return ToolResult(False, "Hesla, PINy a klíče si z bezpečnostních důvodů nepamatuji.")
    ctx.memory.remember(fact)
    return ToolResult(True, f"Zapamatováno: {fact}")


@tool("forget", "Zapomene fakt (podle části textu).", category="paměť")
async def forget(ctx, fact: str) -> ToolResult:
    n = ctx.memory.forget(fact)
    return ToolResult(n > 0, f"Zapomenuto: {n}")


@tool("search_history", "Prohledá historii konverzací.", category="paměť")
async def search_history(ctx, query: str) -> ToolResult:
    hits = ctx.memory.search(query, limit=15)
    return ToolResult(True, f"{len(hits)} zpráv", data=hits)
