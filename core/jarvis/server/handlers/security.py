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


# ---------- 3.14 other PCs (nodes): the pairing key goes to the keyring, never into the settings ----------
@handles("node_add", local_only=True)
async def node_add(c, m: dict) -> None:
    from ... import nodes

    try:
        nodes.add(c.rt, str(m.get("name", "")), str(m.get("url", "")), str(m.get("token", "")), str(m.get("mac", "")))
    except ValueError as e:
        await c.send("error", message=str(e))


@handles("node_remove", local_only=True)
async def node_remove(c, m: dict) -> None:
    from ... import nodes

    nodes.remove(c.rt, str(m.get("name", "")))


@handles("emergency")
async def emergency_start(c, m: dict) -> None:
    """3.14 the SOS button on the phone (with its position, when the phone shared it)."""
    from ... import safety

    where = ""
    lat, lon = m.get("lat"), m.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        where = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
    r = await safety.emergency(c.rt).start(str(m.get("reason") or "SOS z telefonu")[:120], where, wait=20)
    await c.send("notify", title="SOS", body=r["message"], url="", target="mobile")


@handles("emergency_cancel")
async def emergency_cancel(c, m: dict) -> None:
    from ... import safety

    safety.emergency(c.rt).cancel()
