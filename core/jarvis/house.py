"""3.14 JARVIS v celém domě (návrhy 1, 7, 19–23) – like the films, not only in the PC:

- hlášení do reproduktorů: "večeře je hotová" on the speakers of the whole house or one room – in JARVIS's own voice
  (the speakers play it from this PC through Home Assistant; a speaker without that can use Home Assistant's own TTS)
- satelity v místnostech: Home Assistant voice satellites (ESP32 / HA Voice) use JARVIS as their brain – Home Assistant →
  Integrace → Ollama, adresa http://<PC>:8765/ha/<klíč>/<místnost> (see satellite routes in server/app.py)
- přítomnost: home or away by your phone (on the home Wi-Fi, or Home Assistant's person) – back home after a while →
  "Vítejte doma, pane. Zatímco jste byl pryč…" with what happened meanwhile
- následuj mě: JARVIS knows where you are (at the PC, in a room with a satellite, away with the phone) – a spoken notice
  goes there
- scény: "Vítej doma", "Kino", "Odchod", "Spánek" as protocols (PC + house in one word)
"""
from __future__ import annotations

import asyncio
import logging
import secrets as pysecrets
import socket
import time
from collections import OrderedDict
from typing import Any

log = logging.getLogger(__name__)
TTS_KEEP_S = 600
AWAY_MIN_S = 20 * 60          # away at least this long before a welcome
ROOM_FRESH_S = 180            # a satellite spoke this recently → you are in that room
_TTS: "OrderedDict[str, tuple[float, bytes, str]]" = OrderedDict()


def lan_ip() -> str:
    """This PC's address on the home network (where the speakers fetch JARVIS's voice from)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def keep_audio(audio: bytes, mime: str) -> str:
    """Kept for 10 minutes under an unguessable id: /tts/<id>.mp3 (the speaker fetches it once)."""
    now = time.time()
    for k in [k for k, v in _TTS.items() if now - v[0] > TTS_KEEP_S]:
        _TTS.pop(k, None)
    tid = pysecrets.token_urlsafe(18)
    _TTS[tid] = (now, audio, mime)
    while len(_TTS) > 30:
        _TTS.popitem(last=False)
    return tid


def audio_for(tid: str) -> tuple[bytes, str] | None:
    v = _TTS.get(tid)
    if not v or time.time() - v[0] > TTS_KEEP_S:
        return None
    return v[1], v[2]


def _fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)).strip()


def speakers_for(rt: Any, where: str) -> list[str]:
    h = rt.cfg.home
    rooms = dict(getattr(h, "room_speakers", {}) or {})
    w = (where or "all").strip().lower()
    if w in ("", "all", "vsude", "všude", "dum", "dům", "celý dům", "cely dum"):
        out = list(getattr(h, "speakers", []) or []) + [v for v in rooms.values()]
        return list(dict.fromkeys(out))
    hit = next((v for k, v in rooms.items() if _fold(k) == _fold(w) or _fold(w) in _fold(k)), "")
    return [hit] if hit else []


async def announce(rt: Any, text: str, where: str = "all") -> dict:
    """Say `text` on the house speakers (through Home Assistant)."""
    from . import home

    if not home.configured(rt):
        return {"ok": False, "message": "Na hlášení do reproduktorů potřebuju Home Assistant (Nastavení → Domov)."}
    targets = speakers_for(rt, where)
    if not targets:
        return {"ok": False, "message": "Nemám nastavené reproduktory – v Nastavení → Domov vyber, které reproduktory má JARVIS používat."}
    hm = getattr(rt, "home", None) or home.Home(rt)
    tts_entity = getattr(rt.cfg.home, "tts_entity", "")
    if tts_entity:                               # Home Assistant speaks it with its own voice
        await hm.service("tts", "speak", {"entity_id": tts_entity, "media_player_entity_id": targets, "message": text})
    else:                                        # JARVIS's own voice, fetched by the speakers from this PC
        if getattr(rt, "speaker", None) is None:
            return {"ok": False, "message": "Hlas JARVISe tu neběží – zadej v Nastavení → Domov hlas Home Assistantu (tts.…)."}
        audio, mime = await rt.speaker.synth(text, "cs")
        tid = keep_audio(audio, mime)
        ext = "mp3" if "mpeg" in mime else "wav"
        url = f"http://{lan_ip()}:{rt.cfg.phone.port}/tts/{tid}.{ext}"
        await hm.service("media_player", "play_media", {"entity_id": targets, "media_content_id": url,
                                                        "media_content_type": "music", "announce": True})
    return {"ok": True, "message": f"Hlásím: „{text}“", "speakers": targets}


# ---------- presence and "follow me" ----------
class House:
    def __init__(self, rt: Any):
        self.rt = rt
        self.home: bool | None = None
        self.left_at = 0.0
        self.room = ""
        self.room_at = 0.0

    def note_room(self, room: str) -> None:
        if room:
            self.room, self.room_at = room, time.time()

    def phone_home(self) -> bool:
        """Your phone is on the home network now (its app is connected locally)."""
        for c in (getattr(self.rt, "clients", {}) or {}).values():
            if c.get("client") == "mobile" and c.get("local"):
                return True
        phone = getattr(self.rt, "phone", None)
        try:
            return bool(phone and getattr(phone, "nearby", lambda: False)())
        except Exception:  # noqa: BLE001
            return False

    async def person_home(self) -> bool | None:
        """Home Assistant's person (if set): "home" / not."""
        ent = getattr(self.rt.cfg.home, "person_entity", "")
        if not ent:
            return None
        from . import home

        if not home.configured(self.rt):
            return None
        try:
            hm = getattr(self.rt, "home", None) or home.Home(self.rt)
            st = next((e for e in await hm.states() if e.get("entity_id") == ent), None)
        except Exception:  # noqa: BLE001
            return None
        return None if st is None else st.get("state") == "home"

    def where(self) -> str:
        """pc / room:<name> / phone / ""."""
        try:
            idle = float(self.rt.platform.idle_seconds())
        except Exception:  # noqa: BLE001
            idle = 1e9
        if idle < 120:
            return "pc"
        if self.room and time.time() - self.room_at < ROOM_FRESH_S:
            return f"room:{self.room}"
        if self.home is False:
            return "phone"
        return ""

    async def tick(self, now: float | None = None) -> str:
        """Home / away changed? → the welcome. Returns "arrived", "left" or ""."""
        now = now or time.time()
        person = await self.person_home()
        at_home = person if person is not None else self.phone_home()
        was = self.home
        self.home = at_home
        if was is None:
            if not at_home:
                self.left_at = now
            return ""
        if was != at_home:                       # the same moment as the phone's own "Domov" zone (reminders, automations)
            self.rt.bus.publish("phone_zone", event="enter" if at_home else "leave", zone="Domov", source="house")
        if was and not at_home:
            self.left_at = now
            return "left"
        if not was and at_home and now - self.left_at >= AWAY_MIN_S and getattr(self.rt.cfg.home, "welcome", True):
            await self.welcome(now)
            return "arrived"
        return ""

    def summary_since(self, since: float) -> list[str]:
        out = []
        notices = [n for n in list(getattr(self.rt, "notices", []) or []) if float(n.get("ts", 0)) >= since]
        if notices:
            titles = list(dict.fromkeys(n.get("title", "") for n in notices if n.get("title")))[:3]
            out.append(f"{len(notices)} upozornění" + (f" ({', '.join(titles)})" if titles else ""))
        return out

    async def welcome(self, now: float) -> str:
        from .stark import address, find_protocol, start_protocol

        away_min = int((now - self.left_at) / 60)
        bits = self.summary_since(self.left_at)
        line = f"Vítejte doma, {address(self.rt)}."
        if bits:
            line += " Zatímco jste byl pryč: " + ", ".join(bits) + "."
        elif away_min >= 60:
            line += " Během vaší nepřítomnosti se nic důležitého nestalo."
        proto = find_protocol(self.rt, "domu")
        if proto is not None and getattr(self.rt.cfg.home, "welcome_protocol", True):
            start_protocol(self.rt, proto)
        try:
            self.rt.speak(line)
        except Exception:  # noqa: BLE001
            pass
        self.rt.bus.publish("house", event="arrived", text=line)
        return line

    async def run(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001
                log.debug("house: %s", e)
            await asyncio.sleep(30)


def of(rt: Any) -> House:
    h = getattr(rt, "house", None)
    if h is None:
        h = rt.house = House(rt)
    return h


# ---------- scenes: PC + house in one word ----------
def scene_protocols() -> list:
    from .config import Protocol, ProtocolStep as S

    return [
        Protocol(id="domu", name="Vítej doma", icon="house-line", steps=[
            S(tool="home_scene", args={"name": "vítej doma"}),
            S(say="Vše je připraveno, pane.")]),
        Protocol(id="kino", name="Kino", icon="film-strip", steps=[
            S(tool="home_scene", args={"name": "kino"}),
            S(tool="volume", args={"action": "set", "level": 55}),
            S(say="Kino připraveno. Příjemnou zábavu, pane.")]),
        Protocol(id="odchod", name="Odchod", icon="door-open", steps=[
            S(tool="media_control", args={"action": "play_pause"}, when="playing"),
            S(tool="home_scene", args={"name": "odchod"}),
            S(say="Dům zabezpečen. Šťastnou cestu, pane.")]),
        Protocol(id="spanek", name="Spánek", icon="bed", steps=[
            S(tool="media_control", args={"action": "play_pause"}, when="playing"),
            S(tool="home_scene", args={"name": "spánek"}),
            S(tool="set_dark_mode", args={"dark": True}),
            S(say="Dobrou noc, pane. Zhasínám.")]),
    ]


def ensure_scenes(rt: Any) -> list[str]:
    """Adds the house scenes once (a protocol you deleted later is not brought back)."""
    rt.db.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    if rt.db.one("SELECT v FROM kv WHERE k='house_scenes'"):
        return []
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('house_scenes', '1')")
    have = {p.id for p in rt.cfg.stark.protocols}
    new = [p for p in scene_protocols() if p.id not in have]
    if new:
        rt.update_config({"stark": {"protocols": [p.model_dump() for p in rt.cfg.stark.protocols] + [p.model_dump() for p in new]}})
    return [p.id for p in new]
