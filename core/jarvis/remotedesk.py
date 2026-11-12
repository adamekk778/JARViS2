"""3.12 Vzdálená plocha v telefonu: see the PC screen on the phone and drive it with a finger – from home or from
anywhere over JARVIS Link.

It must be allowed once on the PC (Nastavení → Telefon → Vzdálená plocha) and the phone needs the "screen" and
"input" areas. While a phone drives the PC, the frame lines the screen and the notch says "Telefon ovládá PC" with
Ukončit / Zastavit – nothing happens unseen. Windows that look private stay blacked out in the picture. The session
ends by itself after IDLE_S without a touch.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)

IDLE_S = 10 * 60
KEYS = {"enter": ["enter"], "backspace": ["backspace"], "esc": ["esc"], "tab": ["tab"], "win": ["win"],
        "alttab": ["alt", "tab"], "copy": ["ctrl", "c"], "paste": ["ctrl", "v"], "undo": ["ctrl", "z"],
        "desktop": ["win", "d"], "taskmgr": ["ctrl", "shift", "esc"], "up": ["up"], "down": ["down"],
        "left": ["left"], "right": ["right"], "delete": ["delete"], "home": ["home"], "end": ["end"],
        "volup": ["volumeup"], "voldown": ["volumedown"], "mute": ["volumemute"], "close": ["alt", "f4"]}


class RemoteDesk:
    def __init__(self, rt):
        self.rt = rt
        self.on = False
        self.by = ""
        self.last = 0.0
        self._watch: asyncio.Task | None = None
        self._down = False

    def status(self) -> dict:
        return {"on": self.on, "by": self.by, "allowed": bool(self.rt.cfg.phone_link.remote_desktop)}

    def why_not(self, perms: set[str] | None) -> str:
        if not self.rt.cfg.phone_link.remote_desktop:
            return "Vzdálená plocha je na PC vypnutá. Zapni ji jednou na PC: Nastavení → Telefon → Vzdálená plocha."
        if perms is not None and not {"screen", "input"} <= perms:
            return "Telefon nemá povolené „Obrazovka“ a „Myš a klávesnice“ (na PC: Nastavení → Telefon → Co smí telefon)."
        return ""

    def start(self, by: str = "Telefon") -> dict:
        self.on, self.by, self.last = True, by or "Telefon", time.time()
        self.rt.screen_share.start(IDLE_S / 60, quiet=True)
        self.rt.pc_control.remote_on(f"{self.by} – vzdálená plocha")
        self.rt.notify("Vzdálená plocha", f"{self.by} teď vidí a ovládá PC. Ukončíš to v notchi.", speak=False)
        if self._watch is None or self._watch.done():
            self._watch = asyncio.get_running_loop().create_task(self._idle())
        self._publish()
        return self.status()

    def stop(self) -> dict:
        if self.on:
            self.on = False
            self.rt.screen_share.stop()
            self.rt.pc_control.remote_off()
            if self._down:
                self._down = False
                try:
                    self.rt.platform.release_all_input()
                except Exception:  # noqa: BLE001
                    pass
            self._publish()
        if self._watch and not self._watch.done():
            self._watch.cancel()
        return self.status()

    def _publish(self) -> None:
        self.rt.bus.publish("remote_desk", **self.status())

    async def _idle(self) -> None:
        while self.on:
            await asyncio.sleep(15)
            if self.on and time.time() - self.last > IDLE_S:
                self.stop()

    # ---------- the finger ----------
    def _xy(self, m: dict) -> tuple[int, int]:
        w, h = self.rt.screen_share.size or self.rt.platform.screen_size()
        x = min(max(float(m.get("x", 0)), 0.0), 1.0)
        y = min(max(float(m.get("y", 0)), 0.0), 1.0)
        return round(x * (w - 1)), round(y * (h - 1))

    async def input(self, m: dict) -> None:
        if not self.on:
            raise PermissionError("Vzdálená plocha neběží.")
        self.last = time.time()
        ss = self.rt.screen_share
        ss.until = max(ss.until, self.last + IDLE_S)   # the picture keeps going while you use it
        p = self.rt.platform
        kind = str(m.get("kind", ""))
        if kind in ("tap", "double", "right"):
            x, y = self._xy(m)
            await asyncio.to_thread(p.click, x, y, "right" if kind == "right" else "left", kind == "double")
        elif kind == "move":
            x, y = self._xy(m)
            await asyncio.to_thread(p.move, x, y)
        elif kind == "drag":
            x1, y1 = self._xy({"x": m.get("x1"), "y": m.get("y1")})
            x2, y2 = self._xy({"x": m.get("x2"), "y": m.get("y2")})
            await asyncio.to_thread(p.drag, x1, y1, x2, y2)
        elif kind == "scroll":
            dy = max(-30, min(30, int(m.get("dy", 0))))
            if dy:
                await asyncio.to_thread(p.scroll, dy)
        elif kind == "text":
            text = str(m.get("text", ""))[:500]
            if text:
                await asyncio.to_thread(p.type_text, text)
        elif kind == "key":
            keys = KEYS.get(str(m.get("key", "")))
            if keys:
                await asyncio.to_thread(p.hotkey, keys)
