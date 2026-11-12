"""3.12 Telefon na monitoru PC: the phone sends its screen (JPEG, ~4 per second) and gets back the clicks and typing
from the PC window in the answer to each picture. It starts only on the phone (Android asks every time) and the
phone shows a notification with Zastavit the whole time. Pictures stay in memory only – nothing is saved.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

MAX_FRAME = 3 * 2**20
ACTIVE_S = 4.0
KINDS = {"tap", "long", "swipe", "back", "home", "recents", "notifications", "text", "backspace", "enter"}


def _unit(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


class PhoneMirror:
    def __init__(self, rt: Any):
        self.rt = rt
        self.frame: bytes = b""
        self.ts = 0.0                  # the phone's last request (picture or not)
        self.frame_ts = 0.0            # the last picture
        self.size = (0, 0)
        self.control = False
        self.inputs: deque = deque(maxlen=100)
        self._stop = False
        self._new: asyncio.Event | None = None   # created on the running loop when first needed

    def _event(self) -> asyncio.Event:
        if self._new is None:
            self._new = asyncio.Event()
        return self._new

    @property
    def active(self) -> bool:
        return time.time() - self.ts < ACTIVE_S

    def status(self) -> dict:
        return {"active": self.active, "width": self.size[0], "height": self.size[1], "control": self.control, "ts": self.ts}

    # ---------- from the phone ----------
    def receive(self, jpeg: bytes, w: int, h: int, control: bool) -> dict:
        """One picture (or an empty "anything for me?"); the answer carries the PC's clicks since the last one."""
        was = self.active
        now = time.time()
        if jpeg:
            if len(jpeg) > MAX_FRAME or not jpeg.startswith(b"\xff\xd8"):
                raise ValueError("Tohle není obrázek obrazovky")
            self.frame, self.size, self.frame_ts = jpeg, (int(w), int(h)), now
            self._event().set()
            self._new = asyncio.Event()
        self.ts, self.control = now, bool(control)
        if not was:
            self._stop = False
            self.rt.bus.publish("phone_mirror", **self.status())
        if self._stop:
            self._stop = False
            self.inputs.clear()
            self.ts = 0.0
            self.rt.bus.publish("phone_mirror", **self.status())
            return {"inputs": [], "stop": True}
        out = list(self.inputs)
        self.inputs.clear()
        return {"inputs": out, "stop": False}

    # ---------- from the PC window ----------
    async def latest(self, after: float, wait: float = 2.0) -> tuple[bytes, float] | None:
        if self.frame and self.frame_ts > after:
            return self.frame, self.frame_ts
        try:
            await asyncio.wait_for(self._event().wait(), wait)
        except asyncio.TimeoutError:
            return None
        return (self.frame, self.frame_ts) if self.frame else None

    def input(self, m: dict) -> bool:
        kind = str(m.get("kind", ""))
        if kind not in KINDS or not self.active:
            return False
        ev: dict = {"kind": kind}
        if kind in ("tap", "long"):
            ev.update(x=_unit(m.get("x")), y=_unit(m.get("y")))
        elif kind == "swipe":
            ev.update(x1=_unit(m.get("x1")), y1=_unit(m.get("y1")), x2=_unit(m.get("x2")), y2=_unit(m.get("y2")),
                      ms=int(max(80, min(1500, float(m.get("ms") or 250)))))
        elif kind == "text":
            ev["text"] = str(m.get("text", ""))[:500]
            if not ev["text"]:
                return False
        self.inputs.append(ev)
        return True

    def request(self) -> bool:
        """Ask the phone to start (it shows Android's own question there)."""
        return bool(self.rt.phone_push("mirror_ask"))

    def stop(self) -> None:
        self._stop = True
        self.frame = b""
        self.rt.phone_push("mirror_stop")
