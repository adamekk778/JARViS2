"""Focus guard (3.12): while focus is on (the focus mode or the "Fokus" mood), the notch blinks and the eyes frown when
YouTube, Netflix, TikTok, Instagram and the like come to the front. Only the name of the service goes to the notch –
never the window title – and nothing is blocked or closed: it is a nudge, the decision stays with you.
Turned off in Nastavení → Notch."""
from __future__ import annotations

import asyncio
import logging
import time

from . import nowplaying

log = logging.getLogger(__name__)

# services from nowplaying.source() that are a distraction (music is fine – many people focus with it)
_SOURCES = {"youtube": "YouTube", "netflix": "Netflix", "twitch": "Twitch", "kick": "Kick", "crunchyroll": "Crunchyroll",
            "hbomax": "Max", "vimeo": "Vimeo", "steam": "Steam"}
# social sites by the end of a browser tab title ("… • Instagram", "(3) Facebook", "Home / X")
_TITLES = (("tiktok", "TikTok"), ("instagram", "Instagram"), ("facebook", "Facebook"), ("reddit", "Reddit"),
           ("9gag", "9GAG"), ("pinterest", "Pinterest"), ("/ x", "X"), ("snapchat", "Snapchat"))
REPEAT_S = 90.0        # staying there: blink again after this long


def distraction(info: dict | None) -> str:
    """The distracting service in the foreground window ("YouTube", "Instagram"…) or ""."""
    if not info:
        return ""
    app, title = str(info.get("exe") or info.get("app") or ""), str(info.get("title") or "")
    src = nowplaying.source(app, title, fullscreen=bool(info.get("fullscreen")))
    if src in _SOURCES:
        return _SOURCES[src]
    if src == "browser":
        t = title.lower()
        for key, name in _TITLES:
            if key in t:
                return name
    return ""


def focus_active(rt, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    att = getattr(rt, "attention", None)
    mood = getattr(rt, "mood", None)
    return bool((att is not None and att.focus_until > now) or (mood is not None and getattr(mood, "manual", None) == "focus"))


class Guard:
    def __init__(self, rt, clock=time.time):
        self.rt, self.clock = rt, clock
        self.current, self.at = "", 0.0

    def check(self, info: dict | None) -> str | None:
        """One look at the foreground window; returns the service when the notch should blink now."""
        now = self.clock()
        if not getattr(self.rt.cfg.notch, "focus_guard", True) or not focus_active(self.rt, now):
            self.current = ""
            return None
        d = distraction(info)
        if not d:
            self.current = ""
            return None
        if d == self.current and now - self.at < REPEAT_S:
            return None
        self.current, self.at = d, now
        att = getattr(self.rt, "attention", None)
        left = max(0, round((att.focus_until - now) / 60)) if att is not None and att.focus_until > now else 0
        self.rt.bus.publish("focus_nudge", app=d, minutes_left=left)
        return d


async def loop(rt, interval: float = 2.0, rounds: int | None = None) -> None:
    guard = Guard(rt)
    n = 0
    while rounds is None or n < rounds:
        n += 1
        try:
            if focus_active(rt) and getattr(rt.cfg.notch, "focus_guard", True):
                info = await asyncio.to_thread(rt.platform.foreground_info)
                guard.check(info)
            else:
                guard.current = ""
        except Exception as e:  # noqa: BLE001
            log.debug("focus guard: %s", e)
        await asyncio.sleep(interval)
