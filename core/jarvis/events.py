"""In-process event bus: everything the UIs should see goes through here."""
from __future__ import annotations

import asyncio
from typing import Any


class Bus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, type: str, **data: Any) -> None:  # noqa: A002
        msg = {"type": type, **data}
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def publish_threadsafe(self, type: str, **data: Any) -> None:  # noqa: A002
        """Publish from a non-asyncio thread (voice loop, tray, hotkeys)."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: self.publish(type, **data))
        else:
            self.publish(type, **data)
