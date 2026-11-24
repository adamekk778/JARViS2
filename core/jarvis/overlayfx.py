"""3.15 Mega animace na ploše (návrhy 5, 36, 37, 38): what the see-through effects window over the desktop shows.

- čtení obrazovky: a scan beam sweeps the screen when JARVIS takes a screenshot for a task (at most every 20 s),
- klikání: a target reticle and a ripple where JARVIS clicks, a trail while he moves the mouse,
- hlasitost / jas / hudba: a round HUD display when JARVIS changes them,
- odemčení PC: "Vítejte zpět, pane" (at most every 10 minutes).
Only while JARVIS works on something (his own clicks, never yours) and only with Vzhled → Efekty na ploše on.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger("jarvis.overlayfx")

SCAN_EVERY_S = 20.0
WELCOME_EVERY_S = 10 * 60
UNLOCK_POLL_S = 2.0
OSD_TOOLS = {"volume": "volume", "set_volume": "volume", "brightness": "brightness", "set_brightness": "brightness",
             "media_control": "media"}


def enabled(rt: Any) -> bool:
    return bool(getattr(rt.cfg.appearance, "desktop_fx", True))


def emit(rt: Any, kind: str, **data: Any) -> bool:
    if not enabled(rt):
        return False
    rt.bus.publish_threadsafe("overlay_fx", kind=kind, **data)
    show = getattr(rt, "on_overlay_fx", None)              # the PC app draws it (native click-through windows)
    if show is not None:
        try:
            show(kind, data)
        except Exception as e:  # noqa: BLE001
            log.debug("overlay fx: %s", e)
    return True


class Hooks:
    """Wraps the platform's click / move / screenshot so the overlay sees what JARVIS does."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.last_scan = 0.0

    def working(self) -> bool:
        return bool(getattr(getattr(self.rt, "agent", None), "busy", False))

    def install(self) -> bool:
        p = self.rt.platform
        if getattr(p, "_fx_hooked", False):
            return False
        click, move, shot = getattr(p, "click", None), getattr(p, "move", None), getattr(p, "screenshot", None)

        if click:
            def fx_click(x: Any, y: Any, *a: Any, **k: Any) -> Any:
                if self.working():
                    emit(self.rt, "click", x=int(x), y=int(y))
                return click(x, y, *a, **k)
            p.click = fx_click
        if move:
            def fx_move(x: Any, y: Any, *a: Any, **k: Any) -> Any:
                if self.working():
                    emit(self.rt, "move", x=int(x), y=int(y))
                return move(x, y, *a, **k)
            p.move = fx_move
        if shot:
            def fx_shot(*a: Any, **k: Any) -> Any:
                now = time.monotonic()
                if self.working() and now - self.last_scan >= SCAN_EVERY_S:
                    self.last_scan = now
                    emit(self.rt, "scan")
                return shot(*a, **k)
            p.screenshot = fx_shot
        p._fx_hooked = True
        return True


def after_tool(rt: Any, name: str, args: dict, ok: bool, data: Any, summary: str = "") -> bool:
    """A volume / brightness / media change by JARVIS → the round display on the desktop."""
    what = OSD_TOOLS.get(name)
    if not what or not ok:
        return False
    value = None
    if isinstance(data, (int, float)):
        value = float(data)
    elif isinstance(data, dict):
        for k in ("level", "volume", "value", "brightness"):
            if isinstance(data.get(k), (int, float)):
                value = float(data[k])
                break
    text = summary if what == "media" else ""
    return emit(rt, "osd", what=what, value=value, text=str(text)[:80])


class UnlockWatch:
    """Locked → unlocked: "Vítejte zpět" on the desktop."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.was_locked: bool | None = None
        self.last = 0.0

    def step(self, locked: bool | None, now: float) -> bool:
        if locked is None:
            return False
        greet = self.was_locked is True and not locked and now - self.last >= WELCOME_EVERY_S
        self.was_locked = locked
        if greet:
            self.last = now
            a = (getattr(self.rt.cfg.general, "address_as", "") or "pane").strip()
            return emit(self.rt, "welcome", text=f"Vítejte zpět, {a}")
        return False

    async def run(self) -> None:
        from .guard import is_locked

        while True:
            try:
                self.step(await asyncio.to_thread(is_locked), time.time())
            except Exception as e:  # noqa: BLE001
                log.debug("unlock watch: %s", e)
            await asyncio.sleep(UNLOCK_POLL_S)


def start(rt: Any) -> list:
    """Hooks + the unlock watch (called once at start-up)."""
    try:
        Hooks(rt).install()
    except Exception as e:  # noqa: BLE001
        log.debug("overlay hooks: %s", e)
    return [asyncio.get_running_loop().create_task(UnlockWatch(rt).run())]
