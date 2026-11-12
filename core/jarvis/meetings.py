"""3.12 Chytrý režim schůzky: a call is noticed (Teams, Zoom, Meet, Discord, Slack, Webex – the app is using the
microphone, which Windows itself reports), the notch offers "Zapsat schůzku?", less important notices wait, and when
the call ends the recording stops by itself and the notes come with a summary and to-dos.

Nothing is recorded until you click "Zapsat" – the microphone is never switched on behind your back.
"""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

CALL_APPS = {"teams": "Teams", "ms-teams": "Teams", "msteams": "Teams", "zoom": "Zoom", "discord": "Discord", "slack": "Slack",
             "skype": "Skype", "webex": "Webex", "ciscocollabhost": "Webex", "whatsapp": "WhatsApp", "telegram": "Telegram"}
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc"}
OWN = ("jarvis", "python", "pythonw")          # JARVIS's own wake word uses the microphone all the time
MEET_TITLE = re.compile(r"(^Meet\b|Google Meet|meet\.google\.com|Jitsi|Whereby)", re.I)
EVERY_S = 8


def detect(rt) -> str:
    """The call app in use right now, or ""."""
    try:
        users = [u.removesuffix(".exe") for u in rt.platform.mic_users()]
    except Exception:  # noqa: BLE001
        return ""
    users = [u for u in users if not any(o in u for o in OWN)]
    for u in users:
        for key, label in CALL_APPS.items():
            if key in u:
                return label
    if any(b in u for u in users for b in BROWSERS):
        try:
            titles = rt.platform.list_windows() or []
        except Exception:  # noqa: BLE001
            titles = []
        if any(MEET_TITLE.search(str(t)) for t in titles):
            return "Google Meet"
        return "Hovor v prohlížeči"
    return ""


class Meetings:
    def __init__(self, rt):
        self.rt = rt
        self.app = ""                # the call going on now
        self.recording = False       # started from here (so its end stops it)
        self._seen = 0
        self._gone = 0

    @property
    def active(self) -> bool:
        return bool(self.app)

    def tick(self) -> None:
        app = detect(self.rt)
        if app:
            self._gone = 0
            self._seen += 1
            if not self.app and self._seen >= 2:           # two looks in a row: a real call, not a mic test
                self.app = app
                self.rt.bus.publish("meeting", state="started", app=app, recording=False)
        else:
            self._seen = 0
            if self.app:
                self._gone += 1
                if self._gone >= 3:                        # ~25 s without the call app on the mic: it ended
                    self.end()

    def end(self) -> None:
        app, self.app, self._gone = self.app, "", 0
        rec = self.recording
        self.recording = False
        if rec:
            nt = getattr(self.rt, "notetaker", None)
            if nt is not None and nt.state == "recording":
                nt.stop()                                  # transcript, summary and to-dos follow (Notetaker)
        self.rt.bus.publish("meeting", state="ended", app=app, recording=rec)

    def record(self, on: bool) -> dict:
        """Your click on "Zapsat" (or "Přestat")."""
        nt = getattr(self.rt, "notetaker", None)
        if nt is None:
            return {"ok": False, "message": "Zápis hovorů není dostupný."}
        if on:
            r = nt.start()
            self.recording = bool(r.get("ok"))
        else:
            r = nt.stop()
            self.recording = False
        self.rt.bus.publish("meeting", state="started" if self.app else "ended", app=self.app, recording=self.recording)
        return r


async def loop(rt) -> None:
    m = rt.meetings
    while True:
        await asyncio.sleep(EVERY_S)
        try:
            await asyncio.to_thread(m.tick)
        except Exception as e:  # noqa: BLE001
            log.debug("meetings: %s", e)
