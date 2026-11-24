"""3.16 Spojení k AI zůstává otevřené (návrh 4): every request used to open a new connection (TCP + TLS: 100–300 ms
before the first byte, more on a slow line). Now one client per event loop is kept and reused, so the connection to
the AI is ready – and "Hey Jarvis" opens it in advance (prewarm), while you are still speaking.

Tests and special transports (httpx.MockTransport) keep their own short-lived client as before.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)

_clients: dict[tuple[int, str, bool], httpx.AsyncClient] = {}
LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=8, keepalive_expiry=120)


def shared(verify: Any = True, trust_env: bool = True) -> httpx.AsyncClient:
    """The kept client for this event loop (made on first use)."""
    loop = asyncio.get_running_loop()
    key = (id(loop), "v" if verify is True else str(id(verify)), trust_env)
    c = _clients.get(key)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(verify=verify, trust_env=trust_env, limits=LIMITS, timeout=httpx.Timeout(120, connect=10))
        _clients[key] = c
    return c


@contextlib.asynccontextmanager
async def client(transport: Any = None, timeout: Any = None, verify: Any = True,
                 trust_env: bool = True) -> AsyncIterator[httpx.AsyncClient]:
    """`async with pool.client(...) as c:` – the kept client, or a fresh one for a custom transport (tests)."""
    if transport is not None:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, verify=verify, trust_env=trust_env) as c:
            yield c
        return
    yield shared(verify, trust_env)


async def warm(url: str, verify: Any = True, trust_env: bool = True, timeout: float = 4.0) -> bool:
    """Open (and keep) the connection to this AI now – a HEAD that only does TCP + TLS (any answer is fine)."""
    try:
        await shared(verify, trust_env).head(url, timeout=timeout)
        return True
    except httpx.HTTPError as e:
        log.debug("prewarm %s: %s", url, e)
        return False


async def close_all() -> None:
    for c in list(_clients.values()):
        with contextlib.suppress(Exception):
            await c.aclose()
    _clients.clear()
