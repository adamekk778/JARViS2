from __future__ import annotations

import asyncio
import base64
import datetime as dt

from contextlib import contextmanager

from .base import ToolResult, tool


@contextmanager
def capturing(ctx, source: str):
    """Tells the UI (red dot in the notch) that JARVIS is looking at the screen right now."""
    ctx.bus.publish("screen_capture", active=True, source=source)
    try:
        yield
    finally:
        ctx.bus.publish("screen_capture", active=False, source=source)


async def describe_image(ctx, png: bytes, question: str) -> str:
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    msgs = [{"role": "user", "content": [{"type": "text", "text": question},
                                         {"type": "image_url", "image_url": {"url": url}}]}]
    return await ctx.router.complete(msgs, need_vision=True)


@tool("screenshot", "Udělá snímek obrazovky PC, pošle ho do chatu a volitelně popíše, co je na obrazovce.", category="obrazovka")
async def screenshot(ctx, describe: bool = False, question: str = "Popiš stručně česky, co je na obrazovce.") -> ToolResult:
    with capturing(ctx, "screenshot"):
        png = await asyncio.to_thread(ctx.platform.screenshot)
    att = await ctx.store.save(f"screenshot-{dt.datetime.now():%Y%m%d-%H%M%S}.png", png, "image/png")
    summary = "Snímek obrazovky pořízen"
    data = None
    if describe:
        try:
            data = await describe_image(ctx, png, question)
        except Exception as e:  # vision optional
            data = f"(popis se nepodařil: {e})"
    return ToolResult(True, summary, data=data, attachments=[att.id])
