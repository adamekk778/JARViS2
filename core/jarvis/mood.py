"""MoodEngine: turns what JARVIS is doing into one of the character's moods (spec §3)."""
from __future__ import annotations

import asyncio
import logging
import random
import re
import socket
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# Highest first. UI-only moods (dragged, hover, opening, expanded, closing, desktop_interact, personalize, closed)
# are layered on top by the UI itself.
PRIORITY = ["waiting", "error", "limit", "listening", "speaking", "working", "thinking", "updating", "success",
            "offline", "focus", "notify", "dancing", "joy", "sleeping", "idle"]
DURATION = {"success": 2.0, "error": 4.0, "joy": 3.0, "limit": 120.0}
SLEEP_AFTER = 600.0
NOTIFY_SHOW = 30.0
THANKS = re.compile(r"\b(díky|dík|děkuj\w*|dekuj\w*|super|skvěl\w*|skvel\w*|miluju|paráda|parada|perfektní|"
                    r"thanks|thank you|good job|great)\b", re.I)
STATE_MOOD = {"listening": "listening", "thinking": "thinking", "acting": "working", "speaking": "speaking",
              "waiting": "waiting"}
# OMEGA 72 / 73 / 74 / 81 / 738 / 746 / 747 / 749 / 750: short reactions layered over the mood (the UI plays them once)
REACTION_TTL = {"stretch": 3.0, "volume": 1.6, "mute": 2.4, "unmute": 1.6, "plug": 2.6, "unplug": 2.2, "switch": 2.2, "copy": 2.5,
                "toy": 6.0, "easter": 3.0, "custom": 3.0}
COPY_TOOLS = {"copy_file", "move_file", "backup_folder", "organize_media", "organize_downloads", "sort_folder", "make_zip",
              "extract_archive", "rename_files", "save_attachment"}
EASTER = [(re.compile(r"\b(barrel roll|udělej kotoul|udelej kotoul|zatoč se|zatoc se)\b", re.I), "spin"),
          (re.compile(r"\b(smysl života|smysl zivota|meaning of life|odpověď na všechno)\b", re.I), "42"),
          (re.compile(r"\b(mrkni|wink)\b", re.I), "wink"),
          (re.compile(r"\b(žongluj|zongluj|juggle)\b", re.I), "juggle")]
TOYS = ["ball", "yoyo", "plane", "bubble"]
PERSONALITY = {"vyvážený": {"toy": 1.0, "rare": 1.0, "joy": 1.0}, "hravý": {"toy": 2.5, "rare": 3.0, "joy": 2.0},
               "klidný": {"toy": 0.3, "rare": 0.3, "joy": 0.5}, "profesionální": {"toy": 0.0, "rare": 0.0, "joy": 0.2}}
BLENDABLE = {"joy", "success", "thinking", "working", "notify", "dancing", "focus", "limit", "offline", "error"}


MOTIONS = {"hop", "shake", "dance", "wobble", "spin", "none"}


def clean_look(look: dict | None) -> dict:
    """A user-made reaction look, reduced to known keys and safe values (it ends up in the UI's HTML)."""
    look = look if isinstance(look, dict) else {}
    try:
        seconds = min(15.0, max(0.5, float(look.get("seconds") or 3)))
    except (TypeError, ValueError):
        seconds = 3.0
    color = str(look.get("color") or "")
    return {"eyes": re.sub(r"[^a-z]", "", str(look.get("eyes") or "wide").lower())[:20] or "wide",
            "icon": re.sub(r"[^a-z0-9-]", "", str(look.get("icon") or "star").lower())[:40] or "star",
            "motion": look.get("motion") if look.get("motion") in MOTIONS else "hop",
            "color": color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else "", "seconds": seconds}


def part_of_day(hour: int) -> str:
    return "night" if hour >= 22 or hour < 6 else "morning" if hour < 10 else "evening" if hour >= 18 else "day"


def weather_kind(code: int | None) -> str | None:
    if code is None:
        return None
    if code in (95, 96, 99):
        return "storm"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if code in (45, 48):
        return "fog"
    if code in (2, 3):
        return "cloud"
    return "sun"


class MoodEngine:
    def __init__(self, rt: Any, clock: Callable[[], float] = time.monotonic, rng: random.Random | None = None):
        self.rt = rt
        self.clock = clock
        self.rng = rng or random.Random()
        self.agent_state = "idle"
        self.until: dict[str, float] = {}      # timed moods → expiry
        self.manual: str | None = None         # "focus" | "sleeping"
        self.dancing = False
        self.offline = False
        self.badge = 0
        self.notify_at = -1e9
        self.progress: float | None = None
        self.update_progress: float | None = None
        self.detail = ""
        self.last_activity = clock()
        self.last_joy = -1e9
        self._joy_pending = False
        self._last: dict | None = None
        self._tasks: list[asyncio.Task] = []
        self.reaction: dict | None = None
        self._reaction_seq = 0
        self.weather: dict = {}
        self.brain: tuple | None = None
        self.audio: tuple | None = None
        self.last_toy = clock()
        self.wall = time.time
        self._last_wall: float | None = None

    # ---------- inputs ----------
    def touch(self) -> None:
        self.last_activity = self.clock()
        if self.manual == "sleeping":
            self.manual = None

    def set_manual(self, mood: str | None) -> None:
        self.manual = mood if mood in ("focus", "sleeping") else None
        if mood is None:
            self.last_activity = self.clock()
        self._emit()

    def clear_notify(self) -> None:
        self.badge = 0
        self.notify_at = -1e9
        self._emit()

    def set_offline(self, offline: bool) -> None:
        if offline != self.offline:
            self.offline = offline
            self._emit()

    def _flash(self, mood: str, detail: str = "") -> None:
        self.until[mood] = self.clock() + DURATION[mood]
        if detail:
            self.detail = detail

    def react(self, name: str, detail: dict | None = None, ttl: float | None = None) -> None:
        """A one-off reaction for the UI to play (it keeps the mood underneath)."""
        self._reaction_seq += 1
        self.reaction = {"name": name, "id": self._reaction_seq, "detail": detail or {},
                         "until": self.clock() + (ttl or REACTION_TTL.get(name, 2.5))}

    def personality(self) -> dict:
        ch = getattr(getattr(self.rt, "cfg", None), "character", None)
        return PERSONALITY.get(getattr(ch, "personality", "vyvážený"), PERSONALITY["vyvážený"])

    def _custom(self, event: str, text: str) -> None:
        """OMEGA 750: the user's own reactions – {when: notify / message / mail / app, match: words, look: {…}}."""
        ch = getattr(getattr(self.rt, "cfg", None), "character", None)
        for r in getattr(ch, "reactions", None) or []:
            r = r if isinstance(r, dict) else r.model_dump()
            if r.get("when") != event or not r.get("enabled", True):
                continue
            words = [w.strip().lower() for w in (r.get("match") or "").split(",") if w.strip()]
            if not words or any(w in text.lower() for w in words):
                look = clean_look(r.get("look"))
                self.react("custom", {"name": str(r.get("name", ""))[:40], **look}, look["seconds"])
                return

    def on_event(self, m: dict) -> None:
        t = m.get("type")
        now = self.clock()
        if t == "state":
            self.agent_state = m.get("state", "idle")
            if self.agent_state != "idle":
                self.touch()
            else:
                self.progress = None
        elif t == "user_message":
            self.touch()
            text = m.get("text") or ""
            self._joy_pending = bool(THANKS.search(text))
            for rx, kind in EASTER:
                if rx.search(text):
                    self.react("easter", {"kind": kind})
                    break
            else:
                self._custom("message", text)
        elif t == "assistant_done":
            tools = m.get("tools") or []
            if any(not x.get("ok") for x in tools):
                self._flash("error", next((x.get("summary", "") for x in tools if not x.get("ok")), ""))
            elif tools:
                self._flash("success")
            if self._joy_pending:
                self._flash("joy")
                self.last_joy = now
                self._joy_pending = False
        elif t == "error":
            if m.get("kind") == "limit":
                self._flash("limit", m.get("message", ""))
            else:
                self._flash("error", m.get("message", ""))
        elif t == "brain":
            self.until.pop("limit", None)  # a provider answered again
            cur = (m.get("provider"), m.get("model"))
            if self.brain and cur != self.brain and cur[0]:
                self.react("switch", {"from": self.brain[0], "to": cur[0], "model": cur[1]})
            self.brain = cur
        elif t == "guardian" and m.get("key") == "hardware":
            text = m.get("text") or ""
            self.react("plug" if text.startswith("Připojeno") else "unplug", {"text": text[:80]})
        elif t == "tool_start" and m.get("name") in COPY_TOOLS:
            self.react("copy", {"tool": m.get("name")})
        elif t == "mail_new":
            self._custom("mail", f"{m.get('from_name', '')} {m.get('subject', '')}")
        elif t == "media":
            self.dancing = bool(m.get("playing"))
        elif t == "notify":
            self.badge += 1
            self.notify_at = now
            self._custom("notify", f"{m.get('title', '')} {m.get('body', '')} {m.get('text', '')}")
        elif t == "task_update":          # missions: celebrate a verified result, frown at a failed one
            task = m.get("task") or {}
            st, tid = task.get("status"), task.get("id")
            if st in ("done", "failed") and tid and tid != getattr(self, "_task_seen", None):
                self._task_seen = tid
                if st == "failed":
                    self._flash("error", task.get("summary", ""))
                elif task.get("artifacts") and all(e.get("ok") for e in task.get("evidence") or []):
                    self._flash("joy")
        elif t == "task_progress":
            total = max(1, int(m.get("total") or 1))
            self.progress = None if m.get("done") else min(1.0, float(m.get("step", 0)) / total)
        elif t == "update_status":
            st = m.get("state")
            self.update_progress = float(m.get("progress", 0)) if st == "downloading" else None
        elif t == "confirm_timeout":
            if self.agent_state == "waiting":
                self.agent_state = "idle"
        self._emit()

    # ---------- output ----------
    def compute(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        for k, exp in list(self.until.items()):
            if exp <= now:
                del self.until[k]
        active: set[str] = set()
        if self.agent_state in STATE_MOOD:
            active.add(STATE_MOOD[self.agent_state])
        active |= set(self.until)
        if self.update_progress is not None:
            active.add("updating")
        if self.offline:
            active.add("offline")
        if self.manual:
            active.add(self.manual)
        if self.badge and now - self.notify_at < NOTIFY_SHOW:
            active.add("notify")
        if self.dancing:
            active.add("dancing")
        if now - self.last_activity > SLEEP_AFTER:
            active.add("sleeping")
        mood = next((p for p in PRIORITY if p in active), "idle")
        progress = self.progress if mood == "working" else self.update_progress if mood == "updating" else None
        detail = self.detail if mood in ("error", "limit") else ""
        # OMEGA 736: a second feeling mixed into the face (thinking while still happy, working with a pending bell)
        secondary = next((p for p in PRIORITY if p in active and p != mood and p in BLENDABLE), None)
        out = {"mood": mood, "badge": self.badge, "progress": progress, "detail": detail, "secondary": secondary,
               "ambient": self.ambient()}
        if self.reaction and self.reaction["until"] > now:
            out["reaction"] = {k: v for k, v in self.reaction.items() if k != "until"}
        return out

    def ambient(self) -> dict:
        """OMEGA 739 / 740 / 741: what the character wears and how bright he glows – time of day and the weather."""
        import datetime as _dt

        hour = _dt.datetime.fromtimestamp(self.wall()).hour
        w = self.weather
        return {"part": part_of_day(hour), "weather": weather_kind(w.get("code")), "temp": w.get("temp")}

    @property
    def current(self) -> dict:
        return self.compute()

    def tick(self, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        p = self.personality()
        mood = self.compute(now)["mood"]
        awake = now - self.last_activity < SLEEP_AFTER
        # rare spontaneous joy while idle (≤ 1× per hour)
        if (mood == "idle" and now - self.last_joy > 3600 and awake and p["joy"] and self.rng.random() < p["joy"] / 1800):
            self._flash("joy")
            self.last_joy = now
        # OMEGA 747: alone for a while (but awake) → plays with a toy, at most every 15 min
        if (mood == "idle" and awake and now - self.last_activity > 180 and now - self.last_toy > 900 and p["toy"]
                and self.rng.random() < p["toy"] / 120):
            self.last_toy = now
            self.react("toy", {"toy": self.rng.choice(TOYS)})
        # OMEGA 746: a very rare surprise
        if mood == "idle" and awake and p["rare"] and self.rng.random() < p["rare"] / 200000:
            self.react("easter", {"kind": self.rng.choice(["spin", "wink", "juggle"])})
        # OMEGA 72: the wall clock jumped while the monotonic one was asleep → the PC woke up: stretch
        wall = self.wall()
        if self._last_wall is not None and wall - self._last_wall > 60:
            self.touch()
            self.react("stretch", {"slept_s": round(wall - self._last_wall)})
        self._last_wall = wall
        return self._emit(now)["mood"]

    def on_audio(self, volume: int | None, muted: bool | None) -> None:
        """OMEGA 73 / 738: the system volume or mute changed (the first reading only sets the baseline)."""
        prev = self.audio
        self.audio = (volume, muted)
        if prev is None or volume is None:
            return
        if muted != prev[1]:
            self.react("mute" if muted else "unmute", {"level": volume})
        elif prev[0] is not None and abs(volume - prev[0]) >= 2:
            self.react("volume", {"level": volume, "up": volume > prev[0]})
        else:
            return
        self._emit()

    def _emit(self, now: float | None = None) -> dict:
        cur = self.compute(now)
        if cur != self._last:
            self._last = cur
            self.rt.bus.publish("mood", **cur)
        return cur

    # ---------- background ----------
    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._listen()), loop.create_task(self._ticker()),
                       loop.create_task(self._net_watch()), loop.create_task(self._audio_watch()),
                       loop.create_task(self._weather_watch())]

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _listen(self) -> None:
        q = self.rt.bus.subscribe()
        try:
            while True:
                m = await q.get()
                if m.get("type") != "mood":
                    self.on_event(m)
        finally:
            self.rt.bus.unsubscribe(q)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.tick()

    async def _audio_watch(self) -> None:
        state = getattr(self.rt.platform, "audio_state", None)
        if state is None:
            return
        while True:
            try:
                v, m = await asyncio.to_thread(state)
                self.on_audio(v, m)
            except Exception:  # noqa: BLE001 – no speaker / COM busy: try again later
                await asyncio.sleep(30)
            await asyncio.sleep(1.5)

    async def _weather_watch(self) -> None:
        import os

        if os.environ.get("JARVIS_NO_NET"):  # tests
            return
        from .tools.weather import fetch_weather

        while True:
            city = getattr(self.rt.cfg.general, "city", "")
            if city and not self.offline:
                try:
                    w = await asyncio.wait_for(fetch_weather(self.rt, city), 20)
                    self.weather = {"code": w.get("code"), "temp": w.get("temp")}
                    self._emit()
                except Exception as e:  # noqa: BLE001
                    log.debug("mood weather: %s", e)
            await asyncio.sleep(1800)

    async def _net_watch(self) -> None:
        import os

        if os.environ.get("JARVIS_NO_NET"):  # tests
            return
        while True:
            self.set_offline(not await asyncio.to_thread(online))
            await asyncio.sleep(15)


def online(timeout: float = 4.0) -> bool:
    for host, port in (("www.msftconnecttest.com", 80), ("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False
