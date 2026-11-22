"""WebSocket message handlers by area – the long if/elif in server/ws.py moves here piece by piece.

A handler is `async def h(conn, m)`: `conn` is the server/ws.Connection (send, spawn, rt, local, guest…), `m` the
message. Register it with @handles("type", …); local_only = only from this PC, slow = runs beside the other messages
(network or system lookups). Every type must also be in ws.CLIENT_TYPES and web/src/shared/protocol.ts (a test checks).
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Awaitable, Callable

Handler = Callable[[Any, dict], Awaitable[None]]

HANDLERS: dict[str, Handler] = {}
LOCAL_ONLY: set[str] = set()
SLOW: set[str] = set()


def handles(*types: str, local_only: bool = False, slow: bool = False) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        for t in types:
            if t in HANDLERS and HANDLERS[t] is not fn:
                raise ValueError(f"WebSocket type {t!r} has two handlers")
            HANDLERS[t] = fn
            if local_only:
                LOCAL_ONLY.add(t)
            if slow:
                SLOW.add(t)
        return fn
    return deco


_loaded = False


def load() -> None:
    """Import every module in this package (each registers its handlers)."""
    global _loaded
    if _loaded:
        return
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
    _loaded = True
