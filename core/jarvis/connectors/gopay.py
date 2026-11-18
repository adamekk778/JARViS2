"""3.13 GoPay: platby e-shopu – stav platby a výpis pohybů na účtu GoPay (jen čtení). GoID + Client ID + Client secret
z obchodního účtu GoPay; token přes OAuth2 client credentials (scope payment-all) na gate.gopay.cz/api."""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, register, value
from .oauth import ClientCredentials

BASE = "https://gate.gopay.cz/api"
AUTH = ClientCredentials("gopay", BASE + "/oauth2/token", basic=True, extra={"scope": "payment-all"}, name="GoPay")
PAID = {"PAID": "zaplaceno", "CREATED": "založeno", "PAYMENT_METHOD_CHOSEN": "vybírá platbu", "AUTHORIZED": "předautorizováno",
        "CANCELED": "zrušeno", "TIMEOUTED": "vypršelo", "REFUNDED": "vráceno", "PARTIALLY_REFUNDED": "částečně vráceno"}


async def api(method: str, path: str, transport=None, **kw) -> Any:
    tok = await AUTH.token(transport)
    return await call(method, BASE + path, transport=transport, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"}, **kw)


def goid() -> int:
    try:
        return int(value("gopay", "goid").strip())
    except ValueError:
        raise ServiceError("GoPay: GoID je číslo (10 číslic) – najdeš ho v obchodním účtu GoPay.") from None


async def _test(rt: Any) -> str:
    AUTH.forget()
    await AUTH.token()
    return f"Propojeno – GoPay přijal Client ID a secret (GoID {goid()})."


register("gopay", "GoPay (platby)", "credit-card", [
    {"key": "goid", "label": "GoID", "secret": False, "hint": "10 číslic"},
    {"key": "client_id", "label": "Client ID", "secret": False, "hint": ""},
    {"key": "client_secret", "label": "Client secret", "secret": True, "hint": ""},
], [
    "Přihlas se do obchodního účtu GoPay → Nastavení → Integrace (přístupové údaje k REST API).",
    "Zkopíruj GoID, Client ID a Client secret pro ostré prostředí.",
    "Ulož – JARVIS jen čte stav plateb a výpis pohybů.",
], url="https://account.gopay.com/", what="Stav platby podle ID a výpis pohybů na účtu GoPay – jen čtení.", test=_test, group="money",
    probe={"method": "POST", "url": BASE + "/oauth2/token", "auth": ["FAKE", "FAKE"], "data": {"grant_type": "client_credentials",
           "scope": "payment-all"}, "headers": {"Accept": "application/json"}})


@tool("gopay_payment", "GoPay: stav jedné platby podle jejího ID (zaplaceno, zrušeno, vráceno), částka a plátce.",
      category="propojení", perm="network")
@guarded
async def gopay_payment(ctx, payment_id: Annotated[str, "ID platby GoPay (číslo)"]) -> ToolResult:
    p = await api("GET", f"/payments/payment/{int(str(payment_id).strip())}")
    amount = (p.get("amount") or 0) / 100
    out = {"id": p.get("id"), "order": p.get("order_number"), "state": p.get("state"), "state_cz": PAID.get(p.get("state", ""), p.get("state")),
           "amount": amount, "currency": p.get("currency"), "email": ((p.get("payer") or {}).get("contact") or {}).get("email"),
           "method": (p.get("payer") or {}).get("payment_instrument")}
    return ToolResult(True, f"Platba {out['id']} ({out['order']}): {amount:,.2f} {out['currency']} – {out['state_cz']}.", data=out)


def rows(text: str) -> list[dict]:
    """GoPay's CSV statement as records (its delimiter is found from the file)."""
    text = text.lstrip("﻿").strip()
    if not text:
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text), dialect=dialect)]


@tool("gopay_statement", "GoPay: výpis pohybů na účtu GoPay za posledních N dní (příchozí platby, poplatky, výplaty).",
      category="propojení", perm="network")
@guarded
async def gopay_statement(ctx, days: Annotated[int, "kolik dní zpět"] = 7, currency: Annotated[str, "měna účtu"] = "CZK") -> ToolResult:
    today = dt.date.today()
    r = await api("POST", "/accounts/account-statement", json={"date_from": str(today - dt.timedelta(days=max(1, min(int(days), 90)))),
                                                               "date_to": str(today), "goid": goid(), "currency": currency.upper(),
                                                               "format": "CSV_A"}, timeout=60)
    items = rows(r.get("text", "") if isinstance(r, dict) else str(r))
    return ToolResult(True, f"Výpis GoPay za {days} dní: {len(items)} pohybů.", data=items[:200])
