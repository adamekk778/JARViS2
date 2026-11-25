"""3.18 Dlouhý běh (návrh 18): JARVIS runs for weeks – every 5 minutes it notes its own memory, CPU, threads and open
files (7 days, on this PC only). Diagnostika shows the last day; when the memory keeps growing for a day (a leak), you
get one notice a day with what to send. Nothing leaves the PC.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

log = logging.getLogger("jarvis.resmon")

EVERY_S = 300
KEEP_S = 7 * 86400
GROW_MB_PER_DAY = 150.0          # more than this for a whole day = it keeps growing
MIN_RSS_MB = 400.0               # …and only when it is already big
SQL = "CREATE TABLE IF NOT EXISTS resmon (ts REAL PRIMARY KEY, rss REAL, cpu REAL, threads INTEGER, files INTEGER)"


def sample() -> dict:
    import psutil

    p = psutil.Process()
    with p.oneshot():
        rss = p.memory_info().rss / 2**20
        cpu = p.cpu_percent(interval=None)
        threads = p.num_threads()
        try:
            files = len(p.open_files()) + (p.num_handles() if hasattr(p, "num_handles") else 0)
        except Exception:  # noqa: BLE001
            files = 0
    return {"ts": time.time(), "rss": round(rss, 1), "cpu": round(cpu, 1), "threads": threads, "files": files}


def record(rt: Any, s: dict) -> None:
    rt.db.exec(SQL)
    rt.db.exec("INSERT OR REPLACE INTO resmon (ts, rss, cpu, threads, files) VALUES (?,?,?,?,?)",
               (s["ts"], s["rss"], s["cpu"], s["threads"], s["files"]))
    rt.db.exec("DELETE FROM resmon WHERE ts < ?", (s["ts"] - KEEP_S,))


def series(rt: Any, hours: float = 24.0, now: float | None = None) -> list[dict]:
    rt.db.exec(SQL)
    since = (now or time.time()) - hours * 3600
    return [dict(r) for r in rt.db.all("SELECT * FROM resmon WHERE ts >= ? ORDER BY ts", (since,))]


def growth(points: list[dict]) -> float:
    """MB per day by a least-squares line through the memory samples (0 with too few)."""
    if len(points) < 12:
        return 0.0
    t0 = points[0]["ts"]
    xs = [(p["ts"] - t0) / 86400 for p in points]
    ys = [p["rss"] for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den <= 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def summary(rt: Any, now: float | None = None) -> dict:
    pts = series(rt, 24, now)
    if not pts:
        return {"n": 0}
    rss = [p["rss"] for p in pts]
    span_h = (pts[-1]["ts"] - pts[0]["ts"]) / 3600
    g = growth(pts)
    return {"n": len(pts), "hours": round(span_h, 1), "rss_now": rss[-1], "rss_min": min(rss), "rss_max": max(rss),
            "cpu_avg": round(sum(p["cpu"] for p in pts) / len(pts), 1), "threads": pts[-1]["threads"],
            "files": pts[-1]["files"], "grow_mb_day": round(g, 1),
            "leak": span_h >= 20 and g > GROW_MB_PER_DAY and rss[-1] > MIN_RSS_MB,
            "points": [[round(p["ts"]), p["rss"], p["cpu"]] for p in pts[-288:]]}


def check(rt: Any, now: float | None = None) -> bool:
    """One notice a day when it keeps growing."""
    s = summary(rt, now)
    if not s.get("leak"):
        return False
    rt.db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    row = rt.db.one("SELECT v FROM kv WHERE k='resmon_told'")
    t = now or time.time()
    if row and t - float(json.loads(row["v"])) < 86400:
        return False
    rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('resmon_told', ?)", (json.dumps(t),))
    rt.notify("JARVIS roste v paměti", f"Za den o {s['grow_mb_day']:.0f} MB (teď {s['rss_now']:.0f} MB). Restart to spraví; "
              "v Diagnostice je Export – pošli ho prosím, ať se dá najít příčina.", speak=False)
    return True


async def loop(rt: Any) -> None:
    sample()                                   # the first CPU reading is always 0: prime it
    while True:
        await asyncio.sleep(EVERY_S)
        try:
            record(rt, await asyncio.to_thread(sample))
            check(rt)
        except Exception as e:  # noqa: BLE001
            log.debug("resmon: %s", e)
