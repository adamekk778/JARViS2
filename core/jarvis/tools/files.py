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
    from .dev import auto_checkpoint

    await asyncio.to_thread(auto_checkpoint, ctx, resolve(path))
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return ToolResult(True, f"Uloženo {p}")


def _size(p: Path) -> str:
    try:
        n = p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return "?"
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def _path_line(a: dict, key: str = "path") -> list[str]:
    p = resolve(a.get(key, ""))
    return [f"{p} ({_size(p)})"]


def _move_line(a: dict) -> list[str]:
    return [f"{resolve(a.get('source', ''))} → {resolve(a.get('destination', ''))}"]


@tool("move_files", "Přesune víc souborů najednou (např. roztřídění do složek). Uživatel nejdřív uvidí náhled všech "
      "přesunů a schválí je. moves = seznam {src, dst}.", danger=True, category="soubory", perm="files_write",
      details=lambda a: [f"{resolve(m.get('src', ''))} → {resolve(m.get('dst', ''))}" for m in a.get("moves") or []])
async def move_files(ctx, moves: Annotated[list[dict], "seznam {src, dst} – cesty k souborům"],
                     create_dirs: bool = True) -> ToolResult:
    def run():
        moved, failed = 0, []
        for m in moves:
            src, dst = resolve(str(m.get("src", ""))), resolve(str(m.get("dst", "")))
            try:
                if not src.exists():
                    raise FileNotFoundError("zdroj neexistuje")
                if create_dirs:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                if not dst.exists():
                    raise OSError("cíl po přesunu neexistuje")
                moved += 1
            except Exception as e:
                failed.append(f"{src}: {e}")
        return moved, failed

    from .dev import auto_checkpoint

    for m in moves[:1]:
        await asyncio.to_thread(auto_checkpoint, ctx, resolve(str(m.get("src", ""))))
    moved, failed = await asyncio.to_thread(run)
    summary = f"Přesunuto {moved} z {len(moves)}" + (f", selhalo {len(failed)}" if failed else "")
    return ToolResult(not failed, summary, data={"moved": moved, "failed": failed})


@tool("move_file", "Přesune nebo přejmenuje soubor/složku.", danger=True, category="soubory", details=_move_line)
async def move_file(ctx, source: str, destination: str) -> ToolResult:
    dst = shutil.move(str(resolve(source)), str(resolve(destination)))
    return ToolResult(True, f"Přesunuto do {dst}")


@tool("copy_file", "Zkopíruje soubor/složku.", category="soubory",
      details=lambda a: [f"{resolve(a.get('source', ''))} → {resolve(a.get('destination', ''))}"])
async def copy_file(ctx, source: str, destination: str) -> ToolResult:
    s, d = resolve(source), resolve(destination)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return ToolResult(True, f"Zkopírováno do {d}")


@tool("delete_file", "Smaže soubor nebo složku (do koše, pokud to jde).", danger=True, category="soubory",
      details=_path_line)
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
