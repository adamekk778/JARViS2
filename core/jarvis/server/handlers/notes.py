"""Dictation history and the meeting notetaker (moved out of server/ws.py)."""
from __future__ import annotations

from . import handles


@handles("dictation_get")
async def dictation_get(c, m: dict) -> None:
    rt = c.rt
    await c.send("dictation_data", stats=rt.dictation.stats(str(m.get("period", "month"))),
                 history=rt.dictation.history(str(m.get("q", "")), int(m.get("limit", 200))) if c.local else [],
                 state=rt.dictation.state)


@handles("dictation_delete")
async def dictation_delete(c, m: dict) -> None:
    rt = c.rt
    rt.dictation.delete(int(m.get("id", 0)))
    await c.send("dictation_data", stats=rt.dictation.stats("month"), history=rt.dictation.history(), state=rt.dictation.state)


@handles("dictation_clear")
async def dictation_clear(c, m: dict) -> None:
    rt = c.rt
    rt.dictation.clear()
    await c.send("dictation_data", stats=rt.dictation.stats("month"), history=[], state=rt.dictation.state)


async def _notes(c) -> None:
    nt = c.rt.notetaker
    await c.send("notes", items=nt.list(), state=nt.state, current=nt.current)


@handles("notes_get")
async def notes_get(c, m: dict) -> None:
    await _notes(c)


@handles("note_get")
async def note_get(c, m: dict) -> None:
    await c.send("note", note=c.rt.notetaker.get(str(m.get("id", ""))))


@handles("note_delete")
async def note_delete(c, m: dict) -> None:
    c.rt.notetaker.delete(str(m.get("id", "")))
    await _notes(c)


@handles("note_start", "note_stop", "note_cancel")
async def note_control(c, m: dict) -> None:
    t = m["type"]
    nt = c.rt.notetaker
    res = nt.start() if t == "note_start" else nt.stop(cancel=t == "note_cancel")
    if not res.get("ok"):
        await c.send("error", message=res.get("message", ""))
    await _notes(c)
