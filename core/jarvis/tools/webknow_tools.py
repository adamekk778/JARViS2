"""Spec 2026-11-20: JARVIS knows what is on the internet – the tools the AI uses for it."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("web_research", "Rychle najde cokoli na internetu: hledá najednou v DuckDuckGo, Google Zprávách a na Wikipedii a "
      "rovnou přečte nejlepší stránky (jeden krok místo web_search + web_read). verify=true u zdraví, peněz, práva, "
      "bezpečnosti a sporných faktů: stránky aspoň ze 2 různých webů. deep=true přečte víc stránek.",
      category="web", perm="network")
async def web_research(ctx, query: Annotated[str, "co zjistit"], deep: bool = False, verify: bool = False) -> ToolResult:
    from ..webknow import research

    r = await research.research(ctx, query, deep=deep, verify=verify)
    n = len(r["sources"])
    summary = f"{n} zdrojů pro „{query}“ za {r['took_ms'] / 1000:.1f} s" + (" – jen jeden web" if r["single_domain"] else "")
    return ToolResult(n > 0, summary if n else f"Nic jsem nenašel pro „{query}“.", data=research.format_result(r))
