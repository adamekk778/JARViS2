"""Recording platform for tests and non-Windows dev runs."""
from __future__ import annotations

import io

from .base import Platform


class NullPlatform(Platform):
    name = "null"

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.volume = 50
        self.muted = False
        self.clipboard = ""

    def _rec(self, *a):
        self.calls.append(a)

    def open_app(self, name): self._rec("open_app", name); return name
    def close_app(self, name): self._rec("close_app", name); return 1
    def list_apps(self): return ["Spotify", "Discord", "Steam", "Google Chrome"]
    def open_url(self, url): self._rec("open_url", url)
    def open_path(self, path): self._rec("open_path", path)
    def media_key(self, key): self._rec("media_key", key)
    def get_volume(self): return self.volume
    def set_volume(self, level): self._rec("set_volume", level); self.volume = level
    def set_mute(self, mute): self._rec("set_mute", mute); self.muted = mute
    def window_action(self, action, title=""): self._rec("window_action", action, title); return title or action
    def list_windows(self): return ["Spotify", "YouTube - Edge"]
    def power(self, action): self._rec("power", action)
    def clipboard_get(self): return self.clipboard
    def clipboard_set(self, text): self._rec("clipboard_set", text); self.clipboard = text
    def run_shell(self, command, timeout=60): self._rec("run_shell", command); return 0, f"ran: {command}"
    def click(self, x, y, button="left", double=False): self._rec("click", x, y, button, double)
    def move(self, x, y): self._rec("move", x, y)
    def type_text(self, text): self._rec("type_text", text)
    def hotkey(self, keys): self._rec("hotkey", tuple(keys))
    def scroll(self, dy): self._rec("scroll", dy)
    def notify(self, title, body): self._rec("notify", title, body)
    def release_all_input(self): self._rec("release_all_input")
    def set_dark_mode(self, dark): self._rec("set_dark_mode", dark)

    def screenshot(self) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (64, 36), (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()
