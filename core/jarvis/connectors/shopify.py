"""3.12 Shopify: objednávky, produkty a sklad (jen čtení). An Admin API access token of your store's own app (shpat_…)
– or the app's Client ID + secret (newer Dev Dashboard apps, a token for 24 h is asked by itself). GraphQL Admin API."""
from __future__ import annotations

import datetime as dt
import time
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, days_ago, guarded, need, register, value

_TOKEN: dict[str, Any] = {"v": "", "until": 0.0}


def version(today: dt.date | None = None) -> str:
    """An API version Shopify surely supports: the quarterly release from about half a year ago (each lives a year)."""
    d = today or dt.date.today()
    y, m = d.year, ((d.month - 1) // 3) * 3 + 1 - 6
    if m < 1:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


def shop() -> str:
    s = value("shopify", "shop").strip().lower().replace("https://", "").replace("http://", "").strip("/")
    s = s.split("/")[0]
    return s if "." in s else f"{s}.myshopify.com"


async def _token(transport=None) -> str:
    need("shopify")
    if value("shopify", "token"):
        return value("shopify", "token")
    if not (value("shopify", "client_id") and value("shopify", "client_secret")):
        raise ServiceError("Shopify: vlož Admin API access token (shpat_…), nebo Client ID a Client secret aplikace.")
    if _TOKEN["v"] and time.time() < _TOKEN["until"]:
        return _TOKEN["v"]
    r = await call("POST", f"https://{shop()}/admin/oauth/access_token", transport=transport,
                   data={"grant_type": "client_credentials", "client_id": value("shopify", "client_id"),
                         "client_secret": value("shopify", "client_secret")})
    _TOKEN.update(v=r.get("access_token", ""), until=time.time() + int(r.get("expires_in", 86399)) - 300)
    return _TOKEN["v"]


async def gql(query: str, variables: dict | None = None, transport=None) -> dict:
    tok = await _token(transport)
    r = await call("POST", f"https://{shop()}/admin/api/{version()}/graphql.json", transport=transport,
                   json={"query": query, "variables": variables or {}}, headers={"X-Shopify-Access-Token": tok})
    if r.get("errors"):
        errs = r["errors"] if isinstance(r["errors"], list) else [{"message": str(r["errors"])}]
        raise ServiceError("Shopify: " + "; ".join(str(e.get("message", e)) for e in errs)[:300])
    return r.get("data") or {}


async def _test(rt: Any) -> str:
    _TOKEN.update(v="", until=0.0)
    d = await gql("{ shop { name myshopifyDomain currencyCode } }")
    return f"Propojeno – obchod {d['shop']['name']} ({d['shop']['currencyCode']})."


register("shopify", "Shopify (e-shop)", "storefront", [
    {"key": "shop", "label": "Adresa obchodu", "secret": False, "hint": "mujobchod.myshopify.com"},
    {"key": "token", "label": "Admin API access token", "secret": True, "hint": "shpat_… (nebo vyplň Client ID a secret)", "optional": True},
    {"key": "client_id", "label": "Client ID (nepovinné)", "secret": False, "hint": "u novějších aplikací z Dev Dashboardu", "optional": True},
    {"key": "client_secret", "label": "Client secret (nepovinné)", "secret": True, "hint": "", "optional": True},
], [
    "V administraci Shopify: Nastavení → Aplikace a prodejní kanály → Vyvíjet aplikace → Vytvořit aplikaci (nebo v Dev Dashboardu).",
    "Admin API scopes: read_orders, read_products, read_inventory, read_customers → nainstaluj aplikaci do obchodu.",
    "Zkopíruj Admin API access token (shpat_…) – nebo Client ID a Client secret – sem, doplň adresu obchodu a ulož.",
], url="https://admin.shopify.com/", what="Objednávky (tržby, co je k odeslání), produkty a sklad – jen čtení.", test=_test, group="sales",
    any_of=[("token",), ("client_id", "client_secret")])


@tool("shopify_orders", "Shopify: objednávky za posledních N dní (tržby, zaplaceno, k odeslání).", category="propojení", perm="network")
@guarded
async def orders(ctx, days: Annotated[int, "kolik dní zpět"] = 7, unfulfilled: Annotated[bool, "jen neodeslané"] = False) -> ToolResult:
    q = f"created_at:>={days_ago(days).date().isoformat()}" + (" fulfillment_status:unfulfilled" if unfulfilled else "")
    d = await gql("""query($q: String!) { orders(first: 100, reverse: true, sortKey: CREATED_AT, query: $q) { nodes {
        name createdAt displayFinancialStatus displayFulfillmentStatus
        totalPriceSet { shopMoney { amount currencyCode } } customer { displayName }
        lineItems(first: 5) { nodes { title quantity } } } } }""", {"q": q})
    out, total = [], {}
    for o in (d.get("orders") or {}).get("nodes", []):
        money = (o.get("totalPriceSet") or {}).get("shopMoney") or {}
        out.append({"order": o.get("name"), "created": o.get("createdAt"), "paid": o.get("displayFinancialStatus"),
                    "shipped": o.get("displayFulfillmentStatus"), "total": money.get("amount"), "currency": money.get("currencyCode"),
                    "customer": (o.get("customer") or {}).get("displayName"),
                    "items": [f"{x['quantity']}× {x['title']}" for x in (o.get("lineItems") or {}).get("nodes", [])]})
        cur = money.get("currencyCode") or ""
        total[cur] = round(total.get(cur, 0) + float(money.get("amount") or 0), 2)
    return ToolResult(True, f"{len(out)} objednávek za {days} dní, celkem {total or 0}.", data=out)


@tool("shopify_products", "Shopify: produkty – cena, stav, kolik je skladem (hledání podle názvu).", category="propojení", perm="network")
@guarded
async def products(ctx, query: Annotated[str, "název (prázdné = všechny)"] = "", low_stock: Annotated[int, "jen se skladem pod (0 = vše)"] = 0) -> ToolResult:
    d = await gql("""query($q: String) { products(first: 100, query: $q, sortKey: UPDATED_AT, reverse: true) { nodes {
        title status totalInventory priceRangeV2 { minVariantPrice { amount currencyCode } } } } }""",
                  {"q": f"title:*{query.strip()}*" if query.strip() else None})
    out = [{"title": p.get("title"), "status": p.get("status"), "stock": p.get("totalInventory"),
            "price": ((p.get("priceRangeV2") or {}).get("minVariantPrice") or {}).get("amount")} for p in (d.get("products") or {}).get("nodes", [])]
    if low_stock:
        out = [p for p in out if p["stock"] is not None and p["stock"] < low_stock]
    return ToolResult(True, f"{len(out)} produktů.", data=out)
