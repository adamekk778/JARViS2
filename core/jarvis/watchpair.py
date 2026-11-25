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
    """What the tile shows: the most useful line right now – a payment waiting for you (approved only on the phone, with
    the fingerprint – the watch has none), the next trip, a print, parcels, the last notice."""
    lines: list[str] = []
    try:
        from . import trust

        info = getattr(getattr(rt, "agent", None), "confirm_info", {}) or {}
        if any(trust.is_money(str(c.get("tool") or "")) for c in info.values()):
            lines.append("Potvrď platbu v telefonu")
    except Exception:  # noqa: BLE001
        pass
    try:
        lines += [x for x in [next_trip(rt)] if x]
    except Exception:  # noqa: BLE001
        pass
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


def next_trip(rt: Any, now: float | None = None) -> str:
    """3.19 the tile: "Let FR 1234 za 3 h · gate B12" or "Hotel Roma zítra" (within two days)."""
    import datetime as dt

    now = now or time.time()
    best: tuple[float, str] | None = None
    try:
        from . import travel

        for t in travel.upcoming(rt, now, days=2):
            info = t.get("info") or {}
            hours = (float(t["dep"]) + 60 * int(info.get("delay_min") or 0) - now) / 3600
            when = f"za {max(0, round(hours))} h" if hours < 20 else "zítra"
            extra = f" · gate {info['gate']}" if info.get("gate") else (f" · +{info['delay_min']} min" if info.get("delay_min") else "")
            cand = (float(t["dep"]), f"{'Let' if t['kind'] == 'flight' else 'Vlak'} {t['number']} {when}{extra}")
            best = cand if best is None or cand[0] < best[0] else best
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import booking

        today = dt.date.fromtimestamp(now)
        for b in booking.bookings(rt):
            if b["kind"] != "hotel" or b["status"] != "confirmed":
                continue
            try:
                day = dt.date.fromisoformat(str(b["start"])[:10])
            except ValueError:
                continue
            if 0 <= (day - today).days <= 1:
                ts = dt.datetime.combine(day, dt.time(15)).timestamp()
                cand = (ts, f"{b['name'][:22]} {'dnes' if day == today else 'zítra'}")
                best = cand if best is None or cand[0] < best[0] else best
    except Exception:  # noqa: BLE001
        pass
    return best[1] if best else ""
