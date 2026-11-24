"""3.18 Hodinky Wear OS (návrh 14): the JARVIS app on the watch pairs with a 6-digit code the PC shows (Nastavení →
Telefon → Spárovat hodinky), valid 5 minutes, at most 5 tries, used once. The watch then gets its own device key (it
appears among the paired devices and can be revoked alone) and asks JARVIS by voice; its tile shows a short status.
"""
from __future__ import annotations

import hmac
import secrets
import time
from typing import Any

CODE_S = 300
MAX_TRIES = 5


def start(rt: Any) -> dict:
    code = f"{secrets.randbelow(1_000_000):06d}"
    rt.watch_code = {"code": code, "until": time.time() + CODE_S, "tries": 0}
    from .server.pairing import local_ips

    lan, ts = local_ips()
    return {"code": code, "valid_s": CODE_S, "hosts": (lan + ts)[:4], "port": rt.cfg.phone.port}


def redeem(rt: Any, code: str, name: str = "Hodinky") -> tuple[str, str]:
    """(device token, '') or ('', why)."""
    st = getattr(rt, "watch_code", None)
    if not st or time.time() > st["until"]:
        rt.watch_code = None
        return "", "Kód vypršel – na PC dej znovu Spárovat hodinky."
    st["tries"] += 1
    if not hmac.compare_digest(str(code or "").strip(), st["code"]):
        if st["tries"] >= MAX_TRIES:
            rt.watch_code = None
            return "", "Příliš mnoho pokusů – na PC dej znovu Spárovat hodinky."
        return "", "Špatný kód."
    rt.watch_code = None                               # used once
    from . import mobileplus

    token, _dev = mobileplus.issue_device(rt, (name or "Hodinky")[:40])
    return token, ""


def status(rt: Any) -> dict:
    """What the tile shows: the most useful line right now."""
    lines: list[str] = []
    w = getattr(rt, "printer_watch", None)
    if w is not None and (w.last or {}).get("state") in ("printing", "paused"):
        s = w.last
        lines.append(f"Tisk {s.get('progress', 0):.0f} %" + (" (pauza)" if s.get("state") == "paused" else ""))
    try:
        from . import parcels

        ready = [p for p in parcels.listing(rt) if p["state"] == "ready"]
        if ready:
            lines.append(f"{len(ready)} balík{'y' if 1 < len(ready) < 5 else 'ů' if len(ready) >= 5 else ''} k vyzvednutí")
    except Exception:  # noqa: BLE001
        pass
    notices = list(getattr(rt, "notices", []) or [])[:1]
    if notices and time.time() - notices[0]["ts"] < 3600:
        lines.append(str(notices[0]["title"])[:40])
    return {"line": " · ".join(lines[:2]) or "Ťukni a zeptej se", "ts": int(time.time())}
