"""3.5 money by voice: "kolik je euro", "převeď 50 dolarů na koruny", "kolik stojí bitcoin", "hlídej Teslu pod 200"."""
from __future__ import annotations

from typing import Annotated, Literal

from .base import ToolResult, tool


@tool("exchange_rate", "Převod měn podle dnešního kurzu ČNB: „kolik je 50 eur v korunách“, „kurz dolaru“.", category="web", perm="network")
async def exchange_rate(ctx, amount: float = 1, from_currency: Annotated[str, "EUR, USD, GBP… nebo slovy"] = "EUR",
                        to_currency: str = "CZK") -> ToolResult:
    from ..finance import convert, currency_code, fmt_money

    v = await convert(ctx, amount, from_currency, to_currency)
    a, b = currency_code(from_currency), currency_code(to_currency)
    return ToolResult(True, f"{fmt_money(amount, a)} = {fmt_money(v, b)} (kurz ČNB).", data={"value": v})


@tool("price", "Aktuální cena kryptoměny (bitcoin, eth, solana…), akcie (AAPL, TSLA, MSFT…) nebo měny v korunách, "
      "i se změnou za den.", category="web", perm="network")
async def price(ctx, asset: Annotated[str, "bitcoin, eth, AAPL, euro…"], currency: Annotated[str, "czk / usd / eur (kryptoměny)"] = "czk") -> ToolResult:
    from ..finance import quote, say_quote

    q = await quote(ctx, asset, currency)
    return ToolResult(True, say_quote(q) + ".", data=q)


@tool("price_alert", "Hlídá cenu (kryptoměna, akcie, měna) a dá vědět – i zavoláním na mobil –, až překročí hranici: "
      "„dej vědět, až bitcoin klesne pod 1,5 milionu“. Kontroluje každých 15 minut.", category="web", perm="network")
async def price_alert(ctx, asset: str, direction: Literal["above", "below"], value: float, currency: str = "czk",
                      call: Annotated[bool, "zavolat na mobil místo upozornění"] = False) -> ToolResult:
    from ..finance import fmt_money, quote

    if not ctx.scheduler:
        return ToolResult(False, "Plánovač neběží.")
    q = await quote(ctx, asset, currency)           # also checks the asset exists
    payload = {"asset": asset, "dir": direction, "value": float(value), "vs": currency, "call": call}
    ctx.scheduler.add({"type": "interval", "minutes": 15}, "price", payload,
                      f"Hlídat {q['name']} {'nad' if direction == 'above' else 'pod'} {fmt_money(value, q['currency'])}")
    return ToolResult(True, f"Hlídám {q['name']} (teď {fmt_money(q['price'], q['currency'])}); dám vědět, až bude "
                            f"{'nad' if direction == 'above' else 'pod'} {fmt_money(value, q['currency'])}.")
