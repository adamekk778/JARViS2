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
                self.rt.notify(p.get("title", "Připomínka"), p.get("body", ""), target="all", urgent=True)
            elif job["kind"] == "ring":       # "zavolej mi v 7 a připomeň…"
                await self.rt.phone.ring(p.get("text", "Připomínka."), reason="schedule")
            elif job["kind"] == "watch":
                from .powers import check_watch

                fire, msg, new = await check_watch(self.rt, p)
                if new != p:
                    self.db.exec("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(new, ensure_ascii=False), job["id"]))
                if fire:
                    self.rt.notify("Hlídání webu", msg, url=p["url"], target="all")
                    if p.get("text"):     # waited for a text and it is there → done
                        self.delete(job["id"])
            elif job["kind"] == "price":      # "dej vědět, až bitcoin klesne pod …" (one-shot)
                from .finance import check_alert

                hit, msg = await check_alert(self.rt, p)
                if hit:
                    self.delete(job["id"])
                    if p.get("call"):
                        await self.rt.phone.ring(f"Pane, {msg}", reason="price")
                    else:
                        self.rt.notify("Hlídání ceny", msg, speak=True, target="all")
            elif job["kind"] == "backup":     # OMEGA P10.04: automatic incremental backup
                from .sysplus import run_backup

                await run_backup(self.rt, p)
            elif job["kind"] == "multitask":  # 3.14 agents on a schedule ("každé ráno v 8 projdi 10 agenty trhy")
                mt = self.rt.multitask
                if p.get("preset"):
                    s = await mt.start_preset(p["preset"], p.get("topic", ""), p.get("paper"))
                else:
                    s = await mt.start(p.get("goal", ""), p.get("workers") or None, int(p.get("max_agents") or 10),
                                       paper=bool(p.get("paper")))
                self.rt.notify(job["title"] or "Agenti podle plánu", f"Spustil jsem {len(s.workers)} agentů – uvidíš je v notchi "
                               "(Více → Agenti), na konci dám vědět.", speak=False)
            elif job["kind"] == "car_ready":  # 3.14 "připrav auto na 7:30"
                from .car import run_ready

                await run_ready(self.rt, p)
            elif job["kind"] == "prompt":
                self.rt.cheap_turn = bool(p.get("cheap"))       # 3.20 (32) a night task: the cheapest brain
                try:
                    text = await self.rt.agent.handle(
                        p["prompt"], [], "schedule",
                        extra_system="Tohle je automaticky spuštěná naplánovaná úloha (rutina). Splň ji a odpověz stručně, "
                                     "odpověď se přečte nahlas a pošle na telefon.")
                finally:
                    self.rt.cheap_turn = False
                self.rt.notify(job["title"] or "Rutina", text[:300], speak=not p.get("cheap"), target="all")
            elif job["kind"] == "voice_alarm":      # 3.20 (5) budíček s ranním souhrnem
                from .voicex import run_alarm

                await run_alarm(self.rt, p)
            elif job["kind"] == "future_message":   # 3.20 (11) vzkaz pro budoucí já
                from .voicex import run_future

                await run_future(self.rt, p)
            elif job["kind"] == "watch_alarm":      # 3.20 (154) tichý budík na hodinkách
                from .phonex import run_watch_alarm

                run_watch_alarm(self.rt, p)
            elif job["kind"] == "brain_week":       # 3.20 (39) co se JARVIS za týden naučil
                from .brainx import learned_text, learned_week

                self.rt.notify("Co jsem se tento týden naučil", learned_text(learned_week(self.rt)), speak=False)
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
