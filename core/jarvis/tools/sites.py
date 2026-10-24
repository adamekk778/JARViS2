"""Website builder (3.1): "udělej mi web pro kavárnu" → files in the sites folder, a live preview right in the chat.

Every site lives in its own folder named <slug>-<random>; the random part makes the preview link unguessable,
so the phone can show it without the pairing token. Pages are served with a sandbox CSP, so their scripts
can never talk to JARVIS itself.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Annotated

from .. import paths
from .base import ToolResult, tool

SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}-[0-9a-f]{10}$")
TEXT_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".md", ".xml", ".webmanifest"}
MAX_FILE = 2 * 2**20
MAX_FILES = 40


def sites_dir() -> Path:
    return paths.sub("sites")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "web"


def site_path(site_id: str) -> Path | None:
    if not SITE_ID.match(site_id or ""):
        return None
    p = sites_dir() / site_id
    return p if p.is_dir() else None


def safe_rel(name: str) -> str | None:
    """A relative file path inside the site, or None (no absolute paths, no .., only text web files)."""
    name = (name or "").replace("\\", "/").strip()
    while name.startswith("./"):
        name = name[2:]
    if not name or name.startswith("/") or ":" in name or any(part in ("", ".", "..") for part in name.split("/")):
        return None
    return name if PurePosixPath(name).suffix.lower() in TEXT_EXT else None


def preview_url(site_id: str, page: str = "index.html") -> str:
    return f"/sites/{site_id}/{page}"


def list_sites() -> list[dict]:
    out = []
    for d in sites_dir().iterdir():
        if d.is_dir() and SITE_ID.match(d.name):
            title = (d / ".title").read_text("utf-8").strip() if (d / ".title").exists() else d.name.rsplit("-", 1)[0]
            out.append({"id": d.name, "title": title, "updated": d.stat().st_mtime, "url": preview_url(d.name)})
    return sorted(out, key=lambda s: -s["updated"])


@tool("make_website",
      "Vytvoří nebo upraví webovou stránku a hned ukáže její náhled v chatu. Piš kompletní, moderní a hezký web: "
      "html = celý dokument index.html (<!doctype html>, <meta viewport>, responzivní, bez externích knihoven, pokud "
      "nejsou nutné). Další soubory (style.css, script.js, další stránky) dej do files {název: obsah}. "
      "Úprava existujícího webu: pošli jeho site (id z minulého výsledku) a znovu celý změněný soubor.",
      category="kód", perm="files_write")
async def make_website(ctx, title: Annotated[str, "Název webu, např. Kavárna U Lípy"],
                       html: Annotated[str, "Celý obsah index.html"] = "",
                       files: Annotated[dict, "Další soubory {\"style.css\": \"…\"}"] | None = None,
                       site: Annotated[str, "id existujícího webu pro úpravu (prázdné = nový web)"] = "") -> ToolResult:
    todo: dict[str, str] = {}
    if isinstance(files, str):   # some models send the object as a JSON string
        try:
            files = json.loads(files) if files.strip() else {}
        except ValueError:
            return ToolResult(False, "files musí být objekt {název souboru: obsah}.")
    if html.strip():
        todo["index.html"] = html
    for name, body in (files or {}).items():
        rel = safe_rel(str(name))
        if rel is None:
            return ToolResult(False, f"Soubor {name!r} nejde uložit (jen textové soubory webu uvnitř složky webu).")
        todo[rel] = body if isinstance(body, str) else str(body)
    if not todo:
        return ToolResult(False, "Chybí obsah webu (html nebo files).")
    if len(todo) > MAX_FILES or any(len(b.encode("utf-8")) > MAX_FILE for b in todo.values()):
        return ToolResult(False, "Web je moc velký (max 40 souborů po 2 MB).")
    if site:
        root = site_path(site)
        if root is None:
            return ToolResult(False, f"Web {site} neexistuje. Pro nový web nech site prázdné.")
    else:
        if "index.html" not in todo:
            return ToolResult(False, "Nový web potřebuje index.html (parametr html).")
        root = sites_dir() / f"{slugify(title)}-{secrets.token_hex(5)}"
        root.mkdir(parents=True)
    for rel, body in todo.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, "utf-8")
    (root / ".title").write_text((title or root.name)[:120], "utf-8")
    page = "index.html" if (root / "index.html").exists() else sorted(todo)[0]
    url = preview_url(root.name, page)
    verb = "Upravil jsem" if site else "Hotovo, vytvořil jsem"
    res = ToolResult(True, f"{verb} web „{title}“ ({', '.join(sorted(todo))}). Náhled je v chatu. id={root.name}",
                     data={"site": root.name, "url": url, "folder": str(root), "files": sorted(todo),
                           "updated": int(time.time())})
    res.preview = url
    return res


@tool("list_websites", "Seznam webů, které JARVIS vytvořil (id, název, odkaz na náhled).", category="kód", perm="files_read")
async def list_websites(ctx) -> ToolResult:
    items = list_sites()[:30]
    if not items:
        return ToolResult(True, "Zatím žádné weby.", data=[])
    return ToolResult(True, "\n".join(f"{s['id']}: {s['title']}" for s in items), data=items)


@tool("read_website", "Přečte soubor z webu, který JARVIS vytvořil (před úpravou).", category="kód", perm="files_read")
async def read_website(ctx, site: Annotated[str, "id webu"], file: Annotated[str, "soubor, např. index.html"] = "index.html") -> ToolResult:
    root, rel = site_path(site), safe_rel(file)
    if root is None or rel is None or not (root / rel).is_file():
        names = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file() and p.name != ".title") if root else []
        return ToolResult(False, f"Soubor nenalezen. Soubory webu: {', '.join(names) or 'žádné'}")
    return ToolResult(True, (root / rel).read_text("utf-8", errors="replace")[:60000])
