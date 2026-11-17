"""3.12 Velín firmy: agents that react to what happens, not only to the clock.

Every few minutes JARVIS looks – without any AI, only the services' own lists – for what is new: an e-mail (Gmail,
Outlook), an order (Shopify, WooCommerce), an incoming payment (Fio, Stripe). Each new thing is handed to the agents
that subscribed to it ("Spouštět při: novém e-mailu"), as their next job, with what happened in it. The first look at
a service only remembers what is there already: old mail does not start a hundred runs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from . import connectors, tools

log = logging.getLogger(__name__)
EVENTS: dict[str, dict[str, Any]] = {
    "mail": {"label": "nový e-mail", "icon": "envelope-simple"},
    "order": {"label": "nová objednávka", "icon": "shopping-bag"},
    "payment": {"label": "nová příchozí platba", "icon": "bank"},
}
EVERY = 180                     # seconds between two looks
KEEP = 600                      # remembered ids per event


class _Ctx:                     # the tools read connectors only; no runtime needed for these lookups
    pass


async def _call(name: str, **args) -> list[dict]:
    if name not in tools.REGISTRY:
        return []
    r = await tools.call(name, args, _Ctx())
    data = r.data if r.ok else None
    if isinstance(data, dict):
        data = data.get("moves") or data.get("payments") or data.get("items") or []
    return data if isinstance(data, list) else []


async def _mail() -> list[tuple[str, str]]:
    out = []
    if connectors.configured("google"):
        for m in await _call("google_gmail_search", query="is:unread newer_than:1d in:inbox", limit=20):
            out.append((f"g:{m.get('id')}", f"E-mail od {m.get('from', '?')}: „{m.get('subject', '')}“ (Gmail id {m.get('id')})"))
    if connectors.configured("microsoft"):
        for m in await _call("outlook_mail_search", unread=True, limit=20):
            out.append((f"o:{m.get('id')}", f"E-mail od {m.get('from', '?')}: „{m.get('subject', '')}“ (Outlook id {m.get('id')})"))
    return out


async def _order() -> list[tuple[str, str]]:
    out = []
    if connectors.configured("shopify"):
        for o in await _call("shopify_orders", days=2):
            out.append((f"s:{o.get('order')}", f"Objednávka {o.get('order')} (Shopify): {o.get('total')} {o.get('currency') or ''}, "
                        f"{o.get('customer') or 'zákazník'} – {', '.join(o.get('items') or [])[:200]}"))
    if connectors.configured("woocommerce"):
        for o in await _call("woocommerce_orders", days=2):
            out.append((f"w:{o.get('number')}", f"Objednávka {o.get('number')} (WooCommerce): {o.get('total')} {o.get('currency') or ''}, "
                        f"{o.get('customer') or 'zákazník'}, stav {o.get('status')}"))
    return out


async def _payment() -> list[tuple[str, str]]:
    out = []
    if connectors.configured("fio"):
        for m in await _call("fio_account", days=3):
            try:
                amount = float(m.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            if amount > 0 and m.get("id"):
                out.append((f"f:{m.get('id')}", f"Příchozí platba {amount:,.2f} {m.get('currency', '')} od {m.get('account_name') or m.get('account') or '?'}"
                            f"{', VS ' + str(m['vs']) if m.get('vs') else ''}{', zpráva: ' + str(m['message']) if m.get('message') else ''}"))
    if connectors.configured("stripe"):
        for p in await _call("stripe_payments", days=2):
            if p.get("status") == "succeeded":
                out.append((f"st:{p.get('id')}", f"Platba Stripe {p.get('amount')} {p.get('currency')} od {p.get('customer') or '?'} ({p.get('id')})"))
    return out


PROBES: dict[str, Callable[[], Awaitable[list[tuple[str, str]]]]] = {"mail": _mail, "order": _order, "payment": _payment}


def _seen(rt: Any, ev: str) -> list[str] | None:
    from .bizcompany import _kv

    raw = _kv(rt, f"biz_seen_{ev}", "")
    if not raw:
        return None
    try:
        return list(json.loads(raw))
    except ValueError:
        return None


def _remember(rt: Any, ev: str, ids: list[str]) -> None:
    from .bizcompany import _set

    _set(rt, f"biz_seen_{ev}", json.dumps(ids[-KEEP:]))


def subscribers(rt: Any, ev: str) -> list[dict]:
    from .bizagents import agents

    return [a for a in agents(rt) if a.get("enabled") and ev in (a.get("triggers") or [])]


async def check(rt: Any) -> dict[str, int]:
    """One look at every event someone listens to; new things become jobs. Returns how many new things per event."""
    from . import bizcompany
    from .bizagents import enqueue

    found: dict[str, int] = {}
    for ev, probe in PROBES.items():
        subs = subscribers(rt, ev)
        if not subs:
            continue
        try:
            items = await probe()
        except Exception as e:  # noqa: BLE001 – a service down must not stop the others
            log.info("event %s: %s", ev, e)
            continue
        seen = _seen(rt, ev)
        ids = [i for i, _ in items]
        if seen is None:                         # the first look: remember, do not fire
            _remember(rt, ev, ids)
            found[ev] = 0
            continue
        new = [(i, text) for i, text in items if i not in seen]
        found[ev] = len(new)
        if not new:
            continue
        _remember(rt, ev, seen + [i for i, _ in new])
        news = "\n".join(f"- {t}" for _, t in new[:10]) + (f"\n- …a dalších {len(new) - 10}" if len(new) > 10 else "")
        for a in subs:
            if enqueue(rt, a["id"], f"UDÁLOST ({EVENTS[ev]['label']}):\n{news}\nZpracuj to podle své role.", 0, ev):
                bizcompany.log_action(rt, a, "event", "", f"{EVENTS[ev]['label']}: {len(new)}×", True)
    return found


async def loop(rt: Any) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            from . import bizcompany

            if not bizcompany.paused(rt) and not rt.cfg.brain.offline_only:
                await check(rt)
        except Exception as e:  # noqa: BLE001
            log.warning("biz events: %s", e)
        await asyncio.sleep(EVERY)
