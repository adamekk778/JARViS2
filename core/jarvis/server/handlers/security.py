"""3.14 Bezpečnost (návrhy 107, 109): what JARVIS saw and heard; the guest mode switch."""
from __future__ import annotations

from ... import shield
from . import handles


@handles("access_log_get")
async def access_log_get(c, m: dict) -> None:
    await c.send("access_log", **shield.recent(c.rt, max(1, min(int(m.get("days", 1) or 1), 30))),
                 guest=shield.guest_on(c.rt))


@handles("stats_preview_get")
async def stats_preview_get(c, m: dict) -> None:
    """3.14 návrh 117: exactly what the weekly anonymous statistics would send."""
    import asyncio

    from ... import stats

    data = await asyncio.to_thread(stats.payload, c.rt)
    await c.send("stats_preview", data=data, on=bool(c.rt.cfg.privacy.share_stats), url=c.rt.cfg.privacy.stats_url)
