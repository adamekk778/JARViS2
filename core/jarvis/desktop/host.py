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
HUD_TITLE = "JARVIS HUD"
PAD = 28  # must match web/src/notch/main.ts


class NotchApi:
    """Exposed to notch JS as window.pywebview.api."""

    def __init__(self, host: "DesktopHost"):
        self._host = host

    def resize(self, w: int, h: int) -> None:
        self._host.place_notch(int(w), int(h))

    def region(self, polygons: list) -> bool:
        """The page sends the notch outline (window coords, physical px) every frame while it animates and again
        every 2 s; False tells it the region did not take, so it sends it again."""
        return self._host.set_notch_region(polygons)

    def cursor_inside(self) -> bool:
        return winutil.cursor_over(self._host.notch_hwnd())

    def open_chat(self, view: str = "chat") -> None:
        self._host.open_chat(view)

    def smooth(self) -> bool:
        """Is the window per-pixel transparent? Then the page paints only the shape (see DesktopHost._smooth_edges)."""
        return self._host.alpha


class HudApi:
    """Exposed to the HUD page as window.pywebview.api."""

    def __init__(self, host: "DesktopHost"):
        self._host = host

    def close(self) -> None:
        self._host.toggle_hud(False)

    def smooth(self) -> bool:
        return self._host.hud_alpha

    def open_chat(self, view: str = "chat") -> None:
        self._host.toggle_hud(False)
        self._host.open_chat(view)


class DesktopHost:
    def __init__(self, rt, base_url: str):
        self.rt = rt
        self.base = base_url
        self.notch = None
        self.chat = None
        self.full = None   # the full-screen ChatGPT-style chat, created on first use
        self.tray = None
        self._quitting = False
        self._notch_size = (rt.cfg.notch.width + PAD * 2, rt.cfg.notch.height + PAD)
        self._hidden_fullscreen = False
        self.alpha = False
        self.hud = None
        self.hud_visible = False
        self.hud_alpha = False
        self._anchor_win = None
        rt.on_anchor = self._anchor        # OMEGA 752: the runtime tells us which window JARVIS works in
        self._region: list = []            # the last notch outline from the page, put back if Windows drops it
        self._region_applied: tuple | None = None
        self._region_warned = 0.0

    # ---------- geometry ----------
    def _screen(self):
        import webview

        screens = webview.screens or []
        idx = self.rt.cfg.notch.monitor
        return screens[idx] if 0 <= idx < len(screens) else (screens[0] if screens else None)

    def notch_hwnd(self) -> int:
        h = getattr(self, "_notch_hwnd", 0)
        if not h or not winutil.is_window(h):     # not found yet, or WinForms recreated the window
            h = self._notch_hwnd = winutil.window_handle(self.notch, NOTCH_TITLE)
        return h

    def _anchor(self, win: dict | None) -> None:
        self._anchor_win = win
        size = getattr(self, "_notch_size", None)
        if size:
            self.place_notch(*size)

    def set_notch_region(self, polygons: list) -> bool:
        polys = [[(round(x), round(y)) for x, y in poly] for poly in polygons or []]
        self._region = polys
        hwnd = self.notch_hwnd()
        if self._region_applied == (hwnd, str(polys)) and winutil.region_kind(hwnd) >= 2:
            return True                            # the page re-sends every 2 s: no repaint when nothing changed
        ok = winutil.set_region(hwnd, polys)
        self._region_applied = (hwnd, str(polys)) if ok else None
        return bool(ok)

    def heal_region(self) -> bool:
        """Without its region the notch window shows as a grey box around the notch. Windows can drop it (the
        window recreated, a display change) and the page only sends it when the shape changes, so check here."""
        if not self.notch or not self._region:
            return False
        hwnd = self.notch_hwnd()
        if not hwnd or winutil.region_kind(hwnd) not in (0, 1):
            return False
        if time.monotonic() - self._region_warned > 60:
            self._region_warned = time.monotonic()
            log.warning("notch: the window region was missing (window %s), putting it back", hwnd)
        self._region_applied = None
        return self.set_notch_region(self._region)

    def place_notch(self, w: int, h: int) -> None:
        if not self.notch:
            return
        self._notch_size = (w, h)
        hwnd = self.notch_hwnd()
        if hwnd:  # Windows: physical pixels, one SetWindowPos (pywebview's resize+move is two steps and DPI-scales x twice)
            from . import platforms

            mons = platforms.monitors()
            i = self.rt.cfg.notch.monitor
            mon = mons[i if 0 <= i < len(mons) else 0][0]
            scale = winutil.dpi_scale(hwnd)
            pw, ph = round(w * scale), round(h * scale)
            win = getattr(self, "_anchor_win", None)          # OMEGA 752: above the window JARVIS works in
            if win:
                from ..mochiplus import anchor_offset

                x = int(mon.x + (mon.w - pw) // 2 + anchor_offset(win, mon.x, mon.w, pw))
            else:
                x = int(mon.x + (mon.w - pw) // 2 + self.rt.cfg.notch.offset_x * scale)
            winutil.set_window_rect(hwnd, x, mon.y, pw, ph)
            return
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
                frameless=True, easy_drag=False, on_top=True, resizable=False, shadow=False,
                background_color="#000000")  # not transparent: the page clips the window to the notch shape (region)
            self.notch.events.shown += self._on_notch_shown
        self.chat = webview.create_window(
            "JARVIS", f"{self.base}/#chat", width=1240, height=820, min_size=(420, 520), hidden=True,
            background_color="#0a0c0f", text_select=True)
        self.chat.events.closing += self._on_chat_closing

    def _on_notch_shown(self) -> None:
        time.sleep(0.3)
        try:  # the tool-window style only drops the taskbar button if applied while hidden
            self.notch.hide()
            winutil.hide_from_taskbar(NOTCH_TITLE)
            self.notch.show()
        except Exception as e:
            log.debug("taskbar: %s", e)
        self.place_notch(*self._notch_size)
        self._smooth_edges()

    def _smooth_edges(self) -> None:
        """Anti-aliased notch edges: a transparent WebView2 on a per-pixel-alpha window. The page then paints only the
        shape and the region (slightly larger) is just for the mouse. Without it nothing changes: black + region."""
        if self.rt.cfg.notch.edges != "smooth":
            return
        if self._make_alpha(self.notch, self.notch_hwnd()):
            self.alpha = True
            self.notch.evaluate_js("window.__notchAlpha && window.__notchAlpha(true)")
            log.info("notch: smooth edges (per-pixel alpha) on")

    def _make_alpha(self, win, hwnd: int) -> bool:
        """Per-pixel transparency for a pywebview window (WebView2 background transparent + DWM blur-behind)."""
        form = getattr(win, "native", None)
        if form is None or not winutil.IS_WIN or not hwnd:
            return False
        try:
            from System import Action
            from System.Drawing import Color

            def apply():
                form.BackColor = Color.Black   # GDI black has alpha 0 on a blur-behind window → transparent
                form.webview.DefaultBackgroundColor = Color.Transparent

            form.Invoke(Action(apply))
            if winutil.enable_alpha(hwnd):
                return True
            form.Invoke(Action(lambda: setattr(form.webview, "DefaultBackgroundColor", Color.Black)))
        except Exception as e:
            log.warning("per-pixel alpha unavailable: %s", e)
        return False

    # ---------- 3.2 Stark HUD: a holographic overlay over the whole screen ----------
    def toggle_hud(self, show: bool | None = None) -> None:
        threading.Thread(target=self._toggle_hud, args=(show,), daemon=True, name="hud").start()

    def _toggle_hud(self, show: bool | None) -> None:
        import webview

        show = (not self.hud_visible) if show is None else show
        try:
            if not show:
                if self.hud is not None and self.hud_visible:
                    self.hud_visible = False
                    self.hud.evaluate_js("window.__hud && window.__hud.close()")
                    self.hud.hide()
                return
            scr = self._screen()
            x, y, w, h = (scr.x, scr.y, scr.width, scr.height) if scr else (0, 0, 1920, 1080)
            if self.hud is None:
                self.hud = webview.create_window(
                    HUD_TITLE, f"{self.base}/hud", js_api=HudApi(self), x=x, y=y, width=w, height=h,
                    frameless=True, easy_drag=False, on_top=True, resizable=False, shadow=False,
                    background_color="#02060c", focus=True)
                self.hud_visible = True
                # windows created after start-up never fire "shown" in pywebview 6 → wait for it here, then finish
                if not self.hud.events.shown.wait(8):
                    self.hud.events.loaded.wait(10)
                self._on_hud_shown()
                return
            self.hud.show()
            self._place_hud()
            self.hud_visible = True
            self.hud.evaluate_js("window.__hud && window.__hud.open()")
            self.hud.on_top = True
        except Exception as e:
            log.warning("hud: %s", e)

    def _place_hud(self) -> int:
        """Exactly over the notch's monitor, in physical pixels (pywebview would DPI-scale the size a second time)."""
        hwnd = winutil.window_handle(self.hud, HUD_TITLE)
        if hwnd:
            from . import platforms

            mons = platforms.monitors()
            i = self.rt.cfg.notch.monitor
            mon = mons[i if 0 <= i < len(mons) else 0][0]
            winutil.set_window_rect(hwnd, mon.x, mon.y, mon.w, mon.h)
            winutil.focus(hwnd)
            log.info("hud: placed on %s (window %s)", (mon.x, mon.y, mon.w, mon.h), winutil.window_rect(hwnd))
        return hwnd

    def _on_hud_shown(self) -> None:
        try:
            self._finish_hud()
        except Exception:
            log.exception("hud: finishing the window failed")

    def _finish_hud(self) -> None:
        time.sleep(0.2)
        hwnd = self._place_hud()
        threading.Timer(0.8, self._place_hud).start()   # pywebview may still apply its own size right after "shown"
        self.hud_alpha = self._make_alpha(self.hud, hwnd)
        try:
            self.hud.evaluate_js(f"window.__hud && window.__hud.alpha({'true' if self.hud_alpha else 'false'})")
        except Exception:
            pass
        log.info("hud: shown (alpha %s)", self.hud_alpha)

    def _on_chat_closing(self):
        if self._quitting:
            return True
        # closing handlers block the GUI thread; hiding from here would deadlock → do it from another thread
        threading.Thread(target=self.chat.hide, daemon=True).start()
        return False  # keep the window alive, just hidden

    def _on_full_closing(self):
        if self._quitting:
            return True
        threading.Thread(target=self.full.hide, daemon=True).start()
        return False

    def open_fullchat(self) -> None:
        import webview

        try:
            if self.full is None:   # a new window shows itself; later opens just bring it back
                self.full = webview.create_window(
                    "JARVIS Chat", f"{self.base}/chat", width=1280, height=860, min_size=(520, 560), maximized=True,
                    background_color="#0d0d0f", text_select=True)
                self.full.events.closing += self._on_full_closing
                return
            self.full.show()
            self.full.maximize()
            self.full.on_top = True
            self.full.on_top = False
        except Exception as e:
            log.warning("open_fullchat: %s", e)

    def open_chat(self, view: str = "chat") -> None:
        if view in ("hud", "hud-close"):
            return self.toggle_hud(view == "hud")
        if view == "full":   # off the caller's thread: creating a window waits for the GUI thread
            threading.Thread(target=self.open_fullchat, daemon=True, name="fullchat").start()
            return
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
            try:
                self.heal_region()
            except Exception as e:
                log.debug("heal_region: %s", e)
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
            pystray.MenuItem("Celý chat", lambda: self.open_fullchat()),
            pystray.MenuItem("Stark HUD", lambda: self.toggle_hud()),
            pystray.MenuItem("Nastavení", lambda: self.open_chat("general")),
            pystray.MenuItem("Spárovat telefon", lambda: self.open_chat("phone")),
            pystray.MenuItem(voice_label, toggle_voice, visible=lambda _: self.rt.voice is not None),
            pystray.MenuItem("Schránka", pystray.Menu(
                pystray.MenuItem("Shrň schránku", lambda: self._clipboard("Shrň stručně tento text")),
                pystray.MenuItem("Přelož schránku", lambda: self._clipboard("Přelož tento text (česky ↔ anglicky)")),
                pystray.MenuItem("Vysvětli schránku", lambda: self._clipboard("Vysvětli mi jednoduše tento text")))),
            pystray.MenuItem("STOP – zastavit vše", lambda: self.rt.call_soon(self.rt.stop_all)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ukončit", self.quit),
        )
        self.tray = pystray.Icon("JARVIS", img, "JARVIS", menu)
        self.tray.run()

    def _clipboard(self, instruction: str) -> None:
        """Tray → clipboard assistant. The clipboard is read only now, on this explicit click."""
        try:
            text = self.rt.platform.clipboard_get()
        except Exception as e:
            log.warning("clipboard: %s", e)
            return
        if not text.strip():
            self.rt.notify("Schránka je prázdná", "Nejdřív zkopíruj nějaký text.", speak=False)
            return
        self.rt.submit(self.rt.agent.handle(f"{instruction}:\n\n{text[:8000]}", [], "chat"))
        self.open_chat("chat")

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

        def stop_all():
            self.rt.call_soon(self.rt.stop_all)

        def selection():   # 3.3: what to do with the selected text (fix, translate, explain…)
            from .. import powers

            self.rt.submit(powers.selection_menu(self.rt))

        for combo, fn in ((hk.talk, talk), (hk.chat, lambda: self.open_chat("chat")), (hk.stop, stop),
                          (hk.stop_all, stop_all), (hk.hud, lambda: self.toggle_hud()), (hk.selection, selection)):
            try:
                keyboard.add_hotkey(combo, fn, suppress=False)
            except Exception as e:
                log.warning("hotkey %s failed: %s", combo, e)
        # dictation anywhere: hold the dictation key (right Ctrl by default)
        try:
            from .dictation_keys import DictationKeys

            self.dictation_keys = DictationKeys(self.rt)
            self.dictation_keys.install()
        except Exception as e:
            log.warning("dictation keys: %s", e)

    def quit(self, *_):
        self._quitting = True
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        for w in (self.notch, self.chat, self.full, self.hud):
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
        self.rt.ui_hook = lambda view: self.open_chat(view)
        self.create_windows()
        threading.Thread(target=self._tray, daemon=True, name="tray").start()
        threading.Thread(target=self._hotkeys, daemon=True, name="hotkeys").start()
        threading.Thread(target=self._fullscreen_watch, daemon=True, name="fullscreen").start()

        def started():
            if open_chat:
                self.open_chat("chat")
            try:   # "JARVIS online", or the morning briefing when it is due
                from .. import stark

                self.rt.submit(stark.boot(self.rt))
            except Exception as e:
                log.debug("boot greeting: %s", e)

        webview.start(started, gui="edgechromium" if sys.platform == "win32" else None,
                      private_mode=False, storage_path=str(__import__("jarvis.paths", fromlist=["sub"]).sub("webview")))
        self.quit()
