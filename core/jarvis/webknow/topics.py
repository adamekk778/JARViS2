"""Spec 2026-11-20 §5.10 / §5.11: your topics. Own ones ("Co mě zajímá", or "hlídej mi GTA 6") and ones JARVIS guessed
(studied, never announced; a removed guess never comes back). A watched topic gets ONE notice per study round with
everything new about it, at most 6 a day – the notice goes through rt.notify, which already keeps it quiet in a game,
in focus, in a meeting and at night, and sends it to the phone when you are away."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Literal

from ..knowledge import norm

MAX_WATCHED = 10
PER_DAY = 6
SCHEMA = """
CREATE TABLE IF NOT EXISTS web_topics (name TEXT PRIMARY KEY, label TEXT, kind TEXT, watch INTEGER DEFAULT 0, created REAL,
  last_seen REAL, notes_ts REAL DEFAULT 0, dismissed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS web_watch_seen (topic TEXT, hash TEXT, ts REAL, PRIMARY KEY (topic, hash));
"""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", norm(text or ""))


def _tstem(w: str) -> str:
    return w[:max(4, len(w) - 2)] if len(w) >= 5 else w


def matches(topic: str, text: str) -> bool:
    """Every word of the topic is in the text – any Czech ending ("umělá inteligence" ~ "umělou inteligenci"); short
    words and numbers exactly ("GTA 6" is not "GTA 5")."""
    want = _words(topic)
    have = _words(text)
    if not want:
        return False
    for w in want:
        if len(w) < 3:
            if w not in have:
                return False
        elif not any(h.startswith(_tstem(w)) for h in have):
            return False
    return True


class Topics:
    def __init__(self, rt):
        self.rt = rt
        self.db = rt.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)

    def _row(self, name: str) -> dict | None:
        return self.db.one("SELECT * FROM web_topics WHERE name=?", (norm(name),))

    def add(self, name: str, kind: Literal["own", "auto"] = "own", watch: bool = False) -> dict:
        n, label = norm(name), re.sub(r"\s+", " ", (name or "").strip())[:60]
        if not n:
            raise ValueError("Téma potřebuje název.")
        old = self._row(name)
        now = time.time()
        if old is None:
            self.db.exec("INSERT INTO web_topics (name, label, kind, watch, created, last_seen) VALUES (?,?,?,?,?,?)",
                         (n, label, kind, int(watch), now, now))
        elif kind == "own":
            self.db.exec("UPDATE web_topics SET kind='own', dismissed=0, watch=MAX(watch, ?) WHERE name=?", (int(watch), n))
        return self._row(name) or {}

    def watch(self, name: str) -> dict:
        old = self._row(name)
        if not (old and old["watch"]) and len(self.watched()) >= MAX_WATCHED:
            raise ValueError("Hlídat jde nejvýš 10 témat.")
        return self.add(name, "own", watch=True)

    def unwatch(self, name: str) -> None:
        self.db.exec("UPDATE web_topics SET watch=0 WHERE name=?", (norm(name),))

    def remove(self, name: str) -> None:
        row = self._row(name)
        if row is None:
            return
        if row["kind"] == "auto":
            self.db.exec("UPDATE web_topics SET dismissed=1, watch=0 WHERE name=?", (row["name"],))
            return
        self.db.exec("DELETE FROM web_topics WHERE name=?", (row["name"],))
        notes = self.rt.webknow.notes(row["label"])
        if notes:
            self.rt.webknow._delete([notes["id"]])

    def star(self, name: str) -> None:
        self.db.exec("UPDATE web_topics SET kind='own', dismissed=0 WHERE name=?", (norm(name),))

    def seen(self, name: str, now: float | None = None) -> None:
        self.db.exec("UPDATE web_topics SET last_seen=? WHERE name=?", (now or time.time(), norm(name)))

    def list(self) -> list[dict]:
        return self.db.all("SELECT * FROM web_topics WHERE dismissed=0 ORDER BY kind DESC, label")

    def active(self) -> list[dict]:
        return self.list()

    def watched(self) -> list[dict]:
        return self.db.all("SELECT * FROM web_topics WHERE watch=1 AND dismissed=0 ORDER BY label")


def _day_count(rt, topic: str, today: str) -> int:
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (f"webknow_watch_day:{topic}",))
    day, _, n = (row["v"] if row else "").partition(":")
    return int(n or 0) if day == today else 0


async def check_watches(rt, new_ids: list[int], now: float | None = None) -> int:
    """One notice per watched topic with everything new about it (at most 3 headlines), at most 6 a day."""
    topics = getattr(rt, "topics", None)
    if topics is None or not new_ids:
        return 0
    now = now or time.time()
    today = dt.date.fromtimestamp(now).isoformat()
    docs = [d for d in (rt.webknow.get(i) for i in new_ids) if d and d["kind"] == "news"]
    sent = 0
    for t in topics.watched():
        hits, seen = [], set()
        for d in docs:
            if d["hash"] in seen or not matches(t["label"], f"{d['title']} {d['snippet']}"):
                continue
            if rt.db.one("SELECT 1 FROM web_watch_seen WHERE topic=? AND hash=?", (t["name"], d["hash"])):
                continue
            seen.add(d["hash"])
            hits.append(d)
        if not hits:
            continue
        for d in hits:
            rt.db.exec("INSERT OR IGNORE INTO web_watch_seen VALUES (?,?,?)", (t["name"], d["hash"], now))
        topics.seen(t["label"], now)
        n = _day_count(rt, t["name"], today)
        if n >= PER_DAY:
            continue                              # kept; said when asked ("co nového o GTA 6?")
        rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (f"webknow_watch_day:{t['name']}", f"{today}:{n + 1}"))
        titles = [d["title"] for d in hits[:3]]
        rt.notify(f"Novinka: {t['label']}", " · ".join(titles), url=hits[0]["url"], speak=False,
                  actions=[{"label": "Řekni víc", "action": "web_more", "args": {"title": titles[0][:200]}}])
        sent += 1
    return sent
