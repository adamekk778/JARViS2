"""OS abstraction so tools stay testable on Linux."""
from __future__ import annotations

from typing import Literal

MediaKey = Literal["play_pause", "next", "previous", "stop", "mute"]
WindowAction = Literal["minimize_all", "maximize", "minimize", "focus", "close", "restore_all"]
PowerAction = Literal["lock", "sleep", "shutdown", "restart", "cancel_shutdown", "logoff"]


class Platform:
    name = "base"

    def open_app(self, name: str) -> str: raise NotImplementedError
    def close_app(self, name: str) -> int: raise NotImplementedError
    def list_apps(self) -> list[str]: return []
    def open_url(self, url: str) -> None: raise NotImplementedError
    def open_path(self, path: str) -> None: raise NotImplementedError
    def media_key(self, key: MediaKey) -> None: raise NotImplementedError
    def get_volume(self) -> int: raise NotImplementedError
    def set_volume(self, level: int) -> None: raise NotImplementedError
    def set_mute(self, mute: bool) -> None: raise NotImplementedError
    def window_action(self, action: WindowAction, title: str = "") -> str: raise NotImplementedError
    def list_windows(self) -> list[str]: return []
    def power(self, action: PowerAction) -> None: raise NotImplementedError
    def clipboard_get(self) -> str: raise NotImplementedError
    def clipboard_set(self, text: str) -> None: raise NotImplementedError
    def screenshot(self) -> bytes: raise NotImplementedError
    def screen_size(self) -> tuple[int, int]: return (1920, 1080)
    def run_shell(self, command: str, timeout: int = 60) -> tuple[int, str]: raise NotImplementedError
    # computer use
    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None: raise NotImplementedError
    def move(self, x: int, y: int) -> None: raise NotImplementedError
    def type_text(self, text: str) -> None: raise NotImplementedError
    def hotkey(self, keys: list[str]) -> None: raise NotImplementedError
    def scroll(self, dy: int) -> None: raise NotImplementedError
    def notify(self, title: str, body: str) -> None: pass
    def set_dark_mode(self, dark: bool) -> None: raise NotImplementedError
