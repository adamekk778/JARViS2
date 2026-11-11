"""3.12 The frame around the screen while JARVIS controls the PC (see jarvis/pccontrol.py).

Four thin strips per monitor, drawn by Windows itself (no browser window – next to nothing in CPU or memory): always
on top, never take the focus, clicks go straight through them, and they are left out of screenshots so the AI that
looks at the screen does not see them. Blue while JARVIS drives, amber while you have taken over.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading

log = logging.getLogger(__name__)

THICK = 4
BLUE = 0x00FF840A        # COLORREF 0x00BBGGRR = #0a84ff
AMBER = 0x000A9FFF       # #ff9f0a
WM_APP = 0x8000


class ControlFrame:
    def __init__(self):
        self._want: tuple[bool, bool] = (False, False)     # (on, taken over)
        self._tid = 0
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def set(self, on: bool, paused: bool = False) -> None:
        """Thread-safe: show / hide / recolour (called from the event loop)."""
        if sys.platform != "win32":
            return
        self._want = (bool(on), bool(paused))
        if self._thread is None:
            if not on:
                return
            self._thread = threading.Thread(target=self._run, daemon=True, name="control-frame")
            self._thread.start()
            self._ready.wait(2)
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_APP, 0, 0)

    # ---------- the Windows side (its own thread with a message loop) ----------
    def _run(self) -> None:                                    # pragma: no cover – Windows
        from ctypes import wintypes

        from .platforms import monitors

        u, g, k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self._proc = WNDPROC(lambda h, m, w, lp: u.DefWindowProcW(h, m, w, lp))   # kept alive on self

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                        ("lpszClassName", wintypes.LPCWSTR)]

        hinst = k.GetModuleHandleW(None)
        brushes = {False: g.CreateSolidBrush(BLUE), True: g.CreateSolidBrush(AMBER)}
        wc = WNDCLASSW(0, self._proc, 0, 0, hinst, None, None, brushes[False], None, "JarvisControlFrame")
        u.RegisterClassW(ctypes.byref(wc))
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                      wintypes.HINSTANCE, wintypes.LPVOID]
        u.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        g.CreateSolidBrush.restype = wintypes.HBRUSH
        ex = 0x8 | 0x80 | 0x80000 | 0x20 | 0x08000000   # topmost, tool window, layered, click-through, no activate
        hwnds: list[int] = []

        def build():
            for h in hwnds:
                u.DestroyWindow(h)
            hwnds.clear()
            for mon, _work in monitors():
                for x, y, w, h in ((mon.x, mon.y, mon.w, THICK), (mon.x, mon.y + mon.h - THICK, mon.w, THICK),
                                   (mon.x, mon.y, THICK, mon.h), (mon.x + mon.w - THICK, mon.y, THICK, mon.h)):
                    hw = u.CreateWindowExW(ex, "JarvisControlFrame", "JARVIS", 0x80000000, x, y, w, h, None, None, hinst, None)
                    if not hw:
                        continue
                    u.SetLayeredWindowAttributes(hw, 0, 235, 2)         # LWA_ALPHA
                    try:
                        u.SetWindowDisplayAffinity(hw, 0x11)            # WDA_EXCLUDEFROMCAPTURE: not in screenshots
                    except Exception:  # noqa: BLE001
                        pass
                    hwnds.append(hw)

        def apply():
            on, paused = self._want
            if on and not hwnds:
                build()
            for hw in hwnds:
                if on:
                    u.SetClassLongPtrW(hw, -10, brushes[paused] or 0)       # GCLP_HBRBACKGROUND
                    u.InvalidateRect(hw, None, True)
                    u.ShowWindow(hw, 4)                                  # SW_SHOWNOACTIVATE
                    u.SetWindowPos(hw, wintypes.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # topmost, no size/move/activate
                else:
                    u.ShowWindow(hw, 0)
            if not on:                                                   # next time: fresh, monitors may have changed
                for hw in hwnds:
                    u.DestroyWindow(hw)
                hwnds.clear()

        self._tid = k.GetCurrentThreadId()
        msg = wintypes.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)                 # create this thread's message queue
        self._ready.set()
        apply()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP:
                try:
                    apply()
                except Exception as e:  # noqa: BLE001
                    log.debug("control frame: %s", e)
                continue
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
