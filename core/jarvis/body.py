"""3.14 Zdraví jako ve filmu (návrhy 10, 42–44).

- Data z hodinek: the phone app reads Android's Health Connect – where Wear OS / Samsung / Pixel watches and the Garmin
  Connect, Fitbit and other apps write their numbers – and sends the day's steps, last night's sleep, resting heart
  rate, heart-rate variability, average heart rate and blood oxygen here. Kept only in JARVIS's own database on your
  PC (nothing goes anywhere else) for 400 days.
- Ranní „stav systémů“: last night and this morning against your own normal (the median of the last two weeks), then
  what that means for the day ("doporučuji lehčí den"), including today's planned workout.
- Hlídání přetížení u PC: a glass of water every N minutes, one notice after a very long day at the screen, a nudge
  to bed after the time you choose and – only when you switch it on – posture from the webcam (leaning in too close,
  slumped low). Each one is off until you set it, except the long-day notice.

Not a medical device: it compares you with yourself and says so in plain words; with a worrying number it suggests
a doctor, nothing more.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import statistics
import time
from typing import Any

log = logging.getLogger("jarvis.body")

# field → (lowest, highest) a real reading can have; anything outside is a glitch and is dropped
FIELDS: dict[str, tuple[float, float]] = {
    "steps": (0, 200_000), "sleep_h": (0.5, 16), "rest_hr": (25, 150), "hrv": (5, 300), "hr": (30, 220), "spo2": (70, 100),
}
GROWING = {"steps", "sleep_h"}        # the phone counts more as the day goes on: a smaller number never replaces a bigger one
BASE_DAYS, BASE_MIN = 14, 4           # "your normal" = the median of the last 14 days, once there are at least 4
KEEP_DAYS = 400

PRESENT_IDLE_S = 120                  # input in the last 2 minutes = you are at the PC
BREAK_IDLE_S = 5 * 60                 # 5 minutes away = a real break
POSTURE_EVERY_S = 120
POSTURE_BAD_IN_ROW = 3                # three checks in a row (about 6 minutes) before saying anything
POSTURE_REPEAT_S = 30 * 60
CLOSE_RATIO = 1.22                    # the face 22 % wider than when you sat well = you lean in to the screen
LOW_SHIFT = 0.12                      # the face lower by 12 % of the picture = slumped in the chair


def _db(rt: Any) -> Any:
    rt.db.exec("CREATE TABLE IF NOT EXISTS body_day (day TEXT PRIMARY KEY, steps REAL, sleep_h REAL, rest_hr REAL, "
               "hrv REAL, hr REAL, spo2 REAL, updated REAL)")
    return rt.db


def _num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def clean(vals: dict) -> dict:
    """Only real numbers in a real range."""
    out = {}
    for k, (lo, hi) in FIELDS.items():
        v = _num(vals.get(k))
        if v is not None and lo <= v <= hi:
            out[k] = round(v, 1) if k != "steps" else float(int(v))
    return out


def record(rt: Any, day: str | None = None, **vals: Any) -> dict:
    """Store what the phone sent for a day; returns what was actually stored (new or changed values)."""
    d = day or dt.date.today().isoformat()
    dt.date.fromisoformat(d)
    new = clean(vals)
    if not new:
        return {}
    db = _db(rt)
    row = db.one("SELECT * FROM body_day WHERE day=?", (d,))
    old = dict(row) if row else {}
    keep = {}
    for k, v in new.items():
        if k in GROWING and (old.get(k) or 0) >= v:
            continue
        if old.get(k) == v:
            continue
        keep[k] = v
    if not keep:
        return {}
    merged = {k: old.get(k) for k in FIELDS} | keep
    db.exec("INSERT OR REPLACE INTO body_day (day, steps, sleep_h, rest_hr, hrv, hr, spo2, updated) VALUES (?,?,?,?,?,?,?,?)",
            (d, *(merged[k] for k in FIELDS), time.time()))
    db.exec("DELETE FROM body_day WHERE day<?", ((dt.date.fromisoformat(d) - dt.timedelta(days=KEEP_DAYS)).isoformat(),))
    return keep


def day(rt: Any, d: str) -> dict:
    row = _db(rt).one("SELECT * FROM body_day WHERE day=?", (d,))
    return {k: row[k] for k in FIELDS} if row else {}


def history(rt: Any, days: int = 30, today: dt.date | None = None) -> list[dict]:
    t = today or dt.date.today()
    rows = _db(rt).all("SELECT * FROM body_day WHERE day>? ORDER BY day", ((t - dt.timedelta(days=days)).isoformat(),))
    return [{"day": r["day"], **{k: r[k] for k in FIELDS}} for r in rows]


def baseline(rt: Any, field: str, before: str, days: int = BASE_DAYS) -> float | None:
    """Your normal for one number: the median of the days before `before` (not counting that day)."""
    start = (dt.date.fromisoformat(before) - dt.timedelta(days=days)).isoformat()
    vals = [r[field] for r in _db(rt).all(f"SELECT {field} FROM body_day WHERE day>=? AND day<? AND {field} IS NOT NULL",  # noqa: S608
                                          (start, before)) if field in FIELDS]
    return round(statistics.median(vals), 1) if len(vals) >= BASE_MIN else None


def _cs(v: float) -> str:
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",")


def assess(now: dict, base: dict) -> tuple[str, list[tuple[int, str]]]:
    """(level, reasons): level full / normal / easy / unknown; each reason (weight, what)."""
    flags: list[tuple[int, str]] = []
    s, bs = now.get("sleep_h"), base.get("sleep_h")
    if s is not None:
        if s < 5.5:
            flags.append((2, f"spal jste jen {_cs(s)} h"))
        elif bs and s <= bs - 1:
            flags.append((1, f"spal jste o {_cs(bs - s)} h méně než obvykle"))
    r, br = now.get("rest_hr"), base.get("rest_hr")
    if r is not None and br:
        if r >= br + 8:
            flags.append((2, f"klidový tep {int(r)} je o {int(r - br)} úderů nad vaším normálem"))
        elif r >= br + 5:
            flags.append((1, f"klidový tep je trochu výš ({int(r)}, obvykle {int(br)})"))
    v, bv = now.get("hrv"), base.get("hrv")
    if v is not None and bv and v <= bv * 0.8:
        flags.append((2 if v <= bv * 0.65 else 1, f"variabilita tepu je nízko ({int(v)} ms, obvykle {int(bv)}) – tělo se ještě zotavuje"))
    o = now.get("spo2")
    if o is not None and o < 92:
        flags.append((2, f"okysličení krve jen {int(o)} %"))
    if not any(now.get(k) is not None for k in ("sleep_h", "rest_hr", "hrv")):
        return "unknown", flags
    score = sum(w for w, _ in flags)
    return ("easy" if score >= 2 else "normal" if score == 1 else "full"), flags


def _gym_today(rt: Any) -> str:
    try:
        from . import gym

        p = gym.today_plan(rt)
        return str(p.get("split") or "") if p else ""
    except Exception:  # noqa: BLE001 – no gym plan
        return ""


def plan_for(level: str, flags: list[tuple[int, str]], workout: str = "") -> str:
    """What the level means for today, in a sentence or two."""
    if level == "easy":
        txt = "Doporučuji lehčí den: náročné věci dejte do dopoledne, víc vody, kratší přestávky častěji a dnes do postele dřív."
        if workout:
            txt += f" Místo plánovaného tréninku ({workout}) jen lehký pohyb nebo procházka."
        if any("okysličení" in f for _, f in flags):
            txt += " Pokud se necítíte dobře, poraďte se s lékařem."
        return txt
    if level == "normal":
        return "Běžný den – jen to večer nepřehánějte." + (f" Trénink ({workout}) klidně, ale bez rekordů." if workout else "")
    if level == "full":
        return "Systémy v plné síle – ideální den na náročnou práci" + (f" i na trénink ({workout})." if workout else ".")
    return ""


def status(rt: Any, today: dt.date | None = None) -> dict:
    """Today's numbers, your normal, the verdict and the sentence JARVIS says."""
    t = today or dt.date.today()
    d = t.isoformat()
    now = day(rt, d)
    base = {k: baseline(rt, k, d) for k in ("sleep_h", "rest_hr", "hrv", "steps")}
    yday = day(rt, (t - dt.timedelta(days=1)).isoformat())
    level, flags = assess(now, base)
    bits = []
    bs, br = base.get("sleep_h"), base.get("rest_hr")
    if now.get("sleep_h") is not None:
        bits.append(f"spánek {_cs(now['sleep_h'])} h" + (f" (obvykle {_cs(bs)})" if bs else ""))
    if now.get("rest_hr") is not None:
        bits.append(f"klidový tep {int(now['rest_hr'])}" + (f" (obvykle {int(br)})" if br else ""))
    if now.get("hrv") is not None:
        bits.append(f"variabilita tepu {int(now['hrv'])} ms")
    if yday.get("steps"):
        bits.append(f"včera {int(yday['steps']):,} kroků".replace(",", " "))
    text = ""
    if level != "unknown":
        text = "Stav systémů: " + ", ".join(bits) + "."
        if flags:
            text += " " + "; ".join(f for _, f in flags).capitalize() + "."
        text += " " + plan_for(level, flags, _gym_today(rt))
    return {"day": d, "now": now, "base": base, "yesterday": yday, "level": level,
            "reasons": [f for _, f in flags], "text": text.strip()}


def morning_line(rt: Any) -> str:
    """The body part of the morning briefing ("" with no data from the watch today or when switched off)."""
    if not getattr(getattr(rt.cfg, "health", None), "morning", True):
        return ""
    try:
        return status(rt)["text"]
    except Exception as e:  # noqa: BLE001
        log.debug("body morning: %s", e)
        return ""


def from_phone(rt: Any, m: dict) -> dict:
    """The phone's habit_health message: the habits (sleep, steps) and the body numbers."""
    from . import habits as hb

    d = m.get("day") or None
    hb.health_sync(rt, d, _num(m.get("steps")), _num(m.get("sleep_h")))
    return record(rt, d, steps=m.get("steps"), sleep_h=m.get("sleep_h"), rest_hr=m.get("rest_hr"), hrv=m.get("hrv"),
                  hr=m.get("hr"), spo2=m.get("spo2"))


# ---------------------------------------------------------------------------------------------- the posture check
def posture_verdict(face: tuple[int, int, int, int] | None, width: int, height: int, base: dict | None) -> str:
    """"close" (leaning in), "low" (slumped), "ok", or "" when it cannot tell (no face, no baseline yet)."""
    if not face or not base or not width or not height:
        return ""
    x, y, w, h = face
    if w >= base["w"] * CLOSE_RATIO:
        return "close"
    if (y + h / 2) / height - base["cy"] >= LOW_SHIFT:
        return "low"
    return "ok"


def posture_sample(face: tuple[int, int, int, int], width: int, height: int) -> dict:
    x, y, w, h = face
    return {"w": float(w), "cy": (y + h / 2) / height, "width": width}


POSTURE_TEXT = {
    "close": "{a}, jste u monitoru moc blízko – opřete se a oddalte se kousek, oči i krk vám poděkují.",
    "low": "{a}, sjíždíte v židli – narovnejte záda a ramena dozadu.",
}


class DeskCare:
    """Water, the long day, bedtime and (opt-in) posture while you sit at the PC."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.active_today = 0.0
        self.day = ""
        self.last_tick = 0.0
        self.last_water = 0.0
        self.said: dict[str, str] = {}           # what → the day (or night) it was said
        self.bad_in_row = 0
        self.last_posture_check = 0.0
        self.last_posture_said = float("-inf")
        self.samples: list[dict] = []
        self.error = ""

    # ---- settings
    def cfg(self) -> Any:
        return getattr(self.rt.cfg, "health", None)

    def _addr(self) -> str:
        return (getattr(self.rt.cfg.general, "address_as", "") or "pane").capitalize()

    def _notify(self, title: str, text: str, actions: list[dict] | None = None) -> None:
        speak = getattr(self.rt.cfg.voice, "speak_mode", "") != "never"
        self.rt.call_soon(lambda: self.rt.notify(title, text, speak=speak, actions=actions or [{"label": "Ok", "action": "dismiss"}]))

    # ---- one minute
    def tick(self, now: float, idle: float, clock: dt.datetime | None = None) -> list[str]:
        """Returns what it said (for tests); call about once a minute."""
        c = self.cfg()
        if c is None:
            return []
        clock = clock or dt.datetime.fromtimestamp(now)
        today = clock.date().isoformat()
        if today != self.day:
            self.day, self.active_today = today, 0.0
        step = min(now - self.last_tick, 120) if self.last_tick else 0
        self.last_tick = now
        present = idle < PRESENT_IDLE_S
        if present:
            self.active_today += step
        self.work_run = getattr(self, "work_run", 0.0) + step if present and idle < BREAK_IDLE_S else 0.0
        from .lookx import stretch_due

        if stretch_due(self.rt, self.work_run / 60):        # 3.20 (112) 90 minutes in a row: Mochi stretches
            self.rt.bus.publish_threadsafe("mochi_action", action="stretch")
        if idle >= BREAK_IDLE_S:
            self.last_water = max(self.last_water, now - idle)     # away from the PC: maybe you drank, count from then
        out = []
        mins = int(getattr(c, "water_minutes", 0) or 0)
        if mins:
            from .proactx import water_minutes

            mins = water_minutes(self.rt, mins)           # 3.20 (68) a hot day: a glass more often
        if present and mins > 0:
            if not self.last_water:
                self.last_water = now
            elif now - self.last_water >= mins * 60:
                self.last_water = now
                self._notify("Pitný režim", f"{self._addr()}, je čas na sklenici vody.",
                             [{"label": "Vypito", "action": "water_done"}, {"label": "Ok", "action": "dismiss"}])
                out.append("water")
        long_h = float(getattr(c, "long_day_h", 0) or 0)
        if long_h > 0 and self.active_today >= long_h * 3600 and self.said.get("long") != today:
            self.said["long"] = today
            self._notify("Dlouhý den u PC", f"{self._addr()}, dnes jste u počítače už {_cs(self.active_today / 3600)} h. "
                         "Zvažte konec na dnešek nebo aspoň delší pauzu venku.")
            out.append("long")
        bed = str(getattr(c, "bedtime", "") or "")
        if present and bed and self._past_bedtime(clock, bed):
            night = (clock - dt.timedelta(hours=12)).date().isoformat()
            if self.said.get("bed") != night:
                self.said["bed"] = night
                woke = clock.date() - dt.timedelta(days=1) if clock.hour < 12 else clock.date()   # the morning after "last night"
                last = day(self.rt, woke.isoformat()).get("sleep_h")
                extra = f" Minulou noc jste spal jen {_cs(last)} h." if last is not None and last < 6.5 else ""
                self._notify("Čas jít spát", f"{self._addr()}, je {clock:%H:%M}.{extra} Pokud chcete být zítra v plné síle, "
                             "doporučuji to dnes zabalit.")
                out.append("bed")
        return out

    @staticmethod
    def _past_bedtime(clock: dt.datetime, bed: str) -> bool:
        try:
            h, m = (int(x) for x in bed.replace(".", ":").split(":")[:2])
        except ValueError:
            return False
        mins, at = clock.hour * 60 + clock.minute, h * 60 + m
        if at >= 12 * 60:                         # an evening bedtime: from then until 5 in the morning
            return mins >= at or mins < 5 * 60
        return at <= mins < 5 * 60                # after midnight (e.g. 0:30)

    # ---- posture (opt-in)
    def posture_base(self) -> dict | None:
        row = self.rt.db.one("SELECT v FROM kv WHERE k='posture_base'")
        try:
            return json.loads(row["v"]) if row else None
        except (TypeError, ValueError):
            return None

    def set_posture_base(self, base: dict) -> None:
        self.rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('posture_base', ?)", (json.dumps(base),))

    def _face_now(self) -> tuple[tuple[int, int, int, int] | None, int, int]:
        """The latest face: from the look-to-talk watcher when it already has the camera, else one picture."""
        lw = getattr(self.rt, "look_watcher", None)
        last = getattr(lw, "last", None)
        if last and time.monotonic() - last[3] < 5:
            return last[0], last[1], last[2]
        from . import webcam

        frame = webcam.grab(int(getattr(self.rt.cfg.voice, "camera_index", 0) or 0))
        webcam.log_use(self.rt, "posture", "držení těla")
        found = webcam.faces(frame)
        return (found[0] if len(found) == 1 else None), int(frame.shape[1]), int(frame.shape[0])

    def posture_step(self, now: float, face: tuple[int, int, int, int] | None, width: int, height: int) -> str:
        """One check; returns what it said ("close" / "low" / "")."""
        base = self.posture_base()
        if base is None:
            if face:                                 # the first few checks set "how you sit well"
                self.samples.append(posture_sample(face, width, height))
                if len(self.samples) >= 5:
                    self.set_posture_base({"w": statistics.median(s["w"] for s in self.samples),
                                           "cy": statistics.median(s["cy"] for s in self.samples), "width": width})
                    self.samples = []
            return ""
        v = posture_verdict(face, width, height, base)
        if v in ("close", "low"):
            self.bad_in_row += 1
        elif v == "ok":
            self.bad_in_row = 0
        if self.bad_in_row >= POSTURE_BAD_IN_ROW and now - self.last_posture_said >= POSTURE_REPEAT_S:
            self.last_posture_said, self.bad_in_row = now, 0
            self._notify("Držení těla", POSTURE_TEXT[v].format(a=self._addr()))
            return v
        return ""

    async def calibrate(self) -> str:
        """"Teď sedím dobře": the face now becomes the reference."""
        face, w, h = await asyncio.to_thread(self._face_now)
        if not face:
            return "Nevidím vás v kameře – sedněte si před ni a zkuste to znovu."
        self.set_posture_base(posture_sample(face, w, h))
        self.bad_in_row = 0
        return "Hotovo, tohle je od teď vaše správné držení těla."

    async def run(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                idle = float(self.rt.platform.idle_seconds())
                self.tick(now, idle)
                c = self.cfg()
                if (c is not None and getattr(c, "posture", False) and idle < PRESENT_IDLE_S
                        and now - self.last_posture_check >= POSTURE_EVERY_S):
                    self.last_posture_check = now
                    face, w, h = await asyncio.to_thread(self._face_now)
                    self.posture_step(now, face, w, h)
                    self.error = ""
            except Exception as e:  # noqa: BLE001 – no camera / no idle info: try again next minute
                self.error = str(e)[:200]
                log.debug("deskcare: %s", e)


def desk(rt: Any) -> DeskCare:
    d = getattr(rt, "_deskcare", None)
    if d is None:
        d = rt._deskcare = DeskCare(rt)
    return d


def water_done(rt: Any) -> str:
    """"Vypito": ticks a water habit when there is one, and the next reminder counts from now."""
    desk(rt).last_water = time.time()
    try:
        from . import habits as hb

        h = next((x for x in hb.habits(rt) if "vod" in (x.get("name") or "").lower() or "vod" in (x.get("unit") or "").lower()), None)
        if h:
            cur = rt.db.one("SELECT value FROM habit_log WHERE habit_id=? AND day=?", (h["id"], dt.date.today().isoformat()))
            v = float((cur["value"] if cur else 0) or 0)
            litres = (h.get("unit") or "").strip().lower() in ("l", "litr", "litry", "litrů")
            hb.log(rt, h["id"], v + (0.25 if litres else 1))
            hb.publish(rt)
            return "Zapsáno do návyku " + h["name"] + "."
    except Exception as e:  # noqa: BLE001
        log.debug("water habit: %s", e)
    return "Výborně."
