"""Runs the desktop pet: PetSim physics at 30 Hz moving a small transparent pywebview window (spec §6)."""
from __future__ import annotations

import logging
import threading
import time

from . import platforms, winutil
from .pet import PetSim

log = logging.getLogger(__name__)
PET_TITLE = "JARVIS Pet"
SMALL = (220, 220)          # window size without bubble
BIG = (440, 320)            # with speech bubble
FOOT_SMALL = (110, 206)     # where the pet's feet are inside the window
FOOT_BIG = (110, 306)
HZ = 30


class PetApi:
    """window.pywebview.api for web/src/pet."""

    def __init__(self, ctl: "PetController"):
        self._c = ctl

    def grab(self) -> None:
        self._c.grab()

    def drag(self, sx: float, sy: float) -> None:
        self._c.drag(sx, sy)

    def release(self) -> str:
        return self._c.release()

    def hover(self) -> None:
        with self._c.lock:
            self._c.sim.interact() if self._c.sim else None

    def dock(self) -> None:
        self._c.dock()

    def bubble(self, on: bool) -> None:
        self._c.big = bool(on)

    def open_chat(self, view: str = "chat") -> None:
        self._c.host.open_chat(view)

    def open_panel(self) -> None:
        self._c.dock()
        self._c.rt.bus.publish_threadsafe("pet_state", action="open_panel", facing=1)


class PetController:
    def __init__(self, host, rt):
        self.host = host
        self.rt = rt
        self.win = None
        self.sim: PetSim | None = None
        self.lock = threading.RLock()
        self.active = False
        self.big = False
        self._hidden_fs = False
        self._last_state: tuple | None = None
        self._grab_off = (0.0, 0.0)

    # ---------- window ----------
    def create_window(self) -> None:
        import webview

        self.win = webview.create_window(
            PET_TITLE, f"{self.host.base}/pet", js_api=PetApi(self), width=SMALL[0], height=SMALL[1], x=0, y=0,
            frameless=True, easy_drag=False, on_top=True, transparent=True, resizable=False, shadow=False,
            hidden=True, background_color="#000000")
        self.win.events.shown += lambda: threading.Thread(target=self._fix_taskbar, daemon=True).start()

    def _fix_taskbar(self) -> None:
        time.sleep(0.3)
        try:
            self.win.hide()
            winutil.hide_from_taskbar(PET_TITLE)
            if self.active:
                self.win.show()
        except Exception as e:
            log.debug("pet taskbar: %s", e)

    # ---------- commands (from notch / tray / ws) ----------
    def command(self, action: str) -> None:
        if action == "undock" or (action == "toggle" and not self.active):
            self.undock()
        elif action in ("dock", "toggle"):
            self.dock()

    def _notch_point(self) -> tuple[int, int]:
        scr = self.host._screen()
        sx, sy, sw = (scr.x, scr.y, scr.width) if scr else (0, 0, 1920)
        return int(sx + sw / 2 + self.rt.cfg.notch.offset_x), int(sy)

    def undock(self) -> None:
        if not self.win:
            return
        work = platforms.work_area(self.rt.cfg.notch.monitor)
        nx, ny = self._notch_point()
        with self.lock:
            self.sim = PetSim(work, size=96, notch_point=(nx, ny), start_x=nx)
            self.sim.y = float(ny + 140)
            self.sim.action = "fall"
        self.active = True
        self.rt.call_soon(self.rt.update_config, {"character": {"pet_mode": True}})
        self._place()
        try:
            self.win.show()
        except Exception as e:
            log.warning("pet show: %s", e)

    def dock(self) -> None:
        self.active = False
        try:
            if self.win:
                self.win.hide()
        except Exception:
            pass
        self.rt.call_soon(self.rt.update_config, {"character": {"pet_mode": False}})

    def grab(self) -> None:
        with self.lock:
            if self.sim:
                self.sim.grab()

    def drag(self, sx: float, sy: float) -> None:
        with self.lock:
            if self.sim:
                # the pointer holds the pet around its middle → feet a bit lower
                self.sim.drag_to(sx, sy + 40)

    def release(self) -> str:
        with self.lock:
            return self.sim.release() if self.sim else "landed"

    # ---------- loop ----------
    def _place(self) -> None:
        if not (self.win and self.sim):
            return
        w, h = BIG if self.big else SMALL
        fx, fy = FOOT_BIG if self.big else FOOT_SMALL
        try:
            self.win.resize(w, h)
            self.win.move(int(self.sim.x - fx), int(self.sim.y - fy))
        except Exception as e:
            log.debug("pet move: %s", e)

    def run(self) -> None:
        """Physics thread (started by DesktopHost)."""
        last = time.monotonic()
        tops: list = []
        next_scan = 0.0
        while not self.host._quitting:
            time.sleep(1 / HZ)
            now = time.monotonic()
            dt, last = now - last, now
            if not self.active or not self.sim:
                continue
            try:
                if now >= next_scan:
                    tops = platforms.window_tops(self.sim.work)
                    next_scan = now + 0.5
                    self.sim.set_focus(self.rt.mood.current["mood"] == "focus")
                    fs = winutil.foreground_is_fullscreen() and self.rt.cfg.notch.hide_in_fullscreen
                    if fs != self._hidden_fs:
                        self._hidden_fs = fs
                        (self.win.hide if fs else self.win.show)()
                with self.lock:
                    frame = self.sim.step(dt, tops)
                    docked = self.sim.docked
                self._place()
                state = (frame.action, frame.facing)
                if state != self._last_state:
                    self._last_state = state
                    self.rt.bus.publish_threadsafe("pet_state", action=frame.action, facing=frame.facing)
                if docked:
                    self.dock()
            except Exception as e:
                log.warning("pet loop: %s", e)
                time.sleep(1)
