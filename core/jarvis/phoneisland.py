"""3.12 Notch na telefonu: what the phone's island shows – one small, cheap answer the phone asks for every few
seconds while its screen is on (and JARVIS is not open on it)."""
from __future__ import annotations

import time

WORDS = {"thinking": "Přemýšlí…", "working": "Pracuje…", "speaking": "Mluví", "listening": "Poslouchá", "waiting": "Čeká na tebe"}


def state(rt) -> dict:
    """{kind, text, sub}: the most important thing right now, like the PC's notch does (one line, no history)."""
    mood = ""
    try:
        mood = (rt.mood.current() or {}).get("mood", "")
    except Exception:  # noqa: BLE001
        pass
    if getattr(getattr(rt, "pc_control", None), "on", False):
        return {"kind": "control", "text": "JARVIS ovládá PC", "sub": ""}
    dl = getattr(rt, "device_listen", None)
    if dl is not None and dl.on:
        return {"kind": "rec", "text": "Poslouchá PC", "sub": f"{dl.words()} slov"}
    if getattr(getattr(rt, "agent", None), "busy", False) or mood in WORDS:
        return {"kind": "ai", "text": WORDS.get(mood, "Pracuje…"), "sub": ""}
    try:
        timers = sorted(rt.timers.list(), key=lambda t: t.get("remaining", 0))
    except Exception:  # noqa: BLE001
        timers = []
    if timers:
        r = int(timers[0].get("remaining", 0))
        return {"kind": "timer", "text": f"{r // 60}:{r % 60:02d}", "sub": str(timers[0].get("label", ""))[:24]}
    media = getattr(rt, "media_state", None) or {}
    if media.get("playing") and media.get("title"):
        return {"kind": "music", "text": str(media["title"])[:32], "sub": str(media.get("artist", ""))[:24]}
    return {"kind": "idle", "text": "", "sub": "", "ts": time.time()}
