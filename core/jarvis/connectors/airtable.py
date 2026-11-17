"""3.12 Airtable: báze, tabulky a záznamy; nový záznam s potvrzením. Personal access token."""
from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://api.airtable.com/v0"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("airtable")
    return await call(method, API + path, json=body, params=params or None, transport=transport,
                      headers={"Authorization": f"Bearer {value('airtable', 'token')}"})


async def _test(rt: Any) -> str:
    r = await _api("GET", "/meta/bases")
    return f"Propojeno – {len(r.get('bases', []))} bází."


register("airtable", "Airtable", "table", [
    {"key": "token", "label": "Personal access token", "secret": True, "hint": "pat…"},
], [
    "Otevři airtable.com/create/tokens → Create new token.",
    "Scopes: data.records:read, data.records:write, schema.bases:read; Access: báze, které má JARVIS vidět.",
    "Zkopíruj token sem a ulož.",
], url="https://airtable.com/create/tokens", what="Báze, tabulky a záznamy; nový záznam jen s potvrzením.", test=_test, group="tasks",
    probe={"method": "GET", "url": API + "/meta/bases", "headers": {"Authorization": "Bearer FAKE"}})


async def _base(name: str) -> dict:
    bases = (await _api("GET", "/meta/bases")).get("bases", [])
    b = next((x for x in bases if name.lower() in (x["id"].lower(), x["name"].lower())), None) or \
        next((x for x in bases if name.lower() in x["name"].lower()), None)
    if not b:
        raise ServiceError(f"Bázi „{name}“ nevidím. Mám: {', '.join(x['name'] for x in bases[:15])}.")
    return b


@tool("airtable_bases", "Airtable: báze a jejich tabulky (se sloupci).", category="propojení", perm="network")
@guarded
async def bases(ctx, base: Annotated[str, "název báze (prázdné = jen seznam bází)"] = "") -> ToolResult:
    if not base:
        bs = (await _api("GET", "/meta/bases")).get("bases", [])
        return ToolResult(True, f"{len(bs)} bází.", data=[{"id": b["id"], "name": b["name"]} for b in bs])
    b = await _base(base)
    ts = (await _api("GET", f"/meta/bases/{b['id']}/tables")).get("tables", [])
    return ToolResult(True, f"{len(ts)} tabulek v {b['name']}.", data=[{"table": t["name"], "fields": [f["name"] for f in t.get("fields", [])]} for t in ts])


@tool("airtable_records", "Airtable: záznamy z tabulky (volitelně vzorec filtru).", category="propojení", perm="network")
@guarded
async def records(ctx, base: Annotated[str, "báze"], table: Annotated[str, "tabulka"],
                  formula: Annotated[str, "filterByFormula, např. {Stav}='Nové' (nepovinné)"] = "", limit: Annotated[int, "kolik"] = 50) -> ToolResult:
    b = await _base(base)
    params: dict[str, Any] = {"maxRecords": max(1, min(int(limit or 50), 200))}
    if formula:
        params["filterByFormula"] = formula
    r = await _api("GET", f"/{b['id']}/{quote(table, safe='')}", **params)
    out = [{"id": x["id"], **(x.get("fields") or {})} for x in r.get("records", [])]
    return ToolResult(True, f"{len(out)} záznamů.", data=out)


@tool("airtable_create", "Airtable: přidá záznam do tabulky. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"{a.get('base', '')} → {a.get('table', '')}", *[f"{k}: {v}" for k, v in (a.get("fields") or {}).items()][:20]])
@guarded
async def create(ctx, base: Annotated[str, "báze"], table: Annotated[str, "tabulka"], fields: Annotated[dict, "hodnoty {\"Sloupec\": hodnota}"]) -> ToolResult:
    b = await _base(base)
    r = await _api("POST", f"/{b['id']}/{quote(table, safe='')}", {"records": [{"fields": fields}], "typecast": True})
    return ToolResult(True, "Záznam přidán.", data={"id": (r.get("records") or [{}])[0].get("id")})
