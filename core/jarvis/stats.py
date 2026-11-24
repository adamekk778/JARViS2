"""3.14 Anonymní statistiky (návrh 117) – only if you switch them on (Nastavení → Bezpečí a soukromí; off by default).

What goes out, once a week – and you can see exactly that before switching it on ("Ukázat, co by se poslalo"):
- the JARVIS version, Windows / Android / other, the UI language
- how many times each BUILT-IN tool was used and how often it failed (never your own skills, never arguments)
- the median time to the first word per kind of AI (groq, gemini, claude… – never a key or a model answer)
- the voice delay, the number of errors in the log, how many days JARVIS ran that week
- a random install number that changes every month (so one PC is not counted twice in a week, and nothing can follow
  it for longer)

Never: what you said or wrote, names, files, e-mails, places, keys, IP-based anything (the address is not stored).
Where it goes: `privacy.stats_url` – an HTTPS address the author runs (packaging/stats-worker). Empty = nothing is sent
even when the switch is on, so the switch alone can never leak anything.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)
EVERY_S = 7 * 86400
FORMAT = 1


def _kv(rt: Any, k: str) -> str:
    rt.db.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    r = rt.db.one("SELECT v FROM kv WHERE k=?", (k,))
    return str(r["v"]) if r else ""


def _set(rt: Any, k: str, v: str) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, v))


def install_id(rt: Any, now: float | None = None) -> str:
    """Random, and a new one every calendar month."""
    month = time.strftime("%Y-%m", time.gmtime(now or time.time()))
    raw = _kv(rt, "stats_id")
    if raw.startswith(month + ":"):
        return raw.split(":", 1)[1]
    new = uuid.uuid4().hex
    _set(rt, "stats_id", f"{month}:{new}")
    return new


def _os() -> str:
    s = platform.system().lower()
    return "windows" if s.startswith("win") else "android" if "android" in platform.platform().lower() else s or "other"


def builtin_tools() -> set[str]:
    from . import tools

    return {n for n, s in tools.REGISTRY.items() if str(s.source or "").startswith("jarvis.tools")}


def payload(rt: Any, days: int = 7) -> dict:
    from . import quality

    builtin = builtin_tools()
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    rows = quality._db(rt).all("SELECT tool, SUM(calls) c, SUM(fails) f, COUNT(DISTINCT day) d FROM tool_stats "
                               "WHERE day >= ? GROUP BY tool", (since,))
    tools_ = {r["tool"]: {"calls": int(r["c"] or 0), "fails": int(r["f"] or 0)} for r in rows if r["tool"] in builtin}
    days_on = quality._db(rt).one("SELECT COUNT(DISTINCT day) n FROM tool_stats WHERE day >= ?", (since,))
    presets = {p.id: getattr(p, "preset", "") or "custom" for p in rt.cfg.brain.providers}
    ai = [{"kind": presets.get(m["provider"], "custom"), "median_ms": m["median_ms"], "answers": m["answers"]}
          for m in quality.model_latency(rt)]
    voice = quality.voice_latency(rt) or {}
    return {"format": FORMAT, "id": install_id(rt), "version": quality._version(), "os": _os(),
            "lang": getattr(rt.cfg.general, "language", "cs"), "days_on": int((days_on or {}).get("n") or 0),
            "tools": tools_, "ai": ai, "voice_median_ms": voice.get("median_ms"), "errors": quality.crashes(days)}


def due(rt: Any, now: float | None = None) -> bool:
    p = rt.cfg.privacy
    if not getattr(p, "share_stats", False) or not str(getattr(p, "stats_url", "") or "").startswith("https://"):
        return False
    last = float(_kv(rt, "stats_sent") or 0)
    return (now or time.time()) - last >= EVERY_S


async def send(rt: Any, client: Any = None) -> bool:
    """One weekly report. True = accepted by the server."""
    import httpx

    data = await asyncio.to_thread(payload, rt)
    url = rt.cfg.privacy.stats_url
    own = client is None
    c = client or (rt.http() if hasattr(rt, "http") else httpx.AsyncClient(timeout=20))
    try:
        r = await c.post(url, json=data, headers={"User-Agent": "JARVIS-stats"})
        ok = 200 <= r.status_code < 300
    except httpx.HTTPError as e:
        log.info("stats: %s", e)
        ok = False
    finally:
        if own:
            await c.aclose()
    if ok:
        _set(rt, "stats_sent", str(time.time()))
    return ok


async def weekly(rt: Any) -> None:
    await asyncio.sleep(900)
    while True:
        try:
            if due(rt):
                await send(rt)
        except Exception as e:  # noqa: BLE001 – statistics must never disturb anything
            log.info("stats: %s", e)
        await asyncio.sleep(6 * 3600)
