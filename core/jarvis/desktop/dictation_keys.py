"""The dictation key (3.0): hold it anywhere to dictate, tap twice for hands-free, Esc to cancel.

A press only starts the microphone after HOLD_S, and any other key pressed meanwhile cancels it, so the key keeps
working as a normal modifier (right Ctrl + C copies, nothing is recorded).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

HOLD_S = 0.18       # held this long (alone) = start listening
TAP_S = 0.3         # released faster = a tap
DOUBLE_S = 0.45     # two taps this close = hands-free


class DictationKeys:
    def __init__(self, rt: Any, clock: Callable[[], float] = time.monotonic,
                 later: Callable[[float, Callable[[], None]], Any] | None = None):
        self.rt = rt
        self.clock = clock
        self.later = later or self._timer
        self.held = False
        self.down_at = 0.0
        self.other = False
        self.stop_on_up = False
        self.last_tap = -10.0
        self._gen = 0

    @staticmethod
    def _timer(delay: float, fn: Callable[[], None]):
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()
        return t

    @property
    def d(self):
        return self.rt.dictation

    def key(self) -> str:
        return self.rt.cfg.dictation.key

    def on_event(self, name: str, kind: str) -> None:
        """name = keyboard library key name ('right ctrl'), kind = 'down' | 'up'."""
        cfg = self.rt.cfg.dictation
        if not cfg.enabled:
            return
        name = (name or "").lower()
        if name == "esc" and kind == "down" and self.d.state == "listening":
            self.d.cancel()
            return
        if name != self.key():
            if kind == "down" and self.held:
                self.other = True
                if self.d.state == "listening" and not self.d.hands_free:
                    self.d.cancel()
            return
        if kind == "down":
            if self.held:
                return  # auto-repeat
            self.held, self.other, self.down_at = True, False, self.clock()
            if self.d.state == "listening" and self.d.hands_free:
                self.stop_on_up = True   # the tap that ends hands-free dictation
                return
            self._gen += 1
            gen = self._gen
            self.later(HOLD_S, lambda: self._maybe_start(gen))
            return
        # key up
        if not self.held:
            return
        self.held = False
        if self.stop_on_up:
            self.stop_on_up = False
            self.d.finish()
            return
        dur = self.clock() - self.down_at
        if self.other:
            return
        if dur < TAP_S:
            if self.d.state == "listening" and not self.d.hands_free:
                self.d.cancel()
            now = self.clock()
            if cfg.hands_free and now - self.last_tap < DOUBLE_S:
                self.last_tap = -10.0
                self.d.start(hands_free=True)
            else:
                self.last_tap = now
            return
        if self.d.state == "listening" and not self.d.hands_free:
            self.d.finish()

    def _maybe_start(self, gen: int) -> None:
        if gen == self._gen and self.held and not self.other and self.d.state == "idle":
            self.d.start(hands_free=False)

    # ---------- wiring to the keyboard library ----------
    def install(self) -> None:
        try:
            import keyboard
        except ImportError:
            return

        def hook(e):
            try:
                self.on_event(e.name or "", e.event_type)
            except Exception:
                log.exception("dictation key")

        keyboard.hook(hook)
        try:
            keyboard.add_hotkey(self.rt.cfg.dictation.paste_again,
                                lambda: threading.Thread(target=self.d.paste_again, daemon=True).start(), suppress=False)
        except Exception as e:
            log.warning("paste-again hotkey: %s", e)
