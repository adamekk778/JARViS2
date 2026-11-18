"""3.13 Input a game accepts: keys as hardware scan codes and mouse moves as relative motion (SendInput). Games such
as Roblox read raw input and ignore the virtual-key presses ordinary automation sends."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

ULONG_PTR = ctypes.c_size_t
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
VK = {"space": 0x20, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "control": 0x11,
      "alt": 0x12, "backspace": 0x08, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
      **{f"f{i}": 0x6F + i for i in range(1, 13)}}
EXTENDED = {0x25, 0x26, 0x27, 0x28}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def vk_of(key: str) -> int:
    k = key.strip().lower()
    if k in VK:
        return VK[k]
    if len(k) == 1 and (k.isalpha() or k.isdigit()):
        return ord(k.upper())
    raise ValueError(f"Klávesu „{key}“ neznám.")


def _send(*items: INPUT) -> None:
    arr = (INPUT * len(items))(*items)
    ctypes.windll.user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))


def _key(vk: int, up: bool) -> INPUT:
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    return i


def keys(names: list[str], hold_ms: int) -> None:
    """Press these keys together, hold, release (W for 800 ms = walk forward)."""
    vks = [vk_of(n) for n in names][:4]
    _send(*[_key(v, False) for v in vks])
    try:
        time.sleep(max(0.03, min(hold_ms, 5000) / 1000))
    finally:
        _send(*[_key(v, True) for v in reversed(vks)])


def mouse_move(dx: int, dy: int, steps: int = 8) -> None:
    """Turn the camera: relative motion in small steps (games read the motion, not the position)."""
    steps = max(1, steps)
    for k in range(steps):
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(int(dx * (k + 1) / steps) - int(dx * k / steps), int(dy * (k + 1) / steps) - int(dy * k / steps), 0,
                          MOUSEEVENTF_MOVE, 0, 0)
        _send(i)
        time.sleep(0.008)


def mouse_button(button: str = "left", hold_ms: int = 60) -> None:
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    a, b = INPUT(type=INPUT_MOUSE), INPUT(type=INPUT_MOUSE)
    a.mi = MOUSEINPUT(0, 0, 0, down, 0, 0)
    b.mi = MOUSEINPUT(0, 0, 0, up, 0, 0)
    _send(a)
    time.sleep(max(0.02, min(hold_ms, 3000) / 1000))
    _send(b)
