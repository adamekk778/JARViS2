"""OMEGA §39 Proactive Intelligence, built only from what JARVIS already knows on this PC: forgotten work, questions
left unanswered, your daily routines, what to do next (and in a spare five minutes), deadlines at risk, how long a
task usually takes, what you got done today – and when NOT to interrupt (fullscreen, a meeting, focus, night).

Everything is a suggestion with its reason; nothing here acts on its own."""
from __future__ import annotations

import datetime as dt
import re
import statistics
import time

DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def _has(rt, table: str) -> bool:
    return bool(rt.db.one("SELECT 1 FROM sqlite_master WHERE name=?", (table,)))


# ---------------------------------------------------------------------------------------------- 499 forgotten work
def forgotten(rt, days: int = 7, now: float | None = None) -> list[dict]:
    now = now or time.time()
    cut = now - days * 86400
    out = []
    for t in rt.db.all("SELECT id, goal, status, created FROM tasks WHERE status IN ('paused','interrupted','waiting','queued') AND created<? "
                       "ORDER BY created LIMIT 20", (cut,)):
        out.append({"kind": "mission", "text": f"Mise „{t['goal'][:80]}“ stojí ({t['status']}) od {dt.date.fromtimestamp(t['created']):%d. %m.}",
                    "ref": t["id"], "age_days": int((now - t["created"]) // 86400)})
    if _has(rt, "projects"):
        for p in rt.db.all("SELECT name, updated FROM projects WHERE archived=0 AND updated<?", (cut,)):
            out.append({"kind": "project", "text": f"Projekt „{p['name']}“ – {int((now - p['updated']) // 86400)} dní bez práce",
                        "ref": p["name"], "age_days": int((now - p["updated"]) // 86400)})
    if _has(rt, "lists"):
        for li in rt.db.all("SELECT list, COUNT(*) AS n, MIN(ts) AS oldest FROM lists WHERE ts<? GROUP BY list", (cut,)):
            out.append({"kind": "list", "text": f"V seznamu „{li['list']}“ leží {li['n']} položek déle než {days} dní",
                        "ref": li["list"], "age_days": int((now - li["oldest"]) // 86400)})
    return sorted(out, key=lambda x: -x["age_days"])


# ---------------------------------------------------------------------------------------------- 506 unanswered
def unfinished_conversations(rt, days: int = 14, now: float | None = None) -> list[dict]:
    """A conversation whose last word is your question without an answer, or JARVIS's question you never answered."""
    now = now or time.time()
    out = []
    for c in rt.db.all("SELECT id, title, updated FROM conversations WHERE updated>=? ORDER BY updated DESC LIMIT 50", (now - days * 86400,)):
        last = rt.db.one("SELECT role, content, created FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT 1", (c["id"],))
        if not last:
            continue
        text = (last["content"] or "").strip()
        if last["role"] == "user" and now - last["created"] > 600:
            out.append({"conv": c["id"], "title": c["title"] or "Konverzace", "why": "tvoje zpráva zůstala bez odpovědi", "text": text[:160]})
        elif last["role"] == "assistant" and text.rstrip().endswith("?") and now - last["created"] > 3600:
            out.append({"conv": c["id"], "title": c["title"] or "Konverzace", "why": "JARVIS se ptal a odpověď nepřišla",
                        "text": text.rstrip()[-160:]})
    return out


# ---------------------------------------------------------------------------------------------- 497 / 504 routines
def routines(rt, weeks: int = 4, min_days: int = 3, min_minutes: float = 5, today: dt.date | None = None) -> list[dict]:
    """Apps you use at the same hour on many days (weekdays and weekends apart)."""
    if not _has(rt, "app_hours"):
        return []
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=weeks * 7)).isoformat()
    rows = rt.db.all("SELECT day, hour, app, seconds FROM app_hours WHERE day>=? AND seconds>=?", (since, min_minutes * 60))
    groups: dict[tuple[str, int, str], set[str]] = {}
    for r in rows:
        kind = "víkend" if dt.date.fromisoformat(r["day"]).weekday() >= 5 else "všední den"
        groups.setdefault((kind, r["hour"], r["app"]), set()).add(r["day"])
    out = []
    for (kind, hour, app), days in groups.items():
        if len(days) >= min_days:
            out.append({"when": kind, "hour": hour, "app": app, "days": len(days),
                        "text": f"{'Ve všední dny' if kind == 'všední den' else 'O víkendu'} kolem {hour}:00 používáš {app} ({len(days)} dní)"})
    return sorted(out, key=lambda x: (-x["days"], x["hour"]))


# ---------------------------------------------------------------------------------------------- 502 deadlines
def deadline_risks(rt, now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for t in rt.db.all("SELECT id, goal, status, deadline FROM tasks WHERE deadline IS NOT NULL AND status NOT IN ('done','cancelled')"):
        left_h = (t["deadline"] - now) / 3600
        steps = rt.db.all("SELECT status FROM task_steps WHERE task_id=?", (t["id"],))
        todo = sum(1 for s in steps if s["status"] not in ("done", "skipped"))
        risk = "propadlý" if left_h < 0 else "vysoké" if left_h < 2 or (todo and left_h / max(todo, 1) < 0.5) else "střední" if left_h < 24 else "nízké"
        out.append({"kind": "mission", "text": f"„{t['goal'][:70]}“: zbývá {max(0, round(left_h, 1))} h, kroků {todo}", "risk": risk})
    if hasattr(rt, "learning"):
        for e in rt.learning.exams():
            reviewed = rt.db.one("SELECT COUNT(*) AS n FROM card_reviews WHERE ts>=?", (now - 3 * 86400,))["n"]
            risk = "vysoké" if e["days_left"] <= 3 and not reviewed else "střední" if e["days_left"] <= 7 and not reviewed else "nízké"
            out.append({"kind": "exam", "text": f"Zkouška {e['name']} za {e['days_left']} dní" + ("" if reviewed else ", 3 dny bez opakování"), "risk": risk})
    order = {"propadlý": 0, "vysoké": 1, "střední": 2, "nízké": 3}
    return sorted(out, key=lambda x: order[x["risk"]])


# ---------------------------------------------------------------------------------------------- 503 effort
def effort_estimate(rt, goal: str) -> dict:
    """From your own finished missions with similar words: median time and number of actions."""
    words = {w for w in re.findall(r"\w{4,}", goal.lower())}
    sims = []
    for t in rt.db.all("SELECT id, goal, created, finished FROM tasks WHERE status='done' AND finished IS NOT NULL ORDER BY created DESC LIMIT 400"):
        tw = set(re.findall(r"\w{4,}", t["goal"].lower()))
        j = len(words & tw) / len(words | tw) if words and tw else 0
        if j >= 0.3:
            n = rt.db.one("SELECT COUNT(*) AS n FROM task_actions WHERE task_id=?", (t["id"],))["n"]
            sims.append({"goal": t["goal"], "minutes": (t["finished"] - t["created"]) / 60, "actions": n, "sim": j})
    if not sims:
        return {"known": False}
    return {"known": True, "similar": len(sims), "median_minutes": round(statistics.median(s["minutes"] for s in sims), 1),
            "median_actions": int(statistics.median(s["actions"] for s in sims)), "examples": [s["goal"] for s in sims[:3]]}


# ---------------------------------------------------------------------------------------------- 496 / 507 / 501 next
def next_actions(rt, idle_minutes: float = 0, now: float | None = None) -> list[dict]:
    now = now or time.time()
    sug: list[dict] = []
    for r in deadline_risks(rt, now):
        if r["risk"] in ("propadlý", "vysoké"):
            sug.append({"text": r["text"], "why": f"riziko termínu: {r['risk']}", "minutes": 30, "score": 90})
    if hasattr(rt, "learning"):
        due = len(rt.learning.due("", 200))
        if due:
            sug.append({"text": f"Zopakovat {due} kartiček", "why": "jsou na řadě (časované opakování)", "minutes": max(1, round(due * 0.4)), "score": 60})
    for u in unfinished_conversations(rt, 7, now)[:2]:
        sug.append({"text": f"Dořešit „{u['title']}“", "why": u["why"], "minutes": 5, "score": 55})
    hour = dt.datetime.fromtimestamp(now).hour
    weekend = dt.date.fromtimestamp(now).weekday() >= 5
    for r in routines(rt, today=dt.date.fromtimestamp(now)):
        if r["hour"] == hour and (r["when"] == "víkend") == weekend:
            sug.append({"text": f"Otevřít {r['app']}", "why": f"touhle dobou ho obvykle používáš ({r['days']} dní)", "minutes": 1, "score": 40})
    for f in forgotten(rt, 7, now)[:2]:
        sug.append({"text": f["text"], "why": "dlouho se na to nesáhlo", "minutes": 15, "score": 35})
    if _has(rt, "lists"):
        for li in rt.db.all("SELECT list, item FROM lists ORDER BY ts LIMIT 3"):
            sug.append({"text": f"{li['item']} (seznam {li['list']})", "why": "čeká v seznamu", "minutes": 10, "score": 25})
    if idle_minutes:
        sug = [s for s in sug if s["minutes"] <= idle_minutes]
    return sorted(sug, key=lambda s: -s["score"])


# ---------------------------------------------------------------------------------------------- 510 the day
def day_summary(rt, day: dt.date | None = None) -> dict:
    day = day or dt.date.today()
    t0 = dt.datetime.combine(day, dt.time()).timestamp()
    t1 = t0 + 86400
    done = rt.db.all("SELECT goal FROM tasks WHERE status='done' AND finished>=? AND finished<?", (t0, t1))
    msgs = rt.db.one("SELECT COUNT(*) AS n FROM messages WHERE role='user' AND created>=? AND created<?", (t0, t1))["n"]
    reviews = rt.db.one("SELECT COUNT(*) AS n FROM card_reviews WHERE ts>=? AND ts<?", (t0, t1))["n"] if _has(rt, "card_reviews") else 0
    dictated = rt.db.one("SELECT COUNT(*) AS n, SUM(LENGTH(text)) AS c FROM dictations WHERE ts>=? AND ts<?", (t0, t1)) if _has(rt, "dictations") else {"n": 0, "c": 0}
    apps = rt.db.all("SELECT app, seconds FROM app_usage WHERE day=? ORDER BY seconds DESC LIMIT 3", (day.isoformat(),)) if _has(rt, "app_usage") else []
    return {"day": day.isoformat(), "missions_done": [d["goal"] for d in done], "messages": msgs, "card_reviews": reviews,
            "dictations": dictated["n"] or 0, "dictated_words": round((dictated["c"] or 0) / 6),
            "top_apps": [{"app": a["app"], "minutes": round(a["seconds"] / 60)} for a in apps]}


# ---------------------------------------------------------------------------------------------- 500 interruptions
def quiet_reason(rt, now: float | None = None) -> str:
    """Why JARVIS should not speak up right now ("" = it may). Night 22–7, focus/sleep mood, a calendar event now,
    a fullscreen app (game, film, presentation)."""
    now = now or time.time()
    h = dt.datetime.fromtimestamp(now).hour
    if h >= 22 or h < 7:
        return "noc"
    mood = getattr(getattr(rt, "mood", None), "manual", None)
    if mood in ("focus", "sleeping"):
        return "soustředění" if mood == "focus" else "spánek"
    if _has(rt, "cal_events") and rt.db.one("SELECT title FROM cal_events WHERE start<=? AND end>? LIMIT 1", (now, now)):
        return "schůzka"
    try:
        from .desktop import winutil

        if winutil.foreground_is_fullscreen():
            return "aplikace přes celou obrazovku"
    except Exception:  # noqa: BLE001 – not Windows / no desktop
        pass
    return ""


def describe(items: list[dict], key: str = "text", limit: int = 6) -> str:
    return "; ".join(str(i[key]) for i in items[:limit])
