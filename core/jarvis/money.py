"""3.19 Peníze (návrhy 1, 10, 11): the same rules for every step that moves money, today's ČNB rates for the limits,
and one overview of what goes out.

- Kurzy: the limits and the monthly budget count in CZK with today's ČNB rate (fetched at most every 6 hours, the last
  one kept on this PC for when the internet is down); only without any rate a rough estimate is used – and said so.
- Potvrzení: what the confirmation of a payment says comes from JARVIS' own data (the offer it found, the element's
  real text, the payment it looked up), never from the AI's words.
- Přehled: AI spending, trips, subscriptions and the money steps you approved – one place, with the monthly budget.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("jarvis.money")

FALLBACK = {"CZK": 1.0, "EUR": 25.0, "USD": 23.0, "GBP": 29.5, "PLN": 5.8, "CHF": 26.0, "HUF": 0.064}
MAX_AGE_S = 6 * 3600                 # fetch again after this
STALE_S = 10 * 86400                 # an older kept rate is still better than the estimate, but it is said
LOG_SQL = "CREATE TABLE IF NOT EXISTS money_log (ts REAL, kind TEXT, what TEXT, amount REAL, currency TEXT, approved INTEGER)"
_state: dict[str, Any] = {"rates": {}, "ts": 0.0, "date": "", "source": "odhad"}


# ------------------------------------------------------------------------------------------ ČNB rates
def _parse(text: str) -> tuple[dict[str, float], str]:
    from .finance import parse_cnb

    first = (text.splitlines() or [""])[0]
    day = first.split("#")[0].strip()
    try:
        date = dt.datetime.strptime(day, "%d.%m.%Y").date().isoformat()
    except ValueError:
        date = ""
    return parse_cnb(text), date


def _kept(rt: Any) -> dict | None:
    try:
        row = rt.db.one("SELECT v FROM kv WHERE k='cnb_rates'")
        return json.loads(row["v"]) if row else None
    except Exception:  # noqa: BLE001
        return None


def _use(rates: dict, ts: float, date: str, source: str) -> None:
    _state.update(rates=dict(rates), ts=ts, date=date, source=source)
    from . import finance

    finance._cnb = (ts, dict(rates))                 # "kolik je 50 eur" uses the same rate


def reset() -> None:
    """Forget the rates in memory (tests; a new day)."""
    _state.update(rates={}, ts=0.0, date="", source="odhad")
    from . import finance

    finance._cnb = (0.0, {})


async def ensure_rates(rt: Any, transport: Any = None) -> dict[str, float]:
    """Today's ČNB rates (CZK for 1 unit); the kept ones when ČNB cannot be reached; {} when there are none at all."""
    if _state["rates"] and time.time() - _state["ts"] < MAX_AGE_S:
        return _state["rates"]
    tr = transport or getattr(rt, "transport", None)
    if not (os.environ.get("JARVIS_NO_NET") and tr is None):
        try:
            import httpx

            from . import tlsctx
            from .finance import CNB_URL

            async with httpx.AsyncClient(transport=tr, verify=tlsctx.context(), follow_redirects=True, timeout=8) as c:
                r = await c.get(CNB_URL)
            r.raise_for_status()
            rates, date = _parse(r.text)
            if len(rates) > 5:
                now = time.time()
                _use(rates, now, date, "ČNB")
                try:
                    rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('cnb_rates', ?)",
                               (json.dumps({"rates": rates, "ts": now, "date": date}),))
                except Exception as e:  # noqa: BLE001
                    log.debug("keep rates: %s", e)
                return rates
        except Exception as e:  # noqa: BLE001
            log.debug("ČNB: %s", e)
    k = _kept(rt)
    if k and k.get("rates") and float(k.get("ts") or 0) > _state["ts"]:
        _use(k["rates"], float(k["ts"]), str(k.get("date") or ""), "ČNB (uložený)")
    return _state["rates"]


def _fresh() -> dict[str, float]:
    return _state["rates"] if _state["rates"] and time.time() - _state["ts"] < STALE_S else {}


def to_czk(amount: float, currency: str) -> float:
    """CZK value of an amount: today's (or the last kept) ČNB rate; a rough estimate only without any."""
    cur = (currency or "CZK").upper()
    rate = _fresh().get(cur) or FALLBACK.get(cur, 25.0)
    return round(float(amount) * rate, 0)


def rate_note() -> str:
    """For the confirmation and the overview: which rate the CZK figures use."""
    if _fresh():
        d = _state["date"]
        when = f" z {int(d[8:10])}. {int(d[5:7])}." if len(d) == 10 else ""
        return f"kurz ČNB{when}" + (" (uložený – ČNB teď nedostupná)" if _state["source"] != "ČNB" else "")
    return "odhad kurzu (kurz ČNB se nepodařilo stáhnout)"


# ------------------------------------------------------------------------------------------ what a money confirmation says
def confirm_text(rt: Any, name: str, args: dict) -> str:
    """The text of a money confirmation (the phone shows only this) from JARVIS' own data; '' = use the usual one."""
    if name in ("travel_book", "booking_cancel"):
        from . import booking

        return booking.confirm_text(rt, name, args)
    if name == "stripe_refund":
        amt = args.get("amount")
        return (f"Vrátit peníze (Stripe): {'celou platbu' if not amt else f'{float(amt):g}'} – platba "
                f"{str(args.get('payment_id', ''))[:40]}")
    if name == "browser_click":
        from .tools.browser import SESSION

        el = SESSION.element_of(args.get("index"))
        if el:
            host = el[1].split("/")[2] if el[1].count("/") >= 2 else ""
            return f"Kliknout na „{el[0][:80]}“" + (f" na {host}" if host else "") + " – může to zaplatit nebo objednat"
        return ""
    if name == "money_action":
        return f"Nákup / platba: {str(args.get('text', ''))[:200]}"
    return ""


# ------------------------------------------------------------------------------------------ one overview
def log_step(rt: Any, kind: str, what: str, amount: float = 0.0, currency: str = "CZK", approved: bool = True) -> None:
    """A money step you were asked about (and your answer) – for the overview."""
    try:
        rt.db.exec(LOG_SQL)
        rt.db.exec("INSERT INTO money_log VALUES (?,?,?,?,?,?)", (time.time(), kind, what[:200], float(amount or 0),
                                                                 (currency or "CZK").upper(), int(bool(approved))))
        rt.db.exec("DELETE FROM money_log WHERE ts < ?", (time.time() - 400 * 86400,))
    except Exception as e:  # noqa: BLE001
        log.debug("money log: %s", e)


def amount_of(name: str, args: dict) -> tuple[float, str]:
    """The amount a money step names (0 when it does not say)."""
    try:
        if name == "travel_book":
            return float(args.get("expected_total") or 0), str(args.get("currency") or "CZK")
        if name == "stripe_refund":
            return float(args.get("amount") or 0), "CZK"
    except (TypeError, ValueError):
        pass
    return 0.0, "CZK"


def overview(rt: Any, now: float | None = None) -> dict:
    """This month: AI, trips, subscriptions and approved money steps; the budget and how much of it is used."""
    now = now or time.time()
    t = time.localtime(now)
    since = time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    parts: list[dict] = []
    try:
        from . import booking

        rows = booking._db(rt).all("SELECT name, total, currency FROM bookings WHERE created >= ? AND status != 'cancelled' "
                                   "AND sandbox = 0", (since,))
        parts.append({"key": "trips", "label": "Cesty", "czk": round(sum(to_czk(r["total"], r["currency"]) for r in rows)),
                      "count": len(rows)})
    except Exception as e:  # noqa: BLE001
        log.debug("overview trips: %s", e)
    try:
        usage = getattr(rt, "usage", None)
        if usage is not None:
            ai_rows = rt.db.all("SELECT * FROM llm_usage WHERE day >= ?", (time.strftime("%Y-%m-01", t),))
            cost = float(usage.cost(ai_rows))
            cur = str(getattr(rt.cfg.limits, "currency", "Kč") or "Kč")
            czk = cost if cur.upper() in ("KČ", "KC", "CZK") else to_czk(cost, "USD" if cur in ("$", "USD") else cur)
            parts.append({"key": "ai", "label": "AI (Claude a další)", "czk": round(czk),
                          "count": sum(int(r["calls"]) for r in ai_rows)})
    except Exception as e:  # noqa: BLE001
        log.debug("overview ai: %s", e)
    try:
        row = rt.db.one("SELECT v FROM kv WHERE k='subs_monthly'")      # from the last "přehled předplatných"
        if row:
            subs = json.loads(row["v"])
            parts.append({"key": "subs", "label": "Předplatné", "czk": round(float(subs.get("monthly_czk") or 0)),
                          "count": int(subs.get("count") or 0), "checked": subs.get("ts")})
    except Exception as e:  # noqa: BLE001
        log.debug("overview subs: %s", e)
    try:
        rt.db.exec(LOG_SQL)
        steps = rt.db.all("SELECT * FROM money_log WHERE ts >= ? ORDER BY ts DESC", (since,))
    except Exception:  # noqa: BLE001
        steps = []
    other = sum(to_czk(s["amount"], s["currency"]) for s in steps
                if s["approved"] and s["kind"] not in ("travel_book", "booking_cancel"))
    if other:
        parts.append({"key": "other", "label": "Další platby přes JARVISe", "czk": round(other), "count": 0})
    budget = float(getattr(getattr(rt.cfg, "booking", None), "monthly_budget", 0) or 0)
    return {"month": time.strftime("%Y-%m", t), "parts": parts, "total_czk": round(sum(p["czk"] for p in parts)),
            "trip_budget_czk": budget, "rate": rate_note(),
            "steps": [{"ts": s["ts"], "kind": s["kind"], "what": s["what"], "amount": s["amount"], "currency": s["currency"],
                       "approved": bool(s["approved"])} for s in steps[:30]]}
