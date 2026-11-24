"""3.15 Dílna a gesta: the HUD says when it is on screen (then the camera's hand gestures steer the HUD instead of the
music), the gestures themselves, and the 3D printer's state for the HUD's workshop panel."""
from __future__ import annotations

import time

from . import handles

GESTURES = {"left", "right", "up", "down", "wave"}


@handles("hud_presence")
async def hud_presence(c, m: dict) -> None:
    on = bool(m.get("visible"))
    rt = c.rt
    rt.hud_on_screen = time.time() if on else 0.0
    rt.bus.publish("hud_presence", on=on)


@handles("hud_gesture")
async def hud_gesture(c, m: dict) -> None:
    g = str(m.get("g") or "")
    if g in GESTURES:
        c.rt.bus.publish("hud_cmd", action="gesture", gesture=g)


@handles("printer_get")
async def printer_get(c, m: dict) -> None:
    from ... import printer3d

    rt = c.rt
    if not printer3d.configured(rt):
        await c.send("printer", state="off", name="")
        return
    w = getattr(rt, "printer_watch", None)
    s = w.last if w and w.last else await printer3d.status(rt)
    await c.send("printer", **s, name=rt.cfg.workshop.printer_name)
