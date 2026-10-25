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
            self._joy_pending = bool(THANKS.search(m.get("text") or ""))
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
        elif t == "media":
            self.dancing = bool(m.get("playing"))
        elif t == "notify":
            self.badge += 1
            self.notify_at = now
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
        return {"mood": mood, "badge": self.badge, "progress": progress, "detail": detail}

    @property
    def current(self) -> dict:
        return self.compute()

    def tick(self, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        # rare spontaneous joy while idle (≤ 1× per hour)
        if (self.compute(now)["mood"] == "idle" and now - self.last_joy > 3600 and now - self.last_activity < SLEEP_AFTER
                and self.rng.random() < 1 / 1800):
            self._flash("joy")
            self.last_joy = now
        return self._emit(now)["mood"]

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
                       loop.create_task(self._net_watch())]

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
