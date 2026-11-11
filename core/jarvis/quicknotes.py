"""3.12 quick notes in the notch: little sticky notes you type into; kept on this PC (the JARVIS database)."""
from __future__ import annotations

import time

COLORS = ("yellow", "blue", "green", "pink", "violet")
MAX_TEXT = 4000
MAX_NOTES = 60


def _db(rt):
    rt.db.exec("CREATE TABLE IF NOT EXISTS qnotes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, color TEXT, ts REAL, pinned INTEGER DEFAULT 0)")
    return rt.db


def state(rt) -> dict:
    rows = _db(rt).all("SELECT * FROM qnotes ORDER BY pinned DESC, ts DESC LIMIT ?", (MAX_NOTES,))
    return {"items": [{"id": r["id"], "text": r["text"] or "", "color": r["color"] or "yellow", "ts": r["ts"], "pinned": bool(r["pinned"])} for r in rows]}


def save(rt, nid: int | None, text: str | None = None, color: str | None = None, pinned: bool | None = None) -> int:
    """Create (no id) or change a note; returns its id. An empty new note is still created (you start typing into it)."""
    db = _db(rt)
    text = None if text is None else str(text)[:MAX_TEXT]
    color = color if color in COLORS else None
    if not nid:
        cur = db.exec("INSERT INTO qnotes (text, color, ts, pinned) VALUES (?, ?, ?, 0)", (text or "", color or "yellow", time.time()))
        return int(cur.lastrowid)
    if text is not None:
        db.exec("UPDATE qnotes SET text=?, ts=? WHERE id=?", (text, time.time(), int(nid)))
    if color:
        db.exec("UPDATE qnotes SET color=? WHERE id=?", (color, int(nid)))
    if pinned is not None:
        db.exec("UPDATE qnotes SET pinned=? WHERE id=?", (1 if pinned else 0, int(nid)))
    return int(nid)


def delete(rt, nid: int) -> None:
    _db(rt).exec("DELETE FROM qnotes WHERE id=?", (int(nid),))
