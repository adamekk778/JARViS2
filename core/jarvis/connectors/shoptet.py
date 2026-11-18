"""3.13 Shoptet: objednávky, zákazníci a sklad českého e-shopu (jen čtení). Soukromý API token z administrace
(Propojení → Soukromé API, 32 znaků) – posílá se v hlavičce Shoptet-Private-API-Token na api.myshoptet.com."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

BASE = "https://api.myshoptet.com/api"
PER_PAGE = 50                         # Shoptet: at most 50 orders per page


async def api(path: str, params: dict | None = None, transport=None) -> dict:
    need("shoptet")
    r = await call("GET", BASE + path, transport=transport, params=params,
                   headers={"Shoptet-Private-API-Token": value("shoptet", "token").strip(), "Content-Type": "application/json"})
    if isinstance(r, dict) and r.get("data") is None and r.get("errors"):
        raise ServiceError("Shoptet: " + "; ".join(str(e.get("message", e)) for e in r["errors"][:3])[:300])
    return (r or {}).get("data") or {}


async def _test(rt: Any) -> str:
    d = await api("/eshop")
    c = d.get("contactInformation") or {}
    return f"Propojeno – e-shop {c.get('eshopName') or c.get('url') or 'Shoptet'}."


register("shoptet", "Shoptet (e-shop)", "storefront", [
    {"key": "token", "label": "Soukromý API token", "secret": True, "hint": "32 znaků"},
], [
    "V administraci Shoptetu otevři Propojení → Soukromé API (je v tarifech, které API mají).",
    "Vytvoř nový token a dej mu práva ke čtení objednávek, zákazníků, produktů a skladu.",
    "Token zkopíruj sem a ulož – JARVIS z e-shopu jen čte.",
], url="https://www.shoptet.cz/", what="Objednávky (tržby, stav, zaplaceno), zákazníci a zásoby na skladě – jen čtení.",
    test=_test, group="sales",
    probe={"method": "GET", "url": BASE + "/eshop", "headers": {"Shoptet-Private-API-Token": "0" * 32, "Content-Type": "application/json"}})


def _order(o: dict) -> dict:
    p = o.get("price") or {}
    return {"code": o.get("code"), "created": (o.get("creationTime") or "")[:16].replace("T", " "),
            "customer": o.get("fullName") or (o.get("billingAddress") or {}).get("fullName") or o.get("company") or "",
            "company": o.get("company") or (o.get("billingAddress") or {}).get("company") or "", "email": o.get("email"),
            "status": (o.get("status") or {}).get("name"), "total": p.get("withVat"), "currency": p.get("currencyCode"),
            "to_pay": p.get("toPay"), "paid": o.get("paid"), "shipping": (o.get("shipping") or {}).get("name"),
            "payment": (o.get("paymentMethod") or {}).get("name"), "admin": o.get("adminUrl")}


async def orders(days: float, status_id: int | None = None, pages: int = 4, transport=None) -> list[dict]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=float(days or 0))).replace(microsecond=0).isoformat()
    out: list[dict] = []
    for page in range(1, pages + 1):
        params: dict[str, Any] = {"creationTimeFrom": since, "itemsPerPage": PER_PAGE, "page": page}
        if status_id is not None:
            params["statusId"] = status_id
        d = await api("/orders", params, transport)
        out += [_order(o) for o in d.get("orders") or []]
        pg = d.get("paginator") or {}
        if page >= int(pg.get("pageCount") or 1):
            break
    return out


@tool("shoptet_orders", "Shoptet: objednávky za posledních N dní – zákazník, částka, stav, zaplaceno, doprava a platba.",
      category="propojení", perm="network")
@guarded
async def shoptet_orders(ctx, days: Annotated[int, "kolik dní zpět"] = 7) -> ToolResult:
    items = await orders(max(1, min(int(days or 7), 90)))
    sums: dict[str, float] = {}
    for o in items:
        try:
            sums[o["currency"] or "?"] = round(sums.get(o["currency"] or "?", 0) + float(o["total"] or 0), 2)
        except (TypeError, ValueError):
            pass
    unpaid = sum(1 for o in items if o.get("paid") is False)
    return ToolResult(True, f"{len(items)} objednávek za {days} dní" + (f", tržby {sums}" if sums else "")
                      + (f", nezaplaceno {unpaid}" if unpaid else "") + ".", data=items)


@tool("shoptet_order", "Shoptet: detail jedné objednávky podle čísla (položky, adresa, poznámka).", category="propojení", perm="network")
@guarded
async def shoptet_order(ctx, code: Annotated[str, "číslo objednávky, např. 2026000123"]) -> ToolResult:
    d = await api(f"/orders/{str(code).strip()}", {"include": "notes"})
    o = d.get("order") or {}
    items = [{"name": " ".join(x for x in (i.get("name"), i.get("variantName")) if x), "code": i.get("code"), "amount": i.get("amount"),
              "unit": i.get("amountUnit"), "price": (i.get("itemPrice") or {}).get("withVat"), "status": (i.get("status") or {}).get("name")}
             for i in o.get("items") or [] if i.get("itemType", "product") in ("product", "service", "")]
    out = {**_order(o), "items": items[:40], "remark": o.get("remark"),
           "address": {k: v for k, v in (o.get("billingAddress") or {}).items() if isinstance(v, str) and v}}
    return ToolResult(True, f"Objednávka {out['code']}: {out['total']} {out['currency']}, {len(items)} položek, {out['status']}.", data=out)


@tool("shoptet_stock", "Shoptet: zásoby na skladě – co dochází (pod zadaným množstvím).", category="propojení", perm="network")
@guarded
async def shoptet_stock(ctx, below: Annotated[float, "ukázat zboží s množstvím pod touto hodnotou"] = 5) -> ToolResult:
    st = await api("/stocks")
    stocks = st.get("stocks") or []
    sid = st.get("defaultStockId") or (stocks[0]["id"] if stocks else 1)
    low: list[dict] = []
    total = 0
    for page in range(1, 11):
        d = await api(f"/stocks/{sid}/supplies", {"itemsPerPage": 500, "page": page})
        for s in d.get("supplies") or []:
            total += 1
            try:
                amount = float(s.get("amount"))
            except (TypeError, ValueError):
                continue                      # no amount = not tracked / unlimited
            if amount < float(below):
                low.append({"code": s.get("code"), "amount": amount, "reserved": s.get("claim"), "location": s.get("location")})
        if page >= int((d.get("paginator") or {}).get("pageCount") or 1):
            break
    low.sort(key=lambda x: x["amount"])
    return ToolResult(True, f"Dochází {len(low)} z {total} položek skladu (pod {below:g} ks).", data=low[:200])
