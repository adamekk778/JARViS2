"""Routines and reminders that survive restarts (SQLite `jobs` table)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
import uuid

log = logging.getLogger(__name__)
DAY_NAMES = ["po", "út", "st", "čt", "pá", "so", "ne"]


def next_run(spec: dict, after: dt.datetime) -> dt.datetime | None:
    t = spec.get("type")
    if t == "once":
        at = dt.datetime.fromtimestamp(spec["at"])
        return at if at > after else None
    if t == "interval":
        return after + dt.timedelta(minutes=max(1, int(spec.get("minutes", 60))))
    if t == "daily":
        hh, mm = map(int, spec["time"].split(":"))
        days = spec.get("days") or list(range(7))
        cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
        for i in range(8):
            d = cand + dt.timedelta(days=i)
            if d > after and d.weekday() in days:
                return d
    return None


def describe(spec: dict) -> str:
    t = spec.get("type")
    if t == "once":
        return "jednou " + dt.datetime.fromtimestamp(spec["at"]).strftime("%d.%m. %H:%M")
    if t == "interval":
        return f"každých {spec.get('minutes')} min"
    days = spec.get("days") or list(range(7))
    which = "denně" if len(days) == 7 else "všední dny" if days == [0, 1, 2, 3, 4] else ", ".join(DAY_NAMES[d] for d in days)
    return f"{which} v {spec['time']}"


class Scheduler:
    def __init__(self, rt):
        self.rt = rt
        self.db = rt.db
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    # ---------- CRUD ----------
    def add(self, spec: dict, kind: str, payload: dict, title: str = "") -> dict:
        nr = next_run(spec, dt.datetime.now())
        if nr is None:
            raise ValueError("Ten čas už byl")
        jid = uuid.uuid4().hex[:10]
        self.db.exec("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                     (jid, kind, json.dumps(spec), json.dumps(payload, ensure_ascii=False), nr.timestamp(), 1, time.time(),
                      title or payload.get("title") or payload.get("prompt", "")[:60]))
        self._wake.set()
        return self.get(jid)

    def add_once(self, at: dt.datetime, kind: str = "notify", payload: dict | None = None, title: str = "") -> dict:
        return self.add({"type": "once", "at": at.timestamp()}, kind, payload or {}, title)

    def get(self, jid: str) -> dict | None:
        r = self.db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        if not r:
            return None
        spec = json.loads(r["spec"])
        return {"id": r["id"], "kind": r["kind"], "spec": spec, "spec_text": describe(spec), "payload": json.loads(r["payload"]),
                "next_run": r["next_run"], "enabled": bool(r["enabled"]), "title": r["title"]}

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.db.all("SELECT id FROM jobs ORDER BY next_run")]

    def delete(self, jid: str) -> bool:
        return self.db.exec("DELETE FROM jobs WHERE id=?", (jid,)).rowcount > 0

    # ---------- running ----------
    def pause_for(self, seconds: float) -> None:
        """Emergency STOP: no routine starts for a while."""
        self._paused_until = time.monotonic() + seconds

    async def tick(self, now: dt.datetime | None = None) -> int:
        if time.monotonic() < getattr(self, "_paused_until", 0.0):
            return 0
        now = now or dt.datetime.now()
        due = self.db.all("SELECT id FROM jobs WHERE enabled=1 AND next_run<=?", (now.timestamp(),))
        for r in due:
            job = self.get(r["id"])
            nr = next_run(job["spec"], now)
            if nr is None:
                self.delete(job["id"])
            else:
                self.db.exec("UPDATE jobs SET next_run=? WHERE id=?", (nr.timestamp(), job["id"]))
            asyncio.get_running_loop().create_task(self._run(job))
        return len(due)

    async def _run(self, job: dict) -> None:
        p = job["payload"]
        try:
            if job["kind"] == "notify":
                self.rt.notify(p.get("title", "Připomínka"), p.get("body", ""), target="all")
            elif job["kind"] == "prompt":
                text = await self.rt.agent.handle(
                    p["prompt"], [], "schedule",
                    extra_system="Tohle je automaticky spuštěná naplánovaná úloha (rutina). Splň ji a odpověz stručně, "
                                 "odpověď se přečte nahlas a pošle na telefon.")
                self.rt.notify(job["title"] or "Rutina", text[:300], speak=True, target="all")
        except Exception as e:
            log.warning("job %s failed: %s", job["id"], e)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.warning("scheduler tick: %s", e)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
