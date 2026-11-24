"""3.16 Odpovědi připravené dopředu (návrh 18): what you ask about most is fetched in the background, so the answer
is there the moment you ask – "jaké bude počasí", "co mám dnes", "co je nového".

Only things that read and never change anything: the weather at home, today's calendar, the news summary, plus the
read-only tools you use at this hour of the day. Refreshed every 10 minutes while you are at the PC (not when away,
not with "Jen offline"); a fetched answer counts as fresh for 10–30 minutes, then the tool runs as usual.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

FRESH_S = {"weather": 900, "calendar_list": 600, "world_news": 1800, "now_playing_info": 20}
PLAN: list[tuple[str, dict]] = [("weather", {}), ("calendar_list", {}), ("world_news", {})]
EVERY_S = 600
AWAY_S = 600


def _key(name: str, args: dict | None) -> str:
    return name + json.dumps({k: v for k, v in (args or {}).items() if v not in ("", None)}, sort_keys=True, ensure_ascii=False)


class Prefetch:
    def __init__(self, rt: Any):
        self.rt = rt
        self.cache: dict[str, tuple[float, Any]] = {}
        self.hits = 0

    def get(self, name: str, args: dict | None) -> Any | None:
        """A fresh fetched answer for exactly this call (else None)."""
        if name not in FRESH_S:
            return None
        got = self.cache.get(_key(name, args))
        if got and time.time() - got[0] < FRESH_S[name]:
            self.hits += 1
            return got[1]
        return None

    def put(self, name: str, args: dict | None, res: Any) -> None:
        if name in FRESH_S and getattr(res, "ok", False):
            self.cache[_key(name, args)] = (time.time(), res)

    def plan(self) -> list[tuple[str, dict]]:
        out = list(PLAN)
        try:
            from . import toolmind

            out += [(n, {}) for n in toolmind.habits(self.rt) if n in FRESH_S and (n, {}) not in out]
        except Exception:  # noqa: BLE001
            pass
        return out

    async def refresh(self) -> int:
        from . import tools
        from .permissions import allowed

        n = 0
        off = set(self.rt.cfg.tools.disabled or ())
        for name, args in self.plan():
            spec = tools.REGISTRY.get(name)
            if spec is None or name in off or not allowed(self.rt.cfg, spec) or spec.danger:
                continue
            try:
                res = await tools.call(name, args, self.rt)
            except Exception as e:  # noqa: BLE001
                log.debug("prefetch %s: %s", name, e)
                continue
            if res.ok:
                self.put(name, args, res)
                n += 1
        return n

    def should_run(self) -> bool:
        cfg = self.rt.cfg
        if getattr(cfg.brain, "offline_only", False) or not getattr(cfg.agent, "prefetch", True):
            return False
        try:
            return float(self.rt.platform.idle_seconds()) < AWAY_S
        except Exception:  # noqa: BLE001
            return True

    async def run(self) -> None:
        await asyncio.sleep(20)                               # after start-up, not during it
        while True:
            try:
                if self.should_run():
                    await self.refresh()
            except Exception as e:  # noqa: BLE001
                log.debug("prefetch: %s", e)
            await asyncio.sleep(EVERY_S)


def get(rt: Any) -> Prefetch:
    p = getattr(rt, "prefetch", None)
    if p is None:
        p = rt.prefetch = Prefetch(rt)
    return p
