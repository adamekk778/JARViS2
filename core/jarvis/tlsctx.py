"""One TLS context for the whole process, created once at start-up.

Creating an SSL context the first time initialises OpenSSL and reads the Windows certificate store inside native code
that holds the GIL. On the CI Windows machine that ran at the same moment as the first keyring import (DLL loads) and
pywebview creating its window, and the whole process froze (hang-dump.txt, run 3.10.59). So the one-off native set-up
happens here, serially, before any other thread starts – and every HTTP client reuses the same context afterwards
(which is also faster: no certificate store per request)."""
from __future__ import annotations

import logging
import ssl
import threading

log = logging.getLogger(__name__)
_lock = threading.Lock()
_ctx: ssl.SSLContext | None = None


def context() -> ssl.SSLContext:
    global _ctx
    with _lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
        return _ctx


def warm_up() -> None:
    """Called from main() before the server, the UI and the background threads start."""
    context()
    try:
        from . import secrets

        secrets._keyring()          # the keyring backend detection imports win32 DLLs the first time
    except Exception as e:  # noqa: BLE001 – a missing keyring falls back to the file store later anyway
        log.debug("keyring warm-up: %s", e)
