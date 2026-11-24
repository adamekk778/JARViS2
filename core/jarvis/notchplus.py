"""3.14 Notch+ (návrhy 74–79).

- live activities: anything long (a model downloading, the offline pack, a skill, an automation) can show a small
  progress pill in the closed notch – `live(rt, id, title, …)`, the tool `live_activity` for skills
- widgets: your own small tiles in the notch's Více – a read-only tool run every N minutes (the weather in Brno,
  the price of bitcoin, the departures from your stop, a website's status…) and its one-line answer
- Mochi grows: points for the days you spend together, finished missions, habits kept → levels that unlock new
  outfits (never taking away what you already have)
- under heavy load (the processor above 85 % for half a minute) the interface drops its effects until it calms down
- a spectrum of the music playing (8 bands from what the PC plays, 10× a second) for the notch's visualiser
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

log = logging.getLogger(__name__)


# ---------- 75: live activities ----------
def live(rt: Any, id: str, title: str, icon: str = "spinner-gap", progress: float | None = None, text: str = "",  # noqa: A002
         done: bool = False) -> None:
    p = None if progress is None else max(0.0, min(1.0, float(progress)))
    rt.bus.publish("live_activity", id=str(id)[:40], title=str(title)[:40], icon=icon[:30], progress=p, text=str(text)[:24],
                   done=bool(done), ts=time.time())


# ---------- 76: widgets ----------
MIN_EVERY = 1


async def run_widget(rt: Any, w: Any) -> dict:
    from . import tools
    from .permissions import allowed

    spec = tools.REGISTRY.get(w.tool)
    if spec is None:
        return {"ok": False, "text": f"nástroj {w.tool} neexistuje"}
    if spec.danger or (spec.danger_if and spec.danger_if(dict(w.args or {}))) or not allowed(rt.cfg, spec):
        return {"ok": False, "text": "widget smí jen nástroje, které nic nemění"}
    try:
        res = await asyncio.wait_for(tools.call(w.tool, dict(w.args or {}), rt), 30)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "text": str(e)[:80]}
    first = (res.summary or "").split("\n")[0]
    return {"ok": bool(res.ok), "text": first[:120]}


class Widgets:
    def __init__(self, rt: Any):
        self.rt = rt
        self.cache: dict[str, dict] = {}
        self._last: dict[str, float] = {}

    def due(self, now: float | None = None) -> list[Any]:
        now = now or time.time()
        out = []
        for w in getattr(self.rt.cfg.notch, "widgets", []) or []:
            every = max(MIN_EVERY, int(w.every_min or 15)) * 60
            if now - self._last.get(w.id, 0) >= every:
                out.append(w)
        return out

    async def refresh(self, force: bool = False) -> list[dict]:
        ws = list(getattr(self.rt.cfg.notch, "widgets", []) or []) if force else self.due()
        for w in ws:
            self._last[w.id] = time.time()
            r = await run_widget(self.rt, w)
            self.cache[w.id] = {"id": w.id, "name": w.name, "icon": w.icon, **r, "ts": time.time()}
        if ws:
            self.rt.bus.publish("widgets", items=self.items())
        return self.items()

    def items(self) -> list[dict]:
        ids = [w.id for w in getattr(self.rt.cfg.notch, "widgets", []) or []]
        return [self.cache[i] for i in ids if i in self.cache]

    async def loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self.refresh()
            except Exception as e:  # noqa: BLE001
                log.debug("widgets: %s", e)
            await asyncio.sleep(30)


# ---------- 78: Mochi grows ----------
UNLOCKS = [(2, "headphones", "Sluchátka"), (4, "graduate", "Čepice absolventa"), (6, "flower", "Kytička"), (9, "halo", "Svatozář")]


def mochi_level(rt: Any) -> dict:
    db = rt.db

    def n(sql: str, args: tuple = ()) -> int:
        try:
            row = db.one(sql, args)
            return int((row or {}).get("n") or 0)
        except Exception:  # noqa: BLE001 – a table that does not exist yet
            return 0
    days = n("SELECT COUNT(DISTINCT date(created, 'unixepoch', 'localtime')) n FROM messages WHERE role='user'")
    missions = n("SELECT COUNT(*) n FROM tasks WHERE status='done'")
    habits = n("SELECT COUNT(*) n FROM habit_log WHERE value > 0")
    points = days * 10 + missions * 2 + habits
    level = int(math.floor(math.sqrt(points / 20))) + 1
    nxt = (level ** 2) * 20
    return {"level": level, "points": points, "next_at": nxt, "days": days, "missions": missions,
            "unlocked": [{"level": lv, "id": oid, "name": nm} for lv, oid, nm in UNLOCKS if level >= lv],
            "locked": [{"level": lv, "id": oid, "name": nm} for lv, oid, nm in UNLOCKS if level < lv]}


# ---------- 79: heavy load → fewer effects ----------
class LoadWatch:
    HIGH = 85.0
    LOW = 60.0

    def __init__(self, rt: Any):
        self.rt = rt
        self.heavy = False
        self._high = 0

    def sample(self, cpu: float) -> bool | None:
        """Returns the new state when it changes (high three samples in a row → heavy; below LOW → calm)."""
        self._high = self._high + 1 if cpu >= self.HIGH else 0
        if not self.heavy and self._high >= 3:
            self.heavy = True
            return True
        if self.heavy and cpu < self.LOW:
            self.heavy = False
            return False
        return None

    async def loop(self) -> None:
        import psutil

        await asyncio.sleep(30)
        psutil.cpu_percent(None)
        while True:
            await asyncio.sleep(10)
            try:
                changed = self.sample(psutil.cpu_percent(None))
            except Exception:  # noqa: BLE001
                changed = None
            if changed is not None:
                self.rt.bus.publish("perf_hint", heavy=changed)


# ---------- 74: the spectrum of what plays ----------
BANDS = (60, 150, 400, 1000, 2500, 6000, 12000, 20000)


def spectrum(block: Any, rate: int = 48000) -> list[float]:
    """8 bands (0–1, log-scaled) of an audio block (mono float)."""
    import numpy as np

    x = np.asarray(block, dtype=np.float32).reshape(-1)
    if len(x) < 256:
        return [0.0] * len(BANDS)
    win = x[-2048:] * np.hanning(min(2048, len(x)))
    mag = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(win), 1 / rate)
    out, lo = [], 20.0
    for hi in BANDS:
        sel = mag[(freqs >= lo) & (freqs < hi)]
        v = float(sel.mean()) if len(sel) else 0.0
        out.append(round(max(0.0, min(1.0, (20 * math.log10(v + 1e-9) + 20) / 60)), 2))
        lo = hi
    return out


class Spectrum:
    """Reads what the PC plays (loopback) while music plays and the visualiser is on; never the microphone."""

    def __init__(self, rt: Any):
        self.rt = rt

    def wanted(self) -> bool:
        ms = getattr(self.rt, "media_state", {}) or {}
        return bool(getattr(self.rt.cfg.notch, "music_viz", True) and getattr(self.rt.cfg.notch, "spectrum", False)
                    and ms.get("playing"))

    async def loop(self) -> None:
        await asyncio.sleep(40)
        while True:
            if not self.wanted():
                await asyncio.sleep(2)
                continue
            try:
                await asyncio.to_thread(self._run_while_wanted)
            except Exception as e:  # noqa: BLE001 – no loopback device (CI, Linux): stay quiet
                log.debug("spectrum: %s", e)
                await asyncio.sleep(30)

    def _run_while_wanted(self) -> None:
        import soundcard as sc

        spk = sc.default_speaker()
        mic = sc.get_microphone(spk.name, include_loopback=True)
        with mic.recorder(samplerate=48000, channels=1, blocksize=2048) as rec:
            while self.wanted():
                data = rec.record(numframes=4800)          # 0.1 s
                self.rt.bus.publish_threadsafe("viz_bands", bands=spectrum(data))
