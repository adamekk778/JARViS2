"""3.5 lists: "přidej mléko a chleba na nákupní seznam", "co mám na seznamu", "koupil jsem mléko".
Shared by the PC, the phone app and voice; stored in the local database."""
from __future__ import annotations

import time
from typing import Annotated

from .base import ToolResult, tool

LISTS_SQL = """
CREATE TABLE IF NOT EXISTS lists (id INTEGER PRIMARY KEY AUTOINCREMENT, list TEXT NOT NULL, item TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS lists_list ON lists(list);
"""
# spoken name (folded prefix) → the list: "nákupní seznam", "na nákup" → nákup; "seznam filmů" → filmy
ALIASES = {"nakup": "nákup", "na nakup": "nákup", "shopping": "nákup", "ukol": "úkoly", "todo": "úkoly", "to do": "úkoly",
           "film": "filmy", "knih": "knihy", "dar": "dárky"}


def _db(ctx):
    ctx.db.conn.executescript(LISTS_SQL)
    return ctx.db


def list_name(name: str) -> str:
    from ..stark import _fold

    n = _fold(name or "nákup").replace("seznam", "").replace("list", "").strip(" -:")
    for k, v in ALIASES.items():
        if n == k or n.startswith(k):
            return v
    return (name or "nákup").strip().lower().replace("seznam", "").strip(" -:") or "nákup"


def items_of(ctx, name: str) -> list[dict]:
    return [dict(r) for r in _db(ctx).all("SELECT id, item, ts FROM lists WHERE list=? ORDER BY id", (name,))]


def all_lists(ctx) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in _db(ctx).all("SELECT list, item FROM lists ORDER BY id"):
        out.setdefault(r["list"], []).append(r["item"])
    return out


def add_items(ctx, name: str, items: list[str]) -> list[str]:
    from ..stark import _fold

    have = {_fold(x["item"]) for x in items_of(ctx, name)}
    added = []
    for it in items:
        it = " ".join(str(it).split())[:200]
        if it and _fold(it) not in have:
            _db(ctx).exec("INSERT INTO lists (list, item, ts) VALUES (?,?,?)", (name, it, time.time()))
            have.add(_fold(it))
            added.append(it)
    return added


def remove_items(ctx, name: str, items: list[str]) -> list[str]:
    from ..stark import _fold

    gone = []
    rows = items_of(ctx, name)
    for it in items:
        want = _fold(it)
        hit = next((r for r in rows if _fold(r["item"]) == want), None) or next((r for r in rows if want and want in _fold(r["item"])), None)
        if hit:
            _db(ctx).exec("DELETE FROM lists WHERE id=?", (hit["id"],))
            rows.remove(hit)
            gone.append(hit["item"])
    return gone


def _changed(ctx) -> None:
    ctx.bus.publish("lists", lists=all_lists(ctx))


@tool("list_add", "Přidá položky na seznam (výchozí je nákupní seznam). Na „přidej mléko na nákup“, „napiš si, že mám "
      "koupit dárek pro mámu“, „dej na seznam filmů Interstellar“.", category="info", perm="apps")
async def list_add(ctx, items: Annotated[list[str], "položky, každá zvlášť"], list: Annotated[str, "název seznamu"] = "nákup") -> ToolResult:
    name = list_name(list)
    added = add_items(ctx, name, items)
    _changed(ctx)
    if not added:
        return ToolResult(True, f"To už na seznamu {name} je.")
    return ToolResult(True, f"Přidáno na seznam {name}: {', '.join(added)}.", data={"list": name, "items": [x["item"] for x in items_of(ctx, name)]})


@tool("list_show", "Ukáže seznam (nákup, úkoly, filmy…); prázdný název = přehled všech seznamů.", category="info", perm="apps")
async def list_show(ctx, list: str = "nákup") -> ToolResult:
    if not list.strip() or list.strip().lower() in ("vše", "vse", "všechny", "vsechny", "all"):
        lists = all_lists(ctx)
        if not lists:
            return ToolResult(True, "Všechny seznamy jsou prázdné.")
        return ToolResult(True, "\n".join(f"{k} ({len(v)}): {', '.join(v[:8])}{'…' if len(v) > 8 else ''}" for k, v in lists.items()), data=lists)
    name = list_name(list)
    items = [x["item"] for x in items_of(ctx, name)]
    if not items:
        return ToolResult(True, f"Seznam {name} je prázdný.")
    return ToolResult(True, f"Na seznamu {name} ({len(items)}): " + ", ".join(items) + ".", data={"list": name, "items": items})


@tool("list_done", "Odškrtne (smaže) položky ze seznamu: „koupil jsem mléko“, „smaž ze seznamu chleba“.", category="info", perm="apps")
async def list_done(ctx, items: list[str], list: str = "nákup") -> ToolResult:
    name = list_name(list)
    gone = remove_items(ctx, name, items)
    _changed(ctx)
    left = len(items_of(ctx, name))
    if not gone:
        return ToolResult(False, f"Na seznamu {name} jsem to nenašel.")
    return ToolResult(True, f"Odškrtnuto: {', '.join(gone)}. Na seznamu {name} zbývá {left}.")


@tool("list_clear", "Vymaže celý seznam (např. po nákupu).", category="info", perm="apps")
async def list_clear(ctx, list: str = "nákup") -> ToolResult:
    name = list_name(list)
    n = _db(ctx).exec("DELETE FROM lists WHERE list=?", (name,)).rowcount
    _changed(ctx)
    return ToolResult(True, f"Seznam {name} vymazán ({n} položek).")


@tool("list_to_phone", "Pošle seznam (třeba nákupní) do telefonu jako notifikaci, ať ho má uživatel v obchodě.",
      category="telefon", perm="apps")
async def list_to_phone(ctx, list: str = "nákup") -> ToolResult:
    name = list_name(list)
    items = [x["item"] for x in items_of(ctx, name)]
    if not items:
        return ToolResult(False, f"Seznam {name} je prázdný.")
    n = ctx.notify(f"Seznam: {name}", "\n".join(f"• {x}" for x in items), speak=False, target="mobile")
    return ToolResult(True, "Seznam je v telefonu." if n else "Telefon není připojený – seznam je v aplikaci JARVIS v telefonu v sekci Seznamy.")
