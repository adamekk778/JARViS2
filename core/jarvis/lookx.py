"""3.20 Vzhled+ (nápady 101–120 ze stránky „Nápady pro JARVISe“) – what the notch, the wallpaper, the HUD and the desktop
effects get from the core. The drawing itself is in web/src/notch/x320.ts, web/src/wallpaper and web/src/hud.

- hlasitost kolečkem nad notchem (101, notch), naléhavé věci červeně (102), fotka ze stejného dne před lety (103)
- odpočet posledních 10 minut do schůzky (104), režim zen (105), roční období (106), vlastní témata (107)
- počasí za oknem v notchi (108), velikost podle monitoru (109), notch na každém monitoru (110)
- časová osa dne (111), Mochi se protáhne po dlouhé práci (112), ekvalizér nad hlavním panelem (113)
- HUD pro OBS (114), druhé hodiny na cestách (115), tři úkoly na tapetě (116), 3D postava místo notche (117)
- kroužek kolem kurzoru při sdílení obrazovky (118), nával upozornění jako jedna věta (119), startovní zvuk (120)
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import logging
import math
import random
import time
from collections import Counter
from typing import Any

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ (103) fotka ze stejného dne
def photo_of_day(rt: Any, today: dt.date | None = None, rng: random.Random | None = None) -> dict | None:
    today = today or dt.date.today()
    from . import memx

    rows = memx.db(rt).all("SELECT path, taken, place FROM mem_photos WHERE taken IS NOT NULL")
    same = [r for r in rows if (d := dt.date.fromtimestamp(r["taken"])).month == today.month and d.day == today.day and d.year < today.year]
    if not same:
        return None
    r = (rng or random).choice(same)
    years = today.year - dt.date.fromtimestamp(r["taken"]).year
    try:
        from PIL import Image

        with Image.open(r["path"]) as im:
            im.thumbnail((240, 240))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=80)
    except Exception as e:  # noqa: BLE001
        log.debug("photo of day: %s", e)
        return None
    cap = f"Před {years} {'rokem' if years == 1 else 'lety'}" + (f" – {r['place']}" if r["place"] else "")
    return {"img": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "caption": cap}


# ------------------------------------------------------------------ (104) odpočet, (111) časová osa
def next_meeting(rt: Any, now: float | None = None, within_min: int = 10) -> dict | None:
    from .proactx import upcoming_events

    now = now or time.time()
    ev = upcoming_events(rt, now, now + within_min * 60)
    return {"title": ev[0]["title"], "until": ev[0]["start"]} if ev else None


def day_timeline(rt: Any, day: dt.date | None = None) -> dict:
    from .proactx import upcoming_events

    day = day or dt.date.today()
    s = dt.datetime.combine(day, dt.time(0)).timestamp()
    evs = [{"title": e["title"], "start": e["start"], "end": e["end"] or e["start"] + 3600} for e in upcoming_events(rt, s, s + 86400)]
    return {"day_start": s + 7 * 3600, "day_end": s + 22 * 3600, "events": evs}


# ------------------------------------------------------------------ (108) počasí za oknem
def weather_scene(code: int | None, temp: float | None = None, hour: int | None = None) -> str:
    """Open-Meteo weather code → the notch's little scene: rain, snow, storm, fog, sun, clouds, night."""
    if code is None:
        return ""
    if code in (95, 96, 99):
        return "storm"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if code in (45, 48):
        return "fog"
    h = dt.datetime.now().hour if hour is None else hour
    if code <= 1:
        return "night" if h >= 21 or h < 6 else "sun"
    return "clouds"


# ------------------------------------------------------------------ (106) roční období
def season(day: dt.date | None = None) -> str:
    m = (day or dt.date.today()).month
    return "winter" if m in (12, 1, 2) else "spring" if m in (3, 4, 5) else "summer" if m in (6, 7, 8) else "autumn"


# ------------------------------------------------------------------ (107) vlastní témata
THEME_KEYS = ("accent", "bg", "text", "font", "speed", "radius")


def theme_clean(t: dict) -> dict:
    """Only safe values: #rrggbb colours, a known font, a speed 0.25–2, a radius 0–30 px."""
    import re

    out: dict[str, Any] = {"name": str(t.get("name") or "Moje téma")[:40]}
    for k in ("accent", "bg", "text"):
        v = str(t.get(k) or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            out[k] = v.lower()
    if str(t.get("font") or "") in ("system", "Inter", "Rajdhani", "Orbitron", "JetBrains Mono", "Georgia"):
        out["font"] = t["font"]
    try:
        out["speed"] = max(0.25, min(2.0, float(t.get("speed", 1))))
        out["radius"] = max(0, min(30, int(t.get("radius", 14))))
    except (TypeError, ValueError):
        pass
    return out


# ------------------------------------------------------------------ (115) druhé hodiny
COUNTRY_TZ = {"GB": "Europe/London", "UK": "Europe/London", "IE": "Europe/Dublin", "PT": "Europe/Lisbon", "US": "America/New_York",
              "CA": "America/Toronto", "JP": "Asia/Tokyo", "CN": "Asia/Shanghai", "TH": "Asia/Bangkok", "AE": "Asia/Dubai",
              "IN": "Asia/Kolkata", "AU": "Australia/Sydney", "NZ": "Pacific/Auckland", "BR": "America/Sao_Paulo", "MX": "America/Mexico_City",
              "TR": "Europe/Istanbul", "GR": "Europe/Athens", "FI": "Europe/Helsinki", "UA": "Europe/Kyiv", "EG": "Africa/Cairo",
              "SG": "Asia/Singapore", "KR": "Asia/Seoul", "IS": "Atlantic/Reykjavik", "CY": "Asia/Nicosia", "BG": "Europe/Sofia",
              "RO": "Europe/Bucharest"}


def trip_clock(rt: Any, day: dt.date | None = None) -> dict | None:
    """On a trip to another time zone: its clock next to yours."""
    day = day or dt.date.today()
    try:
        rows = rt.db.all("SELECT city, country, start, end FROM bookings WHERE status != 'cancelled'")
    except Exception:  # noqa: BLE001
        return None
    for b in rows:
        if str(b["start"])[:10] <= day.isoformat() <= str(b["end"])[:10]:
            tz = COUNTRY_TZ.get(str(b["country"] or "").upper())
            if tz:
                return {"tz": tz, "label": b["city"] or tz.split("/")[-1]}
    return None


# ------------------------------------------------------------------ (112) Mochi se protáhne
def stretch_due(rt: Any, active_min: float) -> bool:
    """After 90 minutes of work in a row (once per stretch of work)."""
    if active_min < 90:
        rt.lookx_stretched = False
        return False
    if getattr(rt, "lookx_stretched", False):
        return False
    rt.lookx_stretched = True
    return True


# ------------------------------------------------------------------ (119) nával upozornění
class Burst:
    """4+ notices within 90 s: the rest of the burst is held and comes as one line ("5 upozornění: Máma (2), Alza…")."""

    WINDOW = 90.0
    LIMIT = 4

    def __init__(self) -> None:
        self.times: list[float] = []
        self.held: list[str] = []
        self.flush_at = 0.0

    def add(self, title: str, now: float | None = None) -> bool:
        """True = show it now; False = held for the summary."""
        now = now or time.time()
        self.times = [t for t in self.times if now - t < self.WINDOW] + [now]
        if self.held or len(self.times) > self.LIMIT:
            self.held.append(title)
            self.flush_at = now + 20
            return False
        return True

    def due(self, now: float | None = None) -> bool:
        return bool(self.held) and (now or time.time()) >= self.flush_at

    def summary(self) -> tuple[str, str]:
        c = Counter(self.held)
        self.held = []
        n = sum(c.values())
        parts = [f"{k} ({v})" if v > 1 else k for k, v in c.most_common(6)]
        return f"{n} {'upozornění' if n >= 5 else 'další upozornění'}", ", ".join(parts)


# ------------------------------------------------------------------ (120) startovní zvuk
def startup_wav(sr: int = 24000) -> bytes:
    """A short original rising chord (about 0.9 s) – JARVIS is online."""
    import wave

    import numpy as np

    notes = [(523.25, 0.0), (659.25, 0.12), (783.99, 0.24), (1046.5, 0.36)]
    n = int(sr * 0.95)
    t = np.arange(n) / sr
    y = np.zeros(n, np.float32)
    for f, start in notes:
        env = np.clip((t - start) * 30, 0, 1) * np.exp(-np.clip(t - start, 0, None) * 3.2)
        y += (0.16 * np.sin(2 * math.pi * f * t) + 0.04 * np.sin(4 * math.pi * f * t)) * env * (t >= start)
    y = np.clip(y, -0.9, 0.9)
    pcm = (y * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def startup_sound_ok(rt: Any, hour: int | None = None) -> bool:
    if not getattr(rt.cfg.appearance, "startup_sound", True):
        return False
    h = dt.datetime.now().hour if hour is None else hour
    return 7 <= h < 22


# ------------------------------------------------------------------ (118) sdílení obrazovky
SHARING = ("sdilite", "sdileni obrazovky", "is sharing", "you are sharing", "screen sharing", "presenting", "prezentujete",
           "zoom share", "sharing your screen", "sdilis")


def sharing_screen(titles: list[str]) -> bool:
    from .pcx import fold

    return any(any(s in fold(t) for s in SHARING) for t in titles)


# ------------------------------------------------------------------ the loop: what the notch / wallpaper get
async def tick(rt: Any, now: float | None = None) -> list[str]:
    from . import proactx

    now = now or time.time()
    sent: list[str] = []
    bus = rt.bus
    day = dt.date.fromtimestamp(now)
    m = next_meeting(rt, now)
    if m and proactx.once(rt, f"countdown_{m['title']}_{int(m['until'])}", "1"):
        bus.publish("countdown", kind="meeting", title=m["title"], until=m["until"])
        sent.append("countdown")
    if int(now) % 900 < 60 or not getattr(rt, "lookx_sent_once", False):
        rt.lookx_sent_once = True
        bus.publish("day_timeline", **day_timeline(rt, day))
        h = proactx.now_hour(rt, dt.datetime.fromtimestamp(now))
        scene = weather_scene(h.get("weather_code"), h.get("temperature_2m"), dt.datetime.fromtimestamp(now).hour) if h else ""
        bus.publish("weather_now", scene=scene, temp=h.get("temperature_2m") if h else None)
        clock = trip_clock(rt, day)
        bus.publish("second_clock", **(clock or {"tz": getattr(rt.cfg.notch, "second_tz", "") or "", "label": ""}))
        try:
            pins = [r["text"] for r in rt.db.all("SELECT text FROM pinned ORDER BY created LIMIT 3")]
        except Exception:  # noqa: BLE001
            pins = []
        bus.publish("wallpaper_tasks", items=pins)
        sent += ["day_timeline", "weather_now", "second_clock", "wallpaper_tasks"]
    hh = dt.datetime.fromtimestamp(now).hour
    if 10 <= hh < 20 and getattr(rt.cfg.notch, "photo_frame", True) and proactx.once(rt, "photo_frame", day.isoformat()):
        p = photo_of_day(rt, day)
        if p:
            bus.publish("photo_frame", **p)
            sent.append("photo_frame")
    return sent
