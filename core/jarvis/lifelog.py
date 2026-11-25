"""3.14 Paměť života (návrh 53): an optional, encrypted, local-only diary of your days at the PC.

Only after you switch it on (Nastavení → Soukromí → Paměť života). Every few minutes it notes which app and window you
work in (password managers, banking and private windows are never written), merges it into spans, and keeps your own
notes ("zapiš do deníku…"). Everything is encrypted (AES-GCM) with a key kept in the Windows credential vault and never
leaves this PC by itself; after the days you choose (90 by default) it is deleted. "Co jsem dělal minulé úterý?" puts
the day together from it – with the calendar, trips and calls of that day.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import os
import re
import time
from typing import Any

from . import secrets

log = logging.getLogger("jarvis.lifelog")

KEY_NAME = "lifelog_key"
EVERY_S = 120
AWAY_S = 5 * 60
SPAN_MAX_S = 30 * 60
DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
DAY_STEMS = ["pondel", "uter", "stred", "ctvrt", "patek", "sobot", "nedel"]


def _db(rt: Any) -> Any:
    rt.db.exec("CREATE TABLE IF NOT EXISTS life (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, t REAL, kind TEXT, data BLOB)")
    rt.db.exec("CREATE INDEX IF NOT EXISTS ix_life_day ON life(day)")
    return rt.db


def on(rt: Any) -> bool:
    return bool(getattr(rt.cfg.privacy, "life_log", False)) and not getattr(rt.memory, "private", False)


def _key(create: bool = True) -> bytes | None:
    k = secrets.get(KEY_NAME)
    if k:
        return base64.b64decode(k)
    if not create:
        return None
    raw = os.urandom(32)
    secrets.set(KEY_NAME, base64.b64encode(raw).decode())
    return raw


def seal(obj: dict, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, json.dumps(obj, ensure_ascii=False).encode(), b"jarvis-life")


def unseal(blob: bytes, key: bytes) -> dict | None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        return json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], b"jarvis-life"))
    except Exception:  # noqa: BLE001 – another key (wiped) or damaged: skip it
        return None


def add(rt: Any, kind: str, obj: dict, t: float | None = None) -> None:
    key = _key()
    assert key is not None
    t = time.time() if t is None else t
    _db(rt).exec("INSERT INTO life (day, t, kind, data) VALUES (?,?,?,?)",
                 (dt.date.fromtimestamp(t).isoformat(), t, kind, seal(obj, key)))


def entries(rt: Any, day: dt.date) -> list[dict]:
    key = _key(create=False)
    if key is None:
        return []
    out = []
    for r in _db(rt).all("SELECT t, kind, data FROM life WHERE day=? ORDER BY t", (day.isoformat(),)):
        obj = unseal(bytes(r["data"]), key)
        if obj is not None:
            out.append({"t": r["t"], "kind": r["kind"], **obj})
    return out


def wipe(rt: Any) -> int:
    n = (_db(rt).one("SELECT COUNT(*) AS n FROM life") or {"n": 0})["n"]
    _db(rt).exec("DELETE FROM life")
    secrets.set(KEY_NAME, "")                       # a new key next time: old copies (backups) cannot be read
    return int(n)


def prune(rt: Any, today: dt.date | None = None) -> None:
    keep = int(getattr(rt.cfg.privacy, "life_log_days", 90) or 90)
    _db(rt).exec("DELETE FROM life WHERE day<?", (((today or dt.date.today()) - dt.timedelta(days=keep)).isoformat(),))


def _sensitive(app: str, title: str, patterns: list[str] | None) -> bool:
    from .vision import SENSITIVE

    pats = [p.lower() for p in (patterns or SENSITIVE) if p.strip()]
    hay = f"{title} {app}".lower()
    return any(re.search(rf"(^|[^a-z0-9]){re.escape(p)}", hay) for p in pats) or "inprivate" in hay or "anonymn" in hay


class Recorder:
    """Every 2 minutes: the app and window in front → spans (merged while they stay the same)."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.span: dict | None = None

    def flush(self) -> None:
        s, self.span = self.span, None
        if s and s["to"] - s["from"] >= 60:
            add(self.rt, "span", s, s["from"])

    def step(self, now: float, fg: dict, idle: float) -> None:
        if not on(self.rt):
            self.span = None
            return
        app, title = str(fg.get("app") or ""), str(fg.get("title") or "")[:120]
        s = self.span
        if s:                                         # what was in front until now (or until you left the PC)
            s["to"] = max(s["from"], now - idle if idle >= AWAY_S else now)
        if idle >= AWAY_S or not app or _sensitive(app, title, getattr(self.rt.cfg.privacy, "mask_patterns", None)):
            self.flush()
            return
        if s and s["app"] == app and s["title"] == title and now - s["from"] < SPAN_MAX_S \
                and dt.date.fromtimestamp(s["from"]) == dt.date.fromtimestamp(now):
            return
        self.flush()
        self.span = {"app": app, "title": title, "from": now, "to": now}

    async def run(self) -> None:
        pruned = ""
        while True:
            await asyncio.sleep(EVERY_S)
            try:
                if on(self.rt):
                    fg = self.rt.platform.foreground_info() or {}
                    if fg.get("pid") == os.getpid():
                        continue                     # JARVIS itself is not your life
                    self.step(time.time(), fg, float(self.rt.platform.idle_seconds()))
                    if pruned != dt.date.today().isoformat():
                        pruned = dt.date.today().isoformat()
                        prune(self.rt)
                elif self.span:
                    self.span = None
            except Exception as e:  # noqa: BLE001
                log.debug("lifelog: %s", e)


def recorder(rt: Any) -> Recorder:
    r = getattr(rt, "_lifelog", None)
    if r is None:
        r = rt._lifelog = Recorder(rt)
    return r


# ---------------------------------------------------------------------------------------------- asking about a day
def parse_day(text: str, today: dt.date | None = None) -> dt.date | None:
    """"dnes", "včera", "předevčírem", "minulé úterý", "v pondělí", "12. 11.", "2026-11-12" → the date."""
    today = today or dt.date.today()
    t = (text or "").strip().lower()
    import unicodedata

    f = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    if not f or f in ("dnes", "dneska", "today"):
        return today
    if f.startswith("vcer") or f == "yesterday":
        return today - dt.timedelta(days=1)
    if f.startswith("predevcir"):
        return today - dt.timedelta(days=2)
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", f)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.?\s*(20\d{2})?", f)
    if m:
        d = dt.date(int(m.group(3) or today.year), int(m.group(2)), int(m.group(1)))
        return d if d <= today else d.replace(year=d.year - 1)
    for i, stem in enumerate(DAY_STEMS):
        if stem in f:
            back = (today.weekday() - i) % 7 or 7          # "(minulé) úterý": the last Tuesday before today
            if "predminul" in f:
                back += 7
            elif re.search(r"minul\w* tyd", f):            # "úterý minulý týden": that day of last week's Mon–Sun
                back = today.weekday() - i + 7
            return today - dt.timedelta(days=back)
    return None


def _hm(sec: float) -> str:
    m = int(round(sec / 60))
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def day_summary(rt: Any, day: dt.date) -> dict:
    """Apps with time and the windows that mattered, your notes – and the calls and trips of that day."""
    items = entries(rt, day)
    by_app: dict[str, dict] = {}
    notes = []
    for e in items:
        if e["kind"] == "span":
            a = by_app.setdefault(e["app"], {"app": e["app"], "seconds": 0.0, "titles": {}})
            secs = max(60.0, e["to"] - e["from"])
            a["seconds"] += secs
            a["titles"][e["title"]] = a["titles"].get(e["title"], 0) + secs
        elif e["kind"] == "note":
            notes.append({"time": dt.datetime.fromtimestamp(e["t"]).strftime("%H:%M"), "text": e.get("text", "")})
    apps = sorted(by_app.values(), key=lambda a: -a["seconds"])
    for a in apps:
        a["titles"] = [t for t, _ in sorted(a["titles"].items(), key=lambda x: -x[1]) if t][:3]
    spans = [e for e in items if e["kind"] == "span"]
    first = dt.datetime.fromtimestamp(spans[0]["from"]).strftime("%H:%M") if spans else ""
    last = dt.datetime.fromtimestamp(spans[-1]["to"]).strftime("%H:%M") if spans else ""
    extra = []
    start, end = dt.datetime.combine(day, dt.time()).timestamp(), dt.datetime.combine(day, dt.time(23, 59, 59)).timestamp()
    try:
        from . import callagent

        extra += [f"hovor {'od' if c['dir'] == 'in' else 'na'} {c['number']}: {c['summary']}" for c in callagent.history(rt, 50)
                  if start <= c["started"] <= end]
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import travel

        extra += [travel.describe(t) for t in travel.upcoming(rt, now=start, days=1) if start <= t["dep"] <= end]
    except Exception:  # noqa: BLE001
        pass
    return {"day": day.isoformat(), "apps": apps, "notes": notes, "first": first, "last": last, "events": extra}


def describe_day(s: dict) -> str:
    d = dt.date.fromisoformat(s["day"])
    head = f"{DAYS[d.weekday()].capitalize()} {d.day}. {d.month}."
    if not s["apps"] and not s["notes"] and not s["events"]:
        return f"{head}: v paměti života na ten den nic nemám."
    parts = []
    if s["first"]:
        parts.append(f"u PC od {s['first']} do {s['last']}")
    for a in s["apps"][:5]:
        t = f" ({', '.join(a['titles'][:2])})" if a["titles"] else ""
        parts.append(f"{a['app']} {_hm(a['seconds'])}{t}")
    text = f"{head}: " + "; ".join(parts) + "."
    if s["notes"]:
        text += " Poznámky: " + "; ".join(f"{n['time']} {n['text']}" for n in s["notes"][:5]) + "."
    if s["events"]:
        text += " Taky: " + "; ".join(s["events"][:4]) + "."
    return text
