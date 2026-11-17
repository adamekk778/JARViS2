"""3.12 monday.com: nástěnky a položky; nová položka s potvrzením. API token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://api.monday.com/v2"


async def gql(query: str, variables: dict | None = None, transport=None) -> dict:
    need("monday")
    r = await call("POST", API, json={"query": query, "variables": variables or {}}, transport=transport,
                   headers={"Authorization": value("monday", "token")})
    if r.get("errors") or r.get("error_message"):
        raise ServiceError("monday.com: " + (r.get("error_message") or "; ".join(e.get("message", "") for e in r.get("errors", [])))[:300])
    return r.get("data") or {}


async def _test(rt: Any) -> str:
    d = await gql("{ me { name } }")
    return f"Přihlášeno jako {d['me']['name']}."


register("monday", "monday.com", "squares-four", [
    {"key": "token", "label": "API token", "secret": True, "hint": "eyJ…"},
], [
    "V monday.com: avatar → Developers → My access tokens → Show → zkopíruj.",
    "Vlož token sem a ulož.",
], url="https://monday.com/", what="Nástěnky a jejich položky se sloupci; nová položka jen s potvrzením.", test=_test, group="tasks",
    probe={"method": "POST", "url": API, "json": {"query": "{ me { id } }"}, "headers": {"Authorization": "FAKE"}})


@tool("monday_boards", "monday.com: moje nástěnky.", category="propojení", perm="network")
@guarded
async def boards(ctx) -> ToolResult:
    d = await gql("{ boards(limit: 50, state: active) { id name items_count } }")
    return ToolResult(True, f"{len(d.get('boards', []))} nástěnek.", data=d.get("boards", []))


@tool("monday_items", "monday.com: položky nástěnky se sloupci.", category="propojení", perm="network")
@guarded
async def items(ctx, board_id: Annotated[str, "id nástěnky z monday_boards"]) -> ToolResult:
    d = await gql("""query($b: [ID!]) { boards(ids: $b) { name items_page(limit: 100) { items { id name group { title }
        column_values { column { title } text } } } } }""", {"b": [str(board_id)]})
    b = (d.get("boards") or [{}])[0]
    out = [{"item": i["name"], "group": (i.get("group") or {}).get("title"),
            **{c["column"]["title"]: c["text"] for c in i.get("column_values", []) if c.get("text")}} for i in (b.get("items_page") or {}).get("items", [])]
    return ToolResult(True, f"{len(out)} položek na {b.get('name', '')}.", data=out)


@tool("monday_item_create", "monday.com: přidá položku na nástěnku. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Nástěnka: {a.get('board_id', '')}", f"Položka: {a.get('name', '')}"])
@guarded
async def item_create(ctx, board_id: Annotated[str, "id nástěnky"], name: Annotated[str, "název položky"]) -> ToolResult:
    d = await gql("mutation($b: ID!, $n: String!) { create_item(board_id: $b, item_name: $n) { id } }", {"b": str(board_id), "n": name})
    return ToolResult(True, f"Položka „{name}“ přidána.", data=d.get("create_item"))
