from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool


def user_roots(ctx) -> list[Path]:
    home = Path.home()
    roots = [home / n for n in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive")]
    roots += [Path(p) for p in ctx.cfg.tools.allowed_folders]
    return [r for r in roots if r.exists()]


def resolve(path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    aliases = {"plocha": "Desktop", "dokumenty": "Documents", "stažené": "Downloads", "obrázky": "Pictures",
               "hudba": "Music", "videa": "Videos"}
    parts = p.parts
    if parts and parts[0].lower() in aliases:
        p = Path.home() / aliases[parts[0].lower()] / Path(*parts[1:])
    return p


@tool("find_file", "Najde soubory podle části názvu ve složkách uživatele (Plocha, Dokumenty, Stažené…).", category="soubory")
async def find_file(ctx, query: Annotated[str, "část názvu, může obsahovat * "], folder: str = "", limit: int = 20) -> ToolResult:
    def run():
        roots = [resolve(folder)] if folder else user_roots(ctx)
        pat = query if "*" in query else f"*{query}*"
        hits = []
        for r in roots:
            try:
                for p in r.rglob(pat):
                    hits.append({"path": str(p), "size": p.stat().st_size if p.is_file() else None,
                                 "dir": p.is_dir(), "modified": p.stat().st_mtime})
                    if len(hits) >= 500:
                        break
            except (OSError, PermissionError):
                continue
        hits.sort(key=lambda h: h["modified"], reverse=True)
        return hits[:limit]

    hits = await asyncio.to_thread(run)
    return ToolResult(bool(hits), f"Nalezeno {len(hits)}" if hits else "Nic nenalezeno", data=hits)


@tool("open_file", "Otevře soubor nebo složku v PC výchozí aplikací.", category="soubory")
async def open_file(ctx, path: str) -> ToolResult:
    p = resolve(path)
    if not p.exists():
        return ToolResult(False, f"Neexistuje: {p}")
    await asyncio.to_thread(ctx.platform.open_path, str(p))
    return ToolResult(True, f"Otevírám {p.name}")


@tool("list_folder", "Vypíše obsah složky.", category="soubory")
async def list_folder(ctx, path: str) -> ToolResult:
    p = resolve(path)
    items = [{"name": c.name, "dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else None}
             for c in sorted(p.iterdir())[:300]]
    return ToolResult(True, f"{len(items)} položek v {p}", data=items)


@tool("read_text_file", "Přečte textový soubor z PC (txt, kód, csv, md…).", category="soubory")
async def read_text_file(ctx, path: str, max_chars: int = 15000) -> ToolResult:
    p = resolve(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return ToolResult(True, f"{p.name}: {len(text)} znaků", data=text[:max_chars])


@tool("write_text_file", "Vytvoří nebo přepíše textový soubor na PC.", danger_if=lambda a: Path(resolve(a.get("path", ""))).exists(),
      category="soubory")
async def write_text_file(ctx, path: str, content: str) -> ToolResult:
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return ToolResult(True, f"Uloženo {p}")


@tool("move_file", "Přesune nebo přejmenuje soubor/složku.", danger=True, category="soubory")
async def move_file(ctx, source: str, destination: str) -> ToolResult:
    dst = shutil.move(str(resolve(source)), str(resolve(destination)))
    return ToolResult(True, f"Přesunuto do {dst}")


@tool("copy_file", "Zkopíruje soubor/složku.", category="soubory")
async def copy_file(ctx, source: str, destination: str) -> ToolResult:
    s, d = resolve(source), resolve(destination)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return ToolResult(True, f"Zkopírováno do {d}")


@tool("delete_file", "Smaže soubor nebo složku (do koše, pokud to jde).", danger=True, category="soubory")
async def delete_file(ctx, path: str) -> ToolResult:
    p = resolve(path)
    try:
        from send2trash import send2trash

        send2trash(str(p))
        return ToolResult(True, f"{p.name} přesunuto do koše")
    except ImportError:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return ToolResult(True, f"{p.name} smazáno")
