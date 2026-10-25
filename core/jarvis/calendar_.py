"""3.4 calendar: JARVIS's own events (add, delete, remind) plus read-only calendars from an iCal address
(Google, Seznam, Outlook all offer a "secret address in iCal format"). Reminders arrive in the notch, by voice and on
the phone; urgent ones can ring the phone."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

SQL = """
CREATE TABLE IF NOT EXISTS cal_events (id TEXT PRIMARY KEY, title TEXT, start REAL, end REAL, location TEXT,
  remind INTEGER, ring INTEGER DEFAULT 0, created REAL);
"""


def _local(d: Any) -> dt.datetime:
    """icalendar values → naive local datetime (all-day dates start at midnight)."""
    if isinstance(d, dt.datetime):
        return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    return dt.datetime.combine(d, dt.time())


def parse_ics(data: bytes, start: dt.datetime, end: dt.datetime, source: str = "") -> list[dict]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s = ev.get("DTSTART").dt
        e = ev.get("DTEND").dt if ev.get("DTEND") else None
        all_day = not isinstance(s, dt.datetime)
        sl = _local(s)
        el = _local(e) if e else sl + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
        uid = str(ev.get("UID", "")) + "@" + sl.isoformat()
        out.append({"id": f"ics:{uid}", "title": str(ev.get("SUMMARY", "(bez názvu)")), "start": sl.timestamp(),
                    "end": el.timestamp(), "location": str(ev.get("LOCATION", "") or ""), "all_day": all_day,
                    "source": source, "readonly": True})
    return out


class Calendar:
    def __init__(self, rt):
        self.rt = rt
        rt.db.conn.executescript(SQL)
        self._feeds: dict[str, tuple[float, bytes]] = {}     # url → (fetched, ics)
        self._reminded: set[str] = set()
        self._task: asyncio.Task | None = None

    # ---------- own events ----------
    def add(self, title: str, start: dt.datetime, minutes: int = 60, location: str = "", remind: int | None = None,
            ring: bool = False) -> dict:
        eid = uuid.uuid4().hex[:8]
        remind = self.rt.cfg.calendar.remind_minutes if remind is None else remind
        self.rt.db.exec("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?)",
                        (eid, title, start.timestamp(), (start + dt.timedelta(minutes=max(0, minutes))).timestamp(), location,
                         int(remind), int(ring), time.time()))
        return self.get(eid)

    def get(self, eid: str) -> dict | None:
        r = self.rt.db.one("SELECT * FROM cal_events WHERE id=?", (eid,))
        if not r:
            return None
        return {"id": r["id"], "title": r["title"], "start": r["start"], "end": r["end"], "location": r["location"] or "",
                "remind": r["remind"], "ring": bool(r["ring"]), "all_day": False, "source": "JARVIS", "readonly": False}

    def delete(self, eid: str) -> bool:
        return self.rt.db.exec("DELETE FROM cal_events WHERE id=?", (eid,)).rowcount > 0

    # ---------- everything in a range ----------
    async def _feed(self, url: str) -> bytes:
        hit = self._feeds.get(url)
        if hit and time.time() - hit[0] < 900:
            return hit[1]
        async with self.rt.http() as c:
            r = await c.get(url.replace("webcal://", "https://"), timeout=20)
            r.raise_for_status()
        self._feeds[url] = (time.time(), r.content)
        return r.content

    async def events(self, start: dt.datetime, end: dt.datetime) -> list[dict]:
        rows = self.rt.db.all("SELECT id FROM cal_events WHERE end>=? AND start<=? ORDER BY start", (start.timestamp(), end.timestamp()))
        out = [self.get(r["id"]) for r in rows]
        for i, url in enumerate(self.rt.cfg.calendar.ics_urls):
            try:
                data = await self._feed(url)
                out += await asyncio.to_thread(parse_ics, data, start, end, f"kalendář {i + 1}")
            except Exception as e:
                log.debug("ics %s: %s", url[:40], e)
        return sorted((e for e in out if e), key=lambda e: e["start"])

    async def day(self, day: dt.date) -> list[dict]:
        start = dt.datetime.combine(day, dt.time())
        return await self.events(start, start + dt.timedelta(days=1) - dt.timedelta(seconds=1))

    # ---------- reminders ----------
    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def remind_due(self, now: dt.datetime | None = None) -> list[dict]:
        now = now or dt.datetime.now()
        default = self.rt.cfg.calendar.remind_minutes
        evs = await self.events(now, now + dt.timedelta(hours=3))
        due = []
        for e in evs:
            if e.get("all_day"):
                continue
            mins = e.get("remind", default) if not e["readonly"] else default
            if mins is None or mins < 0:
                continue
            left = (e["start"] - now.timestamp()) / 60
            key = f"{e['id']}@{e['start']}"
            if 0 <= left <= mins and key not in self._reminded:
                self._reminded.add(key)
                due.append(e)
                when = "teď" if left < 1 else f"za {round(left)} min"
                where = f" ({e['location']})" if e.get("location") else ""
                text = f"{when.capitalize()}: {e['title']}{where}."
                self.rt.notify("Kalendář", text, speak=self.rt.cfg.voice.speak_mode != "never")
                if e.get("ring") and getattr(self.rt, "phone", None):
                    await self.rt.phone.ring(f"Pane, připomínám: {e['title']} {when}.", reason="calendar")
        return due

    async def _loop(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                await self.remind_due()
            except Exception as e:
                log.debug("calendar: %s", e)
            await asyncio.sleep(30)


def fmt_event(e: dict) -> str:
    s = dt.datetime.fromtimestamp(e["start"])
    if e.get("all_day"):
        when = "celý den"
    else:
        when = f"{s:%H:%M}–{dt.datetime.fromtimestamp(e['end']):%H:%M}"
    return f"{when} {e['title']}" + (f" ({e['location']})" if e.get("location") else "")
