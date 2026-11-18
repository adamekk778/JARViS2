"""3.13 Velín: an address a service's webhook can call ("something new happened") – JARVIS then looks right away
instead of at its next minute. The call only wakes the look: what it carries is ignored (JARVIS reads the news from the
service itself, with your key), so a stranger who learned the address could at most make it look once more. The
address has a long random secret; "Nová adresa" makes the old one stop working.

A service can only call an address that is reachable from the internet over HTTPS with a real certificate (your own
domain, a Cloudflare / Tailscale tunnel to this PC). Without one, the minute-by-minute look does the job.
"""
from __future__ import annotations

import hmac
import secrets as _rand
from typing import Any

from . import secrets

KEY = "biz_hook_key"


def key(create: bool = True) -> str:
    k = secrets.get(KEY)
    if not k and create:
        k = _rand.token_urlsafe(24)
        secrets.set(KEY, k)
    return k


def renew() -> str:
    k = _rand.token_urlsafe(24)
    secrets.set(KEY, k)
    return k


def valid(given: str) -> bool:
    k = key(create=False)
    return bool(k) and hmac.compare_digest(str(given or ""), k)


def info(rt: Any) -> dict:
    host = ""
    try:
        host = (rt.cfg.link.public_host or "").strip()
    except AttributeError:
        pass
    path = f"/api/velin/hook/{key()}"
    return {"path": path, "url": f"https://{host}{path}" if host else "", "host": host}
