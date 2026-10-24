"""Small Win32 helpers (ctypes). All functions are no-ops off Windows."""
from __future__ import annotations

import ctypes
import sys

IS_WIN = sys.platform == "win32"
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000


def find_window(title: str) -> int:
    if not IS_WIN:
        return 0
    return ctypes.windll.user32.FindWindowW(None, title) or 0


def find_own_window(title: str) -> int:
    """A top-level window with this title that belongs to THIS process. FindWindow alone can return a window of
    another JARVIS still running in the background (an old version), and then the region / size went to it."""
    if not IS_WIN:
        return 0
    import os
    from ctypes import wintypes as W

    u = ctypes.windll.user32
    pid = os.getpid()
    found = [0]
    buf = ctypes.create_unicode_buffer(256)

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(hwnd, _):
        owner = W.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            u.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found[0] = hwnd or 0
                return False
        return True

    u.EnumWindows(cb, 0)
    return int(found[0] or 0)


def window_handle(win, title: str) -> int:
    """The HWND of a pywebview window: its own WinForms handle, else a window with this title in this process."""
    if not IS_WIN:
        return 0
    try:
        v = int(win.native.Handle.ToInt64())
        if v:
            return v
    except Exception:
        pass
    return find_own_window(title)


def hide_from_taskbar(title: str) -> bool:
    hwnd = find_own_window(title) or find_window(title)
    if not hwnd:
        return False
    u = ctypes.windll.user32
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    return True


def foreground_is_fullscreen() -> bool:
    """True when the active window covers its whole monitor (game, video, presentation)."""
    if not IS_WIN:
        return False
    from ctypes import wintypes

    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd or hwnd in (u.GetDesktopWindow(), u.GetShellWindow()):
        return False
    cls = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, cls, 256)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False
    rect = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mon = u.MonitorFromWindow(hwnd, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    u.GetMonitorInfoW(mon, ctypes.byref(mi))
    m = mi.rcMonitor
    return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def set_autostart(enabled: bool, command: str) -> None:
    if not IS_WIN:
        return
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\CurrentVersion\\Run", 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, "JARVIS", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "JARVIS")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def set_app_id() -> None:
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JARVIS.Assistant.2")
        except Exception:
            pass


# ---------- window geometry, region, cursor (notch + pet windows) ----------
_geom_typed = False


def _geom_types() -> None:
    global _geom_typed
    if _geom_typed or not IS_WIN:
        return
    from ctypes import wintypes as W

    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT]
    u.SetWindowRgn.argtypes = [W.HWND, W.HRGN, W.BOOL]
    u.WindowFromPoint.argtypes = [W.POINT]
    u.WindowFromPoint.restype = W.HWND
    u.IsChild.argtypes = [W.HWND, W.HWND]
    u.GetCursorPos.argtypes = [ctypes.POINTER(W.POINT)]
    g.CreatePolygonRgn.argtypes = [ctypes.POINTER(W.POINT), ctypes.c_int, ctypes.c_int]
    g.CreatePolygonRgn.restype = W.HRGN
    g.CombineRgn.argtypes = [W.HRGN, W.HRGN, W.HRGN, ctypes.c_int]
    g.DeleteObject.argtypes = [W.HGDIOBJ]
    try:
        u.GetDpiForWindow.argtypes = [W.HWND]
    except AttributeError:
        pass
    _geom_typed = True


def dpi_scale(hwnd: int) -> float:
    """Physical pixels per CSS pixel for the window (1.25 at 125 % Windows scaling)."""
    if not IS_WIN or not hwnd:
        return 1.0
    _geom_types()
    try:
        return (ctypes.windll.user32.GetDpiForWindow(hwnd) or 96) / 96
    except Exception:
        return 1.0


def set_window_rect(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """Move + resize in ONE call (physical pixels): no in-between frame where the page shifts under the cursor."""
    if not IS_WIN or not hwnd:
        return None
    _geom_types()
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    ctypes.windll.user32.SetWindowPos(hwnd, None, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE)
    return None


def set_region(hwnd: int, polygons: list[list[tuple[int, int]]]) -> None:
    """Clip the window to these polygons (window coordinates, physical px). Outside them the window simply does not
    exist: nothing is painted (no white/grey WinForms background) and the mouse goes to whatever is below."""
    if not IS_WIN or not hwnd:
        return None
    _geom_types()
    from ctypes import wintypes as W

    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    polys = [p for p in polygons if len(p) >= 3]
    if not polys:
        u.SetWindowRgn(hwnd, None, True)
        return None
    rgn = None
    for poly in polys:
        pts = (W.POINT * len(poly))(*[W.POINT(int(x), int(y)) for x, y in poly])
        r = g.CreatePolygonRgn(pts, len(poly), 2)  # WINDING
        if rgn is None:
            rgn = r
        else:
            g.CombineRgn(rgn, rgn, r, 2)  # RGN_OR
            g.DeleteObject(r)
    if not u.SetWindowRgn(hwnd, rgn, True):  # on success the system owns the region
        g.DeleteObject(rgn)
    return None


def cursor_over(hwnd: int) -> bool:
    """Is the real mouse cursor over this window (respecting its region)? Used to ignore spurious mouseleave events."""
    if not IS_WIN or not hwnd:
        return False
    _geom_types()
    from ctypes import wintypes as W

    u = ctypes.windll.user32
    pt = W.POINT()
    if not u.GetCursorPos(ctypes.byref(pt)):
        return False
    under = u.WindowFromPoint(pt)
    return bool(under) and (under == hwnd or bool(u.IsChild(hwnd, under)))
