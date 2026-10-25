"""3.4 phone link: JARVIS rings you, dials for you, sends SMS / WhatsApp, and hears about the messages on your phone.

The JARVIS app keeps a small background service on the phone (with a visible notification) that long-polls
/api/phone/poll. Commands go through it even when the app is closed; the app answers with /api/phone/ack, and its
notification listener (only if you allow it on the phone) posts to /api/phone/notification.

Optional fallback: a real phone call to your number through Twilio when the phone app cannot be reached.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Any

from . import secrets

log = logging.getLogger(__name__)

MESSAGING = {
    "com.whatsapp": "WhatsApp", "com.whatsapp.w4b": "WhatsApp Business", "com.facebook.orca": "Messenger",
    "org.telegram.messenger": "Telegram", "org.thoughtcrime.securesms": "Signal", "com.instagram.android": "Instagram",
    "com.google.android.apps.messaging": "SMS", "com.samsung.android.messaging": "SMS", "com.android.mms": "SMS",
    "com.snapchat.android": "Snapchat", "com.discord": "Discord", "com.viber.voip": "Viber",
    "com.google.android.dialer": "Telefon", "com.samsung.android.dialer": "Telefon", "com.android.dialer": "Telefon",
    "com.samsung.android.incallui": "Telefon",
}
LINK_FRESH_S = 75          # a poll within this window = the background link is alive


class PhoneLink:
    def __init__(self, rt):
        self.rt = rt
        self.queue: deque[dict] = deque(maxlen=50)
        self.pending: dict[str, dict] = {}        # sent to the phone, waiting for an ack
        self.notifications: deque[dict] = deque(maxlen=100)
        self.last_poll = 0.0
        self.battery: dict = {}           # 3.5: {"level": 54, "charging": False, "ts": …} from the phone's polls
        self._wake = asyncio.Event()
        self._acks: dict[str, asyncio.Future] = {}

    # ---------- state ----------
    def link_alive(self) -> bool:
        return time.time() - self.last_poll < LINK_FRESH_S

    def status(self) -> dict:
        return {"link": self.link_alive(), "last_poll": self.last_poll, "queued": len(self.queue),
                "twilio": twilio_ready(self.rt), "notifications": len(self.notifications), "battery": self.battery}

    def on_battery(self, level: int, charging: bool) -> None:
        """Every poll carries the phone's battery; JARVIS says once when it gets low (and not charging)."""
        level = max(0, min(100, int(level)))
        was = self.battery.get("level")
        self.battery = {"level": level, "charging": charging, "ts": time.time()}
        if charging or was is None:
            return
        for mark in (15, 5):
            if level <= mark < was:
                self.rt.notify("Telefon", f"Telefonu zbývá {level} % baterie. Dejte ho nabít.",
                               speak=self.rt.cfg.phone_link.speak, target="dashboard")
                break

    # ---------- commands to the phone ----------
    def send(self, kind: str, **data: Any) -> dict:
        cmd = {"id": uuid.uuid4().hex[:10], "kind": kind, "ts": time.time(), **data}
        self.queue.append(cmd)
        self._wake.set()
        # the app in the foreground hears it at once over the WebSocket; the background service picks it up from the queue
        if not self.link_alive():
            self.rt.bus.publish("phone_cmd", target="mobile", **cmd)
        return cmd

    async def poll(self, wait: float = 25.0) -> list[dict]:
        """Long-poll from the phone service: returns the queued commands (at most `wait` seconds)."""
        self.last_poll = time.time()
        if not self.queue:
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        self.last_poll = time.time()
        out = list(self.queue)
        self.queue.clear()
        for c in out:
            self.pending[c["id"]] = c
        return out

    def ack(self, cid: str, state: str = "done", detail: str = "") -> None:
        cmd = self.pending.pop(cid, None)
        fut = self._acks.get(cid)
        if fut and not fut.done():
            fut.set_result(state)
        if cmd is None:
            return
        self.rt.bus.publish("phone_ack", id=cid, kind=cmd["kind"], state=state, detail=detail)
        if cmd["kind"] == "ring":
            if state == "missed":
                self.rt.notify("Zmeškaný hovor", f"Nezvedl jste to. Vzkaz: {cmd.get('text', '')}", speak=False, target="dashboard")
            elif state == "reply" and detail:
                # you answered by voice on the phone → JARVIS goes on with it as a normal request
                asyncio.get_running_loop().create_task(self.rt.agent.handle(detail, [], "mobile_voice"))

    async def wait_ack(self, cid: str, timeout: float) -> str | None:
        fut = self._acks.setdefault(cid, asyncio.get_running_loop().create_future())
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._acks.pop(cid, None)

    # ---------- JARVIS calls you ----------
    async def ring(self, text: str, reason: str = "", wait: bool = False) -> dict:
        """Rings the phone like an incoming call; when answered, the phone says `text` and you can reply by voice.
        If the phone cannot be reached and Twilio is set up, a real call to your number says it instead."""
        cmd = self.send("ring", text=text, reason=reason, caller="JARVIS")
        self.rt.bus.publish("phone_ring", id=cmd["id"], text=text)
        if not wait:
            asyncio.get_running_loop().create_task(self._fallback_if_unreached(cmd))
            return {"id": cmd["id"], "via": "app"}
        state = await self.wait_ack(cmd["id"], 50)
        if state is None and twilio_ready(self.rt):
            sid = await twilio_call(self.rt, text)
            return {"id": cmd["id"], "via": "twilio", "call": sid}
        return {"id": cmd["id"], "via": "app", "state": state}

    async def _fallback_if_unreached(self, cmd: dict) -> None:
        state = await self.wait_ack(cmd["id"], 50)
        if state is None:
            if twilio_ready(self.rt):
                try:
                    await twilio_call(self.rt, cmd["text"])
                except Exception as e:
                    log.warning("twilio call failed: %s", e)
            else:
                self.rt.notify("Telefon nezvoní", "Aplikace JARVIS v telefonu se neozvala – je zapnutá a připojená?", speak=False,
                               target="dashboard")

    # ---------- the phone tells us ----------
    def on_notification(self, n: dict) -> dict | None:
        pkg = str(n.get("package", ""))
        app = MESSAGING.get(pkg) or str(n.get("app") or pkg)
        title, text = str(n.get("title", "")).strip(), str(n.get("text", "")).strip()
        if not (title or text) or pkg.startswith("cz.adamekk.jarvis"):
            return None
        item = {"app": app, "package": pkg, "title": title[:120], "text": text[:600], "ts": float(n.get("ts") or time.time()),
                "messaging": pkg in MESSAGING, "call": n.get("category") == "call" or app == "Telefon"}
        if self.notifications and self.notifications[0]["title"] == item["title"] and self.notifications[0]["text"] == item["text"]:
            return None         # the same message posted again (Android updates group notifications)
        self.notifications.appendleft(item)
        cfg = self.rt.cfg.phone_link
        self.rt.bus.publish("phone_notification", **item)
        if cfg.announce and (item["messaging"] or item["call"]):
            if item["call"]:
                body = f"Volá vám {item['title'] or 'někdo'}."
            else:
                body = f"{item['title']}: {item['text']}" if item["title"] else item["text"]
            self.rt.notify(f"{app} (telefon)", body[:240], speak=cfg.speak and self.rt.cfg.voice.speak_mode != "never",
                           target="dashboard")
        return item


# ---------------------------------------------------------------------------------------------- Twilio (optional)
def twilio_ready(rt) -> bool:
    c = rt.cfg.phone_link
    return bool(c.twilio_sid and c.twilio_from and c.my_number and secrets.get("twilio_token"))


def twiml_say(text: str) -> str:
    from xml.sax.saxutils import escape

    t = escape(text)
    return (f'<Response><Pause length="1"/><Say language="cs-CZ" voice="Google.cs-CZ-Standard-A">{t}</Say><Pause length="1"/>'
            f'<Say language="cs-CZ" voice="Google.cs-CZ-Standard-A">Opakuji. {t}</Say></Response>')


async def twilio_call(rt, text: str) -> str:
    """A real phone call to your own number that reads `text` (needs a Twilio account; it costs a few crowns)."""
    c = rt.cfg.phone_link
    async with rt.http() as h:
        r = await h.post(f"https://api.twilio.com/2010-04-01/Accounts/{c.twilio_sid}/Calls.json",
                         auth=(c.twilio_sid, secrets.get("twilio_token")),
                         data={"To": c.my_number, "From": c.twilio_from, "Twiml": twiml_say(text)}, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Twilio: {r.status_code} {r.text[:200]}")
    return r.json().get("sid", "")
