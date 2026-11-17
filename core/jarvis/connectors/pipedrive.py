"""3.12 Pipedrive CRM: obchody, lidé a aktivity (co dnes udělat). A new deal asks first. Personal API token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.pipedrive.com"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("pipedrive")
    r = await call(method, API + path, json=body, params=params or None, transport=transport, headers={"x-api-token": value("pipedrive", "token")})
    return r.get("data") if isinstance(r, dict) and "data" in r else r


async def _test(rt: Any) -> str:
    me = await _api("GET", "/v1/users/me")
    return f"Přihlášeno jako {me.get('name', '?')} ({me.get('company_name', '')})."


register("pipedrive", "Pipedrive (CRM)", "funnel", [
    {"key": "token", "label": "Personal API token", "secret": True, "hint": "40 znaků"},
], [
    "V Pipedrive klikni na svůj profil → Personal preferences → API.",
    "Zkopíruj „Your personal API token“ sem a ulož.",
], url="https://app.pipedrive.com/settings/api", what="Obchody, lidé, firmy a naplánované aktivity; nový obchod jen s potvrzením.",
    test=_test, group="sales", probe={"method": "GET", "url": API + "/v1/users/me", "headers": {"x-api-token": "FAKE"}})


@tool("pipedrive_deals", "Pipedrive: otevřené obchody (hodnota, fáze, očekávané uzavření).", category="propojení", perm="network")
@guarded
async def deals(ctx, status: Annotated[str, "open / won / lost"] = "open") -> ToolResult:
    d = await _api("GET", "/api/v2/deals", status=status or "open", limit=100, sort_by="update_time", sort_direction="desc")
    out = [{"id": x.get("id"), "title": x.get("title"), "value": x.get("value"), "currency": x.get("currency"), "stage_id": x.get("stage_id"),
            "close": x.get("expected_close_date"), "updated": x.get("update_time")} for x in (d or [])]
    return ToolResult(True, f"{len(out)} obchodů ({status}).", data=out)


@tool("pipedrive_people", "Pipedrive: najde lidi (jméno, e-mail, telefon).", category="propojení", perm="network")
@guarded
async def people(ctx, query: Annotated[str, "jméno nebo e-mail (aspoň 2 znaky)"]) -> ToolResult:
    d = await _api("GET", "/api/v2/persons/search", term=query, limit=25)
    items = (d or {}).get("items", []) if isinstance(d, dict) else []
    out = [{"id": (i.get("item") or {}).get("id"), "name": (i.get("item") or {}).get("name"),
            "emails": (i.get("item") or {}).get("emails"), "phones": (i.get("item") or {}).get("phones"),
            "org": ((i.get("item") or {}).get("organization") or {}).get("name")} for i in items]
    return ToolResult(True, f"{len(out)} lidí.", data=out)


@tool("pipedrive_activities", "Pipedrive: nesplněné aktivity (hovory, schůzky, úkoly) – co je dnes a po termínu.", category="propojení",
      perm="network")
@guarded
async def activities(ctx) -> ToolResult:
    d = await _api("GET", "/api/v2/activities", done="false", limit=100, sort_by="due_date", sort_direction="asc")
    out = [{"subject": a.get("subject"), "type": a.get("type"), "due": a.get("due_date"), "time": a.get("due_time"),
            "deal_id": a.get("deal_id"), "person_id": a.get("person_id")} for a in (d or [])]
    return ToolResult(True, f"{len(out)} nesplněných aktivit.", data=out)


@tool("pipedrive_deal_create", "Pipedrive: založí nový obchod. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Obchod: {a.get('title', '')}", f"Hodnota: {a.get('amount', 0)} {a.get('currency', 'CZK')}"])
@guarded
async def deal_create(ctx, title: Annotated[str, "název obchodu"], amount: Annotated[float, "hodnota"] = 0,
                      currency: Annotated[str, "měna"] = "CZK") -> ToolResult:
    d = await _api("POST", "/api/v2/deals", {"title": title, "value": amount, "currency": currency.upper()})
    return ToolResult(True, f"Obchod „{title}“ je v Pipedrive.", data={"id": (d or {}).get("id")})
