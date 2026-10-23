"""pywebview windows (notch + chat), tray icon and global hotkeys. Runs on the main thread."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

from . import winutil

log = logging.getLogger(__name__)
NOTCH_TITLE = "JARVIS Notch"
PAD = 28  # must match web/src/notch/main.ts


class NotchApi:
    """Exposed to notch JS as window.pywebview.api."""

    def __init__(self, host: "DesktopHost"):
        self._host = host

    def resize(self, w: int, h: int) -> None:
        self._host.place_notch(int(w), int(h))

    def open_chat(self, view: str = "chat") -> None:
        self._host.open_chat(view)


class DesktopHost:
    def __init__(self, rt, base_url: str):
        self.rt = rt
        self.base = base_url
        self.notch = None
        self.chat = None
        self.tray = None
        self._quitting = False
        self._notch_size = (rt.cfg.notch.width + PAD * 2, rt.cfg.notch.height + PAD)
        self._hidden_fullscreen = False

    # ---------- geometry ----------
    def _screen(self):
        import webview

        screens = webview.screens or []
        idx = self.rt.cfg.notch.monitor
        return screens[idx] if 0 <= idx < len(screens) else (screens[0] if screens else None)

    def place_notch(self, w: int, h: int) -> None:
        if not self.notch:
            return
        self._notch_size = (w, h)
        scr = self._screen()
        sx, sy, sw = (scr.x, scr.y, scr.width) if scr else (0, 0, 1920)
        x = int(sx + (sw - w) / 2 + self.rt.cfg.notch.offset_x)
        try:
            self.notch.resize(w, h)
            self.notch.move(x, sy)
        except Exception as e:
            log.debug("place_notch: %s", e)

    # ---------- windows ----------
    def create_windows(self) -> None:
        import webview

        w, h = self._notch_size
        if self.rt.cfg.notch.enabled:
            self.notch = webview.create_window(
                NOTCH_TITLE, f"{self.base}/notch", js_api=NotchApi(self), width=w, height=h, x=0, y=0,
                frameless=True, easy_drag=False, on_top=True, transparent=True, resizable=False, shadow=False,
                background_color="#000000")
            self.notch.events.shown += self._on_notch_shown
        self.chat = webview.create_window(
            "JARVIS", f"{self.base}/#chat", width=1240, height=820, min_size=(420, 520), hidden=True,
            background_color="#0a0c0f", text_select=True)
        self.chat.events.closing += self._on_chat_closing

    def _on_notch_shown(self) -> None:
        time.sleep(0.3)
        winutil.hide_from_taskbar(NOTCH_TITLE)
        self.place_notch(*self._notch_size)

    def _on_chat_closing(self):
        if self._quitting:
            return True
        self.chat.hide()
        return False  # keep the window alive, just hidden

    def open_chat(self, view: str = "chat") -> None:
        if not self.chat:
            return
        try:
            self.chat.show()
            self.chat.restore()
            self.chat.evaluate_js(f"location.hash = {view!r}")
            self.chat.on_top = True
            self.chat.on_top = False
        except Exception as e:
            log.debug("open_chat: %s", e)

    # ---------- background loops ----------
    def _fullscreen_watch(self) -> None:
        while not self._quitting:
            time.sleep(1.5)
            if not self.notch or not self.rt.cfg.notch.hide_in_fullscreen:
                continue
            try:
                fs = winutil.foreground_is_fullscreen()
                if fs and not self._hidden_fullscreen:
                    self.notch.hide()
                    self._hidden_fullscreen = True
                elif not fs and self._hidden_fullscreen:
                    self.notch.show()
                    self._hidden_fullscreen = False
            except Exception:
                pass

    def _tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(10, 12, 15, 255), outline=(46, 230, 255, 255), width=4)
        d.ellipse((20, 20, 44, 44), fill=(46, 230, 255, 255))

        def voice_label(_):
            v = self.rt.voice
            return "Pozastavit poslech" if v and not v.paused else "Zapnout poslech"

        def toggle_voice(_icon, _item):
            v = self.rt.voice
            if v:
                v.set_paused(not v.paused)

        menu = pystray.Menu(
            pystray.MenuItem("Otevřít JARVIS", lambda: self.open_chat("chat"), default=True),
            pystray.MenuItem("Nastavení", lambda: self.open_chat("general")),
            pystray.MenuItem("Spárovat telefon", lambda: self.open_chat("phone")),
            pystray.MenuItem(voice_label, toggle_voice, visible=lambda _: self.rt.voice is not None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ukončit", self.quit),
        )
        self.tray = pystray.Icon("JARVIS", img, "JARVIS", menu)
        self.tray.run()

    def _hotkeys(self) -> None:
        try:
            import keyboard
        except ImportError:
            return
        hk = self.rt.cfg.hotkeys

        def talk():
            if self.rt.voice and getattr(self.rt.voice, "available", False):
                self.rt.voice.push_to_talk()
            else:
                self.open_chat("chat")

        def stop():
            if self.rt.agent.busy or (self.rt.speaker and self.rt.speaker.speaking):
                self.rt.call_soon(self.rt.agent.stop)
                if self.rt.speaker:
                    self.rt.speaker.stop()

        for combo, fn in ((hk.talk, talk), (hk.chat, lambda: self.open_chat("chat")), (hk.stop, stop)):
            try:
                keyboard.add_hotkey(combo, fn, suppress=False)
            except Exception as e:
                log.warning("hotkey %s failed: %s", combo, e)

    def quit(self, *_):
        self._quitting = True
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        for w in (self.notch, self.chat):
            try:
                if w:
                    w.destroy()
            except Exception:
                pass
        os._exit(0)

    # ---------- main ----------
    def run(self, open_chat: bool = False) -> None:
        import webview

        winutil.set_app_id()
        exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m jarvis'
        try:
            winutil.set_autostart(self.rt.cfg.general.autostart, f'"{exe}" --background' if getattr(sys, "frozen", False) else exe)
        except Exception as e:
            log.warning("autostart: %s", e)
        self.create_windows()
        threading.Thread(target=self._tray, daemon=True, name="tray").start()
        threading.Thread(target=self._hotkeys, daemon=True, name="hotkeys").start()
        threading.Thread(target=self._fullscreen_watch, daemon=True, name="fullscreen").start()

        def started():
            if open_chat:
                self.open_chat("chat")

        webview.start(started, gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(__import__("jarvis.paths", fromlist=["sub"]).sub("webview")))
        self.quit()
