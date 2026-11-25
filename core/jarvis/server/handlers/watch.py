"""3.18 Nastavení → Telefon → Spárovat hodinky: a 6-digit code for the JARVIS app on a Wear OS watch."""
from __future__ import annotations

from . import handles


@handles("watch_pair_start", local_only=True)
async def watch_pair_start(c, m: dict) -> None:
    from ... import watchpair

    await c.send("watch_pair", **watchpair.start(c.rt))
