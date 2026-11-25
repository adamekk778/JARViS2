"""3.20 Telefon + Hodinky (nápady 121–160 ze stránky „Nápady pro JARVISe“).

Telefon:
- NFC štítky: ťukneš telefonem a stane se, co sis k štítku nastavil (121)
- dlaždice v rychlém nastavení: ztlumit / zamknout PC (122), režim v autě (123), telefon jako touchpad (124)
- nabíjení v levné hodině přes chytrou zásuvku a hlídání 80 % (125, 137), telefon jako mikrofon (126)
- zapomenutý telefon (127), mobilní data (128), offline povely (129 – jen pravidla, žádný model)
- tichá hodina: Nerušit na spánek a schůzky (130), účtenka (131 – finance), stav na zamčené obrazovce (132)
- hlasitost PC v oznámení (133), roaming podle země (134), sken do PDF (135), telefon jako webkamera (136)
- dovolená (138), sdílení polohy na čas (139), poznámka po hovoru (140 – Android nedovolí nahrávat hovory)

Hodinky:
- vibrační kódy (141), ovládání PC (142), tep při hraní (143), vibrace při zmínce jména (144), minutka (145)
- poklepání při sezení (146), tempo běhu vibracemi (147), platba – hodinky ji otevřou v telefonu (148)
- navigace vibracemi (149), detekce pádu → nouzový protokol (150), komplikace na ciferníku (151 – ne celý ciferník)
- stres z tepu (152 – odhad, ne lékařské měření), BLE hrudní pás (153), tichý budík (154), prezentér (155)
- pitný režim podle pohybu (156), najdi hodinky (157), JARVIS jako asistent (158), titulky pro brýle (159),
  deník tréninků (160)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import ipaddress
import json
import logging
import re
import secrets as pysecrets
import time
import unicodedata
import uuid
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS phx_nfc (tag TEXT PRIMARY KEY, command TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS phx_hr (ts REAL, bpm INT, source TEXT, ctx TEXT);
CREATE TABLE IF NOT EXISTS phx_workouts (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, start REAL, minutes REAL, km REAL,
  hr_avg INT, hr_max INT, note TEXT);
CREATE TABLE IF NOT EXISTS phx_locshare (token TEXT PRIMARY KEY, until REAL, lat REAL, lon REAL, ts REAL, acc REAL, name TEXT);
CREATE TABLE IF NOT EXISTS phx_callnotes (id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT, text TEXT, ts REAL);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_phonex_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._phonex_ready = True
    return rt.db


def _cfg(rt: Any) -> Any:
    return getattr(rt.cfg, "mobx", None)


def _on(rt: Any, name: str, default: bool = True) -> bool:
    c = _cfg(rt)
    return bool(getattr(c, name, default)) if c is not None else default


def _kv(rt: Any, k: str) -> str | None:
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (k,))
    return str(row["v"]) if row else None


def _kv_set(rt: Any, k: str, v: str) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))


# ------------------------------------------------------------------ (141) hodinky: spojení a vibrační kódy
VIBES: dict[str, list[int]] = {        # Android vibration timings: wait, buzz, wait, buzz… (ms)
    "message": [0, 80, 120, 80],                 # ťuk-ťuk: zpráva
    "meeting": [0, 450],                         # jedno dlouhé: schůzka / kalendář
    "urgent": [0, 600, 200, 600, 200, 600],      # tři dlouhá: důležité
    "timer": [0, 250, 150, 250, 150, 250],       # minutka
    "name": [0, 60, 80, 60, 80, 60],             # tři krátké: někdo tě zmínil
    "sit": [0, 120, 350, 120],                   # dvě jemná: protáhni se
    "left": [0, 150, 150, 150],                  # navigace: vlevo dvakrát
    "right": [0, 150, 150, 150, 150, 150],       # vpravo třikrát
    "arrive": [0, 700],
    "slow": [0, 300],                            # běh: přidej
    "fast": [0, 90, 90, 90],                     # běh: zvolni
    "alarm": [0, 800, 400, 800, 400, 800, 400, 800],
    "find": [0, 500, 250, 500, 250, 500],
    "phone": [0, 600, 150, 150, 150, 600],       # telefon zůstal pozadu
    "quiet": [0, 40],
}
VIBE_LEGEND = {"message": "ťuk-ťuk = zpráva", "meeting": "jedno dlouhé = schůzka", "urgent": "tři dlouhá = důležité",
               "timer": "tři střední = minutka", "name": "tři krátké = někdo tě zmínil", "sit": "dvě jemná = protáhni se",
               "left": "dvě = doleva", "right": "tři = doprava", "phone": "dlouhé-krátké-dlouhé = telefon zůstal pozadu"}
WATCH_FRESH_S = 90


class WatchLink:
    """The watch long-polls /api/watch/events (like the phone's link): vibrations, timers, routes, alarms."""

    def __init__(self) -> None:
        self.queue: deque[dict] = deque(maxlen=40)
        self.last_poll = 0.0
        self._wake = asyncio.Event()

    def alive(self) -> bool:
        return time.time() - self.last_poll < WATCH_FRESH_S

    def push(self, kind: str, text: str = "", vibe: str = "", **data: Any) -> dict:
        ev = {"id": uuid.uuid4().hex[:10], "kind": kind, "text": text[:160], "ts": time.time(),
              "pattern": VIBES.get(vibe or kind, VIBES["quiet"] if not vibe else VIBES["message"]), **data}
        self.queue.append(ev)
        try:
            self._wake.set()
        except RuntimeError:
            pass
        return ev

    async def poll(self, wait: float = 25.0) -> list[dict]:
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
        return out


def watch(rt: Any) -> WatchLink:
    w = getattr(rt, "watch_link", None)
    if w is None:
        w = WatchLink()
        rt.watch_link = w
    return w


def vibe_for(title: str, body: str, kind: str = "", urgent: bool = False) -> str:
    t = fold(f"{title} {body}")
    if urgent or kind in ("emergency", "security"):
        return "timer" if "casovac" in t or "minutk" in t else "urgent"
    if re.search(r"schuzk|kalendar|meeting|udalost", t):
        return "meeting"
    if re.search(r"protahn|pitn|sklenic|prestavk", t):
        return "sit"
    return "message"


def on_notice(rt: Any, title: str, body: str, kind: str = "", urgent: bool = False) -> bool:
    """Every JARVIS notice: when you are away from the PC (or it is urgent) the watch taps the matching code."""
    if not _on(rt, "watch_vibes"):
        return False
    w = getattr(rt, "watch_link", None)
    if w is None or not w.alive():
        return False
    away = False
    try:
        away = bool(rt.user_away())
    except Exception:  # noqa: BLE001
        pass
    if not (urgent or away):
        return False
    w.push("notice", f"{title}: {body}"[:160], vibe_for(title, body, kind, urgent))
    return True


# ------------------------------------------------------------------ (127) zapomenutý telefon – podle sítě, odkud se ozývá
def net_of(ip: str) -> str:
    """'home' = the request came over the home network, 'away' = from outside (mobile data, Tailscale, a relay)."""
    try:
        a = ipaddress.ip_address((ip or "").split("%")[0])
    except ValueError:
        return "unknown"
    if a.is_loopback:
        return "home"
    if a in ipaddress.ip_network("100.64.0.0/10"):       # Tailscale – out of the house (or forced on)
        return "away"
    return "home" if a.is_private else "away"


def seen(rt: Any, device: str, ip: str, now: float | None = None) -> None:
    nets = getattr(rt, "phx_nets", None)
    if nets is None:
        nets = rt.phx_nets = {}
    nets[device] = (net_of(ip), now or time.time())


def forgotten_check(rt: Any, now: float | None = None) -> str:
    """The watch talks from outside while the phone still talks from home → "Telefon zůstal doma" on the wrist."""
    if not _on(rt, "forgotten_phone"):
        return ""
    now = now or time.time()
    nets = getattr(rt, "phx_nets", {}) or {}
    w, p = nets.get("watch"), nets.get("phone")
    if not w or not p or w[0] != "away" or p[0] != "home":
        return ""
    if now - w[1] > 300 or now - p[1] > 240:
        return ""
    last = float(_kv(rt, "phx_forgot") or 0)
    if now - last < 2 * 3600:
        return ""
    _kv_set(rt, "phx_forgot", str(now))
    text = "Telefon zůstal doma – hodinky jsou venku, telefon pořád na domácí síti."
    watch(rt).push("notice", text, "phone")
    return text


# ------------------------------------------------------------------ (134) roaming podle země, (128) mobilní data
EU = set("at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se is li no".split())
COUNTRY = {
    "cz": ("Česko", "Kč", "CZ/FR (E)", 0, "112"), "sk": ("Slovensko", "€", "E/F", 0, "112"), "de": ("Německo", "€", "F", 0, "112"),
    "at": ("Rakousko", "€", "F", 0, "112"), "pl": ("Polsko", "zł", "E", 0, "112"), "hu": ("Maďarsko", "Ft", "F", 0, "112"),
    "hr": ("Chorvatsko", "€", "F", 0, "112"), "it": ("Itálie", "€", "F/L", 0, "112"), "es": ("Španělsko", "€", "F", 0, "112"),
    "fr": ("Francie", "€", "E", 0, "112"), "gr": ("Řecko", "€", "F", 1, "112"), "pt": ("Portugalsko", "€", "F", -1, "112"),
    "gb": ("Spojené království", "£", "G", -1, "999 / 112"), "ch": ("Švýcarsko", "CHF", "J", 0, "112"),
    "us": ("USA", "$", "A/B", -6, "911"), "tr": ("Turecko", "TRY", "F", 2, "112"), "eg": ("Egypt", "EGP", "C/F", 1, "122 / 112"),
    "ae": ("Spojené arabské emiráty", "AED", "G", 3, "999"), "th": ("Thajsko", "THB", "A/B/C/O", 6, "191 / 1155"),
    "jp": ("Japonsko", "JPY", "A/B", 8, "110 / 119"), "nl": ("Nizozemsko", "€", "F", 0, "112"), "si": ("Slovinsko", "€", "F", 0, "112"),
    "me": ("Černá Hora", "€", "F", 0, "112"), "al": ("Albánie", "ALL", "F", 0, "112"), "rs": ("Srbsko", "RSD", "F", 0, "112"),
    "ba": ("Bosna a Hercegovina", "BAM", "F", 0, "112"), "mk": ("Severní Makedonie", "MKD", "F", 0, "112"),
}


def roaming_text(cc: str, home: str = "cz") -> str:
    cc, home = (cc or "").lower()[:2], (home or "cz").lower()
    if not cc or cc == home:
        return ""
    name, cur, plug, tz, sos = COUNTRY.get(cc, (cc.upper(), "", "", None, "112"))
    if cc in EU and home in EU:
        roam = "Roaming jako doma (EU) – volání, SMS i data za domácí ceny (u dat platí limit podle tarifu)."
    else:
        roam = "Pozor, mimo EU – data v roamingu můžou být hodně drahá. Zvaž vypnutí dat v roamingu nebo místní eSIM."
    extra = []
    if cur and cur != "Kč":
        extra.append(f"měna {cur}")
    if plug and "F" not in plug.split("/") and "E" not in plug.split("/"):
        extra.append(f"zásuvky typ {plug} – vezmi adaptér")
    if tz:
        extra.append(f"čas {'+' if tz > 0 else ''}{tz} h oproti nám")
    extra.append(f"tísňová linka {sos}")
    return f"Vítej v zemi {name}. {roam} " + ", ".join(extra).capitalize() + "."


def on_country(rt: Any, cc: str) -> str:
    cc = (cc or "").lower()[:2]
    if not re.fullmatch(r"[a-z]{2}", cc) or not _on(rt, "roaming_info"):
        return ""
    last = _kv(rt, "phx_country")
    if last == cc:
        return ""
    _kv_set(rt, "phx_country", cc)
    home = str(getattr(_cfg(rt), "home_country", "cz") or "cz")
    if last is None and cc == home:
        return ""
    text = roaming_text(cc, home) if cc != home else "Vítej zpátky doma – roaming skončil."
    if text:
        rt.notify("Roaming", text, speak=False, target="mobile")
        rt.phone_push("notify", title="Roaming", body=text[:400])
    return text


def on_data(rt: Any, mb_month: int, today: dt.date | None = None) -> str:
    """Mobile data used this month (MB, from the phone): a warning at 80 % and at 100 % of your limit, once each."""
    limit_gb = float(getattr(_cfg(rt), "data_limit_gb", 0) or 0)
    if limit_gb <= 0 or mb_month < 0:
        return ""
    today = today or dt.date.today()
    pct = mb_month / (limit_gb * 1024) * 100
    mark = 100 if pct >= 100 else 80 if pct >= 80 else 0
    if not mark:
        return ""
    key = f"{today:%Y-%m}:{mark}"
    if _kv(rt, "phx_data") == key or (mark == 80 and (_kv(rt, "phx_data") or "").startswith(f"{today:%Y-%m}:100")):
        return ""
    _kv_set(rt, "phx_data", key)
    left = max(0.0, limit_gb - mb_month / 1024)
    text = (f"Mobilní data: vyčerpáno {pct:.0f} % ({mb_month / 1024:.1f} z {limit_gb:g} GB)."
            + (" Zbývá {:.1f} GB do konce měsíce.".format(left) if mark == 80 else " Další data můžou stát navíc – přepni na Wi-Fi."))
    rt.notify("Mobilní data", text, speak=False, target="mobile")
    rt.phone_push("notify", title="Mobilní data", body=text)
    return text


def on_poll(rt: Any, ip: str = "", country: str = "", mdata: int | None = None) -> None:
    seen(rt, "phone", ip)
    if country:
        on_country(rt, country)
    if mdata is not None:
        on_data(rt, int(mdata))


# ------------------------------------------------------------------ (125, 137) nabíjení: levná hodina a 80 %
async def _plug(rt: Any, on: bool) -> bool:
    ent = str(getattr(_cfg(rt), "charger_plug", "") or "")
    if not ent or not getattr(getattr(rt, "home", None), "service", None):
        return False
    try:
        await rt.home.service("switch", "turn_on" if on else "turn_off", {"entity_id": ent})
        return True
    except Exception as e:  # noqa: BLE001
        log.info("charger plug: %s", e)
        return False


def charge_limit(rt: Any) -> int:
    return int(getattr(_cfg(rt), "charge_limit", 80) or 0)


async def on_battery(rt: Any, level: int, charging: bool, now: dt.datetime | None = None) -> str:
    """(137) charging reached the limit → "odpoj telefon" (and the smart plug goes off); (125) plugged in the evening
    outside the cheapest hour → the plug waits for the cheap hour (when you have a plug and spot prices)."""
    now = now or dt.datetime.now()
    lim = charge_limit(rt)
    st = getattr(rt, "phx_charge", None) or {}
    rt.phx_charge = st
    if not charging:
        st.pop("warned", None)
        return ""
    if lim and level >= lim and not st.get("warned"):
        st["warned"] = True
        off = await _plug(rt, False)
        text = f"Telefon má {level} %. " + ("Vypnul jsem zásuvku nabíječky – baterii to prospěje." if off
                                            else "Odpoj ho, baterii prospívá držet se do 80 %.")
        rt.notify("Telefon nabitý", text, speak=False)
        rt.phone_push("notify", title="Nabito na " + str(level) + " %", body=text, quiet=True)
        return text
    if (getattr(_cfg(rt), "charger_plug", "") and getattr(_cfg(rt), "cheap_charging", True) and now.hour >= 19
            and level < max(30, lim - 20) and not st.get("planned")):
        try:
            from . import energy

            items = await energy.prices(rt)
            hours = max(1, round((lim - level) / 40 + 0.4))
            win = energy.cheapest_window(items, hours, now, now.replace(hour=7, minute=0) + dt.timedelta(days=1))
        except Exception as e:  # noqa: BLE001
            log.info("charge plan: %s", e)
            win = None
        if win and win.get("start") and win["start"] > now + dt.timedelta(minutes=30):
            st["planned"] = win["start"].timestamp()
            await _plug(rt, False)
            text = f"Nabíjení telefonu počká na levnou hodinu – zásuvku zapnu v {win['start']:%H:%M}."
            rt.notify("Levné nabíjení", text, speak=False)
            return text
    return ""


async def charge_tick(rt: Any, now: float | None = None) -> bool:
    st = getattr(rt, "phx_charge", None) or {}
    at = st.get("planned")
    if at and (now or time.time()) >= at:
        st.pop("planned", None)
        return await _plug(rt, True)
    return False


# ------------------------------------------------------------------ (121) NFC štítky
TAG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


def tag_id(name: str) -> str:
    t = re.sub(r"[^a-z0-9_-]+", "-", fold(name)).strip("-")[:40]
    if not t:
        raise ValueError("Pojmenuj štítek (třeba „kuchyn“ nebo „auto“).")
    return t


def nfc_bind(rt: Any, name: str, command: str) -> dict:
    tag = tag_id(name)
    command = command.strip()[:300]
    if not command:
        raise ValueError("Co má štítek udělat? Napiš to jako povel pro JARVISe.")
    db(rt).exec("INSERT OR REPLACE INTO phx_nfc VALUES (?,?,?)", (tag, command, time.time()))
    return {"tag": tag, "command": command, "uri": f"jarvis://tag/{tag}"}


def nfc_list(rt: Any) -> list[dict]:
    return [dict(r) for r in db(rt).all("SELECT tag, command, ts FROM phx_nfc ORDER BY tag")]


def nfc_remove(rt: Any, name: str) -> bool:
    tag = tag_id(name)
    had = db(rt).one("SELECT tag FROM phx_nfc WHERE tag=?", (tag,))
    db(rt).exec("DELETE FROM phx_nfc WHERE tag=?", (tag,))
    return bool(had)


async def on_nfc(rt: Any, tag: str) -> str:
    """The phone touched a JARVIS tag (an NFC sticker with jarvis://tag/<name>): run what you set for it. Dangerous
    actions still ask, exactly as when you say them."""
    tag = (tag or "").strip().lower()
    if not TAG_RE.match(tag):
        return "Neznámý štítek."
    row = db(rt).one("SELECT command FROM phx_nfc WHERE tag=?", (tag,))
    if not row:
        _kv_set(rt, "phx_nfc_new", tag)
        text = f"Štítek „{tag}“ zatím nic nedělá. Řekni třeba: „štítek {tag} = zhasni v kuchyni“."
        rt.notify("NFC štítek", text, speak=False, target="mobile")
        return text
    out = await rt.agent.handle(str(row["command"]), [], "mobile", extra_system=f"Povel spustil NFC štítek „{tag}“ u telefonu.")
    return str(out or "Hotovo.").strip()


# ------------------------------------------------------------------ (122, 133, 142, 148, 155) akce PC z telefonu a hodinek
PC_ACTIONS = {"mute": "Ztlumit", "unmute": "Zapnout zvuk", "lock": "Zamknout PC", "vol_up": "Hlasitěji", "vol_down": "Tišeji",
              "play_pause": "Pauza / přehrát", "next": "Další skladba", "prev": "Předchozí skladba",
              "next_slide": "Další snímek", "prev_slide": "Předchozí snímek", "open_payment": "Platba v telefonu",
              "find_phone": "Najít telefon", "find_watch": "Najít hodinky"}


async def pc_action(rt: Any, action: str) -> tuple[bool, str]:
    p = rt.platform
    a = (action or "").strip()
    if a not in PC_ACTIONS:
        return False, "Neznámá akce."
    try:
        if a in ("mute", "unmute"):
            await asyncio.to_thread(p.set_mute, a == "mute")
            return True, "Ztlumeno." if a == "mute" else "Zvuk zapnut."
        if a in ("vol_up", "vol_down"):
            cur = await asyncio.to_thread(p.get_volume)
            new = max(0, min(100, int(cur) + (10 if a == "vol_up" else -10)))
            await asyncio.to_thread(p.set_volume, new)
            return True, f"Hlasitost {new} %."
        if a == "lock":
            await asyncio.to_thread(p.power, "lock")
            return True, "PC je zamčené."
        if a in ("play_pause", "next", "prev"):
            await asyncio.to_thread(p.media_key, {"play_pause": "play_pause", "next": "next", "prev": "previous"}[a])
            return True, PC_ACTIONS[a]
        if a in ("next_slide", "prev_slide"):
            await asyncio.to_thread(p.hotkey, ["right"] if a == "next_slide" else ["left"])
            return True, PC_ACTIONS[a]
        if a == "open_payment":
            return open_payment(rt)
        if a == "find_phone":
            ok = rt.phone_push("find")
            return ok, "Telefon zvoní." if ok else "Telefon teď není připojený."
        if a == "find_watch":
            return find_watch(rt)
    except NotImplementedError:
        return False, "Tohle tenhle počítač neumí."
    except Exception as e:  # noqa: BLE001
        return False, f"Nepovedlo se: {e}"
    return False, "Neznámá akce."


def open_payment(rt: Any) -> tuple[bool, str]:
    """(148) the watch has no fingerprint: a payment waiting for you opens on the phone, where you approve it."""
    from . import trust

    info = getattr(getattr(rt, "agent", None), "confirm_info", {}) or {}
    pay = [c for c in info.values() if trust.is_money(str(c.get("tool") or ""))]
    if not pay:
        return False, "Žádná platba nečeká."
    c = max(pay, key=lambda x: x.get("ts", 0))
    ok = rt.phone_push("confirm", cid=c["id"], text=str(c.get("description") or "")[:300], title="Platba čeká na tebe",
                       yes="Zaplatit")
    return ok, "Otevřel jsem ji v telefonu – potvrď otiskem." if ok else "Telefon teď není připojený."


def find_watch(rt: Any) -> tuple[bool, str]:
    w = getattr(rt, "watch_link", None)
    if w is None or not w.alive():
        return False, "Hodinky teď nejsou připojené (spojení se zapíná v aplikaci na hodinkách)."
    w.push("find", "Tady jsem!", "find")
    return True, "Hodinky vibrují a pípají."


# ------------------------------------------------------------------ (123) režim v autě
def is_car(rt: Any, name: str) -> bool:
    names = [fold(n) for n in (getattr(_cfg(rt), "car_names", []) or []) if n]
    n = fold(name)
    if not n:
        return False
    if names:
        return any(x in n for x in names)
    return bool(re.search(r"\b(car|auto|carplay|android auto|skoda|vw|volkswagen|toyota|hyundai|kia|ford|bmw|audi|"
                          r"mercedes|renault|peugeot|seat|cupra|tesla|mazda|volvo|my car|sync|uconnect|mylink)\b", n))


def on_bt(rt: Any, name: str, on: bool) -> bool | None:
    """The phone connected to / left a Bluetooth device. A car → driving mode on / off. Returns the new state or None."""
    if not _on(rt, "drive_mode") or not is_car(rt, name):
        return None
    was = bool(getattr(rt, "driving", False))
    rt.driving = bool(on)
    if was != rt.driving:
        rt.bus.publish("driving", on=rt.driving, car=name[:40])
        from .carx import on_driving

        on_driving(rt, rt.driving)                      # 3.20 (404) the logbook, (409) where you parked
        if rt.driving:
            rt.phone_push("notify", title="Režim v autě", body="Mluv se mnou hlasem – zprávy ti přečtu, nic nečti z displeje.",
                          quiet=True)
    return rt.driving


DRIVE_RULE = ("Uživatel právě řídí auto: odpovídej jednou dvěma krátkými větami k přečtení nahlas, bez seznamů, čísel "
              "navíc a odkazů. Nic, co by musel číst nebo potvrzovat na displeji; když to jde, nabídni to na později.")


def drive_line(rt: Any) -> str:
    return DRIVE_RULE if getattr(rt, "driving", False) else ""


# ------------------------------------------------------------------ (130) tichá hodina – Nerušit na spánek a schůzky
def _window(spec: str, clock: dt.datetime) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*-\s*(\d{1,2})[:.](\d{2})\s*", spec or "")
    if not m:
        return False
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    t = clock.hour * 60 + clock.minute
    return a <= t < b if a < b else (t >= a or t < b)


def quiet_reason(rt: Any, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    if _window(str(getattr(_cfg(rt), "quiet_sleep", "") or ""), now):
        return "spánek"
    if _on(rt, "quiet_meetings"):
        from .proactx import upcoming_events

        ts = now.timestamp()
        for e in upcoming_events(rt, ts - 8 * 3600, ts):
            if float(e["start"]) <= ts < float(e.get("end") or e["start"]):
                return f"schůzka {e['title']}"[:60]
    return ""


def dnd_tick(rt: Any, now: dt.datetime | None = None) -> str | None:
    """Turns the phone's Do Not Disturb on for sleep / a meeting and back off after (only when it changes)."""
    why = quiet_reason(rt, now)
    want = bool(why)
    was = getattr(rt, "phx_dnd", None)
    if was == want:
        return None
    rt.phx_dnd = want
    if was is None and not want:
        return None
    rt.phone_push("dnd", on=want, why=why)
    return why or "off"


# ------------------------------------------------------------------ (132, 133) stav na zamčené obrazovce s hlasitostí PC
def status_line(rt: Any, now: float | None = None) -> str:
    now = now or time.time()
    parts: list[str] = []
    try:
        from .proactx import upcoming_events

        nxt = upcoming_events(rt, now, now + 12 * 3600)[:1]
        if nxt:
            parts.append(f"{dt.datetime.fromtimestamp(float(nxt[0]['start'])):%H:%M} {nxt[0]['title']}"[:40])
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import watchpair

        line = watchpair.status(rt).get("line", "")
        if line and line != "Ťukni a zeptej se":
            parts.append(line)
    except Exception:  # noqa: BLE001
        pass
    if getattr(rt, "driving", False):
        parts.insert(0, "Režim v autě")
    if vacation_on(rt):
        parts.insert(0, "Dovolená")
    return " · ".join(parts[:3]) or "JARVIS je připravený"


def lock_tick(rt: Any, now: float | None = None) -> str | None:
    if not _on(rt, "lock_status", False):
        return None
    line = status_line(rt, now)
    if getattr(rt, "phx_lock_line", None) == line:
        return None
    rt.phx_lock_line = line
    rt.phone_push("lock_status", line=line, controls=True)
    return line


# ------------------------------------------------------------------ (138) dovolená
def vacation(rt: Any, on: bool, until: str = "") -> str:
    if on:
        day = ""
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", until or "") or re.search(r"(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}))?", until or "")
        if m and "-" in m.group(0):
            day = m.group(0)
        elif m:
            y = int(m.group(3)) if m.group(3) else dt.date.today().year
            d = dt.date(y, int(m.group(2)), int(m.group(1)))
            if d < dt.date.today():
                d = d.replace(year=y + 1)
            day = d.isoformat()
        rt.update_config({"day": {"vacation_until": day or (dt.date.today() + dt.timedelta(days=7)).isoformat()}})
        _kv_set(rt, "phx_vacation", "1")
        rt.bus.publish("vacation", on=True)
        until_s = rt.cfg.day.vacation_until
        return (f"Dovolená do {until_s}: posílám jen důležité, ranní souhrn bez práce, pracovní připomínky počkají. "
                "Automatizace „na dovolené“ se spustí.")
    rt.update_config({"day": {"vacation_until": ""}})
    _kv_set(rt, "phx_vacation", "0")
    rt.bus.publish("vacation", on=False)
    return "Vítej zpátky – dovolená skončila, vše běží jako dřív."


def vacation_on(rt: Any, today: dt.date | None = None) -> bool:
    until = str(getattr(getattr(rt.cfg, "day", None), "vacation_until", "") or "")
    if not until:
        return False
    try:
        return (today or dt.date.today()) <= dt.date.fromisoformat(until)
    except ValueError:
        return False


# ------------------------------------------------------------------ (139) sdílení polohy na čas
def share_start(rt: Any, minutes: int = 60, name: str = "") -> dict:
    minutes = max(5, min(int(minutes or 60), 24 * 60))
    token = pysecrets.token_urlsafe(16)
    until = time.time() + minutes * 60
    db(rt).exec("INSERT INTO phx_locshare VALUES (?,?,?,?,?,?,?)", (token, until, None, None, 0, None, name[:40]))
    sent = rt.phone_push("loc_share", token=token, minutes=minutes)
    base = str(getattr(rt.cfg.phone_link, "public_url", "") or "").rstrip("/")
    return {"token": token, "until": until, "minutes": minutes, "phone": sent,
            "url": f"{base}/share/loc/{token}" if base else f"/share/loc/{token}"}


def share_update(rt: Any, token: str, lat: float, lon: float, acc: float | None = None, now: float | None = None) -> bool:
    now = now or time.time()
    row = db(rt).one("SELECT until FROM phx_locshare WHERE token=?", (token,))
    if not row or float(row["until"]) < now:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    db(rt).exec("UPDATE phx_locshare SET lat=?, lon=?, ts=?, acc=? WHERE token=?", (lat, lon, now, acc, token))
    return True


def share_stop(rt: Any, token: str = "") -> int:
    if token:
        n = db(rt).one("SELECT COUNT(*) n FROM phx_locshare WHERE token=?", (token,))["n"]
        db(rt).exec("UPDATE phx_locshare SET until=0 WHERE token=?", (token,))
    else:
        n = db(rt).one("SELECT COUNT(*) n FROM phx_locshare WHERE until > ?", (time.time(),))["n"]
        db(rt).exec("UPDATE phx_locshare SET until=0 WHERE until > ?", (time.time(),))
    rt.phone_push("loc_share", token="", minutes=0)
    return int(n)


def share_page(rt: Any, token: str, now: float | None = None) -> str | None:
    """The page you send to someone: where you are (OpenStreetMap link) until the share ends – then nothing."""
    now = now or time.time()
    row = db(rt).one("SELECT * FROM phx_locshare WHERE token=?", (token,))
    if not row or float(row["until"]) < now:
        return None
    left = int((float(row["until"]) - now) // 60)
    if row["lat"] is None:
        body = "<p>Poloha zatím nedorazila – telefon ji pošle do minuty.</p>"
    else:
        lat, lon = float(row["lat"]), float(row["lon"])
        ago = int((now - float(row["ts"])) // 60)
        osm = f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=16/{lat:.5f}/{lon:.5f}"
        body = (f"<p class=big>{lat:.5f}, {lon:.5f}</p><p>aktualizováno před {ago} min"
                + (f", přesnost ±{int(row['acc'])} m" if row["acc"] else "") + "</p>"
                f"<p><a href=\"{html.escape(osm)}\" rel=noopener>Otevřít na mapě</a></p>")
    who = html.escape(str(row["name"] or "Moje poloha"))
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv=refresh content=60><title>{who}</title><style>body{{font:16px system-ui;margin:24px;"
            f"background:#0b0f14;color:#e8eef5}}a{{color:#4fc3ff}}.big{{font-size:22px;font-weight:700}}</style>"
            f"<h1>{who}</h1>{body}<p>Sdílení skončí za {left} min.</p>")


# ------------------------------------------------------------------ (140) poznámka po hovoru
def on_call_end(rt: Any, who: str) -> bool:
    if not _on(rt, "call_notes"):
        return False
    who = (who or "").strip()[:60] or "neznámé číslo"
    return rt.phone_push("notify", title=f"Hovor s {who} skončil", body="Chceš si k němu něco poznamenat? Napiš to sem.",
                         actions=[{"label": "Poznámka", "action": "call_note", "args": {"who": who}, "input": True}])


def save_call_note(rt: Any, who: str, text: str) -> int:
    text = (text or "").strip()[:2000]
    if not text:
        raise ValueError("Prázdná poznámka.")
    cur = db(rt).exec("INSERT INTO phx_callnotes (who, text, ts) VALUES (?,?,?)", ((who or "")[:60], text, time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def call_notes(rt: Any, who: str = "", limit: int = 20) -> list[dict]:
    if who:
        rows = db(rt).all("SELECT * FROM phx_callnotes ORDER BY ts DESC LIMIT 200")
        f = fold(who)
        return [dict(r) for r in rows if f in fold(r["who"])][:limit]
    return [dict(r) for r in db(rt).all("SELECT * FROM phx_callnotes ORDER BY ts DESC LIMIT ?", (limit,))]


# ------------------------------------------------------------------ (135) sken dokumentu do PDF
def scan_pdf(images: list[Path], out: Path, mode: str = "doc") -> Path:
    """Photos of pages → one PDF. mode 'doc' = grey and crisp like a scanner, 'bw' = black and white, 'color' = as is."""
    from PIL import Image, ImageOps

    if not images:
        raise ValueError("Žádné stránky.")
    pages = []
    for p in images[:40]:
        im = ImageOps.exif_transpose(Image.open(p))
        im.thumbnail((2480, 3508))
        if mode in ("doc", "bw"):
            g = ImageOps.autocontrast(im.convert("L"), cutoff=2)
            if mode == "bw":
                g = g.point(lambda v: 255 if v > 150 else 0, mode="1").convert("L")
            pages.append(g.convert("RGB"))
        else:
            pages.append(im.convert("RGB"))
    out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return out


# ------------------------------------------------------------------ (136) telefon jako webkamera
class CamFeed:
    """The phone's camera frames (JPEG) – the PC shows them at /api/phonecam.mjpg (an OBS browser source / a window)."""

    def __init__(self) -> None:
        self.frame = b""
        self.ts = 0.0
        self.cond: asyncio.Condition | None = None

    def put(self, jpeg: bytes) -> None:
        if not jpeg.startswith(b"\xff\xd8") or len(jpeg) > 3_000_000:
            raise ValueError("Tohle není JPEG snímek.")
        self.frame, self.ts = jpeg, time.time()

    def fresh(self) -> bool:
        return bool(self.frame) and time.time() - self.ts < 5


def camfeed(rt: Any) -> CamFeed:
    f = getattr(rt, "phx_cam", None)
    if f is None:
        f = rt.phx_cam = CamFeed()
    return f


# ------------------------------------------------------------------ (143, 152) tep: při hraní, stres
def add_hr(rt: Any, bpm: int, source: str = "watch", ctx: str = "", ts: float | None = None) -> dict:
    bpm = int(bpm)
    if not 30 <= bpm <= 230:
        raise ValueError("Nesmyslný tep.")
    ts = ts or time.time()
    if not ctx:
        ctx = "game" if getattr(rt, "game_active", False) or _game_running(rt) else ""
    db(rt).exec("INSERT INTO phx_hr VALUES (?,?,?,?)", (ts, bpm, source[:20], ctx[:20]))
    out = {"bpm": bpm, "ctx": ctx}
    if ctx == "game":
        rt.bus.publish("hr_now", bpm=bpm, ctx=ctx)            # the notch shows ♥ 128 while you play
        hi = high_streak(rt, ts)
        if hi and not getattr(rt, "phx_hr_warned", 0) > ts - 1800:
            rt.phx_hr_warned = ts
            rt.notify("Tep při hraní", f"Tep {bpm} už {hi} min – dej si chvilku, nadechni se.", speak=False)
            out["warned"] = True
    return out


def _game_running(rt: Any) -> bool:
    gs = getattr(rt, "game_state", None)
    return bool(gs and (gs.get("running") if isinstance(gs, dict) else getattr(gs, "running", False)))


def high_streak(rt: Any, now: float, limit: int = 130) -> int:
    """Minutes the heart rate has stayed above `limit` (≥ 10 min counts)."""
    rows = db(rt).all("SELECT ts, bpm FROM phx_hr WHERE ts >= ? ORDER BY ts DESC", (now - 3600,))
    start = None
    for r in rows:
        if int(r["bpm"]) < limit:
            break
        start = float(r["ts"])
    mins = int((now - start) // 60) if start else 0
    return mins if mins >= 10 else 0


def resting_hr(rt: Any, days: int = 14, now: float | None = None) -> float | None:
    now = now or time.time()
    vals = sorted(int(r["bpm"]) for r in db(rt).all("SELECT bpm FROM phx_hr WHERE ts >= ? AND ctx != 'workout'",
                                                      (now - days * 86400,)))
    if len(vals) < 12:
        return None
    return float(sum(vals[: max(3, len(vals) // 10)]) / max(3, len(vals) // 10))   # the lowest tenth


def stress(rt: Any, day: dt.date | None = None) -> dict:
    """An estimate from the heart rate above your resting rate while you are NOT exercising – not a medical measure
    (real stress scores need beat-to-beat HRV, which the watch does not give us)."""
    day = day or dt.date.today()
    rest = resting_hr(rt)
    start = dt.datetime.combine(day, dt.time()).timestamp()
    hours: dict[int, list[int]] = {}
    for r in db(rt).all("SELECT ts, bpm FROM phx_hr WHERE ts >= ? AND ts < ? AND ctx != 'workout'", (start, start + 86400)):
        hours.setdefault(dt.datetime.fromtimestamp(float(r["ts"])).hour, []).append(int(r["bpm"]))
    out = []
    for h in sorted(hours):
        avg = sum(hours[h]) / len(hours[h])
        level = None if rest is None else max(0, min(100, round((avg - rest) / max(rest * 0.5, 1) * 100)))
        out.append({"hour": h, "bpm": round(avg), "level": level})
    return {"day": day.isoformat(), "resting": None if rest is None else round(rest), "hours": out,
            "note": "Odhad z tepu nad klidovým tepem (bez cvičení) – není to lékařské měření."}


# ------------------------------------------------------------------ (153) BLE hrudní pás (PC přes bleak)
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_hr_measurement(data: bytes) -> tuple[int, list[int]]:
    """Bluetooth Heart Rate Measurement (0x2A37): flags, 8/16-bit bpm, optional energy, RR intervals (1/1024 s → ms)."""
    if not data:
        raise ValueError("prázdná data")
    flags = data[0]
    i = 1
    if flags & 0x01:
        bpm = int.from_bytes(data[i:i + 2], "little")
        i += 2
    else:
        bpm = data[i]
        i += 1
    if flags & 0x08:
        i += 2                                     # energy expended
    rr = []
    if flags & 0x10:
        while i + 1 < len(data):
            rr.append(round(int.from_bytes(data[i:i + 2], "little") * 1000 / 1024))
            i += 2
    return bpm, rr


async def ble_hr(rt: Any, address: str = "", seconds: int = 60) -> dict:
    """Reads a Bluetooth heart-rate belt for a while (Polar, Garmin HRM, Wahoo…). Needs `pip install bleak`."""
    try:
        from bleak import BleakClient, BleakScanner  # type: ignore[import-not-found]
    except ImportError:
        return {"ok": False, "message": "Chybí knihovna bleak (pip install bleak)."}
    if not address:
        devs = await BleakScanner.discover(timeout=6.0, service_uuids=["0000180d-0000-1000-8000-00805f9b34fb"])
        if not devs:
            return {"ok": False, "message": "Žádný hrudní pás v dosahu – navlhči ho a nasaď."}
        address = devs[0].address
    got: list[int] = []
    rrs: list[int] = []

    def on(_h: Any, data: bytearray) -> None:
        bpm, rr = parse_hr_measurement(bytes(data))
        got.append(bpm)
        rrs.extend(rr)
        try:
            add_hr(rt, bpm, "ble")
        except ValueError:
            pass

    async with BleakClient(address) as c:
        await c.start_notify(HR_UUID, on)
        await asyncio.sleep(max(5, min(seconds, 3600)))
        await c.stop_notify(HR_UUID)
    if not got:
        return {"ok": False, "message": "Pás neposlal žádný tep."}
    rmssd = None
    if len(rrs) > 3:
        d = [(rrs[k + 1] - rrs[k]) ** 2 for k in range(len(rrs) - 1)]
        rmssd = round((sum(d) / len(d)) ** 0.5)
    return {"ok": True, "address": address, "avg": round(sum(got) / len(got)), "max": max(got), "samples": len(got),
            "rmssd_ms": rmssd, "message": f"Průměr {round(sum(got) / len(got))}, max {max(got)}"
            + (f", HRV (RMSSD) {rmssd} ms" if rmssd else "")}


# ------------------------------------------------------------------ (144) zmínka jména
def my_names(rt: Any) -> set[str]:
    """Your own name(s): the first name from Nastavení → Obecné (+ its short forms you add), never other people's."""
    names = set()
    first = fold(str(getattr(rt.cfg.general, "user_name", "") or "")).split(" ")[0]
    if len(first) >= 3:
        names.add(first)
    names |= {fold(n) for n in (getattr(_cfg(rt), "my_names", []) or []) if len(fold(n)) >= 3}
    return names


def mentions_name(rt: Any, text: str) -> bool:
    t = fold(text)
    # the stem + a Czech ending (Adam, Adame, Adamovi, Adamem…)
    return any(re.search(rf"\b{re.escape(n)}\w{{0,4}}\b", t) for n in my_names(rt))


def on_message(rt: Any, item: dict) -> bool:
    """(144) a group message on the phone mentions you by name → three quick taps on the wrist."""
    if not _on(rt, "name_mentions") or not item.get("messaging"):
        return False
    text = str(item.get("text") or "")
    if not mentions_name(rt, text):
        return False
    w = getattr(rt, "watch_link", None)
    if w is None or not w.alive():
        return False
    w.push("notice", f"{item.get('title') or item.get('app')}: {text}"[:160], "name")
    return True


# ------------------------------------------------------------------ (145) minutka, (146) sezení, (154) tichý budík, (157)
def watch_timer(rt: Any, seconds: int, label: str = "Časovač") -> bool:
    w = getattr(rt, "watch_link", None)
    if w is None or not w.alive():
        return False
    w.push("timer", label, "quiet", until=time.time() + int(seconds), label=label[:40])
    return True


def watch_tap(rt: Any, vibe: str, text: str) -> bool:
    w = getattr(rt, "watch_link", None)
    if w is None or not w.alive():
        return False
    w.push("notice", text, vibe)
    return True


def schedule_silent_alarm(rt: Any, when: str, now: dt.datetime | None = None) -> dict:
    """A wake-up only on the wrist: the watch vibrates until you tap it – nobody else in the room wakes up."""
    from .voicex import parse_when

    at = parse_when(when, now)
    if at is None:
        raise ValueError("Ten čas už byl nebo mu nerozumím.")
    return rt.scheduler.add_once(at, "watch_alarm", {}, title=f"Tichý budík {at:%H:%M}")


def run_watch_alarm(rt: Any, payload: dict | None = None) -> str:
    w = getattr(rt, "watch_link", None)
    if w is not None and w.alive():
        w.push("alarm", "Dobré ráno", "alarm", repeat=True)
        return "watch"
    rt.phone_push("ring", text="Tichý budík – hodinky nebyly připojené, tak zvoní telefon.", caller="Budík")
    return "phone"


# ------------------------------------------------------------------ (147) tempo běhu, (149) navigace vibracemi
def pace_of(seconds: float, km: float) -> float:
    return seconds / km if km > 0 else 0.0


def pace_feedback(target_s_km: float, current_s_km: float, tolerance: float = 0.05) -> str:
    """'slow' (speed up), 'fast' (ease off) or 'ok' – the same rule runs on the watch."""
    if target_s_km <= 0 or current_s_km <= 0:
        return "ok"
    if current_s_km > target_s_km * (1 + tolerance):
        return "slow"
    if current_s_km < target_s_km * (1 - tolerance):
        return "fast"
    return "ok"


def parse_pace(text: str) -> int:
    """"5:30" / "5:30 min/km" / "5.5" → seconds per km."""
    m = re.search(r"(\d{1,2})[:.,](\d{1,2})", text or "")
    if m and ":" in m.group(0):
        return int(m.group(1)) * 60 + int(m.group(2))
    try:
        return int(float((text or "").replace(",", ".").split()[0]) * 60)
    except (ValueError, IndexError):
        raise ValueError("Tempo napiš třeba jako 5:30 (minut na kilometr).") from None


def parse_osrm(data: dict) -> list[dict]:
    """OSRM route → steps for the watch: where to turn (lat, lon), which way, the street, metres to it."""
    steps: list[dict] = []
    for leg in (data.get("routes") or [{}])[0].get("legs", []):
        for s in leg.get("steps", []):
            man = s.get("maneuver") or {}
            loc = man.get("location") or [0, 0]
            mod = str(man.get("modifier") or "")
            typ = str(man.get("type") or "")
            turn = "arrive" if typ == "arrive" else "left" if "left" in mod else "right" if "right" in mod else "straight"
            if typ == "depart":
                turn = "start"
            steps.append({"lat": round(float(loc[1]), 6), "lon": round(float(loc[0]), 6), "turn": turn,
                          "street": str(s.get("name") or "")[:40], "dist": round(float(s.get("distance") or 0))})
    return [s for s in steps if s["turn"] != "straight" or s is steps[-1]]


async def geocode(rt: Any, query: str) -> tuple[float, float] | None:
    async with rt.http() as c:
        r = await c.get("https://nominatim.openstreetmap.org/search", params={"q": query, "format": "json", "limit": 1},
                        headers={"User-Agent": "JARVIS-assistant"}, timeout=10)
    r.raise_for_status()
    items = r.json()
    return (float(items[0]["lat"]), float(items[0]["lon"])) if items else None


async def route(rt: Any, lat: float, lon: float, dest: str, mode: str = "foot") -> dict:
    to = await geocode(rt, dest)
    if not to:
        return {"ok": False, "message": f"Místo „{dest}“ jsem nenašel."}
    prof = {"foot": "routed-foot", "bike": "routed-bike", "car": "routed-car"}.get(mode, "routed-foot")
    url = f"https://routing.openstreetmap.de/{prof}/route/v1/driving/{lon},{lat};{to[1]},{to[0]}"
    async with rt.http() as c:
        r = await c.get(url, params={"steps": "true", "overview": "false"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    steps = parse_osrm(data)
    rt0 = (data.get("routes") or [{}])[0]
    out = {"ok": True, "to": dest, "steps": steps[:80], "km": round(float(rt0.get("distance") or 0) / 1000, 2),
           "minutes": round(float(rt0.get("duration") or 0) / 60)}
    w = getattr(rt, "watch_link", None)
    if w is not None and w.alive():
        w.push("route", f"{dest}: {out['km']} km", "quiet", steps=out["steps"])
    return out


# ------------------------------------------------------------------ (150) pád
async def on_fall(rt: Any, lat: float | None = None, lon: float | None = None) -> dict:
    """The watch saw a hard fall and you did not answer its 30-second question → the emergency protocol (it asks once
    more on the PC / phone before it writes to your emergency contacts)."""
    from . import safety

    where = f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}" if lat is not None and lon is not None else ""
    return await safety.emergency(rt).start(reason="hodinky zaznamenaly pád a neodpověděl jsi", where=where, wait=60)


# ------------------------------------------------------------------ (151) komplikace na ciferníku
def complication(rt: Any, now: float | None = None) -> dict:
    """SHORT_TEXT for a watch face: the next event's time, else a count of what waits, else "OK"."""
    now = now or time.time()
    try:
        from .proactx import upcoming_events

        e = upcoming_events(rt, now, now + 12 * 3600)[:1]
        if e:
            return {"short": f"{dt.datetime.fromtimestamp(float(e[0]['start'])):%H:%M}", "title": str(e[0]["title"])[:20]}
    except Exception:  # noqa: BLE001
        pass
    info = getattr(getattr(rt, "agent", None), "confirm_info", {}) or {}
    if info:
        return {"short": f"✓{len(info)}", "title": "Čeká potvrzení"}
    return {"short": "OK", "title": "JARVIS"}


# ------------------------------------------------------------------ (160) deník tréninků, (156) pitný režim podle pohybu
KINDS = {"run": "běh", "walk": "chůze", "bike": "kolo", "gym": "posilovna", "swim": "plavání", "other": "trénink"}


def add_workout(rt: Any, kind: str, minutes: float, km: float = 0, hr_avg: int = 0, hr_max: int = 0, note: str = "",
                start: float | None = None) -> dict:
    kind = kind if kind in KINDS else "other"
    minutes = max(0.0, min(float(minutes), 24 * 60))
    if minutes < 1:
        raise ValueError("Trénink kratší než minuta neukládám.")
    start = start or time.time() - minutes * 60
    cur = db(rt).exec("INSERT INTO phx_workouts (kind, start, minutes, km, hr_avg, hr_max, note) VALUES (?,?,?,?,?,?,?)",
                      (kind, start, minutes, float(km or 0), int(hr_avg or 0), int(hr_max or 0), note[:200]))
    pace = f", tempo {int(pace_of(minutes * 60, km) // 60)}:{int(pace_of(minutes * 60, km) % 60):02d}/km" if km and kind == "run" else ""
    return {"id": int(getattr(cur, "lastrowid", 0) or 0), "text": f"{KINDS[kind].capitalize()} {minutes:.0f} min"
            + (f", {km:.2f} km" if km else "") + pace + (f", tep ⌀ {hr_avg}" if hr_avg else "")}


def workouts(rt: Any, days: int = 30, now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [dict(r) for r in db(rt).all("SELECT * FROM phx_workouts WHERE start >= ? ORDER BY start DESC", (now - days * 86400,))]


def week_summary(rt: Any, now: float | None = None) -> str:
    ws = workouts(rt, 7, now)
    if not ws:
        return "Tento týden žádný trénink."
    mins = sum(float(w["minutes"]) for w in ws)
    km = sum(float(w["km"] or 0) for w in ws)
    kinds: dict[str, int] = {}
    for w in ws:
        kinds[KINDS.get(w["kind"], w["kind"])] = kinds.get(KINDS.get(w["kind"], w["kind"]), 0) + 1
    parts = ", ".join(f"{k} {v}×" for k, v in kinds.items())
    return f"Za 7 dní {len(ws)} tréninků ({parts}), celkem {mins:.0f} min" + (f" a {km:.1f} km." if km else ".")


def activity_factor(rt: Any, now: float | None = None) -> float:
    """< 1 = drink more often: a workout in the last 3 hours or a high heart rate lately."""
    now = now or time.time()
    try:
        recent = db(rt).one("SELECT COUNT(*) n FROM phx_workouts WHERE start + minutes*60 >= ?", (now - 3 * 3600,))["n"]
        hr = db(rt).one("SELECT AVG(bpm) a FROM phx_hr WHERE ts >= ?", (now - 1800,))["a"]
    except Exception:  # noqa: BLE001
        return 1.0
    if recent:
        return 0.6
    if hr and float(hr) >= 110:
        return 0.75
    return 1.0


# ------------------------------------------------------------------ the minute tick
async def tick(rt: Any, now: float | None = None) -> list[str]:
    out: list[str] = []
    checks = (("forgotten", lambda: forgotten_check(rt, now)), ("dnd", lambda: dnd_tick(rt)), ("lock", lambda: lock_tick(rt, now)))
    for name, fn in checks:
        try:
            if fn():
                out.append(name)
        except Exception as e:  # noqa: BLE001
            log.debug("phonex %s: %s", name, e)
    try:
        if await charge_tick(rt, now):
            out.append("charge")
    except Exception as e:  # noqa: BLE001
        log.debug("phonex charge: %s", e)
    return out


def snapshot(rt: Any) -> dict:
    w = getattr(rt, "watch_link", None)
    return {"watch": bool(w and w.alive()), "driving": bool(getattr(rt, "driving", False)), "vacation": vacation_on(rt),
            "nfc": nfc_list(rt), "legend": VIBE_LEGEND, "dnd": getattr(rt, "phx_dnd", None),
            "camera": camfeed(rt).fresh(), "workouts": week_summary(rt)}


def json_steps(steps: list[dict]) -> str:
    return json.dumps(steps, ensure_ascii=False)
