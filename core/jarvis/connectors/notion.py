"""3.12 Notion: search and read pages, add text to a page – with an internal integration token (you share the pages
with the integration in Notion). Writing asks first."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import friendly, http, need, register, value

API = "https://api.notion.com/v1"


async def _test(rt: Any) -> str:
    me = await _api("GET", "/users/me")
    return f"Integrace „{me.get('name', '?')}“ funguje."


register("notion", "Notion", "notebook", [
    {"key": "token", "label": "Internal integration secret", "secret": True, "hint": "ntn_… nebo secret_…"},
], [
    "Otevři notion.so/profile/integrations → New integration (typ Internal).",
    "Zkopíruj „Internal Integration Secret“ sem a ulož.",
    "V Notionu u stránek, které má JARVIS vidět: ⋯ → Connections → přidej svou integraci.",
], url="https://www.notion.so/profile/integrations",
    what="Hledání a čtení stránek a databází, přidání textu na stránku (s potvrzením).", test=_test)


async def _api(method: str, path: str, body: Any = None, transport=None) -> Any:
    need("notion")
    async with http(transport=transport) as c:
        r = await c.request(method, API + path, json=body, headers={"Authorization": f"Bearer {value('notion', 'token')}",
                                                                    "Notion-Version": "2022-06-28"})
        r.raise_for_status()
        return r.json() if r.content else {}


def _title(o: dict) -> str:
    props = o.get("properties", {}) or {}
    for p in props.values():
        if p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p.get("title", []))
    return "".join(t.get("plain_text", "") for t in o.get("title", []) or []) or "(bez názvu)"


@tool("notion_search", "Notion: najde stránky a databáze podle textu.", category="propojení", perm="network")
async def search(ctx, query: Annotated[str, "co hledat"] = "") -> ToolResult:
    try:
        r = await _api("POST", "/search", {"query": query, "page_size": 20})
        out = [{"id": o["id"], "type": o["object"], "title": _title(o), "url": o.get("url"), "edited": o.get("last_edited_time")}
               for o in r.get("results", [])]
        return ToolResult(True, f"{len(out)} výsledků.", data=out)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("notion_read", "Notion: přečte text stránky.", category="propojení", perm="network")
async def read(ctx, page_id: Annotated[str, "id stránky"]) -> ToolResult:
    try:
        r = await _api("GET", f"/blocks/{page_id}/children?page_size=100")
        lines = []
        for b in r.get("results", []):
            rich = (b.get(b.get("type"), {}) or {}).get("rich_text", [])
            t = "".join(x.get("plain_text", "") for x in rich)
            if t:
                lines.append(t)
        return ToolResult(True, f"{len(lines)} odstavců.", data={"text": "\n".join(lines)[:15000]})
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("notion_append", "Notion: přidá odstavce textu na konec stránky. Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=lambda a: [f"Stránka: {a.get('page_id', '')}", *str(a.get("text", "")).splitlines()[:20]])
async def append(ctx, page_id: Annotated[str, "id stránky"], text: Annotated[str, "text (odstavce oddělené řádky)"]) -> ToolResult:
    try:
        blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": p[:1900]}}]}}
                  for p in text.split("\n") if p.strip()][:50]
        await _api("PATCH", f"/blocks/{page_id}/children", {"children": blocks})
        return ToolResult(True, f"Přidáno {len(blocks)} odstavců.")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))
