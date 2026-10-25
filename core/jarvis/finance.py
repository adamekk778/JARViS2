"""3.5 money: ČNB exchange rates, crypto (CoinGecko) and shares (Stooq), plus "dej vědět, až bitcoin klesne pod …"."""
from __future__ import annotations

import csv
import io
import time

from .stark import _fold

CNB_URL = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
GECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
STOOQ_URL = "https://stooq.com/q/l/"
CRYPTO = {"btc": "bitcoin", "bitcoin": "bitcoin", "eth": "ethereum", "ether": "ethereum", "ethereum": "ethereum",
          "sol": "solana", "solana": "solana", "doge": "dogecoin", "dogecoin": "dogecoin", "ada": "cardano", "cardano": "cardano",
          "xrp": "ripple", "ripple": "ripple", "ltc": "litecoin", "litecoin": "litecoin", "bnb": "binancecoin",
          "usdt": "tether", "tether": "tether", "dot": "polkadot", "polkadot": "polkadot", "trx": "tron", "tron": "tron"}
CURRENCY_WORDS = {"euro": "EUR", "eura": "EUR", "eur": "EUR", "dolar": "USD", "dolary": "USD", "dolaru": "USD", "usd": "USD",
                  "libra": "GBP", "libry": "GBP", "gbp": "GBP", "frank": "CHF", "chf": "CHF", "zloty": "PLN", "zlotych": "PLN",
                  "pln": "PLN", "forint": "HUF", "huf": "HUF", "koruna": "CZK", "koruny": "CZK", "korun": "CZK", "kc": "CZK",
                  "czk": "CZK", "jen": "JPY", "jpy": "JPY", "yuan": "CNY", "juan": "CNY"}
_cnb: tuple[float, dict[str, float]] = (0.0, {})


def currency_code(s: str) -> str:
    f = _fold(s).replace(".", "")
    return CURRENCY_WORDS.get(f, s.strip().upper()[:3])


def parse_cnb(text: str) -> dict[str, float]:
    """ČNB "denni_kurz.txt" → CZK for 1 unit of each currency."""
    out = {"CZK": 1.0}
    for line in text.splitlines()[2:]:
        parts = line.split("|")
        if len(parts) == 5:
            try:
                out[parts[3].strip()] = float(parts[4].replace(",", ".")) / float(parts[2])
            except ValueError:
                continue
    return out


async def cnb_rates(rt) -> dict[str, float]:
    global _cnb
    if time.time() - _cnb[0] < 3600 and _cnb[1]:
        return _cnb[1]
    async with rt.http() as c:
        r = await c.get(CNB_URL, timeout=8)
    r.raise_for_status()
    _cnb = (time.time(), parse_cnb(r.text))
    return _cnb[1]


async def convert(rt, amount: float, frm: str, to: str) -> float:
    rates = await cnb_rates(rt)
    a, b = currency_code(frm), currency_code(to)
    if a not in rates or b not in rates:
        raise ValueError(f"Měnu {a if a not in rates else b} ČNB nevede.")
    return amount * rates[a] / rates[b]


async def crypto(rt, coin: str, vs: str = "czk") -> dict:
    cid = CRYPTO.get(_fold(coin), _fold(coin).replace(" ", "-"))
    async with rt.http() as c:
        r = await c.get(GECKO_URL, params={"ids": cid, "vs_currencies": vs.lower(), "include_24hr_change": "true"}, timeout=8)
    r.raise_for_status()
    d = r.json().get(cid)
    if not d:
        raise ValueError(f"Kryptoměnu „{coin}“ neznám.")
    return {"name": cid, "price": float(d[vs.lower()]), "currency": vs.upper(), "change": d.get(f"{vs.lower()}_24h_change")}


async def stock(rt, symbol: str) -> dict:
    sym = symbol.strip().lower()
    if "." not in sym:
        sym += ".us"
    async with rt.http() as c:
        r = await c.get(STOOQ_URL, params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"}, timeout=8)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows or rows[0].get("Close") in (None, "", "N/D"):
        raise ValueError(f"Akcii „{symbol}“ nenašel.")
    row = rows[0]
    close, opn = float(row["Close"]), float(row.get("Open") or 0) or None
    cur = "USD" if sym.endswith(".us") else ""
    return {"name": row["Symbol"].upper(), "price": close, "currency": cur,
            "change": (close - opn) / opn * 100 if opn else None, "date": row.get("Date", "")}


async def quote(rt, asset: str, vs: str = "czk") -> dict:
    """Anything with a price: "bitcoin", "eth", "AAPL", "euro" (in CZK)."""
    f = _fold(asset)
    if f in CRYPTO:
        return await crypto(rt, asset, vs)
    code = currency_code(asset)
    if f in CURRENCY_WORDS or (len(asset.strip()) == 3 and code in await cnb_rates(rt) and code not in ("CZK",)):
        rate = await convert(rt, 1, code, "CZK")
        return {"name": code, "price": rate, "currency": "CZK", "change": None}
    return await stock(rt, asset)


def fmt_money(v: float, cur: str = "") -> str:
    s = f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"
    return s.replace(",", " ").replace(".", ",") + (f" {cur}" if cur else "")


def say_quote(q: dict) -> str:
    ch = q.get("change")
    tail = f", za den {'+' if ch >= 0 else ''}{ch:.1f} %".replace(".", ",") if isinstance(ch, (int, float)) else ""
    return f"{q['name']}: {fmt_money(q['price'], q['currency'])}{tail}"


async def check_alert(rt, p: dict) -> tuple[bool, str]:
    q = await quote(rt, p["asset"], p.get("vs", "czk"))
    hit = q["price"] >= p["value"] if p["dir"] == "above" else q["price"] <= p["value"]
    word = "vystoupal nad" if p["dir"] == "above" else "klesl pod"
    return hit, f"{q['name']} {word} {fmt_money(p['value'], q['currency'])}: teď {fmt_money(q['price'], q['currency'])}."
