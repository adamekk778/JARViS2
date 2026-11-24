"""3.14 Karaoke: the page asks for the song and its lyrics as they are now (also from a TV / tablet on the home network)."""
from __future__ import annotations

from . import handles


@handles("lyrics_get")
async def lyrics_get(c, m: dict) -> None:
    rt = c.rt
    if rt.media_state:
        await c.send("media", **rt.media_state)
    st = getattr(rt, "lyrics_state", {}) or {}
    if st:
        await c.send("lyrics", **st)
