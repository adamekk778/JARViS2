from __future__ import annotations

import mimetypes
from pathlib import Path

from .base import ToolResult, tool
from .files import resolve


@tool("send_to_phone", "Pošle zprávu/odkaz jako notifikaci na spárovaný telefon.", category="telefon")
async def send_to_phone(ctx, text: str, title: str = "JARVIS", url: str = "") -> ToolResult:
    n = ctx.notify(title, text, url=url, speak=False, target="mobile")
    return ToolResult(True, "Odesláno na telefon" if n else "Telefon není připojený – uloženo do chatu")


@tool("send_file", "Pošle soubor z PC do chatu jako přílohu (stáhne si ho na telefonu).", category="telefon")
async def send_file(ctx, path: str) -> ToolResult:
    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    att = await ctx.store.save_path(Path(p), mime)
    return ToolResult(True, f"Posílám {p.name}", attachments=[att.id])
