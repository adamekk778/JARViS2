from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Annotated

from .base import ToolResult, tool


@tool("generate_image", "Vygeneruje obrázek podle popisu (zdarma přes Pollinations.ai) a pošle ho do chatu. "
      "Popis piš anglicky a detailně.", category="tvorba")
async def generate_image(ctx, prompt: Annotated[str, "detailní popis obrázku (anglicky)"], width: int = 1024,
                         height: int = 1024, seed: int | None = None) -> ToolResult:
    q = urllib.parse.quote(prompt[:900])
    params = {"width": max(256, min(2048, width)), "height": max(256, min(2048, height)), "nologo": "true", "model": "flux"}
    if seed is not None:
        params["seed"] = seed
    async with ctx.http() as c:
        r = await c.get(f"https://image.pollinations.ai/prompt/{q}", params=params, timeout=180)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            return ToolResult(False, "Generátor nevrátil obrázek, zkus to znovu")
    ext = "png" if "png" in r.headers["content-type"] else "jpg"
    att = await ctx.store.save(f"obrazek-{dt.datetime.now():%H%M%S}.{ext}", r.content, r.headers["content-type"])
    return ToolResult(True, "Obrázek hotový", attachments=[att.id])
