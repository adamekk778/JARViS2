"""3.12 Údržba sama od sebe: what used to be found only when something did not work.

- After every update (the first start of a new version) Kontrola funkcí runs by itself and, if something does not
  work (an AI key, "Jen offline", the network for the phone…), a notice says what and where to fix it.
- Once a day the AI keys are tried quietly; a key that stopped working (or a service that switched its model off)
  is reported – never a limit or a busy moment, those pass by themselves.
- A one-click summary for help: version, what works, the AIs and services (never a key), the last log lines
  (passwords and keys removed) – to paste into a chat.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import time
from typing import Any

log = logging.getLogger(__name__)
QUIET = {"loopback", "phone", "ollama"}         # fine to be "off" on many PCs: never a reason for a notice


def _kv(rt: Any, k: str) -> str:
    rt.db.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    r = rt.db.one("SELECT v FROM kv WHERE k=?", (k,))
    return str(r["v"]) if r else ""


def _set(rt: Any, k: str, v: str) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, v))


def problems(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("ok") is False and i.get("key") not in QUIET]


async def after_update(rt: Any, delay: float = 75.0) -> list[dict] | None:
    """First start of a new version: Kontrola funkcí by itself; a notice when something does not work."""
    from . import __version__, brainkey, selfcheck

    if _kv(rt, "selfcheck_version") == __version__:
        return None
    await asyncio.sleep(delay)                      # the voice, the notch and the media watcher are up by now
    items = await selfcheck.run(rt, lambda pid: brainkey.provider_test(rt, pid))
    _set(rt, "selfcheck_version", __version__)
    _set(rt, "selfcheck_last", __import__("json").dumps(items, ensure_ascii=False)[:20000])
    rt.bus.publish("selfcheck", running=False, items=items)
    bad = problems(items)
    if bad:
        rt.notify(f"Po aktualizaci: {len(bad)} {'věc nejde' if len(bad) == 1 else 'věci nejdou' if len(bad) < 5 else 'věcí nejde'}",
                  " · ".join(f"{i['name']}: {i['detail'][:70]}" for i in bad[:3]) + " – víc v Diagnostika → Kontrola funkcí.",
                  speak=False)
    return bad


async def check_keys(rt: Any) -> list[dict]:
    """Every cloud AI with a key, tried once; the ones whose key or model really stopped working."""
    from . import brainkey
    from .llm import quota

    items = [i for i in quota.overview(rt) if i["enabled"] and i["key"] and not i["local"]]
    broken = []
    for it in items:
        r = await brainkey.provider_test(rt, it["id"])
        if r.get("ok"):
            continue
        ok, msg = brainkey.explain(str(r.get("message", "")))
        if not ok:                                   # a limit / a busy model is ok=True: those pass by themselves
            broken.append({"id": it["id"], "label": it["label"], "message": msg})
    return broken


async def keys_daily(rt: Any) -> None:
    await asyncio.sleep(600)
    while True:
        try:
            last = float(_kv(rt, "keys_checked") or 0)
            if time.time() - last > 22 * 3600 and not rt.cfg.brain.offline_only:
                _set(rt, "keys_checked", str(time.time()))
                broken = await check_keys(rt)
                if broken:
                    rt.notify("AI klíč přestal fungovat", " · ".join(f"{b['label']}: {b['message'][:90]}" for b in broken[:3])
                              + " – Nastavení → Mozek.", speak=False)
        except Exception as e:  # noqa: BLE001
            log.info("daily key check: %s", e)
        await asyncio.sleep(3600)


def summary(rt: Any) -> str:
    """A text to paste when asking for help: what is set and what works – never a key, password or token."""
    import json

    from . import __version__, connectors
    from .llm import quota
    from .redact import redact

    lines = [f"JARVIS {__version__} · {platform.system()} {platform.release()} · Python {platform.python_version()}"]
    c = rt.cfg
    lines.append(f"Jen offline: {'ANO' if c.brain.offline_only else 'ne'} · texty písní: {'ano' if getattr(c.notch, 'lyrics', True) else 'NE'}"
                 f" · notch: {c.notch.style} · pořadí AI: {', '.join(c.brain.chain)}")
    try:
        for i in quota.overview(rt):
            lines.append(f"  AI {i['id']} ({i['preset']}, model {i.get('model') or '?'}): {'zapnutá' if i['enabled'] else 'vypnutá'}, "
                         f"klíč {'ano' if i['key'] else 'NE'}{', limit' if i.get('limited_s') else ''}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"  AI: {e}")
    try:
        on = [x["name"] for x in connectors.status() if x["connected"]]
        lines.append(f"Propojení: {', '.join(on) or 'žádné'}")
    except Exception:  # noqa: BLE001
        pass
    try:
        items = json.loads(_kv(rt, "selfcheck_last") or "[]")
        if items:
            lines.append("Poslední Kontrola funkcí:")
            lines += [f"  {'OK ' if i.get('ok') else 'CHYBA' if i.get('ok') is False else '–  '} {i.get('name')}: {i.get('detail', '')[:140]}" for i in items]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .diagnostics import _log_tail

        tail = [ln for ln in _log_tail() if " WARNING " in ln or " ERROR " in ln][-25:]
        if tail:
            lines.append("Poslední varování z logu:")
            lines += [f"  {ln[:220]}" for ln in tail]
    except Exception:  # noqa: BLE001
        pass
    return redact("\n".join(lines))
