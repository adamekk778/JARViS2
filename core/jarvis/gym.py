"""3.12 Gym deník: every set you do (exercise, kg, reps), and how you get stronger – the best set per exercise, the
estimated one-rep max over the weeks (a line that should go up), records and this week's volume. A set logged today
also ticks the training habit. By voice too: "bench 60 kilo 8 opakování". Everything stays in the local database.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

SQL = """
CREATE TABLE IF NOT EXISTS gym_sets (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, exercise TEXT NOT NULL,
  weight REAL, reps INTEGER, ts REAL);
CREATE INDEX IF NOT EXISTS gym_sets_ex ON gym_sets (exercise, day);
"""
# names people say → one name, so "bench", "benčpres" and "bench press" are one line in the chart
ALIASES = {"bench": "Bench press", "bench press": "Bench press", "benchpress": "Bench press", "benč": "Bench press",
           "benčpres": "Bench press", "tlak na lavici": "Bench press", "dřep": "Dřep", "drep": "Dřep", "squat": "Dřep",
           "mrtvý tah": "Mrtvý tah", "mrtvy tah": "Mrtvý tah", "deadlift": "Mrtvý tah", "shyby": "Shyby",
           "pull up": "Shyby", "pullup": "Shyby", "kliky": "Kliky", "push up": "Kliky", "tlaky nad hlavu": "Tlaky nad hlavu",
           "ohp": "Tlaky nad hlavu", "military press": "Tlaky nad hlavu", "bicepsový zdvih": "Biceps", "biceps": "Biceps",
           "přítahy": "Přítahy", "veslování": "Přítahy", "row": "Přítahy", "legpress": "Leg press", "leg press": "Leg press"}


def _db(rt: Any):
    rt.db.conn.executescript(SQL)
    return rt.db


def today() -> dt.date:
    return dt.date.today()


def name(ex: str) -> str:
    raw = " ".join(str(ex or "").split())[:60]
    if not raw:
        raise ValueError("Napiš, jaký cvik to byl.")
    return ALIASES.get(raw.lower(), raw[:1].upper() + raw[1:])


def one_rm(weight: float, reps: int) -> float:
    """Estimated one-rep max (Epley) – lets 60 kg × 10 and 70 kg × 5 be compared on one line."""
    if weight <= 0 or reps <= 0:
        return 0.0
    return round(weight * (1 + min(reps, 30) / 30), 1) if reps > 1 else round(weight, 1)


def add_set(rt: Any, exercise: str, weight: float, reps: int, day: str | None = None, sets: int = 1) -> list[int]:
    ex = name(exercise)
    w = round(float(weight or 0), 2)
    r = int(reps or 0)
    if w < 0 or w > 1000:
        raise ValueError("Váha musí být mezi 0 a 1000 kg.")
    if r <= 0 or r > 500:
        raise ValueError("Počet opakování musí být aspoň 1.")
    d = dt.date.fromisoformat(day) if day else today()
    if d > today():
        raise ValueError("Do budoucna se zapisovat nedá.")
    db = _db(rt)
    ids = [int(db.exec("INSERT INTO gym_sets (day, exercise, weight, reps, ts) VALUES (?,?,?,?,?)",
                       (d.isoformat(), ex, w, r, time.time())).lastrowid) for _ in range(max(1, min(int(sets or 1), 20)))]
    if d == today():
        _tick_training(rt)
    return ids


def _tick_training(rt: Any) -> None:
    """A set today = the training habit is done today (if you have one)."""
    try:
        from . import habits

        for h in habits.habits(rt):
            if h.get("area") == "gym" and h.get("kind") == "check":
                habits.log(rt, h["id"], 1)
                break
    except Exception:  # noqa: BLE001 – the diary works without the habits
        pass


def delete_set(rt: Any, sid: int) -> None:
    _db(rt).exec("DELETE FROM gym_sets WHERE id=?", (int(sid),))


def snapshot(rt: Any, days: int = 120) -> dict:
    db = _db(rt)
    t = today()
    since = (t - dt.timedelta(days=days - 1)).isoformat()
    rows = db.all("SELECT id, day, exercise, weight, reps FROM gym_sets WHERE day >= ? ORDER BY day, id", (since,))
    today_rows = [dict(r) for r in rows if r["day"] == t.isoformat()]
    by_ex: dict[str, dict] = {}
    for r in rows:
        e = by_ex.setdefault(r["exercise"], {"name": r["exercise"], "days": {}, "best": None, "last": r["day"], "sets": 0})
        rm = one_rm(r["weight"] or 0, r["reps"] or 0)
        e["days"][r["day"]] = max(e["days"].get(r["day"], 0.0), rm)
        e["sets"] += 1
        e["last"] = max(e["last"], r["day"])
        if e["best"] is None or (r["weight"] or 0, r["reps"] or 0) > (e["best"]["weight"], e["best"]["reps"]):
            e["best"] = {"weight": r["weight"] or 0, "reps": r["reps"] or 0, "day": r["day"]}
    exercises = []
    for e in sorted(by_ex.values(), key=lambda x: x["last"], reverse=True):
        pts = [{"day": d, "rm": v} for d, v in sorted(e["days"].items())]
        first, last = (pts[0]["rm"], pts[-1]["rm"]) if pts else (0, 0)
        exercises.append({"name": e["name"], "best": e["best"], "sets": e["sets"], "last": e["last"], "points": pts[-40:],
                          "rm": last, "gain": round(last - first, 1) if len(pts) > 1 else None,
                          "pr_today": bool(pts and pts[-1]["day"] == t.isoformat() and last >= max(p["rm"] for p in pts))})
    monday = t - dt.timedelta(days=t.weekday())
    week = [r for r in rows if r["day"] >= monday.isoformat()]
    prev = [r for r in rows if (monday - dt.timedelta(days=7)).isoformat() <= r["day"] < monday.isoformat()]
    vol = lambda rs: round(sum((r["weight"] or 0) * (r["reps"] or 0) for r in rs))   # noqa: E731
    names = [r["exercise"] for r in db.all("SELECT exercise, MAX(day) AS d FROM gym_sets GROUP BY exercise ORDER BY d DESC LIMIT 40")]
    return {"date": t.isoformat(), "today": today_rows, "exercises": exercises, "names": names,
            "week": {"sets": len(week), "volume": vol(week), "days": len({r["day"] for r in week}),
                     "prev_volume": vol(prev)}}


def publish(rt: Any) -> None:
    rt.bus.publish("gym", **snapshot(rt))
