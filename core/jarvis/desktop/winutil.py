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


def hide_from_taskbar(title: str) -> bool:
    hwnd = find_window(title)
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
