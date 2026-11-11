"""3.12 Schránka and Snímky in the notch.

Schránka: what you copy (Ctrl+C) shows up in the notch. Like before it stays in memory only and passwords / keys are
never kept (powers.looks_secret); only what you pin or put into a folder is written to disk – you decide that.
Snímky: the newest screenshots and screen clips from the folders Windows saves them to (Win+Shift+S, PrintScreen,
Xbox Game Bar), with pins and your own folders. Nothing is deleted; "Skrýt" only hides one from the list.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote

IMG = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
VID = (".mp4", ".webm", ".mkv")
MAX_SHOTS = 60
MAX_TEXT = 20000


def _db(rt):
    db = rt.db
    db.exec("CREATE TABLE IF NOT EXISTS clip_saved (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, ts REAL, app TEXT, "
            "pinned INTEGER DEFAULT 0, folder TEXT DEFAULT '')")
    db.exec("CREATE TABLE IF NOT EXISTS shot_meta (path TEXT PRIMARY KEY, pinned INTEGER DEFAULT 0, folder TEXT DEFAULT '', hidden INTEGER DEFAULT 0)")
    db.exec("CREATE TABLE IF NOT EXISTS shelf_folders (kind TEXT, name TEXT, PRIMARY KEY (kind, name))")
    return db


def _clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:40]


def folders(rt, kind: str) -> list[str]:
    return [r["name"] for r in _db(rt).all("SELECT name FROM shelf_folders WHERE kind=? ORDER BY name COLLATE NOCASE", (kind,))]


def _memory(rt) -> list[dict]:
    return list(getattr(getattr(rt, "activity", None), "clips", []) or [])


# ---------------------------------------------------------------- Schránka
def clips_state(rt) -> dict:
    db = _db(rt)
    saved = [{"id": f"s{r['id']}", "text": r["text"], "ts": r["ts"], "app": r["app"] or "", "pinned": bool(r["pinned"]),
              "folder": r["folder"] or "", "saved": True} for r in db.all("SELECT * FROM clip_saved ORDER BY ts DESC")]
    kept = {s["text"] for s in saved}
    recent = [{"id": f"m{int(c['ts'] * 1000)}", "text": c["text"], "ts": c["ts"], "app": c.get("app", ""), "pinned": False,
               "folder": "", "saved": False} for c in _memory(rt) if c["text"] not in kept]
    items = sorted(saved + recent, key=lambda x: (not x["pinned"], -x["ts"]))
    return {"items": [{**it, "text": it["text"][:MAX_TEXT]} for it in items], "folders": folders(rt, "clip"),
            "enabled": bool(getattr(rt.cfg.powers, "clipboard_history", True))}


def _find_memory(rt, cid: str) -> dict | None:
    for c in _memory(rt):
        if f"m{int(c['ts'] * 1000)}" == cid:
            return c
    return None


def clip_action(rt, action: str, cid: str = "", folder: str = "", name: str = "") -> dict:
    db = _db(rt)
    folder, name = _clean_name(folder), _clean_name(name)
    if action == "folder_add" and name:
        db.exec("INSERT OR IGNORE INTO shelf_folders (kind, name) VALUES ('clip', ?)", (name,))
    elif action == "folder_delete" and name:
        db.exec("DELETE FROM shelf_folders WHERE kind='clip' AND name=?", (name,))
        db.exec("UPDATE clip_saved SET folder='' WHERE folder=?", (name,))
        db.exec("DELETE FROM clip_saved WHERE pinned=0 AND folder=''")
    elif action == "clear":                       # forget what is only in memory; pinned and filed ones stay
        act = getattr(rt, "activity", None)
        if act is not None:
            act.clips.clear()
    elif cid.startswith("m"):
        c = _find_memory(rt, cid)
        if c is None:
            return {"ok": False, "error": "Položka už ve schránce není"}
        if action in ("pin", "move"):
            if action == "move" and folder:
                db.exec("INSERT OR IGNORE INTO shelf_folders (kind, name) VALUES ('clip', ?)", (folder,))
            db.exec("INSERT INTO clip_saved (text, ts, app, pinned, folder) VALUES (?,?,?,?,?)",
                    (c["text"][:MAX_TEXT], c["ts"], c.get("app", ""), 1 if action == "pin" else 0, folder if action == "move" else ""))
        elif action == "delete":
            act = getattr(rt, "activity", None)
            if act is not None:
                try:
                    act.clips.remove(c)
                except ValueError:
                    pass
        elif action == "copy":
            rt.platform.clipboard_set(c["text"])
    elif cid.startswith("s") and cid[1:].isdigit():
        sid = int(cid[1:])
        row = db.one("SELECT * FROM clip_saved WHERE id=?", (sid,))
        if not row:
            return {"ok": False, "error": "Položka nenalezena"}
        if action == "pin":
            db.exec("UPDATE clip_saved SET pinned=1 WHERE id=?", (sid,))
        elif action == "unpin":
            db.exec("UPDATE clip_saved SET pinned=0 WHERE id=?", (sid,))
        elif action == "move":
            if folder:
                db.exec("INSERT OR IGNORE INTO shelf_folders (kind, name) VALUES ('clip', ?)", (folder,))
            db.exec("UPDATE clip_saved SET folder=? WHERE id=?", (folder, sid))
        elif action == "delete":
            db.exec("DELETE FROM clip_saved WHERE id=?", (sid,))
        elif action == "copy":
            rt.platform.clipboard_set(row["text"])
        db.exec("DELETE FROM clip_saved WHERE pinned=0 AND folder=''")   # neither pinned nor filed: back to memory only
    else:
        return {"ok": False, "error": "Neznámá položka"}
    return {"ok": True}


# ---------------------------------------------------------------- Snímky
def shot_folders(home: Path | None = None) -> list[Path]:
    from .sysplus import screenshot_folders

    return screenshot_folders(home)


def _is_shot(p: Path, folder: Path) -> bool:
    from .sysplus import SHOT

    if p.suffix.lower() not in IMG + VID:
        return False
    import re

    dedicated = bool(re.search(r"(?i)screenshot|snímky obrazovky|captures|recording", folder.name))
    return dedicated or bool(SHOT.search(p.name))


def list_shots(rt, home: Path | None = None) -> list[Path]:
    found: list[tuple[float, Path]] = []
    for d in shot_folders(home):
        try:
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.is_file() and _is_shot(p, d):
                    found.append((p.stat().st_mtime, p))
        except OSError:
            continue
    found.sort(key=lambda x: -x[0])
    return [p for _, p in found[:400]]


def shots_state(rt, home: Path | None = None) -> dict:
    db = _db(rt)
    meta = {r["path"]: r for r in db.all("SELECT * FROM shot_meta")}
    items = []
    for p in list_shots(rt, home):
        m = meta.get(str(p))
        if m and m["hidden"]:
            continue
        st = p.stat()
        items.append({"path": str(p), "name": p.name, "ts": st.st_mtime, "bytes": st.st_size,
                      "video": p.suffix.lower() in VID, "url": f"/api/shot?path={quote(str(p))}&v={int(st.st_mtime)}",
                      "pinned": bool(m and m["pinned"]), "folder": (m and m["folder"]) or ""})
    keep = [i for i in items if i["pinned"] or i["folder"]]
    rest = [i for i in items if not (i["pinned"] or i["folder"])][:MAX_SHOTS]
    out = sorted(keep + rest, key=lambda x: (not x["pinned"], -x["ts"]))
    return {"items": out, "folders": folders(rt, "shot")}


def allowed_shot(rt, path: str, home: Path | None = None) -> Path | None:
    """Only a screenshot from one of the screenshot folders may be served (never any other file on the PC)."""
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return None
    for d in shot_folders(home):
        try:
            if p.parent == d.resolve() and p.is_file() and _is_shot(p, d):
                return p
        except OSError:
            continue
    return None


def shot_action(rt, action: str, path: str = "", folder: str = "", name: str = "", home: Path | None = None) -> dict:
    db = _db(rt)
    folder, name = _clean_name(folder), _clean_name(name)
    if action == "folder_add" and name:
        db.exec("INSERT OR IGNORE INTO shelf_folders (kind, name) VALUES ('shot', ?)", (name,))
        return {"ok": True}
    if action == "folder_delete" and name:
        db.exec("DELETE FROM shelf_folders WHERE kind='shot' AND name=?", (name,))
        db.exec("UPDATE shot_meta SET folder='' WHERE folder=?", (name,))
        return {"ok": True}
    p = allowed_shot(rt, path, home)
    if p is None:
        return {"ok": False, "error": "Snímek nenalezen"}
    key = str(p)
    db.exec("INSERT OR IGNORE INTO shot_meta (path) VALUES (?)", (key,))
    if action == "pin":
        db.exec("UPDATE shot_meta SET pinned=1 WHERE path=?", (key,))
    elif action == "unpin":
        db.exec("UPDATE shot_meta SET pinned=0 WHERE path=?", (key,))
    elif action == "move":
        if folder:
            db.exec("INSERT OR IGNORE INTO shelf_folders (kind, name) VALUES ('shot', ?)", (folder,))
        db.exec("UPDATE shot_meta SET folder=? WHERE path=?", (folder, key))
    elif action == "hide":
        db.exec("UPDATE shot_meta SET hidden=1, pinned=0 WHERE path=?", (key,))
    elif action == "open":
        rt.platform.open_path(key)
    elif action == "reveal":
        rt.platform.open_path(str(p.parent))
    else:
        return {"ok": False, "error": "Neznámá akce"}
    return {"ok": True}


def changed(rt) -> None:
    """Called from the clipboard watcher (a worker thread): the notch gets the fresh list."""
    def push():
        try:
            rt.bus.publish("clips", **clips_state(rt))
        except Exception:  # noqa: BLE001 – a list update must never break the watcher
            pass
    rt.call_soon(push)


_last_shots: dict[int, float] = {}


def watch_shots(rt, now: float | None = None) -> None:
    """Every few seconds from the watcher: a new screenshot → the notch's Snímky list updates."""
    now = time.time() if now is None else now
    try:
        newest = max((p.stat().st_mtime for p in list_shots(rt)[:1]), default=0.0)
    except OSError:
        return
    key = id(rt)
    if _last_shots.get(key) is None:
        _last_shots[key] = newest
        return
    if newest > _last_shots[key]:
        _last_shots[key] = newest
        def push():
            try:
                rt.bus.publish("shots", **shots_state(rt))
            except Exception:  # noqa: BLE001
                pass
        rt.call_soon(push)
