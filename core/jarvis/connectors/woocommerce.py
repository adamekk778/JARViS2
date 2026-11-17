"""3.12 WooCommerce (e-shop na WordPressu): objednávky a produkty – jen čtení. REST API klíč (ck_… + cs_…)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, days_ago, guarded, need, register, value


def site() -> str:
    s = value("woocommerce", "site").strip().rstrip("/")
    return s if s.startswith("http") else "https://" + s


async def _api(path: str, transport=None, **params) -> Any:
    need("woocommerce")
    return await call("GET", f"{site()}/wp-json/wc/v3{path}", params=params or None, transport=transport,
                      auth=(value("woocommerce", "key"), value("woocommerce", "secret")))


async def _test(rt: Any) -> str:
    r = await _api("/orders", per_page=1)
    return "Propojeno – objednávky jdou číst." if isinstance(r, list) else "Propojeno."


register("woocommerce", "WooCommerce (e-shop)", "shopping-cart", [
    {"key": "site", "label": "Adresa webu", "secret": False, "hint": "https://mujobchod.cz"},
    {"key": "key", "label": "Consumer key", "secret": True, "hint": "ck_…"},
    {"key": "secret", "label": "Consumer secret", "secret": True, "hint": "cs_…"},
], [
    "Ve WordPressu: WooCommerce → Nastavení → Pokročilé → REST API → Přidat klíč.",
    "Oprávnění: Číst (Read) → Vygenerovat API klíč.",
    "Zkopíruj Consumer key a Consumer secret sem, doplň adresu webu (https://…) a ulož.",
], url="", what="Objednávky (tržby, stav) a produkty se skladem – jen čtení.", test=_test, group="sales")


@tool("woocommerce_orders", "WooCommerce: objednávky za posledních N dní (stav, částka, zákazník).", category="propojení", perm="network")
@guarded
async def orders(ctx, days: Annotated[int, "kolik dní zpět"] = 7, status: Annotated[str, "processing / completed / on-hold / any"] = "any") -> ToolResult:
    r = await _api("/orders", per_page=100, after=days_ago(days).replace(microsecond=0, tzinfo=None).isoformat(), status=status or "any")
    out, total = [], {}
    for o in r if isinstance(r, list) else []:
        b = o.get("billing") or {}
        out.append({"number": o.get("number"), "created": o.get("date_created"), "status": o.get("status"), "total": o.get("total"),
                    "currency": o.get("currency"), "customer": f"{b.get('first_name', '')} {b.get('last_name', '')}".strip() or b.get("company"),
                    "items": [f"{i.get('quantity')}× {i.get('name')}" for i in o.get("line_items", [])[:5]]})
        if o.get("status") in ("processing", "completed", "on-hold"):
            total[o.get("currency")] = round(total.get(o.get("currency"), 0) + float(o.get("total") or 0), 2)
    return ToolResult(True, f"{len(out)} objednávek, tržby {total or 0}.", data=out)


@tool("woocommerce_products", "WooCommerce: produkty – cena a sklad (hledání podle názvu).", category="propojení", perm="network")
@guarded
async def products(ctx, query: Annotated[str, "název (prázdné = všechny)"] = "") -> ToolResult:
    params: dict[str, Any] = {"per_page": 100}
    if query.strip():
        params["search"] = query.strip()
    r = await _api("/products", **params)
    out = [{"name": p.get("name"), "price": p.get("price"), "stock": p.get("stock_quantity"), "stock_status": p.get("stock_status"),
            "status": p.get("status")} for p in (r if isinstance(r, list) else [])]
    return ToolResult(True, f"{len(out)} produktů.", data=out)
