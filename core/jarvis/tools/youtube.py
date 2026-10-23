from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


def search_youtube(query: str, n: int = 1) -> list[dict]:
    import yt_dlp

    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    return [{"id": e["id"], "title": e.get("title", ""), "channel": e.get("channel") or e.get("uploader", ""),
             "duration": e.get("duration")} for e in (info.get("entries") or []) if e.get("id")]


@tool("youtube_play", "Najde video na YouTube a rovnou ho pustí v prohlížeči (písničky, trailery, videa).", category="média")
async def youtube_play(ctx, query: Annotated[str, "co pustit"]) -> ToolResult:
    res = await asyncio.to_thread(search_youtube, query, 1)
    if not res:
        return ToolResult(False, f"Na YouTube jsem nic nenašel pro „{query}“")
    v = res[0]
    await asyncio.to_thread(ctx.platform.open_url, f"https://www.youtube.com/watch?v={v['id']}&autoplay=1")
    return ToolResult(True, f"Pouštím: {v['title']}", data=v)


@tool("youtube_search", "Vyhledá videa na YouTube a vrátí seznam (nepouští).", category="média")
async def youtube_search(ctx, query: Annotated[str, "dotaz"], count: int = 5) -> ToolResult:
    res = await asyncio.to_thread(search_youtube, query, count)
    return ToolResult(True, f"{len(res)} videí", data=res)
