"""3.14 Myslí dopředu (návrhy 58–66) – what JARVIS brings up by itself, and how it learns not to be a nuisance.

- every proactive notice has a kind ("evening", "leave", "repeat", "memory", …); the notch reports whether you used
  it or let it pass; a kind you keep ignoring (5× in two weeks, never used) goes quiet, and JARVIS says so once
- at most `stark.proactive_daily_max` proactive notices a day (asked-for things – timers, reminders – never count)
- the evening review (návrh 58): what got done today, what is left, tomorrow's calendar, meetings tomorrow without
  anything prepared (návrh 59), on Sunday also the week at the PC (návrh 63)
- leaving home with the phone (návrh 60): the weather, the next event, an umbrella when it rains, the next
  departures from your stop (Prague, with a Golemio key) – to the phone
- "připomeň mi, až…" (návrh 61): when I sit down at the PC, when Petr calls, when I open Excel, when I come home –
  a one-shot automation that removes itself after it fires
- the same steps a third time (návrh 62): "Tohle děláš potřetí – mám z toho udělat dovednost?"
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_stats (kind TEXT, day TEXT, shown INT DEFAULT 0, used INT DEFAULT 0, ignored INT DEFAULT 0,
  PRIMARY KEY (kind, day));
"""
AUTO_MUTE_IGNORED = 5
AUTO_MUTE_DAYS = 14
KIND_LABEL = {"evening": "večerní přehled", "leave": "brífink při odchodu", "repeat": "návrhy dovedností",
              "memory": "úklid paměti", "insight": "tipy a postřehy", "prep": "příprava na schůzky"}


def _db(rt: Any):
    db = rt.db
    if not getattr(db, "_proactive_schema", False):
        db.conn.executescript(SCHEMA)
        db._proactive_schema = True
    return db


def _today() -> str:
    return dt.date.today().isoformat()


def _bump(rt: Any, kind: str, col: str) -> None:
    _db(rt).exec(f"INSERT INTO notice_stats (kind, day, {col}) VALUES (?, ?, 1) ON CONFLICT(kind, day) DO UPDATE SET "
                 f"{col} = {col} + 1", (kind, _today()))


def muted(rt: Any) -> set[str]:
    return set(getattr(rt.cfg.stark, "muted_kinds", []) or [])


def allow(rt: Any, kind: str) -> bool:
    """May a proactive notice of this kind be shown now (not muted, under the daily cap)?"""
    if kind in muted(rt):
        return False
    cap = int(getattr(rt.cfg.stark, "proactive_daily_max", 8) or 0)
    if cap:
        row = _db(rt).one("SELECT SUM(shown) n FROM notice_stats WHERE day=?", (_today(),))
        if int((row or {}).get("n") or 0) >= cap:
            return False
    return True


def shown(rt: Any, kind: str) -> None:
    _bump(rt, kind, "shown")


def feedback(rt: Any, kind: str, action: str) -> str:
    """"used" (a button / opened) or "ignored" (it went away by itself). Returns the kind when it got muted now."""
    if not kind:
        return ""
    _bump(rt, kind, "used" if action == "used" else "ignored")
    since = (dt.date.today() - dt.timedelta(days=AUTO_MUTE_DAYS)).isoformat()
    row = _db(rt).one("SELECT SUM(used) u, SUM(ignored) i FROM notice_stats WHERE kind=? AND day>=?", (kind, since)) or {}
    if int(row.get("i") or 0) >= AUTO_MUTE_IGNORED and int(row.get("u") or 0) == 0 and kind not in muted(rt):
        rt.update_config({"stark": {"muted_kinds": sorted(muted(rt) | {kind})}})
        rt.notify("Už tě s tím nebudu rušit", f"Poslední dva týdny jsi {KIND_LABEL.get(kind, kind)} nechal bez povšimnutí – "
                  "vypnul jsem je. Zapneš je v Nastavení → Obecné.", speak=False)
        return kind
    return ""


def stats(rt: Any, days: int = 14) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = _db(rt).all("SELECT kind, SUM(shown) s, SUM(used) u, SUM(ignored) i FROM notice_stats WHERE day>=? GROUP BY kind", (since,))
    return [{"kind": r["kind"], "label": KIND_LABEL.get(r["kind"], r["kind"]), "shown": int(r["s"] or 0), "used": int(r["u"] or 0),
             "ignored": int(r["i"] or 0), "muted": r["kind"] in muted(rt)} for r in rows]


# ---------- 58 / 59 / 63: the evening review ----------
async def tomorrow_events(rt: Any) -> list[dict]:
    cal = getattr(rt, "calendar", None)
    if cal is None:
        return []
    try:
        evs = await cal.day(dt.date.today() + dt.timedelta(days=1))
    except Exception as e:  # noqa: BLE001
        log.debug("tomorrow: %s", e)
        evs = []
    out = []
    for ev in evs:
        if isinstance(ev, dict):
            t = ev.get("start")
            out.append({**ev, "time": dt.datetime.fromtimestamp(t).strftime("%H:%M") if isinstance(t, (int, float)) else ""})
    return out


def _prepared(rt: Any, title: str) -> bool:
    """Something about this meeting already exists (a note, a fact, a file name with its words)."""
    words = [w for w in title.lower().split() if len(w) > 3][:3]
    if not words:
        return True
    try:
        hits = rt.knowledge.search(" ".join(words), limit=5)
        return bool(hits)
    except Exception:  # noqa: BLE001
        return True


def evening_review(rt: Any, today: dt.date | None = None, tomorrow: list[dict] | None = None) -> dict:
    from . import proactive

    today = today or dt.date.today()
    day = proactive.day_summary(rt, today)
    left = proactive.forgotten(rt, days=3)[:4]
    tomorrow = tomorrow or []
    unprepared = [e for e in tomorrow if e.get("title") and not _prepared(rt, str(e["title"]))][:3]
    lines = []
    done = day.get("done") or day.get("tasks_done") or []
    if done:
        lines.append(f"Dnes hotovo: {', '.join(str(d)[:60] for d in done[:4])}.")
    if left:
        lines.append("Zbývá: " + "; ".join(x["text"] for x in left[:3]) + ".")
    if tomorrow:
        lines.append("Zítra: " + ", ".join(f"{e.get('time', '')} {e.get('title', '')}".strip() for e in tomorrow[:4]) + ".")
    if unprepared:
        lines.append("Na schůzku " + ", ".join(f"„{e['title']}“" for e in unprepared) + " nemáš nic připravené – mám udělat podklady?")
    week = None
    if today.weekday() == 6:
        try:
            week = rt.attention.week() if getattr(rt, "attention", None) else None
        except Exception:  # noqa: BLE001
            week = None
        if week and week.get("top"):
            lines.append("Tento týden u PC nejvíc: " + ", ".join(f"{a['app']} {round(a['minutes'] / 60, 1)} h" for a in week["top"][:3]) + ".")
    return {"lines": lines, "unprepared": unprepared, "tomorrow": tomorrow, "left": left, "week": week}


def due_today(rt: Any, key: str, at: str, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    try:
        h, m = (int(x) for x in str(at).split(":")[:2])
    except ValueError:
        h, m = 21, 0
    if (now.hour, now.minute) < (h, m):
        return False
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
    return not row or row["v"] != now.date().isoformat()


def notify_kind(rt: Any, kind: str, title: str, body: str, actions: list[dict] | None = None, speak: bool = False,
                target: str = "all") -> bool:
    if not allow(rt, kind):
        return False
    shown(rt, kind)
    rt.notify(title, body, speak=speak, target=target, actions=actions, kind=kind)
    return True


async def evening_loop(rt: Any) -> None:
    import asyncio

    await asyncio.sleep(120)
    while True:
        try:
            st = rt.cfg.stark
            if getattr(st, "evening_review", True) and due_today(rt, "evening_review_at", getattr(st, "evening_time", "21:00")):
                idle = float(rt.platform.idle_seconds()) if hasattr(rt.platform, "idle_seconds") else 0
                if idle < 600:                                    # only when you are at the PC
                    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('evening_review_at', ?)", (dt.date.today().isoformat(),))
                    rev = evening_review(rt, tomorrow=await tomorrow_events(rt))
                    if rev["lines"]:
                        acts = [{"label": "Připravit podklady", "action": "ask",
                                 "args": {"text": f"připrav mě na schůzku {rev['unprepared'][0]['title']}"}}] if rev["unprepared"] else []
                        notify_kind(rt, "evening", "Večerní přehled", " ".join(rev["lines"]), actions=acts)
        except Exception as e:  # noqa: BLE001
            log.info("evening review: %s", e)
        await asyncio.sleep(300)


# ---------- 60: leaving home ----------
HOME_WORDS = ("domov", "doma", "home", "byt", "dum", "dům")


async def leave_briefing(rt: Any) -> list[str]:
    lines: list[str] = []
    try:
        from .tools import REGISTRY

        w = await REGISTRY["weather"].func(rt) if "weather" in REGISTRY else None
        if w is not None and getattr(w, "ok", False):
            lines.append(w.summary[:160])
            if any(x in w.summary.lower() for x in ("déšť", "dest", "přeháň", "prš", "bouř")):
                lines.append("Vezmi si deštník.")
    except Exception as e:  # noqa: BLE001
        log.debug("leave weather: %s", e)
    try:
        nxt: list[dict] = []
        cal = getattr(rt, "calendar", None)
        if cal is not None:
            now = dt.datetime.now()
            nxt = [ev for ev in await cal.events(now, now + dt.timedelta(hours=12)) if isinstance(ev, dict)]
        if nxt:
            first = nxt[0]
            at = dt.datetime.fromtimestamp(first["start"]).strftime("%H:%M") if isinstance(first.get("start"), (int, float)) else ""
            lines.append(f"Další: {at} {first.get('title', '')}".strip())
    except Exception as e:  # noqa: BLE001
        log.debug("leave calendar: %s", e)
    stop = getattr(rt.cfg.stark, "home_stop", "") or ""
    if stop:
        try:
            from . import bridges, secrets

            key = secrets.get("golemio")
            deps = await bridges.pid_departures(key, stop, limit=3) if key else []
            if deps:
                lines.append("Odjezdy: " + ", ".join(f"{d.get('line', '')} {d.get('time', '')}" for d in deps[:3]))
        except Exception as e:  # noqa: BLE001
            log.debug("leave departures: %s", e)
    return lines


async def on_event(rt: Any, ev: dict) -> None:
    """Called for each automation event (phone zones)."""
    if ev.get("type") == "phone_zone" and ev.get("event") == "leave" and getattr(rt.cfg.stark, "leave_briefing", True):
        zone = str(ev.get("zone", "")).lower()
        if any(w in zone for w in HOME_WORDS):
            lines = await leave_briefing(rt)
            if lines:
                notify_kind(rt, "leave", "Na cestu", " ".join(lines), target="mobile")


# ---------- 61: "připomeň mi, až…" ----------
WHEN_LABEL = {"pc": "až si sedneš k PC", "home": "až přijdeš domů", "away_home": "až odejdeš z domu", "call": "až zavolá",
              "message": "až napíše", "app": "až otevřeš", "mail": "až přijde e-mail od"}
WHEN = {"pc": ("back", "5"), "home": ("zone_enter", "Domov"), "away_home": ("zone_leave", "Domov"),
        "call": ("phone_call", ""), "message": ("phone_message", ""), "app": ("app_open", ""), "mail": ("mail", "")}


def remind_on(rt: Any, when: str, text: str, who: str = "") -> dict:
    from .config import Automation, AutoTrigger, ProtocolStep

    if when not in WHEN:
        raise ValueError(f"neznám chvíli „{when}“ (umím: {', '.join(WHEN)})")
    typ: Any
    typ, default = WHEN[when]
    a = Automation(id=uuid.uuid4().hex[:10], name=f"Připomínka: {text[:40]}", trigger=AutoTrigger(type=typ, value=who or default),
                   steps=[ProtocolStep(say=f"Připomínám: {text}")], once=True)
    items = [x.model_dump() for x in rt.cfg.automations.items] + [a.model_dump()]
    rt.update_config({"automations": {"items": items}})
    return {"id": a.id, "trigger": typ, "value": a.trigger.value}


# ---------- 62: the same steps a third time ----------
def signature(rt: Any, task_id: str) -> tuple[str, ...]:
    rows = rt.db.all("SELECT tool FROM task_actions WHERE task_id=? ORDER BY id", (task_id,))
    seq = [r["tool"] for r in rows if r["tool"] not in ("update_plan", "find_tools")]
    out: list[str] = []
    for t in seq:                                     # repeated calls of one tool count once (paging, retries)
        if not out or out[-1] != t:
            out.append(t)
    return tuple(out)


def repeated(rt: Any, task_id: str, days: int = 30, times: int = 3) -> int:
    sig = signature(rt, task_id)
    if len(sig) < 2:
        return 0
    since = time.time() - days * 86400
    n = 0
    for t in rt.db.all("SELECT id FROM tasks WHERE created>=? AND status='done'", (since,)):
        if signature(rt, t["id"]) == sig:
            n += 1
    return n if n >= times else 0


def after_mission(rt: Any, task_id: str) -> bool:
    n = repeated(rt, task_id)
    if not n:
        return False
    key = "repeat_offer:" + json.dumps(signature(rt, task_id))
    if rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
        return False                                   # offered once already
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(time.time())))
    return notify_kind(rt, "repeat", "Tohle děláš potřetí", f"Stejný postup jsi udělal už {n}×. Mám z něj udělat dovednost, "
                       "kterou spustíš jedním slovem?",
                       actions=[{"label": "Udělat dovednost", "action": "ask", "args": {"text": "ulož poslední misi jako dovednost"}}])
