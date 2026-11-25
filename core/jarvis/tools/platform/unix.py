"""3.20 (488, 489) JARVIS on a Linux desktop and on a Mac.

The everyday commands through the tools every desktop has: xdg-open / open, pactl / osascript for the volume, playerctl
or media keys, xdotool / ydotool / osascript for typing and keys, xclip / wl-copy / pbcopy for the clipboard,
loginctl / pmset for locking and sleep, notify-send / osascript for notices. A tool that is not installed says which
package to add instead of failing silently. Windows-only powers (UI Automation, game input) stay Windows-only."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from .null import NullPlatform

KEYMAP_X = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "win": "super", "cmd": "super", "enter": "Return", "esc": "Escape", "tab": "Tab",
            "space": "space", "+": "plus", "-": "minus", "right": "Right", "left": "Left", "up": "Up", "down": "Down", "delete": "Delete",
            "backspace": "BackSpace", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next"}
KEYMAP_MAC = {"ctrl": "control down", "alt": "option down", "shift": "shift down", "win": "command down", "cmd": "command down"}
MAC_CODES = {"enter": 36, "esc": 53, "tab": 48, "space": 49, "right": 124, "left": 123, "up": 126, "down": 125, "delete": 51}


class UnixPlatform(NullPlatform):
    """Shared by Linux and macOS: a runner that can be swapped in tests."""

    def __init__(self, runner=subprocess.run, which=shutil.which) -> None:
        super().__init__()
        self._run = runner
        self._which = which

    def sh(self, args: list[str], timeout: float = 10, input_: str | None = None) -> tuple[int, str]:
        self._rec(*args[:1])
        try:
            r = self._run(args, capture_output=True, text=True, timeout=timeout, input=input_)
        except FileNotFoundError:
            return 127, f"{args[0]} není nainstalovaný"
        except subprocess.TimeoutExpired:
            return 124, "vypršel čas"
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def need(self, *names: str) -> str:
        for n in names:
            if self._which(n):
                return n
        raise RuntimeError(f"Chybí program {' nebo '.join(names)} – nainstaluj ho balíčkovačem.")

    def run_shell(self, command: str, timeout: int = 60) -> tuple[int, str]:
        return self.sh(["/bin/sh", "-c", command], timeout)


class LinuxPlatform(UnixPlatform):
    name = "linux"

    def wayland(self) -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY"))

    def open_url(self, url: str) -> None:
        self.sh(["xdg-open", url])

    def open_path(self, path: str) -> None:
        self.sh(["xdg-open", path])

    def open_app(self, name: str) -> str:
        exe = name.strip().lower().replace(" ", "-")
        if self._which(exe):
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # noqa: S603
            return name
        code, _ = self.sh(["gtk-launch", exe])
        if code != 0:
            raise RuntimeError(f"Aplikaci {name} jsem nenašel.")
        return name

    def close_app(self, name: str) -> int:
        code, _ = self.sh(["pkill", "-f", name])
        return 1 if code == 0 else 0

    def media_key(self, key: str) -> None:
        cmd = {"play_pause": "play-pause", "next": "next", "previous": "previous", "stop": "stop"}.get(key)
        if key == "mute":
            self.set_mute(not self.audio_state()[1])
        elif cmd:
            self.sh([self.need("playerctl"), cmd])

    def get_volume(self) -> int:
        code, out = self.sh(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        m = re.search(r"(\d+)%", out)
        return int(m.group(1)) if code == 0 and m else 50

    def set_volume(self, level: int) -> None:
        self.sh(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{max(0, min(150, int(level)))}%"])

    def set_mute(self, mute: bool) -> None:
        self.sh(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"])

    def audio_state(self) -> tuple[int | None, bool | None]:
        code, out = self.sh(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        return self.get_volume(), ("yes" in out.lower()) if code == 0 else None

    def clipboard_get(self) -> str:
        args = ["wl-paste", "--no-newline"] if self.wayland() else [self.need("xclip", "xsel"), "-selection", "clipboard", "-o"]
        if args[0] == "xsel":
            args = ["xsel", "--clipboard", "--output"]
        return self.sh(args)[1]

    def clipboard_set(self, text: str) -> None:
        if self.wayland():
            self.sh(["wl-copy"], input_=text)
        else:
            tool = self.need("xclip", "xsel")
            self.sh(["xclip", "-selection", "clipboard"] if tool == "xclip" else ["xsel", "--clipboard", "--input"], input_=text)
        self.clipboard = text

    def type_text(self, text: str) -> None:
        if self.wayland():
            self.sh([self.need("ydotool", "wtype"), "type", text] if self._which("ydotool") else ["wtype", text])
        else:
            self.sh([self.need("xdotool"), "type", "--delay", "8", text])

    def hotkey(self, keys: list[str]) -> None:
        combo = "+".join(KEYMAP_X.get(k.lower(), k) for k in keys)
        if self.wayland() and self._which("wtype"):
            self.sh(["wtype", *[x for k in keys for x in ("-k", KEYMAP_X.get(k.lower(), k))]])
        else:
            self.sh([self.need("xdotool"), "key", combo])

    def power(self, action: str) -> None:
        cmd = {"lock": ["loginctl", "lock-session"], "sleep": ["systemctl", "suspend"], "shutdown": ["systemctl", "poweroff"],
               "restart": ["systemctl", "reboot"], "logoff": ["loginctl", "terminate-user", os.environ.get("USER", "")],
               "cancel_shutdown": ["shutdown", "-c"]}[action]
        self.sh(cmd)

    def notify(self, title: str, body: str) -> None:
        self.sh(["notify-send", "-a", "JARVIS", title, body])

    def screenshot(self) -> bytes:
        import mss
        import mss.tools

        with mss.mss() as s:
            shot = s.grab(s.monitors[1])
            return mss.tools.to_png(shot.rgb, shot.size) or b""

    def idle_seconds(self) -> float:
        if self._which("xprintidle"):
            code, out = self.sh(["xprintidle"])
            if code == 0 and out.strip().isdigit():
                return int(out.strip()) / 1000
        return 0.0

    def foreground_app(self) -> str:
        if self._which("xdotool"):
            return self.sh(["xdotool", "getactivewindow", "getwindowname"])[1].strip()
        return ""


class MacPlatform(UnixPlatform):
    name = "mac"

    def osa(self, script: str) -> tuple[int, str]:
        return self.sh(["osascript", "-e", script])

    def open_url(self, url: str) -> None:
        self.sh(["open", url])

    def open_path(self, path: str) -> None:
        self.sh(["open", path])

    def open_app(self, name: str) -> str:
        code, out = self.sh(["open", "-a", name])
        if code != 0:
            raise RuntimeError(f"Aplikaci {name} jsem nenašel.")
        return name

    def close_app(self, name: str) -> int:
        safe = name.replace('"', "")
        code, _ = self.osa(f'tell application "{safe}" to quit')
        return 1 if code == 0 else 0

    def media_key(self, key: str) -> None:
        if key == "mute":
            self.set_mute(not self.audio_state()[1])
            return
        verb = {"play_pause": "playpause", "next": "next track", "previous": "previous track", "stop": "pause"}.get(key)
        if verb:
            self.osa(f'tell application "Music" to {verb}')

    def get_volume(self) -> int:
        code, out = self.osa("output volume of (get volume settings)")
        return int(out.strip()) if code == 0 and out.strip().isdigit() else 50

    def set_volume(self, level: int) -> None:
        self.osa(f"set volume output volume {max(0, min(100, int(level)))}")

    def set_mute(self, mute: bool) -> None:
        self.osa(f"set volume output muted {'true' if mute else 'false'}")

    def audio_state(self) -> tuple[int | None, bool | None]:
        code, out = self.osa("output muted of (get volume settings)")
        return self.get_volume(), (out.strip() == "true") if code == 0 else None

    def clipboard_get(self) -> str:
        return self.sh(["pbpaste"])[1]

    def clipboard_set(self, text: str) -> None:
        self.sh(["pbcopy"], input_=text)
        self.clipboard = text

    def type_text(self, text: str) -> None:
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        self.osa(f'tell application "System Events" to keystroke "{esc}"')

    def hotkey(self, keys: list[str]) -> None:
        mods = [KEYMAP_MAC[k.lower()] for k in keys if k.lower() in KEYMAP_MAC]
        main = [k for k in keys if k.lower() not in KEYMAP_MAC]
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        k = main[-1].lower() if main else ""
        if k in MAC_CODES:
            self.osa(f'tell application "System Events" to key code {MAC_CODES[k]}{using}')
        else:
            self.osa(f'tell application "System Events" to keystroke "{k}"{using}')

    def power(self, action: str) -> None:
        if action == "lock":
            self.sh(["pmset", "displaysleepnow"])
        elif action == "sleep":
            self.sh(["pmset", "sleepnow"])
        else:
            verb = {"shutdown": "shut down", "restart": "restart", "logoff": "log out"}.get(action)
            if verb:
                self.osa(f'tell application "System Events" to {verb}')

    def notify(self, title: str, body: str) -> None:
        t, b = title.replace('"', "'"), body.replace('"', "'")
        self.osa(f'display notification "{b}" with title "{t}"')

    def idle_seconds(self) -> float:
        code, out = self.sh(["ioreg", "-c", "IOHIDSystem"])
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if code == 0 and m else 0.0

    def foreground_app(self) -> str:
        return self.osa('tell application "System Events" to get name of first process whose frontmost is true')[1].strip()


def pick(platform: str, env: Any = os.environ) -> type[NullPlatform] | None:
    """Which desktop layer fits: a Mac, a Linux desktop session (not a headless server), else none."""
    if platform == "darwin":
        return MacPlatform
    if platform.startswith("linux") and (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) and env.get("JARVIS_HEADLESS") != "1" \
            and "PYTEST_CURRENT_TEST" not in env:
        return LinuxPlatform
    return None
