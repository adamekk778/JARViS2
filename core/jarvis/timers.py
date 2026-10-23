"""In-memory timers (minutky). Reminders at a clock time live in the scheduler."""
from __future__ import annotations

import asyncio
import itertools
import time
from typing import Callable


class Timers:
    def __init__(self, on_fire: Callable[[str], None]):
        self.on_fire = on_fire
        self._ids = itertools.count(1)
        self._t: dict[str, dict] = {}

    def add(self, seconds: int, label: str = "Časovač") -> dict:
        tid = str(next(self._ids))
        ends = time.time() + seconds
        task = asyncio.get_event_loop().create_task(self._run(tid, seconds, label))
        self._t[tid] = {"id": tid, "label": label, "ends_at": ends, "seconds": seconds, "_task": task}
        return self.public(self._t[tid])

    async def _run(self, tid: str, seconds: int, label: str):
        try:
            await asyncio.sleep(seconds)
            self._t.pop(tid, None)
            self.on_fire(label)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def public(t: dict) -> dict:
        return {k: v for k, v in t.items() if not k.startswith("_")} | {"remaining": max(0, round(t["ends_at"] - time.time()))}

    def list(self) -> list[dict]:
        return [self.public(t) for t in self._t.values()]

    def cancel(self, id_or_label: str = "") -> int:
        hit = [k for k, t in self._t.items() if not id_or_label or k == id_or_label or id_or_label.lower() in t["label"].lower()]
        for k in hit:
            self._t.pop(k)["_task"].cancel()
        return len(hit)
