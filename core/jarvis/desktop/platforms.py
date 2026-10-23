"""Where the pet can stand: the monitor work area and the top edges of normal windows (Windows only)."""
from __future__ import annotations

import ctypes
import sys

from .pet import Rect

IS_WIN = sys.platform == "win32"
SKIP_TITLES = ("JARVIS", "Program Manager")


def monitors() -> list[tuple[Rect, Rect]]:
    """[(monitor_rect, work_rect)] in Windows' order (primary first)."""
    if not IS_WIN:
        return [(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040))]
    from ctypes import wintypes

    u = ctypes.windll.user32
    out: list[tuple[Rect, Rect, bool]] = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), ctypes.c_long)

    def cb(hmon, hdc, rect, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetMonitorInfoW(hmon, ctypes.byref(mi))
        m, w = mi.rcMonitor, mi.rcWork
        out.append((Rect(m.left, m.top, m.right - m.left, m.bottom - m.top),
                    Rect(w.left, w.top, w.right - w.left, w.bottom - w.top), bool(mi.dwFlags & 1)))
        return 1

    u.EnumDisplayMonitors(None, None, proto(cb), 0)
    out.sort(key=lambda t: not t[2])
    return [(m, w) for m, w, _ in out] or [(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040))]


def work_area(monitor: int = 0) -> Rect:
    mons = monitors()
    return mons[monitor if 0 <= monitor < len(mons) else 0][1]


def window_tops(work: Rect, limit: int = 15) -> list[Rect]:
    """Visible, normal (not minimized/maximized/cloaked) windows overlapping the work area, top-most first."""
    if not IS_WIN:
        return []
    from ctypes import wintypes

    u = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    found: list[Rect] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if len(found) >= limit:
            return False
        if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or u.IsZoomed(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if any(buf.value.startswith(t) for t in SKIP_TITLES):
            return True
        cloaked = ctypes.c_int(0)
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))  # DWMWA_CLOAKED
        if cloaked.value:
            return True
        r = wintypes.RECT()
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # EXTENDED_FRAME_BOUNDS
            u.GetWindowRect(hwnd, ctypes.byref(r))
        rect = Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        if rect.right > work.x and rect.x < work.right and work.y < rect.y < work.bottom:
            found.append(rect)
        return True

    u.EnumWindows(proto(cb), 0)
    return found
