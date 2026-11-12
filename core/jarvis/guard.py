"""3.12 Hlídání PC: switched on from the phone when you leave ("Hlídat PC" / "Zamknout a hlídat"). If someone then
unlocks the PC or uses its mouse / keyboard, the phone gets a notice right away – and, if you want, the PC locks
itself again. It only watches whether the PC is in use (lock state, time since the last input); no camera, no
microphone, no screenshots. The notice goes only to your paired phone, never shown on the PC itself.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import deque
from typing import Any

log = logging.getLogger("jarvis.guard")

POLL_S = 3
GRACE_S = 20          # after switching it on: time to walk away from the PC
QUIET_S = 30          # the PC must have been untouched this long before a touch counts as "someone"
REPEAT_S = 10 * 60    # still in use: remind at most every 10 minutes


def is_locked() -> bool | None:
    """Windows: is the screen locked (the input desktop is the secure Winlogon one)? Elsewhere: unknown."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        u = ctypes.windll.user32
        h = u.OpenInputDesktop(0, False, 0x0100)          # DESKTOP_SWITCHDESKTOP
        if not h:
            return True
        try:
            return not u.SwitchDesktop(h)
        finally:
            u.CloseDesktop(h)
    except Exception:  # noqa: BLE001
        return None


class Guard:
    def __init__(self, rt: Any):
        self.rt = rt
        self.armed = False
        self.auto_lock = False
        self.since = 0.0
        self.events: deque = deque(maxlen=10)
        self._was_locked = False
        self._quiet_long = False
        self._alerted: float | None = None

    def arm(self, on: bool, auto_lock: bool | None = None, now: float | None = None) -> dict:
        now = now if now is not None else time.time()
        if auto_lock is not None:
            self.auto_lock = bool(auto_lock)
        if on and not self.armed:
            self.since, self._was_locked, self._quiet_long, self._alerted = now, False, False, None
        self.armed = bool(on)
        return self.status()

    def status(self) -> dict:
        return {"armed": self.armed, "auto_lock": self.auto_lock, "since": self.since if self.armed else 0,
                "locked": is_locked(), "events": list(self.events)}

    def step(self, now: float, locked: bool | None, idle_s: float) -> dict | None:
        """One look at the PC; returns the event when someone is using it."""
        if not self.armed:
            return None
        if locked:
            self._was_locked = True
            return None
        if now - self.since < GRACE_S:                 # still leaving the desk
            self._quiet_long = idle_s >= QUIET_S
            return None
        kind = None
        if self._was_locked and locked is False:
            kind = "unlock"
        elif self._quiet_long and idle_s < POLL_S + 2:
            kind = "input"
        self._was_locked = False if locked is False else self._was_locked
        self._quiet_long = idle_s >= QUIET_S
        if kind is None or (self._alerted is not None and now - self._alerted < REPEAT_S):
            return None
        self._alerted = now
        ev = {"kind": kind, "t": now, "locked_again": False}
        self.events.appendleft(ev)
        self._alert(ev)
        return ev

    def _alert(self, ev: dict) -> None:
        when = time.strftime("%H:%M", time.localtime(ev["t"]))
        what = "odemkl" if ev["kind"] == "unlock" else "začal používat"
        body = f"V {when} někdo {what} tvoje PC, zatímco ho JARVIS hlídá."
        if self.auto_lock:
            try:
                self.rt.platform.power("lock")
                ev["locked_again"] = True
                body += " PC jsem hned znovu zamkl."
            except Exception as e:  # noqa: BLE001
                log.debug("guard lock: %s", e)
        else:
            body += " V aplikaci ho můžeš zamknout."
        try:
            sent = self.rt.phone_push("notify", title="Někdo používá tvoje PC", body=body)
        except Exception:  # noqa: BLE001
            sent = False
        ev["sent"] = bool(sent)
        self.rt.bus.publish("guard", **self.status())    # the open phone app shows it at once

    async def loop(self) -> None:
        while True:
            if self.armed:
                try:
                    idle = float(self.rt.platform.idle_seconds())
                    self.step(time.time(), await asyncio.to_thread(is_locked), idle)
                except Exception as e:  # noqa: BLE001 – the watch must keep going
                    log.debug("guard step: %s", e)
            await asyncio.sleep(POLL_S)
