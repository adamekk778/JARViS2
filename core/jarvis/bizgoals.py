"""3.13 Velín firmy: cíle firmy. You set a goal ("tržby 500 000 Kč za měsíc", "odpověď zákazníkovi do 2 hodin") and
the control room shows how it goes – measured by itself from the connected services where it can (shop orders, money
on the bank account, unpaid invoices, the agents' own work), otherwise the agents report the number. Every agent sees
the goals in its brief, so the work leans towards them.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Annotated, Any

from .tools.base import ToolResult, tool

log = logging.getLogger(__name__)
SQL = """
CREATE TABLE IF NOT EXISTS biz_goals (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, metric TEXT DEFAULT '',
  target REAL DEFAULT 0, unit TEXT DEFAULT '', period TEXT DEFAULT 'month', direction TEXT DEFAULT 'up', current REAL,
  updated REAL, note TEXT DEFAULT '', source TEXT DEFAULT '', created REAL);
"""
METRICS: dict[str, dict[str, str]] = {
    "revenue": {"label": "Tržby z e-shopu", "unit": "Kč", "direction": "up", "how": "objednávky z Shoptetu, Shopify a WooCommerce"},
    "orders": {"label": "Počet objednávek", "unit": "ks", "direction": "up", "how": "objednávky z e-shopů"},
    "payments_in": {"label": "Příchozí platby", "unit": "Kč", "direction": "up", "how": "příjmy na účtu (Fio / ABRA Flexi) a Stripe"},
    "unpaid": {"label": "Nezaplacené faktury", "unit": "Kč", "direction": "down", "how": "vydané faktury (Fakturoid / ABRA Flexi)"},
    "saved_hours": {"label": "Čas ušetřený agenty", "unit": "h", "direction": "up", "how": "odhad z práce agentů (bez 👎)"},
    "approved": {"label": "Provedené akce agentů", "unit": "ks", "direction": "up", "how": "schválené a provedené návrhy"},
}
PERIODS = {"week": "týden", "month": "měsíc", "quarter": "kvartál", "year": "rok"}
EVERY = 1800


def _db(rt: Any):
    from .bizagents import _db as base

    db = base(rt)
    if not getattr(db, "_goals_ready", False):
        db.conn.executescript(SQL)
        try:
            db._goals_ready = True
        except AttributeError:
            pass
    return db


def start(period: str, now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return d0 - dt.timedelta(days=d0.weekday())
    if period == "quarter":
        return d0.replace(day=1, month=((d0.month - 1) // 3) * 3 + 1)
    if period == "year":
        return d0.replace(day=1, month=1)
    return d0.replace(day=1)


def end(period: str, now: dt.datetime | None = None) -> dt.datetime:
    s = start(period, now)
    if period == "week":
        return s + dt.timedelta(days=7)
    if period == "year":
        return s.replace(year=s.year + 1)
    months = 3 if period == "quarter" else 1
    m = s.month - 1 + months
    return s.replace(year=s.year + m // 12, month=m % 12 + 1)


def _row(r: dict, now: dt.datetime | None = None) -> dict:
    g = dict(r)
    now = now or dt.datetime.now()
    s, e = start(g["period"], now), end(g["period"], now)
    elapsed = max(0.0, min(1.0, (now - s).total_seconds() / max(1.0, (e - s).total_seconds())))
    cur, target = g.get("current"), float(g.get("target") or 0)
    pct = None
    if cur is not None and target:
        pct = (cur / target * 100) if g["direction"] == "up" else (100.0 if cur <= target else max(0.0, target / cur * 100))
    g.update(period_name=PERIODS.get(g["period"], g["period"]), days_left=max(0, (e.date() - now.date()).days), elapsed=round(elapsed * 100),
             pct=round(pct) if pct is not None else None, auto=bool(g.get("metric")),
             on_track=None if pct is None else (pct >= elapsed * 100 - 5 if g["direction"] == "up" else pct >= 100))
    return g


def goals(rt: Any) -> list[dict]:
    now = dt.datetime.now()
    return [_row(r, now) for r in _db(rt).all("SELECT * FROM biz_goals ORDER BY id")]


def save(rt: Any, g: dict) -> int:
    name = " ".join(str(g.get("name") or "").split())[:80]
    metric = str(g.get("metric") or "")
    if metric and metric not in METRICS:
        raise ValueError("Takové měření neznám.")
    if not name:
        name = METRICS[metric]["label"] if metric else ""
    if not name:
        raise ValueError("Pojmenuj cíl.")
    try:
        target = float(str(g.get("target") or "0").replace(" ", "").replace(",", "."))
    except ValueError:
        raise ValueError("Cíl napiš jako číslo, např. 500000.") from None
    if target <= 0:
        raise ValueError("Cíl musí být větší než 0.")
    period = str(g.get("period") or "month")
    period = period if period in PERIODS else "month"
    unit = str(g.get("unit") or (METRICS[metric]["unit"] if metric else ""))[:12]
    direction = str(g.get("direction") or (METRICS[metric]["direction"] if metric else "up"))
    direction = direction if direction in ("up", "down") else "up"
    db = _db(rt)
    if g.get("id"):
        db.exec("UPDATE biz_goals SET name=?, metric=?, target=?, unit=?, period=?, direction=? WHERE id=?",
                (name, metric, target, unit, period, direction, int(g["id"])))
        return int(g["id"])
    return int(db.exec("INSERT INTO biz_goals (name, metric, target, unit, period, direction, created) VALUES (?,?,?,?,?,?,?)",
                       (name, metric, target, unit, period, direction, time.time())).lastrowid)


def delete(rt: Any, gid: int) -> None:
    _db(rt).exec("DELETE FROM biz_goals WHERE id=?", (int(gid),))


def resolve(rt: Any, ref: str) -> dict | None:
    ref = str(ref or "").strip().lower()
    gs = goals(rt)
    return next((g for g in gs if str(g["id"]) == ref), None) or next((g for g in gs if ref and ref in g["name"].lower()), None)


def report(rt: Any, ref: str, value: float, note: str = "", source: str = "") -> dict:
    """A number for a goal JARVIS cannot measure by itself (an agent or you report it)."""
    g = resolve(rt, ref)
    if not g:
        raise ValueError(f"Cíl „{ref}“ neznám.")
    if g["metric"]:
        raise ValueError(f"Cíl „{g['name']}“ se měří sám ({METRICS[g['metric']]['how']}).")
    _db(rt).exec("UPDATE biz_goals SET current=?, updated=?, note=?, source=? WHERE id=?",
                 (float(value), time.time(), str(note)[:300], source[:60], g["id"]))
    return _row(_db(rt).one("SELECT * FROM biz_goals WHERE id=?", (g["id"],)))


# ---------------------------------------------------------------- measuring (only the services' lists – no AI)
class _Ctx:
    pass


async def _data(name: str, **args: Any) -> Any:
    from . import tools

    if name not in tools.REGISTRY:
        return None
    r = await tools.call(name, args, _Ctx())
    return r.data if r.ok else None


def _sum(items: Any, amount: str = "total", cur: str = "currency", home: str = "CZK") -> float:
    """Money in the home currency (other currencies are left out rather than mixed in)."""
    tot = 0.0
    for x in items if isinstance(items, list) else []:
        if not isinstance(x, dict) or str(x.get(cur) or home).upper() != home:
            continue
        try:
            tot += float(x.get(amount) or 0)
        except (TypeError, ValueError):
            pass
    return tot


async def measure(rt: Any, metric: str, since: dt.datetime) -> float | None:
    from . import connectors

    on = connectors.configured
    days = max(1, (dt.datetime.now() - since).days + 1)
    ts = since.timestamp()
    if metric in ("revenue", "orders"):
        found, tot, n = False, 0.0, 0
        for cid, name in (("shoptet", "shoptet_orders"), ("shopify", "shopify_orders"), ("woocommerce", "woocommerce_orders")):
            if on(cid):
                items = await _data(name, days=days)
                if isinstance(items, list):
                    found = True
                    n += len(items)
                    tot += _sum(items)
        return (round(tot) if metric == "revenue" else float(n)) if found else None
    if metric == "payments_in":
        found, tot = False, 0.0
        if on("fio"):
            d = await _data("fio_account", days=days)
            moves = (d or {}).get("moves") if isinstance(d, dict) else d
            if isinstance(moves, list):
                found = True
                tot += sum(float(m.get("amount") or 0) for m in moves if float(m.get("amount") or 0) > 0
                           and str(m.get("currency") or "CZK").upper() == "CZK")
        elif on("flexi"):
            d = await _data("flexi_bank", days=days)
            if isinstance(d, list):
                found = True
                tot += sum(m["amount"] for m in d if m.get("amount", 0) > 0 and str(m.get("currency") or "CZK").upper() == "CZK")
        if on("stripe"):
            d = await _data("stripe_payments", days=days)
            pays = (d or {}).get("payments") if isinstance(d, dict) else None
            if isinstance(pays, list):
                found = True
                tot += _sum([p for p in pays if p.get("status") == "succeeded"], "amount")
        return round(tot) if found else None
    if metric == "unpaid":
        if on("fakturoid"):
            d = await _data("fakturoid_invoices", status="open")
            if isinstance(d, list):
                return round(_sum(d))
        if on("flexi"):
            d = await _data("flexi_invoices", unpaid=True)
            if isinstance(d, list):
                return round(_sum(d, "left"))
        return None
    from .bizcompany import _db as bdb

    if metric == "saved_hours":
        r = bdb(rt).one("SELECT SUM(saved) AS s FROM biz_runs WHERE started >= ? AND COALESCE(rating,0) >= 0", (ts,))
        return round(float((r or {})["s"] or 0) / 60, 1) if r else 0.0
    if metric == "approved":
        r = bdb(rt).one("SELECT COUNT(*) AS n FROM biz_proposals WHERE status='done' AND decided >= ?", (ts,))
        return float(r["n"] or 0) if r else 0.0
    return None


async def refresh(rt: Any) -> int:
    """Measure every goal that measures itself; returns how many got a number."""
    n = 0
    for g in goals(rt):
        if not g["metric"]:
            continue
        try:
            v = await measure(rt, g["metric"], start(g["period"]))
        except Exception as e:  # noqa: BLE001 – one service down must not stop the others
            log.info("goal %s: %s", g["name"], e)
            continue
        if v is not None:
            _db(rt).exec("UPDATE biz_goals SET current=?, updated=?, source=? WHERE id=?", (v, time.time(), "měřeno", g["id"]))
            n += 1
    return n


def fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "?"
    s = f"{v:,.0f}".replace(",", " ") if abs(v) >= 100 or float(v).is_integer() else f"{v:.1f}".replace(".", ",")
    return f"{s} {unit}".strip()


def context(rt: Any) -> str:
    """The goals for every agent's brief: what the company aims at and how far it is."""
    gs = goals(rt)
    if not gs:
        return ""
    lines = ["CÍLE FIRMY (pracuj tak, aby se k nim firma blížila):"]
    for g in gs:
        st = "" if g["pct"] is None else f" – {g['pct']} %" + ("" if g["on_track"] is None else (", v plánu" if g["on_track"] else ", POZADU"))
        lines.append(f"- {g['name']}: {fmt(g.get('current'), g['unit'])} z {fmt(g['target'], g['unit'])} za {g['period_name']}"
                     f"{' (méně je lépe)' if g['direction'] == 'down' else ''}{st}, zbývá {g['days_left']} dní"
                     f"{'' if g['metric'] else ' [hlásí agenti: company_goal_update]'}")
    return "\n".join(lines)


async def loop(rt: Any) -> None:
    await asyncio.sleep(240)
    while True:
        try:
            if any(g["metric"] for g in goals(rt)) and not rt.cfg.brain.offline_only:
                await refresh(rt)
                from .bizagents import publish

                publish(rt)
        except Exception as e:  # noqa: BLE001
            log.info("goals: %s", e)
        await asyncio.sleep(EVERY)


# ---------------------------------------------------------------- the agents' tools
@tool("company_goals", "Firma: cíle firmy a jak se jim daří (tržby, objednávky, platby, vlastní cíle).", category="propojení", perm="network")
async def company_goals(ctx) -> ToolResult:
    gs = goals(ctx)
    if not gs:
        return ToolResult(True, "Firma zatím nemá nastavené cíle (Velín → Cíle).", data=[])
    return ToolResult(True, context(ctx), data=[{k: g[k] for k in ("id", "name", "current", "target", "unit", "pct", "on_track", "days_left")}
                                                for g in gs])


@tool("company_goal_update", "Firma: zapíše aktuální hodnotu cíle, který se neměří sám (např. průměrná doba odpovědi, počet "
      "nových zákazníků). Jen čísla, která jsi opravdu zjistil.", category="propojení", perm="network")
async def company_goal_update(ctx, goal: Annotated[str, "název cíle (nebo jeho část)"], value: Annotated[float, "aktuální hodnota"],
                              note: Annotated[str, "odkud číslo je (krátce)"] = "") -> ToolResult:
    try:
        g = report(ctx, goal, float(value), note, "agent")
    except ValueError as e:
        return ToolResult(False, str(e))
    try:
        from . import bizcompany

        bizcompany.log_action(ctx, {"id": None, "name": "Cíle"}, "goal", "company_goal_update", f"{g['name']}: {fmt(g['current'], g['unit'])}", True)
    except Exception:  # noqa: BLE001
        pass
    return ToolResult(True, f"Zapsáno: {g['name']} = {fmt(g['current'], g['unit'])} ({g['pct']} % cíle).", data=g)

