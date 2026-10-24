"""Recording platform for tests and non-Windows dev runs."""
from __future__ import annotations

import io

from .base import Platform, norm


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
    def hotkey(self, keys):
        self._rec("hotkey", tuple(keys))
        if tuple(keys) == ("ctrl", "c") and getattr(self, "selection", None) is not None:
            self.clipboard = self.selection   # the app in front copies its selected text
    def foreground_app(self): return getattr(self, "front_app", "Poznámkový blok")
    def foreground_info(self): return getattr(self, "front", {"hwnd": 42, "pid": 4242, "app": self.foreground_app(), "title": "Dokument"})
    def focus_window(self, hwnd): self._rec("focus_window", hwnd); return True
    def clipboard_seq(self): return hash(self.clipboard) & 0xFFFFFFF
    def empty_recycle_bin(self): self._rec("empty_recycle_bin"); return 1234
    def idle_seconds(self): return getattr(self, "idle", 0.0)
    def scroll(self, dy): self._rec("scroll", dy)
    def notify(self, title, body): self._rec("notify", title, body)
    def release_all_input(self): self._rec("release_all_input")
    def drag(self, x1, y1, x2, y2): self._rec("drag", x1, y1, x2, y2)

    # ---------- fake UI Automation tree: a calculator window ----------
    _WINDOW = "Kalkulačka"

    def _ui_nodes(self) -> list[dict]:
        if not hasattr(self, "_nodes"):
            self._nodes = [
                {"ref": "w0:1", "role": "Button", "name": "Sedm", "automation_id": "num7Button", "value": None},
                {"ref": "w0:2", "role": "Button", "name": "Krát", "automation_id": "multiplyButton", "value": None},
                {"ref": "w0:3", "role": "Button", "name": "Rovná se", "automation_id": "equalButton", "value": None},
                {"ref": "w0:4", "role": "Edit", "name": "Výsledek", "automation_id": "CalculatorResults", "value": "0"},
                {"ref": "w0:5", "role": "Button", "name": "Odeslat", "automation_id": "sendButton", "value": None},
            ]
            for n in self._nodes:
                n.update(enabled=True, rect=[0, 0, 40, 30], depth=1)
        return self._nodes

    def _win_ok(self, window: str) -> bool:
        return not window or norm(window) in norm(self._WINDOW)

    def ui_tree(self, window="", depth=4, limit=150):
        return [dict(n) for n in self._ui_nodes()][:limit] if self._win_ok(window) else []

    def ui_find(self, window="", name="", role="", automation_id="", timeout=0.0):
        if not self._win_ok(window):
            return None
        for n in self._ui_nodes():
            if name and norm(name) != norm(n["name"]):
                continue
            if role and norm(role) != norm(n["role"]):
                continue
            if automation_id and automation_id != n["automation_id"]:
                continue
            return dict(n)
        return None

    def ui_get(self, ref):
        return next((dict(n) for n in self._ui_nodes() if n["ref"] == ref), None)

    def ui_act(self, ref, action):
        self._rec("ui_act", ref, action)
        return action

    def ui_set_text(self, ref, text):
        self._rec("ui_set_text", ref, text)
        for n in self._ui_nodes():
            if n["ref"] == ref:
                n["value"] = text

    def ui_read(self, window="", limit=4000):
        return " ".join(n["name"] for n in self._ui_nodes())[:limit] if self._win_ok(window) else ""

    def ui_state(self, window=""):
        return {"window": self._WINDOW, "focused": "Výsledek"}
    def set_dark_mode(self, dark): self._rec("set_dark_mode", dark)

    def screenshot(self) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (64, 36), (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()
