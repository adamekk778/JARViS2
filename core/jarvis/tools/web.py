from __future__ import annotations

import asyncio
import urllib.parse
from typing import Annotated

from .base import ToolResult, tool


@tool("open_url", "Otevře webovou adresu ve výchozím prohlížeči.", category="web")
async def open_url(ctx, url: Annotated[str, "URL"]) -> ToolResult:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    await asyncio.to_thread(ctx.platform.open_url, url)
    return ToolResult(True, f"Otevírám {url}")


@tool("google_search", "Otevře vyhledávání Google v prohlížeči (když chce uživatel výsledky VIDĚT).", category="web")
async def google_search(ctx, query: Annotated[str, "co hledat"]) -> ToolResult:
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    await asyncio.to_thread(ctx.platform.open_url, url)
    return ToolResult(True, f"Hledám na Googlu: {query}")


def _ddg(query: str, max_results: int, news: bool) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as d:
        if news:
            return list(d.news(query, max_results=max_results))
        return list(d.text(query, max_results=max_results))


@tool("web_search", "Vyhledá na internetu a vrátí výsledky (titulek, odkaz, úryvek). Použij pro aktuální informace, "
      "zprávy, fakta, ceny. Pro detail pak web_read.", category="web")
async def web_search(ctx, query: Annotated[str, "dotaz"], max_results: int = 6, news: bool = False) -> ToolResult:
    res = await asyncio.to_thread(_ddg, query, max_results, news)
    items = [{"title": r.get("title"), "url": r.get("href") or r.get("url"), "snippet": r.get("body") or r.get("excerpt"),
              "date": r.get("date")} for r in res]
    return ToolResult(True, f"{len(items)} výsledků pro „{query}“", data=items)


@tool("web_read", "Stáhne webovou stránku a vrátí její hlavní text (pro shrnutí článku, přečtení stránky).", category="web")
async def web_read(ctx, url: Annotated[str, "URL"], max_chars: int = 12000) -> ToolResult:
    import trafilatura

    async with ctx.http() as client:
        r = await client.get(url, follow_redirects=True, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/2"})
        r.raise_for_status()
        html = r.text
    text = await asyncio.to_thread(trafilatura.extract, html, include_links=False) or ""
    if not text:
        import re

        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
    return ToolResult(True, f"Přečteno {len(text)} znaků", data=text[:max_chars])
