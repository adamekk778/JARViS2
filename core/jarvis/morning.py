"""3.12 Ranní souhrn do telefonu: at the time you choose (Více → Telefon in the phone app), the morning briefing –
weather, calendar, e-mail, today's plan – plus what happened on the PC overnight, as a notice on the phone with
"Přehrát" (JARVIS's voice; with headphones on it can play by itself). Off until you switch it on.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from typing import Any

log = logging.getLogger("jarvis.morning")
WINDOW_H = 3          # the phone was off at the time: still try for 3 hours, then skip that day


def _hhmm(s: str) -> tuple[int, int]:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return 7, 0
    return int(m.group(1)), int(m.group(2))


def overnight(rt: Any, now: float | None = None) -> list[str]:
    """What happened on the PC since yesterday evening, in a few short sentences."""
    now = now if now is not None else time.time()
    since = now - 12 * 3600
    out = []
    health = getattr(rt, "health", None)
    if health is not None:
        alerts = [a for a in health.alerts if a.get("t", 0) >= since]
        if alerts:
            out.append("Na PC přes noc: " + "; ".join(dict.fromkeys(a["title"] for a in alerts[:3])) + ".")
    guard = getattr(rt, "guard", None)
    if guard is not None:
        evs = [e for e in guard.events if e.get("t", 0) >= since]
        if evs:
            out.append(f"Pozor: hlídané PC někdo {'odemkl' if evs[0]['kind'] == 'unlock' else 'použil'} v "
                       f"{time.strftime('%H:%M', time.localtime(evs[0]['t']))}.")
    pb = getattr(rt, "photo_backup", None)
    if pb is not None and float(pb.stats.get("last", 0) or 0) >= since:
        out.append(f"Záloha fotek z telefonu proběhla, na PC je celkem {pb.stats.get('count', 0)} fotek a videí.")
    return out


async def build(rt: Any) -> dict:
    from .stark import briefing

    b = await briefing(rt)
    text = " ".join([b["text"], *overnight(rt)])
    return {"title": "Ranní souhrn", "text": text}


def due(rt: Any, now: dt.datetime | None = None) -> bool:
    cfg = rt.cfg.phone_link
    if not getattr(cfg, "morning", False):
        return False
    now = now or dt.datetime.now()
    h, m = _hhmm(cfg.morning_time)
    start = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if not start <= now < start + dt.timedelta(hours=WINDOW_H):
        return False
    row = rt.db.one("SELECT v FROM kv WHERE k='phone_morning_day'")
    return not (row and row["v"] == now.date().isoformat())


async def send(rt: Any, test: bool = False) -> bool:
    """Build it and hand it to the phone; True when the phone's link took it."""
    s = await build(rt)
    ok = rt.phone_push("morning", title=s["title"], text=s["text"][:1500],
                       autoplay=bool(getattr(rt.cfg.phone_link, "morning_autoplay", False)) and not test)
    if ok and not test:
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('phone_morning_day', ?)", (dt.date.today().isoformat(),))
    return ok


async def loop(rt: Any) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            if due(rt):
                await send(rt)
        except Exception as e:  # noqa: BLE001 – try again next minute
            log.debug("morning: %s", e)
