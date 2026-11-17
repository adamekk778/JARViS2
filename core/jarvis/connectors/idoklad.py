"""3.12 iDoklad: vydané faktury a kontakty (jen čtení). Client ID + Client secret from Nastavení → API."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, register, slim
from .oauth import ClientCredentials

API = "https://api.idoklad.cz/v3"
AUTH = ClientCredentials("idoklad", "https://identity.idoklad.cz/server/connect/token", extra={"scope": "idoklad_api"}, name="iDoklad")


async def _api(path: str, transport=None, **params) -> Any:
    tok = await AUTH.token(transport)
    r = await call("GET", API + path, params=params or None, transport=transport, headers={"Authorization": f"Bearer {tok}"})
    return r.get("Data", r) if isinstance(r, dict) else r


async def _test(rt: Any) -> str:
    AUTH.forget()
    d = await _api("/IssuedInvoices", page=1, pageSize=1)
    return f"Propojeno – {d.get('TotalItems', '?')} vydaných faktur."


register("idoklad", "iDoklad (faktury)", "receipt-x", [
    {"key": "client_id", "label": "Client ID", "secret": False, "hint": ""},
    {"key": "client_secret", "label": "Client secret", "secret": True, "hint": ""},
], [
    "V iDokladu otevři Nastavení → Uživatelé a API (nebo Nastavení → API) a vygeneruj přístup pro API v3 (Client ID a Client secret).",
    "Zkopíruj obojí sem a ulož.",
], url="https://app.idoklad.cz/", what="Vydané faktury (zaplacené, nezaplacené) a kontakty – jen čtení.", test=_test, group="money",
    probe={"method": "POST", "url": "https://identity.idoklad.cz/server/connect/token",
           "data": {"grant_type": "client_credentials", "client_id": "FAKE", "client_secret": "FAKE", "scope": "idoklad_api"}})

KEEP = ("Id", "DocumentNumber", "DateOfIssue", "DateOfMaturity", "DateOfPayment", "PartnerName", "PurchaserName", "Description",
        "Prices.TotalWithVat", "Prices.TotalWithVatHc", "CurrencyId", "PaymentStatus", "IsPaid", "VariableSymbol")


@tool("idoklad_invoices", "iDoklad: poslední vydané faktury (odběratel, částka, splatnost, zaplaceno).", category="propojení", perm="network")
@guarded
async def invoices(ctx, limit: Annotated[int, "kolik (max 50)"] = 20) -> ToolResult:
    d = await _api("/IssuedInvoices", page=1, pageSize=max(1, min(int(limit or 20), 50)), sort="DateOfIssue~desc")
    items = [slim(i, KEEP) for i in d.get("Items", [])]
    return ToolResult(True, f"{len(items)} faktur (celkem {d.get('TotalItems', '?')}).", data=items)


@tool("idoklad_contacts", "iDoklad: kontakty (odběratelé a dodavatelé).", category="propojení", perm="network")
@guarded
async def contacts(ctx, query: Annotated[str, "hledat v názvu (nepovinné)"] = "") -> ToolResult:
    d = await _api("/Contacts", page=1, pageSize=100)
    items = [slim(c, ("Id", "CompanyName", "Firstname", "Surname", "IdentificationNumber", "Email", "City", "Phone")) for c in d.get("Items", [])]
    if query.strip():
        items = [c for c in items if query.lower() in str(c).lower()]
    return ToolResult(True, f"{len(items)} kontaktů.", data=items[:40])
