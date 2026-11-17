"""3.12 Fakturoid: vydané faktury (co je nezaplacené a po splatnosti), kontakty a nová faktura (s potvrzením).
API v3: Client ID + Client secret from Nastavení → Uživatelský účet → API v3 (client credentials)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, register, value
from .oauth import ClientCredentials

BASE = "https://app.fakturoid.cz/api/v3"
_SLUG: dict[str, str] = {}


def _ua() -> dict:
    # Fakturoid asks every app to name itself and a contact e-mail in User-Agent – the account owner's own e-mail
    return {"User-Agent": f"JARVIS ({value('fakturoid', 'email') or 'bez e-mailu'})"}


AUTH = ClientCredentials("fakturoid", BASE + "/oauth/token", basic=True, json_body=True, headers=_ua, name="Fakturoid")


async def _api(method: str, path: str, transport=None, **kw) -> Any:
    tok = await AUTH.token(transport)
    return await call(method, BASE + path, transport=transport, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                                                                        **_ua()}, **kw)


async def slug(transport=None) -> str:
    s = value("fakturoid", "slug").strip()
    if s:
        return s.split("/")[-1] if "/" in s else s
    if not _SLUG.get("v"):
        u = await _api("GET", "/user.json", transport)
        acc = u.get("default_account") or ((u.get("accounts") or [{}])[0]).get("slug", "")
        _SLUG["v"] = acc if isinstance(acc, str) else (acc or {}).get("slug", "")
    return _SLUG["v"]


async def _test(rt: Any) -> str:
    AUTH.forget()
    _SLUG.clear()
    s = await slug()
    acc = await _api("GET", f"/accounts/{s}/account.json")
    return f"Propojeno – účet {acc.get('name') or s}."


register("fakturoid", "Fakturoid (faktury)", "receipt", [
    {"key": "client_id", "label": "Client ID", "secret": False, "hint": "z Nastavení → Uživatelský účet"},
    {"key": "client_secret", "label": "Client secret", "secret": True, "hint": ""},
    {"key": "email", "label": "Tvůj e-mail ve Fakturoidu", "secret": False, "hint": "Fakturoid ho chce u každého dotazu"},
    {"key": "slug", "label": "Účet (nepovinné)", "secret": False, "hint": "např. mojefirma – jinak výchozí účet", "optional": True},
], [
    "Ve Fakturoidu otevři Nastavení → Uživatelský účet → sekce API v3 (Client credentials).",
    "Zkopíruj Client ID a Client secret sem, doplň svůj přihlašovací e-mail a ulož.",
    "Máš víc firem? Do „Účet“ napiš tu z adresy app.fakturoid.cz/<účet>.",
], url="https://app.fakturoid.cz/",
    what="Vydané faktury (nezaplacené, po splatnosti), kontakty; nová faktura jen s potvrzením.", test=_test, group="money",
    probe={"method": "POST", "url": BASE + "/oauth/token", "auth": ["FAKE", "FAKE"], "json": {"grant_type": "client_credentials"},
           "headers": {"Accept": "application/json", "User-Agent": "JARVIS (netcheck)"}})


def _inv(i: dict) -> dict:
    return {"id": i.get("id"), "number": i.get("number"), "client": i.get("client_name"), "total": i.get("total"),
            "currency": i.get("currency"), "status": i.get("status"), "issued": i.get("issued_on"), "due": i.get("due_on"),
            "paid": i.get("paid_on"), "url": i.get("html_url")}


@tool("fakturoid_invoices", "Fakturoid: vydané faktury – nezaplacené, po splatnosti nebo hledání podle textu.", category="propojení",
      perm="network")
@guarded
async def invoices(ctx, status: Annotated[str, "open (nezaplacené) / overdue (po splatnosti) / paid / sent / vše = prázdné"] = "open",
                   query: Annotated[str, "hledat (číslo, odběratel) – nepovinné"] = "") -> ToolResult:
    s = await slug()
    if query.strip():
        r = await _api("GET", f"/accounts/{s}/invoices/search.json", params={"query": query.strip()})
    else:
        r = await _api("GET", f"/accounts/{s}/invoices.json", params={"status": status} if status else None)
    items = [_inv(i) for i in (r if isinstance(r, list) else r.get("data", []) or [])]
    unpaid = {}
    for i in items:
        if i["status"] in ("open", "sent", "overdue"):
            unpaid[i["currency"]] = round(unpaid.get(i["currency"], 0) + float(i["total"] or 0), 2)
    return ToolResult(True, f"{len(items)} faktur" + (f", nezaplaceno {unpaid}" if unpaid else "") + ".", data=items)


@tool("fakturoid_contacts", "Fakturoid: kontakty (odběratelé) – hledání podle názvu nebo IČO.", category="propojení", perm="network")
@guarded
async def contacts(ctx, query: Annotated[str, "název nebo IČO (prázdné = všechny)"] = "") -> ToolResult:
    s = await slug()
    r = await _api("GET", f"/accounts/{s}/subjects/search.json" if query.strip() else f"/accounts/{s}/subjects.json",
                   params={"query": query.strip()} if query.strip() else None)
    out = [{"id": c.get("id"), "name": c.get("name"), "ico": c.get("registration_no"), "email": c.get("email"),
            "city": c.get("city")} for c in (r if isinstance(r, list) else [])]
    return ToolResult(True, f"{len(out)} kontaktů.", data=out)


@tool("fakturoid_invoice_create", "Fakturoid: vystaví novou fakturu odběrateli (položky: název, množství, cena). Zeptá se uživatele.",
      danger=True, category="propojení", perm="network",
      details=lambda a: [f"Odběratel: {a.get('client', '')}", *[f"• {x.get('name', '')}: {x.get('quantity', 1)} × {x.get('unit_price', '')}"
                                                                for x in (a.get('lines') or []) if isinstance(x, dict)],
                         f"Splatnost: {a.get('due_days', 14)} dní"])
@guarded
async def invoice_create(ctx, client: Annotated[str, "odběratel – název nebo IČO (musí být v kontaktech)"],
                         lines: Annotated[list[dict], "položky: [{\"name\": \"Web\", \"quantity\": 1, \"unit_price\": 15000, \"vat_rate\": 21}]"],
                         due_days: Annotated[int, "splatnost ve dnech"] = 14, note: Annotated[str, "poznámka na faktuře"] = "") -> ToolResult:
    s = await slug()
    found = await _api("GET", f"/accounts/{s}/subjects/search.json", params={"query": client})
    found = found if isinstance(found, list) else []
    subj = next((c for c in found if client.lower() in ((c.get("name") or "").lower(), str(c.get("registration_no") or ""))), None) \
        or (found[0] if len(found) == 1 else None)
    if not subj:
        names = ", ".join(c.get("name", "") for c in found[:5])
        return ToolResult(False, f"Odběratele „{client}“ jsem ve Fakturoidu nenašel jednoznačně" + (f" (možná: {names})" if names else "")
                          + " – přidej ho do kontaktů nebo napiš přesný název.")
    body: dict[str, Any] = {"subject_id": subj["id"], "due": int(due_days or 14), "lines": [
        {"name": str(x.get("name", "")), "quantity": x.get("quantity", 1), "unit_name": x.get("unit_name", ""),
         "unit_price": x.get("unit_price", 0), **({"vat_rate": x["vat_rate"]} if "vat_rate" in x else {})} for x in lines if isinstance(x, dict)]}
    if note:
        body["note"] = note
    inv = await _api("POST", f"/accounts/{s}/invoices.json", json=body)
    return ToolResult(True, f"Faktura {inv.get('number')} vystavena ({inv.get('total')} {inv.get('currency')}).", data=_inv(inv))
