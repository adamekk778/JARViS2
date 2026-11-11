"""3.12 "JARVIS právě ovládá tvůj PC": while JARVIS moves the mouse or types, a thin frame lines the screen and the
notch says so, with "Převzít kontrolu" (JARVIS stops before its next move until you give it back) and "Zastavit".

Every tool that drives the mouse/keyboard (permission "input") runs inside a session; a short pause between quick
actions (typing, then a key) keeps the frame steady instead of flashing. Taking over pauses the running task and the
computer-use loop waits at its next step – JARVIS never fights you for the mouse.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Callable

log = logging.getLogger(__name__)

LINGER_S = 1.5          # the frame stays this long after the last action (no flicker between quick actions)
LABELS = {"computer_use": "Myš a klávesnice", "type_text": "Píše", "press_keys": "Klávesy",
          "mouse": "Myš", "ui_click": "Kliká", "ui_type": "Píše"}


class PcControl:
    def __init__(self, rt):
        self.rt = rt
        self.active = 0
        self.on = False
        self.paused = False             # you took over: JARVIS waits
        self.label = ""
        self._off_handle: asyncio.TimerHandle | None = None
        self._resume = asyncio.Event()
        self._resume.set()
        self.listeners: list[Callable[[dict], None]] = []    # the desktop frame (desktop/control_frame.py)

    def state(self) -> dict:
        return {"on": self.on, "paused": self.paused, "label": self.label}

    def _emit(self) -> None:
        st = self.state()
        self.rt.bus.publish("pc_control", **st)
        for f in list(self.listeners):
            try:
                f(st)
            except Exception as e:  # noqa: BLE001
                log.debug("pc_control listener: %s", e)

    @contextlib.asynccontextmanager
    async def session(self, tool: str):
        """Around one mouse/keyboard tool: the frame shows; it goes LINGER_S after the last one ends."""
        if self._off_handle:
            self._off_handle.cancel()
            self._off_handle = None
        self.active += 1
        label = LABELS.get(tool, "Myš a klávesnice")
        if not self.on or label != self.label:
            self.on, self.label = True, label
            self._emit()
        try:
            await self.wait_if_taken()
            yield
        finally:
            self.active -= 1
            if self.active <= 0:
                self.active = 0
                self._off_handle = asyncio.get_running_loop().call_later(LINGER_S, self._off)

    def _off(self) -> None:
        self._off_handle = None
        if self.active or self.paused:
            return                       # taken over: the frame stays until you give control back or stop
        if self.on:
            self.on, self.label = False, ""
            self._emit()

    async def wait_if_taken(self) -> None:
        """computer_use calls this before every move: while you hold control, JARVIS waits here."""
        await self._resume.wait()

    def take_over(self) -> None:
        if not self.on or self.paused:
            return
        self.paused = True
        self._resume.clear()
        with contextlib.suppress(Exception):
            self.rt.tasks.pause()
            self.rt.platform.release_all_input()     # nothing JARVIS held down stays pressed
        self._emit()

    def give_back(self) -> None:
        if not self.paused:
            return
        self.paused = False
        self._resume.set()
        with contextlib.suppress(Exception):
            self.rt.tasks.resume()
        self._emit()
        if not self.active:
            self._off_handle = asyncio.get_running_loop().call_later(LINGER_S, self._off)

    def reset(self) -> None:
        """STOP: everything off at once."""
        if self._off_handle:
            self._off_handle.cancel()
            self._off_handle = None
        was = self.on or self.paused
        self.paused, self.on, self.label, self.active = False, False, "", 0
        self._resume.set()
        if was:
            self._emit()
