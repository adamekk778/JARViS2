"""3.15 Mega animace: each window reports its frame rate and effects tier (Diagnostika shows them)."""
from __future__ import annotations

import time

from . import handles

PAGES = {"dashboard", "notch", "mobile", "fullchat", "hud", "karaoke", "overlay", "wallpaper"}
TIERS = {"ultra", "high", "eco", "off"}


@handles("fx_report")
async def fx_report(c, m: dict) -> None:
    page = str(m.get("page") or "")
    if page not in PAGES:
        return
    try:
        fps = max(0, min(int(m.get("fps") or 0), 500))
    except (TypeError, ValueError):
        return
    tier = str(m.get("tier") or "")
    fx = getattr(c.rt, "_fx", None)
    if fx is None:
        fx = c.rt._fx = {}
    fx[page] = {"fps": fps, "tier": tier if tier in TIERS else "", "t": time.time()}
