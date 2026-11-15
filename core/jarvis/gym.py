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
            "plan": today_plan(rt), "plans": {k: v[0] for k, v in PLANS.items()}, "rest": rest_seconds(rt),
            "week": {"sets": len(week), "volume": vol(week), "days": len({r["day"] for r in week}),
                     "prev_volume": vol(prev)}}


# ---------- 3.12 plán tréninku: what to do today, and with how much (last time + a small step) ----------
PLANS: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "ppl": ("Push / Pull / Nohy", [("Push", ["Bench press", "Tlaky nad hlavu", "Kliky na bradlech", "Triceps"]),
                                   ("Pull", ["Mrtvý tah", "Shyby", "Přítahy", "Biceps"]),
                                   ("Nohy", ["Dřep", "Leg press", "Výpady", "Lýtka"])]),
    "upperlower": ("Horní / spodní", [("Horní", ["Bench press", "Přítahy", "Tlaky nad hlavu", "Shyby"]),
                                      ("Spodní", ["Dřep", "Mrtvý tah", "Výpady", "Lýtka"])]),
    "fullbody": ("Celé tělo", [("Celé tělo A", ["Dřep", "Bench press", "Přítahy"]),
                               ("Celé tělo B", ["Mrtvý tah", "Tlaky nad hlavu", "Shyby"])]),
}
REST_DEFAULT = 120


def plan_id(rt: Any) -> str:
    row = _db(rt).one("SELECT v FROM kv WHERE k='gym_plan'")
    return str(row["v"]) if row and row["v"] in PLANS else ""


def set_plan(rt: Any, pid: str) -> None:
    if pid and pid not in PLANS:
        raise ValueError("Takový plán neznám.")
    _db(rt).exec("INSERT OR REPLACE INTO kv VALUES ('gym_plan', ?)", (pid,))


def rest_seconds(rt: Any) -> int:
    row = _db(rt).one("SELECT v FROM kv WHERE k='gym_rest'")
    try:
        return max(0, min(600, int(row["v"]))) if row else REST_DEFAULT
    except (TypeError, ValueError):
        return REST_DEFAULT


def set_rest(rt: Any, secs: int) -> None:
    _db(rt).exec("INSERT OR REPLACE INTO kv VALUES ('gym_rest', ?)", (str(max(0, min(600, int(secs)))),))


def _split_of(splits: list[tuple[str, list[str]]], exercises: set[str]) -> int:
    """Which part of the plan a day's exercises were (the most of its exercises); -1 when none fits."""
    best, idx = 0, -1
    for k, (_, ex) in enumerate(splits):
        n = len(exercises & set(ex))
        if n > best:
            best, idx = n, k
    return idx


def today_plan(rt: Any) -> dict | None:
    pid = plan_id(rt)
    if not pid:
        return None
    name, splits = PLANS[pid]
    db = _db(rt)
    t = today().isoformat()
    by_day: dict[str, set[str]] = {}
    for r in db.all("SELECT day, exercise FROM gym_sets WHERE day >= ? ORDER BY day", ((today() - dt.timedelta(days=60)).isoformat(),)):
        by_day.setdefault(r["day"], set()).add(r["exercise"])
    if t in by_day and _split_of(splits, by_day[t]) >= 0:
        idx = _split_of(splits, by_day[t])                      # already training: today's part stays
    else:
        last = next((_split_of(splits, ex) for d, ex in sorted(by_day.items(), reverse=True) if d < t and _split_of(splits, ex) >= 0), -1)
        idx = (last + 1) % len(splits)
    split, exercises = splits[idx]
    items = []
    for ex in exercises:
        last = db.one("SELECT day, weight, reps FROM gym_sets WHERE exercise=? AND day < ? ORDER BY day DESC, weight DESC, reps DESC LIMIT 1",
                      (ex, t))
        sug = None
        if last:
            w, r = float(last["weight"] or 0), int(last["reps"] or 0)
            sug = ({"weight": w, "reps": r + 1} if w <= 0 else
                   {"weight": round(w + 2.5, 1), "reps": r} if r >= 8 else {"weight": w, "reps": r + 1})
        done = db.one("SELECT COUNT(*) AS n FROM gym_sets WHERE exercise=? AND day=?", (ex, t))["n"]
        items.append({"exercise": ex, "last": dict(last) if last else None, "suggest": sug, "done_sets": done})
    return {"plan": pid, "name": name, "split": split, "items": items}


def publish(rt: Any) -> None:
    rt.bus.publish("gym", **snapshot(rt))
