"""3.12 Stripe: balance, payments, customers and invoices. A refund or a new payment link asks first. Best with a
restricted key (read for everything, write only for refunds and payment links)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, days_ago, guarded, need, register, value

API = "https://api.stripe.com/v1"
ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}


def money(amount: Any, currency: str) -> float:
    """Stripe counts in the smallest unit (cents, haléře) – except a few currencies."""
    a = float(amount or 0)
    return a if (currency or "").lower() in ZERO_DECIMAL else round(a / 100, 2)


def minor(amount: float, currency: str) -> int:
    return int(round(float(amount))) if (currency or "").lower() in ZERO_DECIMAL else int(round(float(amount) * 100))


async def _api(method: str, path: str, transport=None, **kw) -> Any:
    need("stripe")
    return await call(method, API + path, headers={"Authorization": f"Bearer {value('stripe', 'key')}"}, transport=transport, **kw)


async def _test(rt: Any) -> str:
    b = await _api("GET", "/balance")
    av = ", ".join(f"{money(x['amount'], x['currency']):,.2f} {x['currency'].upper()}" for x in b.get("available", [])) or "0"
    return f"Propojeno{' (testovací režim)' if not b.get('livemode', True) else ''} – k dispozici {av}."


register("stripe", "Stripe (platby)", "credit-card", [
    {"key": "key", "label": "Secret nebo Restricted key", "secret": True, "hint": "rk_live_… / sk_live_…"},
], [
    "Otevři dashboard.stripe.com/apikeys.",
    "Nejbezpečnější je „Create restricted key“: Read u Balance, Charges, Customers, Invoices a PaymentIntents; "
    "Write jen u Refunds, Prices, Products a Payment Links, pokud je chceš.",
    "Zkopíruj klíč sem a ulož.",
], url="https://dashboard.stripe.com/apikeys",
    what="Zůstatek, platby, zákazníci a faktury; vrácení peněz a platební odkaz jen s potvrzením.", test=_test, group="money",
    probe={"method": "GET", "url": API + "/balance", "headers": {"Authorization": "Bearer sk_test_FAKE"}})


@tool("stripe_balance", "Stripe: zůstatek (k dispozici a čekající).", category="propojení", perm="network")
@guarded
async def balance(ctx) -> ToolResult:
    b = await _api("GET", "/balance")
    f = lambda xs: {x["currency"].upper(): money(x["amount"], x["currency"]) for x in xs}  # noqa: E731
    return ToolResult(True, "Zůstatek na Stripe.", data={"available": f(b.get("available", [])), "pending": f(b.get("pending", [])),
                                                        "test_mode": not b.get("livemode", True)})


@tool("stripe_payments", "Stripe: platby za posledních N dní (kolik, od koho, stav) a součet.", category="propojení", perm="network")
@guarded
async def payments(ctx, days: Annotated[int, "kolik dní zpět"] = 7) -> ToolResult:
    r = await _api("GET", "/payment_intents", params={"limit": 100, "created[gte]": int(days_ago(days).timestamp()),
                                                      "expand[]": "data.customer"})
    out, total = [], {}
    for p in r.get("data", []):
        cur = p.get("currency", "")
        amt = money(p.get("amount_received") or p.get("amount"), cur)
        cust = p.get("customer") if isinstance(p.get("customer"), dict) else {}
        out.append({"id": p["id"], "amount": amt, "currency": cur.upper(), "status": p.get("status"), "created": p.get("created"),
                    "customer": cust.get("email") or cust.get("name") or p.get("receipt_email"), "description": p.get("description")})
        if p.get("status") == "succeeded":
            total[cur.upper()] = round(total.get(cur.upper(), 0) + amt, 2)
    return ToolResult(True, f"{len(out)} plateb za {days} dní, přijato {total or 0}.", data={"payments": out, "received": total,
                                                                                        "more": r.get("has_more", False)})


@tool("stripe_customers", "Stripe: najde zákazníky (jméno nebo e-mail).", category="propojení", perm="network")
@guarded
async def customers(ctx, query: Annotated[str, "jméno nebo e-mail (prázdné = poslední)"] = "") -> ToolResult:
    q = query.replace("'", "").strip()
    if len(q) >= 3:                                   # Stripe's search: "~" needs at least 3 letters
        r = await _api("GET", "/customers/search", params={"query": f"email~'{q}' OR name~'{q}'", "limit": 25})
    elif q:
        r = await _api("GET", "/customers", params={"limit": 100})
        r["data"] = [c for c in r.get("data", []) if q.lower() in f"{c.get('name') or ''} {c.get('email') or ''}".lower()]
    else:
        r = await _api("GET", "/customers", params={"limit": 25})
    out = [{"id": c["id"], "name": c.get("name"), "email": c.get("email"), "created": c.get("created"), "currency": c.get("currency")}
           for c in r.get("data", [])]
    return ToolResult(True, f"{len(out)} zákazníků.", data=out)


@tool("stripe_invoices", "Stripe: faktury (otevřené = nezaplacené, nebo podle stavu).", category="propojení", perm="network")
@guarded
async def invoices(ctx, status: Annotated[str, "open / paid / draft / uncollectible / void"] = "open") -> ToolResult:
    r = await _api("GET", "/invoices", params={"limit": 50, "status": status or "open"})
    out = [{"number": i.get("number"), "customer": i.get("customer_email") or i.get("customer_name"),
            "amount": money(i.get("amount_due"), i.get("currency", "")), "currency": (i.get("currency") or "").upper(),
            "due": i.get("due_date"), "status": i.get("status"), "url": i.get("hosted_invoice_url")} for i in r.get("data", [])]
    return ToolResult(True, f"{len(out)} faktur ({status}).", data=out)


@tool("stripe_refund", "Stripe: vrátí peníze za platbu (celou nebo část). Zeptá se uživatele.", danger=True, category="propojení",
      perm="network", details=lambda a: [f"Platba: {a.get('payment_id', '')}", f"Částka: {a.get('amount') or 'celá'}",
                                         f"Důvod: {a.get('reason') or '–'}"])
@guarded
async def refund(ctx, payment_id: Annotated[str, "id platby (pi_…)"], amount: Annotated[float, "kolik vrátit (0 = celé)"] = 0,
                 reason: Annotated[str, "duplicate / fraudulent / requested_by_customer"] = "requested_by_customer") -> ToolResult:
    data: dict[str, Any] = {"payment_intent": payment_id}
    if reason in ("duplicate", "fraudulent", "requested_by_customer"):
        data["reason"] = reason
    if amount:
        pi = await _api("GET", f"/payment_intents/{payment_id}")
        data["amount"] = minor(amount, pi.get("currency", ""))
    r = await _api("POST", "/refunds", data=data)
    return ToolResult(True, f"Vráceno {money(r.get('amount'), r.get('currency', ''))} {(r.get('currency') or '').upper()} ({r.get('status')}).")


@tool("stripe_payment_link", "Stripe: vytvoří platební odkaz na částku (pošleš ho zákazníkovi). Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=lambda a: [f"Za: {a.get('name', '')}", f"Částka: {a.get('amount', '')} {a.get('currency', 'czk')}"])
@guarded
async def payment_link(ctx, name: Annotated[str, "za co (název)"], amount: Annotated[float, "částka"],
                       currency: Annotated[str, "měna, např. czk, eur"] = "czk") -> ToolResult:
    cur = (currency or "czk").lower()
    price = await _api("POST", "/prices", data={"unit_amount": minor(amount, cur), "currency": cur, "product_data[name]": name})
    link = await _api("POST", "/payment_links", data={"line_items[0][price]": price["id"], "line_items[0][quantity]": 1})
    return ToolResult(True, f"Platební odkaz: {link.get('url')}", data={"url": link.get("url")})
