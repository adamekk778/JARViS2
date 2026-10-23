from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from .base import ToolResult, tool
from .files import resolve


@tool("read_attachment", "Přečte obsah přílohy (text z PDF, dokumentu, přepis audia…) po částech od offsetu.", category="přílohy")
async def read_attachment(ctx, id: str, offset: int = 0, length: int = 8000) -> ToolResult:  # noqa: A002
    att = ctx.store.get(id)
    if not att:
        return ToolResult(False, "Příloha nenalezena")
    text = att.text or ""
    chunk = text[offset:offset + length]
    more = offset + length < len(text)
    return ToolResult(True, f"{att.name}: znaky {offset}–{offset + len(chunk)} z {len(text)}" + (" (pokračuje)" if more else ""),
                      data=chunk)


@tool("save_attachment", "Uloží přílohu do složky na PC (výchozí Stažené) a volitelně ji otevře.", category="přílohy")
async def save_attachment(ctx, id: str, folder: str = "Downloads", open: bool = False) -> ToolResult:  # noqa: A002
    att = ctx.store.get(id)
    if not att:
        return ToolResult(False, "Příloha nenalezena")
    dest_dir = resolve(folder) if folder else Path.home() / "Downloads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / att.name
    i = 1
    while dest.exists():
        dest = dest_dir / f"{Path(att.name).stem} ({i}){Path(att.name).suffix}"
        i += 1
    shutil.copy2(att.path, dest)
    if open:
        await asyncio.to_thread(ctx.platform.open_path, str(dest))
    return ToolResult(True, f"Uloženo do {dest}", data=str(dest))
