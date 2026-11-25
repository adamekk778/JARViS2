"""3.15 Mega animace na ploše – the Windows side: each effect (jarvis/fxrender.py) plays in its own small layered
window that is always on top, never takes the focus, lets every click through and is left out of screenshots (so
the AI that looks at the screen never sees its own reticle). Frames are pushed with UpdateLayeredWindow (per-pixel
alpha), about 30 a second; at most 4 effects at once, the rest are dropped.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Any

from .. import fxrender

log = logging.getLogger(__name__)

MAX_LIVE = 4
MOTIF_COLORS = {"stark": "#4fc3ff", "mark": "#ff4d3d", "friday": "#b48cff", "stealth": "#9aa4b2"}


def accent(rt: Any) -> str:
    a = rt.cfg.appearance
    return MOTIF_COLORS.get(getattr(a, "motif", ""), "") or getattr(a, "accent", "") or "#4fc3ff"


def monitor(rt: Any) -> tuple[int, int, int, int]:
    """The notch's monitor in physical pixels (x, y, w, h)."""
    try:
        from .platforms import monitors

        mons = monitors()
        i = rt.cfg.notch.monitor
        m = mons[i if 0 <= i < len(mons) else 0][0]
        return int(m.x), int(m.y), int(m.w), int(m.h)
    except Exception:  # noqa: BLE001
        return 0, 0, 1920, 1080


def effect_for(rt: Any, kind: str, data: dict) -> fxrender.Effect | None:
    """overlay_fx event → the effect to play (None = nothing to show)."""
    col = accent(rt)
    mx, my, mw, mh = monitor(rt)
    if kind == "click":
        return fxrender.Effect(220, 220, 1.4, fxrender.reticle(col, str(data.get("label") or "")), cx=int(data["x"]), cy=int(data["y"]))
    if kind == "move":
        return fxrender.Effect(64, 64, 0.5, fxrender.dot(col), cx=int(data["x"]), cy=int(data["y"]))
    if kind == "scan":
        return fxrender.Effect(mw, 46, 1.4, fxrender.scanline(mw, col), move=lambda t: (mx, my + int(fxrender.ease_out(t) * mh) - 23))
    if kind == "osd":
        return fxrender.Effect(220, 220, 1.8, fxrender.osd(str(data.get("what") or "volume"), data.get("value"), str(data.get("text") or ""), col),
                               cx=mx + mw - 170, cy=my + mh // 2)
    if kind == "welcome":
        return fxrender.Effect(760, 300, 3.2, fxrender.welcome(str(data.get("text") or "Vítejte zpět"), col), cx=mx + mw // 2, cy=my + mh // 2)
    if kind == "ring":                      # 3.20 (118) sharing the screen: where the cursor is
        return fxrender.Effect(120, 120, 1.0, fxrender.ring("#ffcc00"), cx=int(data["x"]), cy=int(data["y"]))
    if kind == "eq":                        # 3.20 (113) music above the taskbar (bottom centre of the monitor)
        return fxrender.Effect(420, 46, 1.9, fxrender.eq(list(data.get("bars") or []), col), cx=mx + mw // 2, cy=my + mh - 70)
    return None


class FxWin:
    def __init__(self, rt: Any):
        self.rt = rt
        self.live = 0
        self._lock = threading.Lock()
        self._reg = threading.Lock()
        self._class: Any = None

    def handle(self, kind: str, data: dict) -> None:
        """From any thread: play the effect for this event (Windows only; ignored elsewhere)."""
        if sys.platform != "win32":
            return
        eff = effect_for(self.rt, kind, data)
        if eff is None:
            return
        with self._lock:
            if self.live >= MAX_LIVE:
                return
            self.live += 1
        threading.Thread(target=self._play, args=(eff,), daemon=True, name=f"fx-{kind}").start()

    # ---------- Windows ----------
    def _play(self, eff: fxrender.Effect) -> None:                       # pragma: no cover – Windows
        hwnd = 0
        try:
            hwnd = self._window(eff.w, eff.h)
            n = eff.frames()
            t0 = time.perf_counter()
            for i in range(n):
                t = i / max(1, n - 1)
                img = eff.frame(t)
                x, y = eff.move(t) if eff.move else (eff.cx - eff.w // 2, eff.cy - eff.h // 2)
                self._push(hwnd, img, x, y)
                self._pump()
                wait = t0 + (i + 1) / fxrender.FPS - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            log.debug("fx window: %s", e)
        finally:
            if hwnd:
                ctypes.windll.user32.DestroyWindow(ctypes.c_void_p(hwnd))
            with self._lock:
                self.live -= 1

    def _window(self, w: int, h: int) -> int:                              # pragma: no cover – Windows
        from ctypes import wintypes

        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.CreateWindowExW.restype = ctypes.c_void_p
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        with self._reg:                                                    # one window class for all the effect windows
            if self._class is None:
                WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                self._proc = WNDPROC(lambda hh, m, wp, lp: u.DefWindowProcW(hh, m, wp, lp))

                class WNDCLASSW(ctypes.Structure):
                    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

                wc = WNDCLASSW()
                wc.lpfnWndProc = self._proc
                wc.hInstance = k.GetModuleHandleW(None)
                wc.lpszClassName = "JarvisFx"
                u.RegisterClassW(ctypes.byref(wc))
                self._class = wc
        ex = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000   # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
        hwnd = u.CreateWindowExW(ex, "JarvisFx", "JARVIS FX", 0x80000000, 0, 0, w, h, None, None, k.GetModuleHandleW(None), None)   # WS_POPUP
        if not hwnd:
            raise OSError("CreateWindowEx failed")
        try:
            u.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), 0x11)       # WDA_EXCLUDEFROMCAPTURE: not in screenshots
        except (AttributeError, OSError):
            pass
        u.ShowWindow(ctypes.c_void_p(hwnd), 4)                            # SW_SHOWNOACTIVATE
        return int(hwnd)

    @staticmethod
    def _pump() -> None:                                                   # pragma: no cover – Windows
        from ctypes import wintypes

        u = ctypes.windll.user32
        msg = wintypes.MSG()
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):          # PM_REMOVE
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    @staticmethod
    def _push(hwnd: int, img: Any, x: int, y: int) -> None:               # pragma: no cover – Windows
        from ctypes import wintypes

        from PIL import Image, ImageChops

        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        w, h = img.size
        r, gg, b, a = img.split()
        aa = Image.merge("RGB", (a, a, a))
        pr, pg, pb = ImageChops.multiply(Image.merge("RGB", (r, gg, b)), aa).split()   # premultiplied alpha
        data = Image.merge("RGBA", (pb, pg, pr, a)).tobytes()                          # BGRA

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte), ("SourceConstantAlpha", ctypes.c_ubyte),
                        ("AlphaFormat", ctypes.c_byte)]

        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateDIBSection.restype = ctypes.c_void_p
        g.SelectObject.restype = ctypes.c_void_p
        u.GetDC.restype = ctypes.c_void_p
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(ctypes.c_void_p(screen))
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(ctypes.c_void_p(mem), ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data))
            old = g.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(bmp))
            blend = BLENDFUNCTION(0, 0, 255, 1)                                      # AC_SRC_OVER, AC_SRC_ALPHA
            u.UpdateLayeredWindow(ctypes.c_void_p(hwnd), ctypes.c_void_p(screen), ctypes.byref(wintypes.POINT(int(x), int(y))),
                                  ctypes.byref(wintypes.SIZE(w, h)), ctypes.c_void_p(mem), ctypes.byref(wintypes.POINT(0, 0)), 0,
                                  ctypes.byref(blend), 2)                                     # ULW_ALPHA
            g.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(old))
        finally:
            g.DeleteObject(ctypes.c_void_p(bmp))
            g.DeleteDC(ctypes.c_void_p(mem))
            u.ReleaseDC(None, ctypes.c_void_p(screen))
