"""OMEGA 171 / 565 / 446: project deadlines and milestones as a calendar file (.ics) any calendar imports (Google,
Outlook, phone); OMEGA 175: a weekly work report – missions finished, meetings, time in apps, dictation, what is due."""
from __future__ import annotations

import datetime as dt
import time



def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(events: list[dict], name: str = "JARVIS – termíny") -> str:
    """events: {uid, title, start (date or datetime), end?, note?}. All-day for dates, with time for datetimes."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//CS", "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_esc(name)}"]
    for e in events:
        st = e["start"]
        out += ["BEGIN:VEVENT", f"UID:{e['uid']}@jarvis", f"DTSTAMP:{now}", f"SUMMARY:{_esc(e['title'])}"]
        if isinstance(st, dt.datetime):
            en = e.get("end") or st + dt.timedelta(hours=1)
            out += [f"DTSTART:{st.strftime('%Y%m%dT%H%M%S')}", f"DTEND:{en.strftime('%Y%m%dT%H%M%S')}"]
        else:
            out += [f"DTSTART;VALUE=DATE:{st.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(st + dt.timedelta(days=1)).strftime('%Y%m%d')}"]
        if e.get("note"):
            out.append(f"DESCRIPTION:{_esc(e['note'])}")
        if e.get("remind_h"):
            out += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(e['title'])}", f"TRIGGER:-PT{int(e['remind_h'])}H", "END:VALARM"]
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def milestones(rt, now: float | None = None) -> list[dict]:
    """Mission deadlines, exams and dated pins – everything with a date that lies ahead."""
    now = now or time.time()
    ev = []
    for t in rt.db.all("SELECT id, goal, deadline FROM tasks WHERE deadline IS NOT NULL AND deadline>=? AND status NOT IN ('done','cancelled')", (now,)):
        ev.append({"uid": f"task-{t['id']}", "title": f"Termín: {t['goal'][:80]}", "start": dt.datetime.fromtimestamp(t["deadline"]),
                   "note": "Mise v JARVISovi", "remind_h": 24, "kind": "mise"})
    if hasattr(rt, "learning"):
        for e in rt.learning.exams():
            ev.append({"uid": f"exam-{e['id']}", "title": f"Zkouška: {e['name']}", "start": dt.date.fromisoformat(e["date"]),
                       "note": "Témata: " + ", ".join(e["topics"]), "remind_h": 48, "kind": "zkouška"})
    try:
        from .uiplus import list_pins

        for p in list_pins(rt):
            if p["due"] and p["due"] >= now:
                ev.append({"uid": f"pin-{p['id']}", "title": p["text"][:80], "start": dt.datetime.fromtimestamp(p["due"]), "kind": "připnuté"})
    except Exception:  # noqa: BLE001 – pins table not created yet
        pass
    return sorted(ev, key=lambda e: e["start"] if isinstance(e["start"], dt.datetime) else dt.datetime.combine(e["start"], dt.time()))


def content_plan(topics: list[str], start: dt.date, per_week: int = 2, channels: list[str] | None = None) -> list[dict]:
    """OMEGA 446: posts spread over the weeks (Tue / Thu by default, more per week → Mon / Wed / Fri…), channels rotated."""
    days = {1: [1], 2: [1, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4]}[max(1, min(5, per_week))]
    chans = channels or ["Instagram", "Facebook", "Web"]
    out, d, i = [], start, 0
    while i < len(topics):
        if d.weekday() in days:
            out.append({"uid": f"post-{d.isoformat()}-{i}", "title": f"{chans[i % len(chans)]}: {topics[i]}",
                        "start": dt.datetime.combine(d, dt.time(10, 0)), "kind": "příspěvek", "remind_h": 24})
            i += 1
        d += dt.timedelta(days=1)
    return out


def weekly_report(rt, today: dt.date | None = None) -> dict:
    """The past Monday–Sunday: missions done / failed, most used tools, meetings, time in apps, dictation, what is due."""
    from .dictation import week_bounds

    start, end = week_bounds(today)
    t0 = dt.datetime.combine(start, dt.time()).timestamp()
    t1 = dt.datetime.combine(end, dt.time()).timestamp()
    has = lambda t: bool(rt.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))  # noqa: E731
    done = rt.db.all("SELECT goal FROM tasks WHERE status='done' AND finished>=? AND finished<?", (t0, t1))
    failed = rt.db.all("SELECT goal FROM tasks WHERE status IN ('failed','interrupted') AND created>=? AND created<?", (t0, t1))
    tools = rt.db.all("SELECT tool, COUNT(*) AS n FROM task_actions WHERE ts>=? AND ts<? GROUP BY tool ORDER BY n DESC LIMIT 5", (t0, t1))
    meetings = rt.db.all("SELECT title, seconds FROM notes WHERE created>=? AND created<? AND status='done'", (t0, t1)) if has("notes") else []
    apps = (rt.db.all("SELECT app, SUM(seconds) AS s FROM app_usage WHERE day>=? AND day<? GROUP BY app ORDER BY s DESC LIMIT 5",
                      (start.isoformat(), end.isoformat())) if has("app_usage") else [])
    words = (rt.db.one("SELECT SUM(words) AS w FROM dictations WHERE ts>=? AND ts<?", (t0, t1)) or {}).get("w") if has("dictations") else 0
    horizon = (today or dt.date.today()) + dt.timedelta(days=7)
    ahead = [m for m in milestones(rt) if (m["start"].date() if isinstance(m["start"], dt.datetime) else m["start"]) <= horizon]
    return {"from": start.isoformat(), "to": (end - dt.timedelta(days=1)).isoformat(), "done": [d["goal"] for d in done],
            "failed": [f["goal"] for f in failed], "tools": tools, "meetings": meetings,
            "apps": [{"app": a["app"], "hours": round(a["s"] / 3600, 1)} for a in apps], "dictated_words": words or 0,
            "upcoming": [{"title": m["title"], "when": str(m["start"])[:16]} for m in ahead]}


def report_markdown(r: dict) -> str:
    out = [f"# Týdenní report {r['from']} – {r['to']}", ""]
    out += ["## Hotovo", ""] + ([f"- {g}" for g in r["done"]] or ["- (žádná dokončená mise)"]) + [""]
    if r["failed"]:
        out += ["## Nedokončené", ""] + [f"- {g}" for g in r["failed"]] + [""]
    if r["meetings"]:
        out += ["## Schůzky", ""] + [f"- {m['title']} ({round((m['seconds'] or 0) / 60)} min)" for m in r["meetings"]] + [""]
    if r["apps"]:
        out += ["## Čas v aplikacích", ""] + [f"- {a['app']}: {a['hours']} h" for a in r["apps"]] + [""]
    if r["dictated_words"]:
        out += [f"Nadiktováno {r['dictated_words']} slov.", ""]
    if r["upcoming"]:
        out += ["## Příští týden", ""] + [f"- {u['when']}: {u['title']}" for u in r["upcoming"]] + [""]
    return "\n".join(out)


