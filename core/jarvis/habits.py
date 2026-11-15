"""3.12 Návyky a zdraví: gym, spánek, jídlo, voda… – every day you tick what you did and JARVIS counts how you are
doing (today, this week, the month, streaks, a trend, which habit holds best). Shown in the notch (a tab of the open
notch) and full screen (the main window). Also by voice: "byl jsem v gymu", "spal jsem 7 hodin".
Everything stays in the local database – nothing leaves the PC.
"""
from __future__ import annotations

import calendar
import datetime as dt
import time
from typing import Any

SQL = """
CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, icon TEXT, color TEXT,
  area TEXT, kind TEXT, target REAL, unit TEXT, days TEXT, ord INTEGER, created TEXT, archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS habit_log (habit_id INTEGER NOT NULL, day TEXT NOT NULL, value REAL, note TEXT, ts REAL,
  PRIMARY KEY (habit_id, day));
CREATE TABLE IF NOT EXISTS habit_meals (day TEXT NOT NULL, slot TEXT NOT NULL, text TEXT, ts REAL, PRIMARY KEY (day, slot));
"""

AREAS = {"gym": "Pohyb", "jidlo": "Jídlo", "spanek": "Spánek", "zdravi": "Zdraví", "mysl": "Mysl", "jine": "Ostatní"}
MEAL_SLOTS = [("snidane", "Snídaně"), ("obed", "Oběd"), ("vecere", "Večeře"), ("svacina", "Svačina")]
ALL_DAYS = "0123456"                     # Monday = 0
DEFAULTS = [
    {"name": "Spánek", "icon": "moon-stars", "color": "#8b9cff", "area": "spanek", "kind": "amount", "target": 7, "unit": "h"},
    {"name": "Trénink", "icon": "barbell", "color": "#ff6b6b", "area": "gym", "kind": "check", "days": "024"},
    {"name": "Zdravé jídlo", "icon": "bowl-food", "color": "#3ddc97", "area": "jidlo", "kind": "check"},
    {"name": "Voda", "icon": "drop", "color": "#4cc9f0", "area": "zdravi", "kind": "amount", "target": 8, "unit": "sklenic"},
    {"name": "Bez sladkého", "icon": "cookie", "color": "#ffb84d", "area": "jidlo", "kind": "check"},
    {"name": "Meditace", "icon": "flower-lotus", "color": "#c77dff", "area": "mysl", "kind": "check"},
]


def _db(rt: Any):
    rt.db.conn.executescript(SQL)
    return rt.db


def today() -> dt.date:
    return dt.date.today()


def _iso(d: dt.date) -> str:
    return d.isoformat()


def seed(rt: Any) -> None:
    """The first time: a sensible start (sleep, training, food, water…) – everything can be changed or removed."""
    db = _db(rt)
    if db.one("SELECT v FROM kv WHERE k='habits_seeded'"):
        return
    if not db.one("SELECT id FROM habits LIMIT 1"):
        start = _iso(today())
        for i, h in enumerate(DEFAULTS):
            db.exec("INSERT INTO habits (name, icon, color, area, kind, target, unit, days, ord, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (h["name"], h["icon"], h["color"], h["area"], h["kind"], float(h.get("target", 1)), h.get("unit", ""),
                     h.get("days", ALL_DAYS), i, start))
    db.exec("INSERT OR REPLACE INTO kv VALUES ('habits_seeded', '1')")


def habits(rt: Any, archived: bool = False) -> list[dict]:
    rows = _db(rt).all("SELECT * FROM habits WHERE archived=? ORDER BY ord, id", (1 if archived else 0,))
    for r in rows:
        r["target"] = float(r.get("target") or 1)
        r["days"] = r.get("days") or ALL_DAYS
    return rows


def _clean(h: dict) -> dict:
    kind = "amount" if h.get("kind") == "amount" else "check"
    days = "".join(sorted({c for c in str(h.get("days") or ALL_DAYS) if c in ALL_DAYS})) or ALL_DAYS
    target = float(h.get("target") or 1) if kind == "amount" else 1.0
    return {"name": " ".join(str(h.get("name") or "").split())[:40], "icon": str(h.get("icon") or "check-circle")[:40],
            "color": str(h.get("color") or "#3ddc97")[:20], "area": h.get("area") if h.get("area") in AREAS else "jine",
            "kind": kind, "target": max(0.1, min(target, 1_000_000)), "unit": str(h.get("unit") or "")[:16], "days": days}


def save(rt: Any, h: dict) -> int:
    c = _clean(h)
    if not c["name"]:
        raise ValueError("Návyk potřebuje název.")
    db = _db(rt)
    if h.get("id"):
        db.exec("UPDATE habits SET name=?, icon=?, color=?, area=?, kind=?, target=?, unit=?, days=? WHERE id=?",
                (c["name"], c["icon"], c["color"], c["area"], c["kind"], c["target"], c["unit"], c["days"], int(h["id"])))
        return int(h["id"])
    n = (db.one("SELECT MAX(ord) AS m FROM habits") or {}).get("m")
    cur = db.exec("INSERT INTO habits (name, icon, color, area, kind, target, unit, days, ord, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (c["name"], c["icon"], c["color"], c["area"], c["kind"], c["target"], c["unit"], c["days"],
                   (n if n is not None else -1) + 1, _iso(today())))
    return int(cur.lastrowid)


def remove(rt: Any, hid: int) -> None:
    """Archived, not deleted: the history (and the past percentages) stay right."""
    _db(rt).exec("UPDATE habits SET archived=1 WHERE id=?", (int(hid),))


def reorder(rt: Any, ids: list[int]) -> None:
    for i, hid in enumerate(ids):
        _db(rt).exec("UPDATE habits SET ord=? WHERE id=?", (i, int(hid)))


def log(rt: Any, hid: int, value: float | None, day: str | None = None, note: str | None = None) -> None:
    d = day or _iso(today())
    dt.date.fromisoformat(d)                                   # a real date, or ValueError
    if dt.date.fromisoformat(d) > today():
        raise ValueError("Do budoucna se odškrtávat nedá.")
    db = _db(rt)
    old = db.one("SELECT value, note FROM habit_log WHERE habit_id=? AND day=?", (int(hid), d)) or {}
    v = old.get("value") if value is None else max(0.0, min(float(value), 1_000_000))
    n = old.get("note") if note is None else str(note)[:300]
    if not v and not n:
        db.exec("DELETE FROM habit_log WHERE habit_id=? AND day=?", (int(hid), d))
        return
    db.exec("INSERT OR REPLACE INTO habit_log (habit_id, day, value, note, ts) VALUES (?,?,?,?,?)", (int(hid), d, v or 0, n or "", time.time()))


def set_meal(rt: Any, slot: str, text: str, day: str | None = None) -> None:
    d = day or _iso(today())
    dt.date.fromisoformat(d)
    if slot not in dict(MEAL_SLOTS):
        raise ValueError("Neznámé jídlo dne.")
    t = " ".join(str(text or "").split())[:200]
    if t:
        _db(rt).exec("INSERT OR REPLACE INTO habit_meals (day, slot, text, ts) VALUES (?,?,?,?)", (d, slot, t, time.time()))
    else:
        _db(rt).exec("DELETE FROM habit_meals WHERE day=? AND slot=?", (d, slot))


# ---------- counting ----------
def _due(h: dict, d: dt.date) -> bool:
    return str(d.weekday()) in h["days"] and (h.get("created") or "0000") <= _iso(d)


def _done(h: dict, value: float | None) -> bool:
    if not value:
        return False
    return value >= h["target"] if h["kind"] == "amount" else value >= 1


def _logs(rt: Any, start: dt.date, end: dt.date) -> dict[tuple[int, str], dict]:
    rows = _db(rt).all("SELECT habit_id, day, value, note FROM habit_log WHERE day BETWEEN ? AND ?", (_iso(start), _iso(end)))
    return {(r["habit_id"], r["day"]): r for r in rows}


def _day_score(hs: list[dict], logs: dict, d: dt.date) -> tuple[int, int]:
    due = [h for h in hs if _due(h, d)]
    done = sum(1 for h in due if _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value")))
    return done, len(due)


def _pct(done: int, due: int) -> int | None:
    return round(100 * done / due) if due else None


def _range_pct(hs: list[dict], logs: dict, start: dt.date, end: dt.date) -> int | None:
    done = due = 0
    d = start
    while d <= end:
        a, b = _day_score(hs, logs, d)
        done, due = done + a, due + b
        d += dt.timedelta(days=1)
    return _pct(done, due)


def _streaks(h: dict, logs: dict, end: dt.date, days: int = 400) -> tuple[int, int]:
    """(current, best) – days in a row the habit was done; days it was not planned do not break it; today not done yet
    does not break it either (the day is not over)."""
    cur = best = run = 0
    counting_current = True
    d = end
    for i in range(days):
        if (h.get("created") or "0000") > _iso(d):
            break
        if _due(h, d):
            ok = _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value"))
            if ok:
                run += 1
            elif not (i == 0 and d == today()):
                if counting_current:
                    cur, counting_current = run, False
                best = max(best, run)
                run = 0
        d -= dt.timedelta(days=1)
    if counting_current:
        cur = run
    return cur, max(best, run, cur)


def snapshot(rt: Any, month: str | None = None) -> dict:
    """Everything the notch and the full screen show, in one piece."""
    seed(rt)
    hs = habits(rt)
    t = today()
    try:
        m0 = dt.date.fromisoformat((month or _iso(t)[:7]) + "-01")
    except ValueError:
        m0 = t.replace(day=1)
    m_last = m0.replace(day=calendar.monthrange(m0.year, m0.month)[1])
    start = min(t - dt.timedelta(days=400), m0)
    logs = _logs(rt, start, max(t, m_last))
    ti = _iso(t)
    items = []
    for h in hs:
        lg = logs.get((h["id"], ti)) or {}
        cur, best = _streaks(h, logs, t)
        last7 = []
        for k in range(6, -1, -1):
            d = t - dt.timedelta(days=k)
            v = (logs.get((h["id"], _iso(d))) or {}).get("value")
            last7.append(None if not _due(h, d) else _done(h, v))
        since = max(t - dt.timedelta(days=29), dt.date.fromisoformat(h.get("created") or ti))
        due30 = done30 = 0
        d = since
        while d <= t:
            if _due(h, d):
                due30 += 1
                done30 += _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value"))
            d += dt.timedelta(days=1)
        items.append({**{k: h[k] for k in ("id", "name", "icon", "color", "area", "kind", "target", "unit", "days")},
                      "value": lg.get("value") or 0, "note": lg.get("note") or "", "due": _due(h, t), "done": _done(h, lg.get("value")),
                      "streak": cur, "best": best, "last7": last7, "rate30": _pct(done30, due30)})
    done_t, due_t = _day_score(hs, logs, t)
    monday = t - dt.timedelta(days=t.weekday())
    week = _range_pct(hs, logs, monday, t)
    last_week = _range_pct(hs, logs, monday - dt.timedelta(days=7), t - dt.timedelta(days=7))
    trend = []
    for k in range(29, -1, -1):
        d = t - dt.timedelta(days=k)
        a, b = _day_score(hs, logs, d)
        trend.append({"day": _iso(d), "pct": _pct(a, b)})
    grid = []
    for h in hs:
        cells = []
        d = m0
        while d <= m_last:
            if d > t or not _due(h, d):
                cells.append("future" if d > t else "off")
            else:
                cells.append("done" if _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value")) else ("today" if d == t else "miss"))
            d += dt.timedelta(days=1)
        grid.append({"id": h["id"], "cells": cells})
    meals = {r["slot"]: r["text"] for r in _db(rt).all("SELECT slot, text FROM habit_meals WHERE day=?", (ti,))}
    consistency = _range_pct(hs, logs, t - dt.timedelta(days=29), t)
    board = sorted([i for i in items if i["rate30"] is not None], key=lambda i: -i["rate30"])
    return {
        "date": ti, "weekday": t.weekday(), "items": items,
        "today": {"done": done_t, "due": due_t, "pct": _pct(done_t, due_t)},
        "week": week, "last_week": last_week, "delta": (week - last_week) if week is not None and last_week is not None else None,
        "consistency": consistency, "trend": trend,
        "month": {"id": _iso(m0)[:7], "days": m_last.day, "first_weekday": m0.weekday(), "grid": grid},
        "leaders": [{"id": i["id"], "name": i["name"], "color": i["color"], "rate": i["rate30"]} for i in board[:5]],
        "streaks": sorted([{"id": i["id"], "name": i["name"], "color": i["color"], "streak": i["streak"]} for i in items if i["streak"]],
                          key=lambda x: -x["streak"])[:5],
        "meals": [{"slot": s, "label": label, "text": meals.get(s, "")} for s, label in MEAL_SLOTS],
        "remind": remind_time(rt),
        "areas": AREAS,
    }


def find(rt: Any, name: str) -> dict | None:
    """"gym", "posilovna", "trénink" → the training habit; by name first, then by area words."""
    from .stark import _fold

    q = _fold(name or "")
    hs = habits(rt)
    for h in hs:
        if _fold(h["name"]) == q:
            return h
    for h in hs:
        if q and (q in _fold(h["name"]) or _fold(h["name"]) in q):
            return h
    words = {"gym": ("gym", "posil", "trenink", "trenin", "cvic", "beh", "sport", "workout"), "spanek": ("spal", "span", "sleep"),
             "jidlo": ("jidl", "jedl", "strava", "jidelnic"), "zdravi": ("vod", "pil", "drink"), "mysl": ("medit", "dych")}
    for area, keys in words.items():
        if any(k in q for k in keys):
            hit = next((h for h in hs if h["area"] == area and (area != "zdravi" or "vod" in _fold(h["name"]))), None) or \
                next((h for h in hs if h["area"] == area), None)
            if hit:
                return hit
    return None


def summary(rt: Any) -> str:
    s = snapshot(rt)
    if not s["items"]:
        return "Zatím nemáš žádné návyky."
    left = [i["name"] for i in s["items"] if i["due"] and not i["done"]]
    t = s["today"]
    head = f"Dnes máš splněno {t['done']} z {t['due']} ({t['pct'] or 0} %)." if t["due"] else "Dnes nic naplánovaného nemáš."
    week = f" Tento týden {s['week']} %." if s["week"] is not None else ""
    rest = f" Zbývá: {', '.join(left)}." if left else (" Všechno hotovo, paráda!" if t["due"] else "")
    best = max(s["items"], key=lambda i: i["streak"])
    streak = f" Nejdelší série: {best['name']} {best['streak']} dní v řadě." if best["streak"] >= 2 else ""
    return head + week + rest + streak


def publish(rt: Any) -> None:
    rt.bus.publish("habits", **snapshot(rt))


# ---------- the evening reminder ----------
REMIND_DEFAULT = "20:30"


def remind_time(rt: Any) -> str:
    """"HH:MM" or "" (off)."""
    row = _db(rt).one("SELECT v FROM kv WHERE k='habits_remind'")
    return REMIND_DEFAULT if row is None else str(row["v"] or "")


def set_remind(rt: Any, value: str) -> None:
    v = (value or "").strip()
    if v:
        hh, mm = v.split(":")
        v = f"{int(hh):02d}:{int(mm):02d}"
        if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
            raise ValueError("Neplatný čas připomínky.")
    _db(rt).exec("INSERT OR REPLACE INTO kv VALUES ('habits_remind', ?)", (v,))


def remind_due(rt: Any, now: dt.datetime | None = None) -> str:
    """The reminder text when it is time (once a day, only if something is left), else ""."""
    t = remind_time(rt)
    if not t:
        return ""
    now = now or dt.datetime.now()
    if now.strftime("%H:%M") < t:
        return ""
    day = now.date().isoformat()
    row = _db(rt).one("SELECT v FROM kv WHERE k='habits_reminded'")
    if row and row["v"] == day:
        return ""
    _db(rt).exec("INSERT OR REPLACE INTO kv VALUES ('habits_reminded', ?)", (day,))
    s = snapshot(rt)
    left = [i["name"] for i in s["items"] if i["due"] and not i["done"]]
    if not left:
        return ""
    return f"Dnes máš {s['today']['pct'] or 0} %. Ještě zbývá: {', '.join(left)}."


async def remind_loop(rt: Any) -> None:
    import asyncio
    import logging

    while True:
        await asyncio.sleep(60)
        try:
            text = remind_due(rt)
            if text:
                rt.notify("Návyky na dnes", text, speak=False)
                if not rt.user_away():                 # away: notify already sent it to the phone
                    rt.phone_push("notify", title="Návyky na dnes", body=text)
        except Exception as e:  # noqa: BLE001 – try again next minute
            logging.getLogger("jarvis.habits").debug("remind: %s", e)
