"""3.14 Zkušební obchodování: trading with play money before real money.

JARVIS (or an agent on a monitor) does not click Buy / Sell in the real app – it writes the trade here at the price it
saw on the screen. The play wallet keeps cash, what you hold, the last price seen for each coin/stock and every trade,
so you see whether the strategy would have earned or lost before it touches a single real crown.
"""
from __future__ import annotations

import json
import time
from typing import Any

START_CASH = 10_000.0
MAX_TRADES = 300


def _num(v: Any) -> float:
    """"2 012 400 Kč" / "2,5" / 1000 → a number (0 when it is not one)."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace(" ", "").replace(" ", "").replace("Kč", "").replace("CZK", "").replace("$", "")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


class Paper:
    def __init__(self, rt: Any):
        self.rt = rt

    # ---------- the wallet (one JSON row) ----------
    def _load(self) -> dict:
        db = self.rt.db
        row = db.one("SELECT v FROM kv WHERE k='paper_wallet'")
        try:
            d = json.loads(row["v"]) if row else {}
        except ValueError:
            d = {}
        if not isinstance(d, dict) or "cash" not in d:
            d = {"start": START_CASH, "cash": START_CASH, "pos": {}, "price": {}, "trades": [], "since": time.time()}
        return d

    def _save(self, d: dict) -> None:
        d["trades"] = d.get("trades", [])[-MAX_TRADES:]
        self.rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('paper_wallet', ?)", (json.dumps(d, ensure_ascii=False),))
        try:
            self.rt.bus.publish("paper", **self.summary())
        except Exception:  # noqa: BLE001
            pass

    def reset(self, cash: float = START_CASH) -> dict:
        cash = max(100.0, min(_num(cash) or START_CASH, 100_000_000.0))
        self._save({"start": cash, "cash": cash, "pos": {}, "price": {}, "trades": [], "since": time.time()})
        return self.summary()

    # ---------- trading ----------
    def mark(self, symbol: str, price: Any) -> None:
        """The last price seen for a symbol (a watching agent reads it off the screen)."""
        p = _num(price)
        sym = str(symbol or "").strip().upper()[:20]
        if p > 0 and sym:
            d = self._load()
            d.setdefault("price", {})[sym] = p
            self._save(d)

    def trade(self, side: str, symbol: str, price: Any, czk: Any = 0, qty: Any = 0, who: str = "") -> dict:
        """Buy for `czk` crowns (or `qty` pieces) / sell `qty` (or `czk` worth; nothing given = all) at `price`."""
        side = str(side or "").strip().lower()
        side = {"koupit": "buy", "nákup": "buy", "nakup": "buy", "prodat": "sell", "prodej": "sell"}.get(side, side)
        if side not in ("buy", "sell"):
            raise ValueError("Obchod je buď nákup (buy), nebo prodej (sell).")
        sym = str(symbol or "").strip().upper()[:20]
        if not sym:
            raise ValueError("Chybí, co obchodovat (např. BTC).")
        p = _num(price)
        if p <= 0:
            raise ValueError("Chybí cena – zkušební obchod se zapisuje za cenu, kterou je vidět na obrazovce.")
        d = self._load()
        pos = d.setdefault("pos", {}).setdefault(sym, {"qty": 0.0, "cost": 0.0})
        q = _num(qty)
        amount = _num(czk)
        if side == "buy":
            if q <= 0:
                q = amount / p if amount > 0 else 0
            if q <= 0:
                raise ValueError("Řekni, za kolik korun nebo kolik kusů koupit.")
            cost = q * p
            if cost > d["cash"] + 1e-6:
                raise ValueError(f"Na zkušebním účtu je jen {d['cash']:,.0f} Kč – na nákup za {cost:,.0f} Kč to nestačí.".replace(",", " "))
            d["cash"] -= cost
            pos["qty"] += q
            pos["cost"] += cost
        else:
            have = pos["qty"]
            if have <= 0:
                raise ValueError(f"{sym} na zkušebním účtu nemáš – není co prodat.")
            if q <= 0:
                q = amount / p if amount > 0 else have
            q = min(q, have)
            avg = pos["cost"] / have if have else 0
            d["cash"] += q * p
            pos["qty"] = have - q
            pos["cost"] = max(0.0, pos["cost"] - avg * q)
            if pos["qty"] <= 1e-12:
                d["pos"].pop(sym, None)
        d.setdefault("price", {})[sym] = p
        t = {"ts": time.time(), "side": side, "symbol": sym, "qty": round(q, 8), "price": p, "czk": round(q * p, 2), "who": who[:40]}
        d.setdefault("trades", []).append(t)
        self._save(d)
        return t

    def summary(self) -> dict:
        d = self._load()
        rows, value = [], d["cash"]
        for sym, pos in d.get("pos", {}).items():
            price = d.get("price", {}).get(sym) or (pos["cost"] / pos["qty"] if pos["qty"] else 0)
            v = pos["qty"] * price
            value += v
            rows.append({"symbol": sym, "qty": round(pos["qty"], 8), "avg": round(pos["cost"] / pos["qty"], 2) if pos["qty"] else 0,
                         "price": price, "value": round(v, 2), "pl": round(v - pos["cost"], 2)})
        pl = value - d["start"]
        return {"start": d["start"], "cash": round(d["cash"], 2), "value": round(value, 2), "pl": round(pl, 2),
                "pl_pct": round(pl / d["start"] * 100, 2) if d["start"] else 0, "positions": rows,
                "trades": list(reversed(d.get("trades", [])[-12:])), "count": len(d.get("trades", [])), "since": d.get("since", 0)}

    def describe(self) -> str:
        s = self.summary()
        sign = "+" if s["pl"] >= 0 else ""
        lines = [f"Zkušební účet: hodnota {s['value']:,.0f} Kč (start {s['start']:,.0f} Kč), {sign}{s['pl']:,.0f} Kč "
                 f"({sign}{s['pl_pct']} %), hotovost {s['cash']:,.0f} Kč, obchodů {s['count']}."]
        for p in s["positions"]:
            lines.append(f"- {p['symbol']}: {p['qty']} ks, průměr {p['avg']:,.0f}, teď {p['price']:,.0f} → {'+' if p['pl'] >= 0 else ''}{p['pl']:,.0f} Kč")
        return "\n".join(lines).replace(",", " ")


def of(rt: Any) -> Paper:
    p = getattr(rt, "paper", None)
    if p is None:
        p = Paper(rt)
        rt.paper = p
    return p
