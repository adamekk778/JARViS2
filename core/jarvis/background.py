"""Fire-and-forget work that is not lost: asyncio keeps only a weak reference to a task, so a task nobody holds can be
garbage-collected before it finishes (the lyrics never came, a notch action did nothing). Every such task is held
here until it ends, and a failure is written to the log instead of vanishing."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

log = logging.getLogger("jarvis.bg")
_RUNNING: set[asyncio.Task] = set()


def _done(t: asyncio.Task) -> None:
    _RUNNING.discard(t)
    if not t.cancelled() and t.exception() is not None:
        log.warning("úloha na pozadí selhala: %s: %s", type(t.exception()).__name__, t.exception())


def bg(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    t = asyncio.get_running_loop().create_task(coro)
    _RUNNING.add(t)
    t.add_done_callback(_done)
    return t
