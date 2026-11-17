"""3.12 Trello: nástěnky, sloupce a karty; nová karta s potvrzením. API key + token (Power-Up admin)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://api.trello.com/1"


async def _api(method: str, path: str, transport=None, **params) -> Any:
    need("trello")
    auth = f'OAuth oauth_consumer_key="{value("trello", "key")}", oauth_token="{value("trello", "token")}"'
    return await call(method, API + path, params=params or None, transport=transport, headers={"Authorization": auth})


async def _test(rt: Any) -> str:
    me = await _api("GET", "/members/me", fields="fullName,username")
    return f"Přihlášeno jako {me.get('fullName') or me.get('username')}."


register("trello", "Trello", "kanban", [
    {"key": "key", "label": "API key", "secret": False, "hint": "32 znaků"},
    {"key": "token", "label": "Token", "secret": True, "hint": "ATTA…"},
], [
    "Otevři trello.com/power-ups/admin → New → vytvoř Power-Up „JARVIS“ (workspace libovolný).",
    "V něm záložka API key → Generate a new API key → zkopíruj API key sem.",
    "Na téže stránce klikni na odkaz „Token“ (vpravo od klíče) → Allow → zkopíruj token sem a ulož.",
], url="https://trello.com/power-ups/admin", what="Nástěnky, sloupce a karty (termíny); nová karta jen s potvrzením.", test=_test,
    group="tasks", probe={"method": "GET", "url": API + "/members/me", "headers": {"Authorization": 'OAuth oauth_consumer_key="FAKE", oauth_token="FAKE"'}})


async def _board(name: str) -> dict:
    boards = await _api("GET", "/members/me/boards", fields="name,url", filter="open")
    b = next((x for x in boards if name.lower() == x["name"].lower()), None) or next((x for x in boards if name.lower() in x["name"].lower()), None)
    if not b:
        raise ServiceError(f"Nástěnku „{name}“ nevidím. Mám: {', '.join(x['name'] for x in boards[:15])}.")
    return b


@tool("trello_boards", "Trello: moje nástěnky.", category="propojení", perm="network")
@guarded
async def boards(ctx) -> ToolResult:
    bs = await _api("GET", "/members/me/boards", fields="name,url,dateLastActivity", filter="open")
    return ToolResult(True, f"{len(bs)} nástěnek.", data=[{"name": b["name"], "url": b.get("url"), "active": b.get("dateLastActivity")} for b in bs])


@tool("trello_cards", "Trello: karty na nástěnce po sloupcích (s termíny).", category="propojení", perm="network")
@guarded
async def cards(ctx, board: Annotated[str, "název nástěnky"]) -> ToolResult:
    b = await _board(board)
    lists = {x["id"]: x["name"] for x in await _api("GET", f"/boards/{b['id']}/lists", fields="name", filter="open")}
    cs = await _api("GET", f"/boards/{b['id']}/cards", fields="name,due,dueComplete,idList,url,dateLastActivity")
    out = [{"card": c["name"], "list": lists.get(c["idList"]), "due": c.get("due"), "done": c.get("dueComplete"), "url": c.get("url")} for c in cs]
    return ToolResult(True, f"{len(out)} karet na {b['name']}.", data={"lists": list(lists.values()), "cards": out})


@tool("trello_card_create", "Trello: přidá kartu do sloupce. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Nástěnka: {a.get('board', '')} → {a.get('list', '')}", f"Karta: {a.get('name', '')}", f"Termín: {a.get('due', '') or '–'}"])
@guarded
async def card_create(ctx, board: Annotated[str, "nástěnka"], list: Annotated[str, "sloupec (např. To Do)"], name: Annotated[str, "název karty"],  # noqa: A002
                      description: Annotated[str, "popis"] = "", due: Annotated[str, "termín ISO (nepovinné)"] = "") -> ToolResult:
    b = await _board(board)
    lists = await _api("GET", f"/boards/{b['id']}/lists", fields="name", filter="open")
    lst = next((x for x in lists if list.lower() in x["name"].lower()), None)
    if not lst:
        return ToolResult(False, f"Sloupec „{list}“ na {b['name']} není. Jsou tam: {', '.join(x['name'] for x in lists)}.")
    params = {"idList": lst["id"], "name": name, "desc": description}
    if due:
        params["due"] = due
    c = await _api("POST", "/cards", **params)
    return ToolResult(True, f"Karta „{name}“ je v {lst['name']}.", data={"url": c.get("url")})
