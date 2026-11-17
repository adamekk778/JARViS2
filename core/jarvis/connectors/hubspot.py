"""3.12 HubSpot CRM: kontakty, firmy a obchody (deals). A new contact or a note asks first. Private app token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.hubapi.com"


async def _api(method: str, path: str, body: Any = None, transport=None) -> Any:
    need("hubspot")
    return await call(method, API + path, json=body, transport=transport, headers={"Authorization": f"Bearer {value('hubspot', 'token')}"})


async def _test(rt: Any) -> str:
    r = await _api("POST", "/crm/v3/objects/contacts/search", {"limit": 1})
    return f"Propojeno – {r.get('total', 0)} kontaktů v CRM."


register("hubspot", "HubSpot (CRM)", "address-book", [
    {"key": "token", "label": "Private app access token", "secret": True, "hint": "pat-eu1-…"},
], [
    "V HubSpotu: Nastavení (ozubené kolo) → Integrace → Private Apps (nebo Development → Legacy apps) → Create a private app.",
    "Scopes: crm.objects.contacts.read/write, crm.objects.companies.read, crm.objects.deals.read.",
    "Create app → zkopíruj Access token sem a ulož.",
], url="https://app.hubspot.com/", what="Kontakty, firmy a obchody v CRM; nový kontakt nebo poznámka jen s potvrzením.", test=_test,
    group="sales", probe={"method": "POST", "url": API + "/crm/v3/objects/contacts/search", "json": {"limit": 1},
                          "headers": {"Authorization": "Bearer FAKE"}})


async def _search(obj: str, query: str, props: list[str], limit: int = 25) -> list[dict]:
    body: dict[str, Any] = {"limit": limit, "properties": props, "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}]}
    if query.strip():
        body["query"] = query.strip()
    r = await _api("POST", f"/crm/v3/objects/{obj}/search", body)
    return [{"id": x["id"], **{k: v for k, v in (x.get("properties") or {}).items() if v not in (None, "") and k not in ("hs_object_id",)}}
            for x in r.get("results", [])]


@tool("hubspot_contacts", "HubSpot: najde kontakty (jméno, e-mail, firma).", category="propojení", perm="network")
@guarded
async def contacts(ctx, query: Annotated[str, "jméno / e-mail / firma (prázdné = poslední)"] = "") -> ToolResult:
    out = await _search("contacts", query, ["firstname", "lastname", "email", "company", "phone", "lifecyclestage", "createdate"])
    return ToolResult(True, f"{len(out)} kontaktů.", data=out)


@tool("hubspot_deals", "HubSpot: obchody (deals) – fáze, částka, termín uzavření.", category="propojení", perm="network")
@guarded
async def deals(ctx, query: Annotated[str, "název (prázdné = poslední)"] = "") -> ToolResult:
    out = await _search("deals", query, ["dealname", "amount", "dealstage", "closedate", "pipeline", "createdate"])
    return ToolResult(True, f"{len(out)} obchodů.", data=out)


@tool("hubspot_companies", "HubSpot: firmy v CRM.", category="propojení", perm="network")
@guarded
async def companies(ctx, query: Annotated[str, "název nebo doména"] = "") -> ToolResult:
    out = await _search("companies", query, ["name", "domain", "city", "industry", "createdate"])
    return ToolResult(True, f"{len(out)} firem.", data=out)


@tool("hubspot_contact_create", "HubSpot: přidá nový kontakt. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"{a.get('firstname', '')} {a.get('lastname', '')}", f"E-mail: {a.get('email', '')}", f"Firma: {a.get('company', '')}"])
@guarded
async def contact_create(ctx, email: Annotated[str, "e-mail"], firstname: Annotated[str, "jméno"] = "", lastname: Annotated[str, "příjmení"] = "",
                         company: Annotated[str, "firma"] = "", phone: Annotated[str, "telefon"] = "") -> ToolResult:
    props = {k: v for k, v in {"email": email, "firstname": firstname, "lastname": lastname, "company": company, "phone": phone}.items() if v}
    r = await _api("POST", "/crm/v3/objects/contacts", {"properties": props})
    return ToolResult(True, f"Kontakt {email} je v HubSpotu.", data={"id": r.get("id")})


@tool("hubspot_note", "HubSpot: zapíše poznámku ke kontaktu (např. shrnutí hovoru). Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=lambda a: [f"Kontakt: {a.get('contact_id', '')}", *str(a.get("text", "")).splitlines()[:15]])
@guarded
async def note(ctx, contact_id: Annotated[str, "id kontaktu z hubspot_contacts"], text: Annotated[str, "text poznámky"]) -> ToolResult:
    import time

    await _api("POST", "/crm/v3/objects/notes", {"properties": {"hs_note_body": text, "hs_timestamp": int(time.time() * 1000)},
                                                 "associations": [{"to": {"id": contact_id}, "types": [
                                                     {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}]})
    return ToolResult(True, "Poznámka je u kontaktu.")
