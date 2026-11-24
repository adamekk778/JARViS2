"""3.14 Bezpečnost a soukromí (návrhy 107–111).

- an access log: every time JARVIS looked at the screen, used the clipboard, the mouse / keyboard, the camera or the
  microphone – what, when and for which request (Diagnostika → Co JARVIS viděl a slyšel); with the existing
  microphone log
- a suspicious sentence in a web page / e-mail / file ("ignoruj předchozí pokyny…") is shown to you with where it
  came from, not only told to the AI
- guest mode: someone else sits at the PC – no memory about you in the answers, notices show only their title,
  nothing private said aloud (switch it on by voice, chat or tray; off again the same way)
- a new device paired: every other paired phone hears about it with a "Odvolat" button
"""
from __future__ import annotations

import re
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, tool TEXT, what TEXT);
CREATE INDEX IF NOT EXISTS ix_access_ts ON access_log(ts);
"""
KIND_OF = {"screen": "obrazovka", "input": "myš a klávesnice", "camera": "kamera", "clipboard": "schránka", "mic": "mikrofon",
           "injection": "podezřelý text"}
CLIPBOARD_TOOLS = {"clipboard_get", "clipboard_history", "clipboard_set", "clipboard_restore"}
CAMERA_TOOLS = {"ask_phone_photo", "camera_calibrate", "track_object", "motion_analysis"}
KEEP_DAYS = 30


def _db(rt: Any):
    db = rt.db
    if not getattr(db, "_shield_schema", False):
        db.conn.executescript(SCHEMA)
        db._shield_schema = True
    return db


def kind_for(tool: str, perm: str) -> str:
    if tool in CLIPBOARD_TOOLS:
        return "clipboard"
    if tool in CAMERA_TOOLS:
        return "camera"
    if perm in ("screen", "input"):
        return perm
    return ""


def log_access(rt: Any, tool: str, perm: str, args: dict | None = None) -> None:
    kind = kind_for(tool, perm)
    if not kind or getattr(getattr(rt, "memory", None), "private", False):
        return
    what = ""
    for k in ("window", "app", "target", "query", "text", "url"):
        v = (args or {}).get(k)
        if isinstance(v, str) and v:
            what = f"{k}: {v[:60]}"
            break
    try:
        _db(rt).exec("INSERT INTO access_log (ts, kind, tool, what) VALUES (?,?,?,?)", (time.time(), kind, tool, what))
    except Exception:  # noqa: BLE001 – logging must never stop a tool
        pass


def recent(rt: Any, days: int = 1) -> dict:
    since = time.time() - days * 86400
    _db(rt).exec("DELETE FROM access_log WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))
    rows = _db(rt).all("SELECT ts, kind, tool, what FROM access_log WHERE ts >= ? ORDER BY ts DESC LIMIT 200", (since,))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    mic = {}
    ml = getattr(rt, "miclog", None)
    if ml is not None:
        try:
            mic = ml.recent(days)
        except Exception:  # noqa: BLE001
            mic = {}
    return {"rows": [{**r, "label": KIND_OF.get(r["kind"], r["kind"])} for r in rows], "counts": counts, "mic": mic}


# ---------- 108: the suspicious sentence and where it came from ----------
def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?\n])\s+", text or "") if s.strip()]


def suspicious(text: str) -> list[dict]:
    from .injection import _RX

    out = []
    for s in sentences(text)[:2000]:
        for rx, why in _RX:
            if rx.search(s):
                out.append({"why": why, "sentence": s[:220]})
                break
        if len(out) >= 3:
            break
    return out


def source_of(args: dict | None) -> str:
    for k in ("url", "path", "file", "subject", "query", "id", "name"):
        v = (args or {}).get(k)
        if isinstance(v, (str, int)) and str(v):
            return f"{k}: {str(v)[:80]}"
    return ""


def report_injection(rt: Any, tool: str, args: dict | None, text: str) -> list[dict]:
    hits = suspicious(text)
    if not hits:
        return []
    src = source_of(args)
    h = hits[0]
    try:
        rt.notify("Podezřelý text", f"{tool}{' (' + src + ')' if src else ''}: „{h['sentence']}“ – {h['why']}. JARVIS z toho nic "
                  "neprovede.", speak=False)
        _db(rt).exec("INSERT INTO access_log (ts, kind, tool, what) VALUES (?,?,?,?)",
                     (time.time(), "injection", tool, f"{h['why']}: {h['sentence'][:120]}"))
    except Exception:  # noqa: BLE001
        pass
    return hits


# ---------- 109: guest mode ----------
def guest_on(rt: Any) -> bool:
    return bool(getattr(rt.cfg.privacy, "guest_mode", False))


GUEST_RULE = ("Režim host: u počítače teď sedí někdo jiný než majitel. Nic osobního o majiteli neříkej ani neprozrazuj "
              "(paměť, e-maily, zprávy, kalendář, soubory, historie). Na takové dotazy řekni, že v režimu host to nejde.")
GUEST_BLOCKED = {"email_inbox", "email_read", "email_search", "phone_messages", "search_memory", "memory_overview",
                 "memory_timeline", "calendar_list", "clipboard_history", "recent_files", "screen_time", "fio_account",
                 "google_gmail_read", "google_gmail_search", "outlook_mail_read", "outlook_mail_search", "notes_get"}


# ---------- 111: a new device ----------
def announce_device(rt: Any, name: str, new_id: str) -> None:
    try:
        rt.phone_push("notify", title="Nové zařízení u JARVISe", body=f"„{name}“ se právě spárovalo s tvým PC. Pokud jsi to "
                      "nebyl ty, ťukni na Odvolat.", actions=[{"label": "Odvolat", "action": "device_revoke", "args": {"id": new_id}}])
        rt.notify("Nové zařízení", f"„{name}“ se spárovalo s JARVISem.", speak=False)
    except Exception:  # noqa: BLE001
        pass
