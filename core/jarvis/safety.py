"""3.14 Ochrana a nouze (návrhy 8, 37–41) – the house and you looked after like in the films:

- ochrana PC: the guard (Hlídat PC) can also take a photo with the webcam when someone uses the PC while you are away;
  the photo comes to your phone's chat (opt-in, Nastavení → Bezpečí)
- kamery domu: Frigate (person detection, free, runs next to Home Assistant) – a person in a zone at night, at the
  door → a notice with the snapshot; the doorbell (a Home Assistant binary_sensor) → "Někdo zvoní" + the door camera
- nouzový protokol: "JARVIS, pomoc" / the SOS button on the phone → "Jsi v pořádku?" for 30 s, then a text message
  with your last known place to your emergency contacts; 112 only after you confirm (never by itself)
- týdenní bezpečnostní brífink: new devices on the home network, failed sign-ins to Windows, pending Windows updates,
  leaked e-mail addresses (Have I Been Pwned, with your own key)
- dětský režim: like the guest mode, plus no shopping, no locks / alarm, no deleting, no new apps, kind language
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)
EMERGENCY_WAIT_S = 30


# ---------------------------------------------------------------- the guard's photo
async def guard_photo(rt: Any, why: str) -> str:
    """A webcam photo for the guard → the phone's chat. Returns the attachment id ('' when not possible)."""
    if not getattr(rt.cfg.privacy, "guard_photo", False):
        return ""
    from . import webcam

    try:
        frame = await asyncio.to_thread(webcam.grab, int(getattr(rt.cfg.voice, "camera_index", 0) or 0))
        data = webcam.jpeg(frame)
    except Exception as e:  # noqa: BLE001
        log.info("guard photo: %s", e)
        return ""
    webcam.log_use(rt, "guard_photo", why)
    att = await rt.store.save(f"hlidani-{time.strftime('%Y%m%d-%H%M%S')}.jpg", data, "image/jpeg")
    msg = rt.memory.add_message("assistant", f"📷 {why}", attachments=[att.id], source="guard")
    rt.bus.publish("assistant_done", id=msg["id"], text=f"📷 {why}", tools=[], attachments=[att.public()])
    return att.id


# ---------------------------------------------------------------- house cameras (Frigate)
NIGHT = (22, 6)


def is_night(hour: int) -> bool:
    return hour >= NIGHT[0] or hour < NIGHT[1]


def interesting(ev: dict, watched: list[str], hour: int, away: bool) -> bool:
    """A Frigate event worth telling: a person; at night or while you are away everywhere, by day in the watched zones."""
    if ev.get("label") != "person" or ev.get("false_positive"):
        return False
    return is_night(hour) or away or bool(set(ev.get("zones") or []) & set(watched or []))


class Cameras:
    POLL_S = 10

    def __init__(self, rt: Any):
        self.rt = rt
        self.seen: set[str] = set()
        self.since = time.time()
        self.door_state = ""

    async def frigate_events(self) -> list[dict]:
        url = getattr(self.rt.cfg.home, "frigate_url", "").rstrip("/")
        if not url:
            return []
        async with self.rt.http() as c:
            r = await c.get(f"{url}/api/events", params={"after": int(self.since) - 5, "limit": 20, "include_thumbnails": 0}, timeout=8)
        r.raise_for_status()
        return [e for e in r.json() if isinstance(e, dict)]

    async def snapshot(self, ev: dict) -> bytes:
        url = getattr(self.rt.cfg.home, "frigate_url", "").rstrip("/")
        async with self.rt.http() as c:
            r = await c.get(f"{url}/api/events/{ev['id']}/snapshot.jpg", params={"bbox": 1}, timeout=8)
        return r.content if r.status_code == 200 else b""

    async def check(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        hour = time.localtime(now).tm_hour
        cfg = self.rt.cfg.home
        house = getattr(self.rt, "house", None)
        away = bool(house is not None and house.home is False)
        told = []
        for ev in await self.frigate_events():
            eid = str(ev.get("id") or "")
            if eid in self.seen:
                continue
            self.seen.add(eid)
            if not interesting(ev, getattr(cfg, "camera_zones", []), hour, away):
                continue
            zones = set(ev.get("zones") or [])
            where = ev.get("camera", "kamera") + (f" ({', '.join(sorted(zones))})" if zones else "")
            await self.tell(f"Osoba u kamery {where}.", await self.snapshot(ev))
            told.append(ev)
        self.since = now
        if len(self.seen) > 500:
            self.seen = set(list(self.seen)[-200:])
        return told

    async def doorbell(self) -> bool:
        """The doorbell's binary_sensor went "on" → "Někdo zvoní" with the door camera's picture."""
        ent = getattr(self.rt.cfg.home, "doorbell_entity", "")
        hm = getattr(self.rt, "home", None)
        if not ent or hm is None:
            return False
        st = next((e for e in await hm.states(fresh=True) if (e.get("id") or e.get("entity_id")) == ent), None)
        state = (st or {}).get("state", "")
        rang = state == "on" and self.door_state != "on"
        self.door_state = state
        if not rang:
            return False
        img = b""
        cam = getattr(self.rt.cfg.home, "door_camera", "")
        if cam:
            try:
                async with self.rt.http() as c:
                    r = await c.get(hm._url(f"/api/camera_proxy/{cam}"), headers=hm._headers(), timeout=8)
                img = r.content if r.status_code == 200 else b""
            except Exception:  # noqa: BLE001
                img = b""
        await self.tell("Někdo zvoní u dveří.", img, speak=True)
        return True

    async def tell(self, text: str, image: bytes = b"", speak: bool = False) -> None:
        att_id = ""
        if image:
            att = await self.rt.store.save(f"kamera-{time.strftime('%Y%m%d-%H%M%S')}.jpg", image, "image/jpeg")
            att_id = att.id
            msg = self.rt.memory.add_message("assistant", f"📷 {text}", attachments=[att_id], source="cameras")
            self.rt.bus.publish("assistant_done", id=msg["id"], text=f"📷 {text}", tools=[], attachments=[att.public()])
        self.rt.notify("Kamery", text, speak=speak, urgent=speak)
        self.rt.phone_push("notify", title="JARVIS – dům", body=text)

    async def run(self) -> None:
        await asyncio.sleep(25)
        while True:
            try:
                if getattr(self.rt.cfg.home, "frigate_url", ""):
                    await self.check()
                if getattr(self.rt.cfg.home, "doorbell_entity", ""):
                    await self.doorbell()
            except Exception as e:  # noqa: BLE001
                log.debug("cameras: %s", e)
            await asyncio.sleep(self.POLL_S)


def cameras(rt: Any) -> Cameras:
    c = getattr(rt, "cameras", None)
    if c is None:
        c = rt.cameras = Cameras(rt)
    return c


# ---------------------------------------------------------------- emergency
class Emergency:
    def __init__(self, rt: Any):
        self.rt = rt
        self.pending: asyncio.Task | None = None
        self.ok_event: asyncio.Event | None = None
        self.last: dict = {}

    def contacts(self) -> list[dict]:
        return [c for c in (getattr(self.rt.cfg.privacy, "emergency_contacts", []) or []) if isinstance(c, dict) and c.get("phone")]

    async def start(self, reason: str = "požádal jsi o pomoc", where: str = "", wait: float = EMERGENCY_WAIT_S) -> dict:
        if self.pending and not self.pending.done():
            return {"ok": True, "message": "Nouzový protokol už běží."}
        self.ok_event = asyncio.Event()
        self.last = {"reason": reason, "where": where, "started": time.time(), "sent": []}
        self.rt.notify("Nouzový protokol", f"Jsi v pořádku? ({reason}) Když do {int(wait)} s neodpovíš „jsem v pořádku“, napíšu "
                       "tvým nouzovým kontaktům.", speak=True, urgent=True,
                       actions=[{"label": "Jsem v pořádku", "action": "emergency_ok", "args": {}}])
        self.rt.phone_push("notify", title="Jsi v pořádku?", body=f"JARVIS: {reason}. Ťukni, jestli jsi v pořádku.",
                           actions=[{"label": "Jsem v pořádku", "action": "emergency_ok", "args": {}}])
        self.pending = asyncio.get_running_loop().create_task(self._countdown(wait))
        # 3.15 the phone shows the countdown full screen (red rings, "Jsem v pořádku")
        self.rt.bus.publish("emergency_state", active=True, until=time.time() + wait, reason=reason, sent=[])
        return {"ok": True, "message": f"Nouzový protokol: čekám {int(wait)} s, jestli jsi v pořádku."}

    def cancel(self) -> bool:
        if self.ok_event is not None:
            self.ok_event.set()
        running = bool(self.pending and not self.pending.done())
        return running

    async def _countdown(self, wait: float) -> None:
        assert self.ok_event is not None
        try:
            await asyncio.wait_for(self.ok_event.wait(), wait)
            self.rt.notify("Nouzový protokol", "Dobře, ruším. Jsem rád, že jsi v pořádku.", speak=True, urgent=True)
            self.rt.bus.publish("emergency_state", active=False, until=0, reason="", sent=[])
            return
        except asyncio.TimeoutError:
            pass
        await self.alert()

    def message(self) -> str:
        name = self.rt.cfg.general.user_name or "Uživatel"
        where = self.last.get("where") or "poloha neznámá"
        return (f"JARVIS (asistent {name}): {name} možná potřebuje pomoc – {self.last.get('reason', '')}. "
                f"Na otázku, jestli je v pořádku, neodpověděl. Poloha: {where}. Zkuste mu zavolat.")

    async def alert(self) -> list[str]:
        sent = []
        text = self.message()
        for c in self.contacts():
            try:
                ok = self.rt.phone_push("sms", to=c["phone"], text=text)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                sent.append(c.get("name") or c["phone"])
        self.last["sent"] = sent
        self.rt.bus.publish("emergency_state", active=False, until=0, reason=self.last.get("reason", ""), sent=sent, alerted=True)
        self.rt.notify("Nouzový protokol", ("Napsal jsem: " + ", ".join(sent)) if sent else
                       "Nemám komu napsat – nastav nouzové kontakty (Nastavení → Bezpečí) a telefon s JARVISem.",
                       speak=True, urgent=True, actions=[{"label": "Volat 112", "action": "dial", "args": {"number": "112"}}])
        return sent


def emergency(rt: Any) -> Emergency:
    e = getattr(rt, "emergency", None)
    if e is None:
        e = rt.emergency = Emergency(rt)
    return e


# ---------------------------------------------------------------- the weekly security briefing
async def briefing(rt: Any) -> dict:
    """What is worth knowing about the safety of your devices this week."""
    out: dict = {"items": [], "ok": []}
    try:
        from . import network

        known = network.known(rt)
        if known:                                     # only once JARVIS has a list to compare with
            new = [d for d in await network.devices(rt) if d.get("mac") and network.norm_mac(d["mac"]) not in known]
            if new:
                out["items"].append(f"{len(new)} neznámá zařízení v síti: " + ", ".join(str(d.get("name") or d.get("ip")) for d in new[:4]))
            else:
                out["ok"].append("žádné neznámé zařízení v síti")
    except Exception:  # noqa: BLE001
        pass
    try:
        fails = await asyncio.to_thread(failed_logons, 7)
        if fails:
            out["items"].append(f"{fails}× neúspěšné přihlášení do Windows za týden")
        else:
            out["ok"].append("žádné neúspěšné přihlášení")
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import secrets

        key = secrets.get("hibp")
        emails = [a.address for a in rt.cfg.mail.accounts]
        if key and emails:
            leaks = await pwned(rt, key, emails)
            if leaks:
                out["items"].append("Únik dat: " + "; ".join(f"{e} ({', '.join(b[:3])})" for e, b in leaks.items()))
            else:
                out["ok"].append("e-maily nejsou v nových únicích")
    except Exception as e:  # noqa: BLE001
        log.debug("hibp: %s", e)
    return out


def failed_logons(days: int = 7) -> int:
    """Windows security log: failed sign-ins (event 4625) in the last days (needs the log to be readable)."""
    import subprocess
    import sys

    if sys.platform != "win32":
        return 0
    ps = (f"(Get-WinEvent -FilterHashtable @{{LogName='Security';Id=4625;StartTime=(Get-Date).AddDays(-{int(days)})}} "
          "-ErrorAction SilentlyContinue | Measure-Object).Count")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                       creationflags=0x08000000)
    try:
        return int((r.stdout or "0").strip() or 0)
    except ValueError:
        return 0


async def pwned(rt: Any, key: str, emails: list[str]) -> dict[str, list[str]]:
    """Have I Been Pwned: breaches for each e-mail address added in the last 60 days (your own HIBP key)."""
    from urllib.parse import quote

    out: dict[str, list[str]] = {}
    async with rt.http() as c:
        for e in emails[:10]:
            r = await c.get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(e)}", params={"truncateResponse": "false"},
                            headers={"hibp-api-key": key, "user-agent": "JARVIS-assistant"}, timeout=15)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            recent = [b.get("Name", "") for b in r.json() if str(b.get("AddedDate", ""))[:10] >= time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - 60 * 86400))]
            if recent:
                out[e] = recent
            await asyncio.sleep(6.5)                     # HIBP: about 10 requests a minute
    return out


# ---------------------------------------------------------------- kids mode
KIDS_RULE = ("Dětský režim: mluvíš s dítětem. Mluv laskavě, jednoduše a bezpečně, nic nevhodného (násilí, sex, drogy, "
             "strašidelné věci), žádné nákupy, žádné osobní údaje o rodičích. Na nevhodné dotazy řekni, ať se zeptá rodičů.")
KIDS_BLOCKED = {"app_install", "app_uninstall", "delete_files", "empty_trash", "system_power", "email_send", "email_reply",
                "phone_sms", "phone_call", "home_lock", "make_purchase", "fio_payment", "create_skill", "run_python",
                "run_powershell", "browser_type", "computer_use", "guest_access", "brain_switch", "persona_switch"}
KIDS_HOME_DOMAINS = ("lock", "alarm_control_panel", "climate")


def kids_on(rt: Any) -> bool:
    return bool(getattr(rt.cfg.privacy, "kids_mode", False))


def kids_blocks(rt: Any, tool: str, args: dict | None = None) -> str:
    """Why this tool is off in kids mode ('' = allowed)."""
    if not kids_on(rt):
        return ""
    if tool in KIDS_BLOCKED:
        return "V dětském režimu tohle nejde – zeptej se rodičů."
    if tool.startswith(("home_", "house_")):
        what = " ".join(str(v) for v in (args or {}).values()).lower()
        if any(d in what for d in ("zámek", "zamk", "odemk", "alarm", "lock", "topení", "termostat")):
            return "Zámky, alarm a topení v dětském režimu neovládám."
    return ""


async def weekly(rt: Any) -> None:
    """Sunday evening (after 19:00), once a week: the security briefing as a notice."""
    await asyncio.sleep(120)
    while True:
        try:
            lt = time.localtime()
            week = time.strftime("%G-%V", lt)
            rt.db.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
            done = rt.db.one("SELECT v FROM kv WHERE k='security_week'")
            if (getattr(rt.cfg.privacy, "security_weekly", True) and lt.tm_wday == 6 and lt.tm_hour >= 19
                    and (not done or done["v"] != week)):
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('security_week', ?)", (week,))
                b = await briefing(rt)
                text = ("Pozor: " + "; ".join(b["items"]) + ".") if b["items"] else "Tento týden je všechno v pořádku: " + ", ".join(b["ok"]) + "."
                rt.notify("Bezpečnostní brífink", text, speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("security weekly: %s", e)
        await asyncio.sleep(1800)
