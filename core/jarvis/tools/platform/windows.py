"""Real Windows implementation. Every import is local so this file imports anywhere."""
from __future__ import annotations

import ctypes
import difflib
import io
import os
import subprocess
import webbrowser
from pathlib import Path

from .base import Platform

VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "mute": 0xAD}
KEYEVENTF_KEYUP = 0x0002
CREATE_NO_WINDOW = 0x08000000

ALIASES = {
    "chrome": "Google Chrome", "google": "Google Chrome", "edge": "Microsoft Edge", "prohlížeč": "Microsoft Edge",
    "spotify": "Spotify", "discord": "Discord", "steam": "Steam", "word": "Word", "excel": "Excel",
    "powerpoint": "PowerPoint", "outlook": "Outlook", "teams": "Microsoft Teams", "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code", "kalkulačka": "Calculator", "kalkulacka": "Calculator",
    "poznámkový blok": "Notepad", "notepad": "Notepad", "průzkumník": "File Explorer", "explorer": "File Explorer",
    "nastavení": "Settings", "terminál": "Terminal", "cmd": "Command Prompt", "obs": "OBS Studio",
}
DIRECT = {
    "Calculator": "calc.exe", "Notepad": "notepad.exe", "File Explorer": "explorer.exe",
    "Settings": "ms-settings:", "Command Prompt": "cmd.exe", "Task Manager": "taskmgr.exe",
    "správce úloh": "taskmgr.exe", "Paint": "mspaint.exe",
}


def _ps(command: str, timeout: int = 30) -> tuple[int, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


class WindowsPlatform(Platform):
    name = "windows"

    def __init__(self) -> None:
        self._start_apps: dict[str, str] | None = None
        self._lnks: dict[str, str] | None = None

    # ---------- apps ----------
    def _index(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._lnks is None:
            lnks: dict[str, str] = {}
            roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
                     Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
                     Path.home() / "Desktop", Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
            for root in roots:
                if root.exists():
                    for p in root.rglob("*"):
                        if p.suffix.lower() in (".lnk", ".url", ".appref-ms"):
                            lnks.setdefault(p.stem, str(p))
            self._lnks = lnks
        if self._start_apps is None:
            apps: dict[str, str] = {}
            try:
                code, out = _ps("Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }", timeout=20)
                for line in out.splitlines():
                    if "|" in line:
                        n, aid = line.rsplit("|", 1)
                        apps[n.strip()] = aid.strip()
            except Exception:
                pass
            self._start_apps = apps
        return self._lnks, self._start_apps

    def list_apps(self) -> list[str]:
        lnks, apps = self._index()
        return sorted(set(lnks) | set(apps))

    def open_app(self, name: str) -> str:
        key = name.strip()
        target = ALIASES.get(key.lower(), key)
        if target in DIRECT or key.lower() in DIRECT:
            os.startfile(DIRECT.get(target) or DIRECT[key.lower()])
            return target
        lnks, apps = self._index()
        names = list(apps) + list(lnks)
        low = {n.lower(): n for n in names}
        hit = low.get(target.lower())
        if not hit:
            contains = [n for n in names if target.lower() in n.lower()]
            hit = min(contains, key=len) if contains else None
        if not hit:
            m = difflib.get_close_matches(target.lower(), list(low), n=1, cutoff=0.6)
            hit = low[m[0]] if m else None
        if hit and hit in apps:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{apps[hit]}"], creationflags=CREATE_NO_WINDOW)
            return hit
        if hit:
            os.startfile(lnks[hit])
            return hit
        # last resort: let Windows resolve it (e.g. "notepad", "msedge")
        subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=CREATE_NO_WINDOW)
        return target

    def close_app(self, name: str) -> int:
        import psutil

        target = ALIASES.get(name.lower(), name).lower().replace(" ", "")
        n = 0
        for p in psutil.process_iter(["name"]):
            pname = (p.info["name"] or "").lower().removesuffix(".exe")
            if pname and (target in pname or pname in target) and pname not in ("python", "pythonw", "jarvis"):
                try:
                    p.terminate()
                    n += 1
                except Exception:
                    pass
        return n

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def open_path(self, path: str) -> None:
        os.startfile(path)

    # ---------- media / volume ----------
    def media_key(self, key) -> None:
        vk = VK[key]
        u = ctypes.windll.user32
        u.keybd_event(vk, 0, 0, 0)
        u.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _endpoint(self):
        from pycaw.pycaw import AudioUtilities

        dev = AudioUtilities.GetSpeakers()
        if hasattr(dev, "EndpointVolume"):
            return dev.EndpointVolume
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume

        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))

    def _com(self, fn):
        import comtypes

        comtypes.CoInitialize()
        try:
            return fn(self._endpoint())
        finally:
            comtypes.CoUninitialize()

    def get_volume(self) -> int:
        return self._com(lambda ep: round(ep.GetMasterVolumeLevelScalar() * 100))

    def set_volume(self, level: int) -> None:
        level = max(0, min(100, int(level)))
        self._com(lambda ep: ep.SetMasterVolumeLevelScalar(level / 100, None))

    def set_mute(self, mute: bool) -> None:
        self._com(lambda ep: ep.SetMute(1 if mute else 0, None))

    # ---------- windows ----------
    def _windows(self) -> list[tuple[int, str]]:
        u = ctypes.windll.user32
        out: list[tuple[int, str]] = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(hwnd, _):
            if u.IsWindowVisible(hwnd):
                n = u.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(hwnd, buf, n + 1)
                    if buf.value and buf.value not in ("Program Manager", "JARVIS Notch"):
                        out.append((hwnd, buf.value))
            return True

        u.EnumWindows(proto(cb), 0)
        return out

    def list_windows(self) -> list[str]:
        return [t for _, t in self._windows()]

    def window_action(self, action, title: str = "") -> str:
        u = ctypes.windll.user32
        if action in ("minimize_all", "restore_all"):
            _ps("(New-Object -ComObject Shell.Application)." + ("MinimizeAll()" if action == "minimize_all" else "UndoMinimizeALL()"))
            return action
        hwnd, name = None, ""
        if title:
            wins = self._windows()
            cand = [(h, t) for h, t in wins if title.lower() in t.lower()]
            if not cand:
                m = difflib.get_close_matches(title.lower(), [t.lower() for _, t in wins], n=1, cutoff=0.4)
                cand = [(h, t) for h, t in wins if m and t.lower() == m[0]]
            if cand:
                hwnd, name = cand[0]
        else:
            hwnd = u.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError(f"Okno '{title}' nenalezeno")
        if action == "focus":
            u.ShowWindow(hwnd, 9)
            u.keybd_event(0x12, 0, 0, 0)  # ALT trick allows SetForegroundWindow
            u.SetForegroundWindow(hwnd)
            u.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        elif action == "maximize":
            u.ShowWindow(hwnd, 3)
        elif action == "minimize":
            u.ShowWindow(hwnd, 6)
        elif action == "close":
            u.PostMessageW(hwnd, 0x0010, 0, 0)
        return name or action

    # ---------- power ----------
    def power(self, action) -> None:
        if action == "lock":
            ctypes.windll.user32.LockWorkStation()
        elif action == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "15"], creationflags=CREATE_NO_WINDOW)
        elif action == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "15"], creationflags=CREATE_NO_WINDOW)
        elif action == "cancel_shutdown":
            subprocess.Popen(["shutdown", "/a"], creationflags=CREATE_NO_WINDOW)
        elif action == "logoff":
            subprocess.Popen(["shutdown", "/l"], creationflags=CREATE_NO_WINDOW)

    # ---------- clipboard / screen / shell ----------
    def clipboard_get(self) -> str:
        try:
            import pyperclip

            return pyperclip.paste()
        except Exception:
            return _ps("Get-Clipboard -Raw")[1]

    def clipboard_set(self, text: str) -> None:
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception:
            subprocess.run(["clip"], input=text.encode("utf-16-le"), creationflags=CREATE_NO_WINDOW)

    def screenshot(self) -> bytes:
        import mss
        import mss.tools

        with mss.mss() as s:
            shot = s.grab(s.monitors[1])
            return mss.tools.to_png(shot.rgb, shot.size)

    def screen_size(self) -> tuple[int, int]:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)

    def run_shell(self, command: str, timeout: int = 60) -> tuple[int, str]:
        return _ps(command, timeout=timeout)

    # ---------- computer use ----------
    def _pg(self):
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        return pyautogui

    def click(self, x, y, button="left", double=False):
        pg = self._pg()
        pg.click(x, y, clicks=2 if double else 1, button=button)

    def move(self, x, y):
        self._pg().moveTo(x, y, duration=0.15)

    def type_text(self, text):
        # pyautogui.write can't type non-ASCII (č, ř, ž) → paste via clipboard
        if text.isascii():
            self._pg().write(text, interval=0.01)
        else:
            old = self.clipboard_get()
            self.clipboard_set(text)
            self._pg().hotkey("ctrl", "v")
            import time

            time.sleep(0.2)
            self.clipboard_set(old)

    def hotkey(self, keys):
        self._pg().hotkey(*[k.lower() for k in keys])

    def scroll(self, dy):
        self._pg().scroll(int(dy))

    def set_dark_mode(self, dark: bool) -> None:
        v = 0 if dark else 1
        key = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        _ps(f"Set-ItemProperty -Path '{key}' -Name AppsUseLightTheme -Value {v}; "
            f"Set-ItemProperty -Path '{key}' -Name SystemUsesLightTheme -Value {v}")

    def notify(self, title: str, body: str) -> None:
        pass


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
