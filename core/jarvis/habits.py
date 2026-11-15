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
CREATE TABLE IF NOT EXISTS habit_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, text TEXT NOT NULL,
  done INTEGER DEFAULT 0, ts REAL);
CREATE TABLE IF NOT EXISTS habit_days (day TEXT PRIMARY KEY, mindset TEXT);
CREATE TABLE IF NOT EXISTS habit_goals (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, target REAL, current REAL,
  unit TEXT, deadline TEXT, color TEXT, created TEXT);
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
    cols = {r[1] for r in rt.db.conn.execute("PRAGMA table_info(habit_days)")}
    for c in ("energy", "focus", "motivation"):          # the mindset tracker (1–5 a day), added after the first version
        if c not in cols:
            rt.db.conn.execute(f"ALTER TABLE habit_days ADD COLUMN {c} INTEGER")
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


def _rate(h: dict, logs: dict, start: dt.date, end: dt.date) -> int | None:
    due = done = 0
    d = max(start, dt.date.fromisoformat(h.get("created") or _iso(start)))
    while d <= end:
        if _due(h, d):
            due += 1
            done += _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value"))
        d += dt.timedelta(days=1)
    return _pct(done, due)


# ---------- Úkoly (the week planner) and Cíle (goals) ----------
def plan(rt: Any, hs: list[dict], logs: dict, week: int = 0) -> dict:
    """The week (Monday–Sunday, `week` weeks from this one): every day its tasks, its "mindset" line, how much of the
    tasks and of the habits was done – for the bars on top and a ring on every day."""
    t = today()
    mon = t - dt.timedelta(days=t.weekday()) + dt.timedelta(weeks=max(-52, min(52, int(week or 0))))
    sun = mon + dt.timedelta(days=6)
    db = _db(rt)
    tasks = db.all("SELECT id, day, text, done FROM habit_tasks WHERE day BETWEEN ? AND ? ORDER BY id", (_iso(mon), _iso(sun)))
    minds = {r["day"]: r for r in db.all("SELECT day, mindset, energy, focus, motivation FROM habit_days WHERE day BETWEEN ? AND ?",
                                          (_iso(mon), _iso(sun)))}
    days = []
    for k in range(7):
        d = mon + dt.timedelta(days=k)
        di = _iso(d)
        ts = [{"id": x["id"], "text": x["text"], "done": bool(x["done"])} for x in tasks if x["day"] == di]
        a, b = _day_score(hs, logs, d) if d <= t else (0, 0)
        tdone = sum(1 for x in ts if x["done"])
        both_done, both_all = tdone + a, len(ts) + b
        md = minds.get(di) or {}
        days.append({"day": di, "weekday": k, "tasks": ts, "mindset": md.get("mindset") or "", "future": d > t, "today": d == t,
                     "energy": md.get("energy"), "focus": md.get("focus"), "motivation": md.get("motivation"),
                     "task_pct": _pct(tdone, len(ts)), "habit_pct": _pct(a, b), "pct": _pct(both_done, both_all)})
    done_all = sum(sum(1 for x in d["tasks"] if x["done"]) for d in days)
    all_tasks = sum(len(d["tasks"]) for d in days)
    return {"week": int(week or 0), "start": _iso(mon), "end": _iso(sun), "days": days, "done": done_all, "total": all_tasks,
            "pct": _pct(done_all, all_tasks)}


def task_add(rt: Any, text: str, day: str | None = None) -> int:
    t = " ".join(str(text or "").split())[:160]
    if not t:
        raise ValueError("Napiš, jaký úkol.")
    d = day or _iso(today())
    dt.date.fromisoformat(d)
    return int(_db(rt).exec("INSERT INTO habit_tasks (day, text, done, ts) VALUES (?,?,0,?)", (d, t, time.time())).lastrowid)


def task_set(rt: Any, tid: int, done: bool | None = None, text: str | None = None, day: str | None = None) -> None:
    db = _db(rt)
    if done is not None:
        db.exec("UPDATE habit_tasks SET done=? WHERE id=?", (1 if done else 0, int(tid)))
    if text is not None:
        db.exec("UPDATE habit_tasks SET text=? WHERE id=?", (" ".join(text.split())[:160] or "?", int(tid)))
    if day:
        dt.date.fromisoformat(day)
        db.exec("UPDATE habit_tasks SET day=? WHERE id=?", (day, int(tid)))


def task_delete(rt: Any, tid: int) -> None:
    _db(rt).exec("DELETE FROM habit_tasks WHERE id=?", (int(tid),))


def set_mindset(rt: Any, text: str | None = None, day: str | None = None, **rate: Any) -> None:
    """The day's mindset: a line of text and/or Energie / Soustředění / Motivace from 1 to 5 (0 = clear)."""
    d = day or _iso(today())
    dt.date.fromisoformat(d)
    db = _db(rt)
    db.exec("INSERT OR IGNORE INTO habit_days (day) VALUES (?)", (d,))
    if text is not None:
        db.exec("UPDATE habit_days SET mindset=? WHERE day=?", (" ".join(str(text).split())[:200], d))
    for k in ("energy", "focus", "motivation"):
        if rate.get(k) is not None:
            v = max(0, min(5, int(rate[k])))
            db.exec(f"UPDATE habit_days SET {k}=? WHERE day=?", (v or None, d))


def goals(rt: Any) -> list[dict]:
    out = []
    for g in _db(rt).all("SELECT * FROM habit_goals ORDER BY id"):
        target, cur = float(g.get("target") or 0), float(g.get("current") or 0)
        pct = max(0, min(100, round(100 * cur / target))) if target else 0
        days_left = None
        if g.get("deadline"):
            try:
                days_left = (dt.date.fromisoformat(g["deadline"]) - today()).days
            except ValueError:
                days_left = None
        out.append({**g, "target": target, "current": cur, "pct": pct, "days_left": days_left})
    return out


def goal_save(rt: Any, g: dict) -> int:
    name = " ".join(str(g.get("name") or "").split())[:60]
    if not name:
        raise ValueError("Cíl potřebuje název.")
    target = float(g.get("target") or 0)
    if target <= 0:
        raise ValueError("Cíl potřebuje číslo, kam chceš dojít (třeba 10 km nebo 5 kg).")
    current = max(0.0, float(g.get("current") or 0))
    deadline = str(g.get("deadline") or "")[:10]
    if deadline:
        dt.date.fromisoformat(deadline)
    color = str(g.get("color") or "#2ee6a6")[:20]
    unit = str(g.get("unit") or "")[:16]
    db = _db(rt)
    if g.get("id"):
        db.exec("UPDATE habit_goals SET name=?, target=?, current=?, unit=?, deadline=?, color=? WHERE id=?",
                (name, target, current, unit, deadline, color, int(g["id"])))
        return int(g["id"])
    return int(db.exec("INSERT INTO habit_goals (name, target, current, unit, deadline, color, created) VALUES (?,?,?,?,?,?,?)",
                       (name, target, current, unit, deadline, color, _iso(today()))).lastrowid)


def goal_delete(rt: Any, gid: int) -> None:
    _db(rt).exec("DELETE FROM habit_goals WHERE id=?", (int(gid),))


def snapshot(rt: Any, month: str | None = None, week_offset: int = 0) -> dict:
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
        hist = []                                   # the last 30 days of this habit (the Přehled chart can show one habit)
        for k in range(29, -1, -1):
            d = t - dt.timedelta(days=k)
            hist.append(None if not _due(h, d) else _done(h, (logs.get((h["id"], _iso(d))) or {}).get("value")))
        items.append({**{k: h[k] for k in ("id", "name", "icon", "color", "area", "kind", "target", "unit", "days")},
                      "value": lg.get("value") or 0, "note": lg.get("note") or "", "due": _due(h, t), "done": _done(h, lg.get("value")),
                      "streak": cur, "best": best, "last7": last7, "rate30": _pct(done30, due30),
                      "rate7": _rate(h, logs, t - dt.timedelta(days=6), t), "rate90": _rate(h, logs, t - dt.timedelta(days=89), t),
                      "hist": hist})
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
        "plan": plan(rt, hs, logs, week_offset),
        "goals": goals(rt),
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


def weekly_due(rt: Any, now: dt.datetime | None = None) -> str:
    """3.12 Sunday evening (from 19:00, once a week): how the week went – the %, against last week, the best habit,
    the one that lags, the longest streak. "" when it is not time, it was sent already, or there is nothing to say."""
    now = now or dt.datetime.now()
    if now.weekday() != 6 or now.hour < 19 or not remind_time(rt):
        return ""
    week = now.date().isocalendar()
    key = f"{week[0]}-W{week[1]:02d}"
    row = _db(rt).one("SELECT v FROM kv WHERE k='habits_weekly'")
    if row and row["v"] == key:
        return ""
    _db(rt).exec("INSERT OR REPLACE INTO kv VALUES ('habits_weekly', ?)", (key,))
    s = snapshot(rt)
    rated = [i for i in s["items"] if i.get("rate7") is not None]
    if s["week"] is None or not rated:
        return ""
    parts = [f"Tenhle týden {s['week']} %"
             + (f" ({'+' if s['delta'] >= 0 else ''}{s['delta']} % proti minulému)." if s.get("delta") is not None else ".")]
    best = max(rated, key=lambda i: i["rate7"])
    worst = min(rated, key=lambda i: i["rate7"])
    parts.append(f"Nejlíp ti šlo: {best['name']} ({best['rate7']} %).")
    if worst["id"] != best["id"] and worst["rate7"] < 80:
        parts.append(f"Nejvíc vázne: {worst['name']} ({worst['rate7']} %) – zkus ho příští týden dát hned ráno.")
    top = max(s["items"], key=lambda i: i["streak"])
    if top["streak"] >= 3:
        parts.append(f"Nejdelší série: {top['name']} {top['streak']} dní 🔥")
    return " ".join(parts)


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
            week = weekly_due(rt)
            if week:                                   # 3.12 the week in one message, on the PC and the phone
                rt.notify("Týden v návycích", week, speak=False)
                if not rt.user_away():
                    rt.phone_push("notify", title="Týden v návycích", body=week)
        except Exception as e:  # noqa: BLE001 – try again next minute
            logging.getLogger("jarvis.habits").debug("remind: %s", e)
