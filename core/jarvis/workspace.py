"""OMEGA §21 / §40 desktop: workspace profiles (which programs and where their windows are), restore and compare,
a window to another monitor, reopening programs that crashed, keyboard shortcuts for the app in front, and search
over the commands you gave JARVIS. Restoring only starts programs that were in the profile and moves windows."""
from __future__ import annotations

import difflib
import json
import os
import time
from typing import Any

from .comms import fold

SCHEMA = "CREATE TABLE IF NOT EXISTS workspaces (name TEXT PRIMARY KEY, windows TEXT, created REAL, updated REAL, project TEXT DEFAULT '')"


def _db(rt):
    rt.db.exec(SCHEMA)
    return rt.db


def save(rt, name: str, project: str = "") -> dict:
    wins = [w for w in rt.platform.window_layout() if w.get("path") or w.get("exe")]
    if not wins:
        raise ValueError("Nevidím žádná okna, která by šla uložit.")
    keep = [{k: w.get(k) for k in ("title", "exe", "path", "app", "x", "y", "w", "h", "state")} for w in wins]
    now = time.time()
    _db(rt).exec("INSERT INTO workspaces VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET windows=excluded.windows, updated=excluded.updated, "
                 "project=excluded.project", (name.strip()[:60], json.dumps(keep, ensure_ascii=False), now, now, project))
    return {"name": name, "windows": keep}


def get(rt, name: str) -> dict | None:
    r = _db(rt).one("SELECT * FROM workspaces WHERE lower(name)=lower(?)", (name.strip(),))
    return {**r, "windows": json.loads(r["windows"])} if r else None


def list_all(rt) -> list[dict]:
    return [{**r, "windows": len(json.loads(r["windows"]))} for r in _db(rt).all("SELECT * FROM workspaces ORDER BY updated DESC")]


def delete(rt, name: str) -> bool:
    return _db(rt).exec("DELETE FROM workspaces WHERE lower(name)=lower(?)", (name.strip(),)).rowcount > 0


def _match(saved: dict, live: list[dict], used: set[int]) -> dict | None:
    cands = [w for w in live if w["hwnd"] not in used and fold(w.get("exe") or "") == fold(saved.get("exe") or "")]
    if not cands:
        return None
    return max(cands, key=lambda w: difflib.SequenceMatcher(None, fold(w["title"]), fold(saved.get("title") or "")).ratio())


def compare(rt, name: str) -> dict:
    """OMEGA 518: what is missing, what is extra and what moved, against a saved profile."""
    ws = get(rt, name)
    if not ws:
        raise ValueError(f"Profil „{name}“ neexistuje.")
    live = rt.platform.window_layout()
    used: set[int] = set()
    missing, moved = [], []
    for s in ws["windows"]:
        m = _match(s, live, used)
        if not m:
            missing.append(s)
            continue
        used.add(m["hwnd"])
        if abs(m["x"] - s["x"]) > 20 or abs(m["y"] - s["y"]) > 20 or abs(m["w"] - s["w"]) > 20 or m["state"] != s["state"]:
            moved.append({"app": s.get("app") or s.get("exe"), "title": m["title"]})
    extra = [w for w in live if w["hwnd"] not in used]
    return {"missing": missing, "moved": moved, "extra": [{"app": w.get("app") or w.get("exe"), "title": w["title"]} for w in extra]}


def restore(rt, name: str, launch_wait: float = 8.0, sleep=time.sleep) -> dict:
    """Start what is missing (from the saved program path), then put every window back in place."""
    ws = get(rt, name)
    if not ws:
        raise ValueError(f"Profil „{name}“ neexistuje.")
    live = rt.platform.window_layout()
    started, failed = [], []
    used: set[int] = set()
    for s in ws["windows"]:
        if _match(s, live, used):
            used.add(_match(s, live, used)["hwnd"])
            continue
        path = s.get("path") or ""
        try:
            if path and os.path.isfile(path):
                rt.platform.open_path(path)
            else:
                rt.platform.open_app(s.get("app") or s.get("exe") or "")
            started.append(s.get("app") or s.get("exe"))
        except Exception as e:  # noqa: BLE001 – reported, the rest still restores
            failed.append(f"{s.get('app') or s.get('exe')}: {e}")
    if started:
        deadline = time.monotonic() + launch_wait
        while time.monotonic() < deadline:
            sleep(0.5)
            live = rt.platform.window_layout()
            if all(_match(s, live, set()) for s in ws["windows"]):
                break
    live = rt.platform.window_layout()
    used = set()
    placed = 0
    for s in ws["windows"]:
        m = _match(s, live, used)
        if not m:
            continue
        used.add(m["hwnd"])
        if rt.platform.place_window(m["hwnd"], s["x"], s["y"], s["w"], s["h"], s["state"]):
            placed += 1
    return {"started": started, "placed": placed, "total": len(ws["windows"]), "failed": failed}


def to_monitor(rt, app: str, monitor: int) -> dict:
    """OMEGA 238: move an app's window to monitor N (1 = primary), keeping its size where it fits."""
    from .desktop import platforms

    mons = platforms.monitors()
    if not 1 <= monitor <= len(mons):
        raise ValueError(f"Monitor {monitor} nemáš (počet monitorů: {len(mons)}).")
    work = mons[monitor - 1][1]
    wx, wy, ww, wh = _rect(work)
    live = rt.platform.window_layout()
    f = fold(app)
    w = next((x for x in live if f in fold(x.get("app") or "") or f in fold(x.get("exe") or "") or f in fold(x["title"])), None)
    if not w:
        raise ValueError(f"Okno „{app}“ nevidím.")
    nw, nh = min(w["w"], ww), min(w["h"], wh)
    ok = rt.platform.place_window(w["hwnd"], wx + (ww - nw) // 2, wy + (wh - nh) // 2, nw, nh, "maximized" if w["state"] == "maximized" else "normal")
    return {"ok": ok, "app": w.get("app") or w["title"], "monitor": monitor}


def _rect(r: Any) -> tuple[int, int, int, int]:
    for names in (("x", "y", "w", "h"), ("left", "top", "width", "height")):
        if all(hasattr(r, n) for n in names):
            return tuple(int(getattr(r, n)) for n in names)  # type: ignore[return-value]
    x, y, w, h = r
    return int(x), int(y), int(w), int(h)


# ---------------------------------------------------------------------------------------------- 521 shortcuts
SHORTCUTS: dict[str, list[tuple[str, str]]] = {
    "windows": [("Win+D", "plocha"), ("Win+E", "Průzkumník"), ("Win+Shift+S", "výřez obrazovky"), ("Win+V", "historie schránky"),
                ("Alt+Tab", "přepnout okno"), ("Win+šipky", "přichytit okno"), ("Win+L", "zamknout"), ("Win+.", "emoji"),
                ("Ctrl+Shift+Esc", "Správce úloh"), ("Win+Ctrl+D", "nová plocha")],
    "chrome": [("Ctrl+T", "nová karta"), ("Ctrl+Shift+T", "obnovit zavřenou kartu"), ("Ctrl+L", "adresní řádek"), ("Ctrl+W", "zavřít kartu"),
               ("Ctrl+Tab", "další karta"), ("Ctrl+F", "hledat na stránce"), ("Ctrl+H", "historie"), ("Ctrl+Shift+N", "anonymní okno")],
    "edge": [("Ctrl+T", "nová karta"), ("Ctrl+Shift+T", "obnovit zavřenou kartu"), ("Ctrl+L", "adresní řádek"), ("Ctrl+Shift+N", "InPrivate")],
    "firefox": [("Ctrl+T", "nová karta"), ("Ctrl+Shift+T", "obnovit zavřenou kartu"), ("Ctrl+L", "adresní řádek"), ("Ctrl+Shift+P", "soukromé okno")],
    "word": [("Ctrl+B / I / U", "tučně / kurzíva / podtržení"), ("Ctrl+Shift+>", "větší písmo"), ("Ctrl+Enter", "nová stránka"),
             ("F7", "kontrola pravopisu"), ("Ctrl+K", "odkaz"), ("Ctrl+Z / Y", "zpět / znovu"), ("Ctrl+H", "najít a nahradit")],
    "excel": [("Ctrl+šipka", "na konec dat"), ("Ctrl+Shift+L", "filtr"), ("F2", "upravit buňku"), ("Alt+=", "automatický součet"),
              ("Ctrl+;", "dnešní datum"), ("Ctrl+1", "formát buňky"), ("Ctrl+Space / Shift+Space", "celý sloupec / řádek")],
    "code": [("Ctrl+P", "otevřít soubor"), ("Ctrl+Shift+P", "příkazy"), ("Ctrl+/", "zakomentovat"), ("Alt+šipky", "posunout řádek"),
             ("F12", "na definici"), ("Ctrl+`", "terminál"), ("Ctrl+D", "další výskyt")],
    "explorer": [("Ctrl+Shift+N", "nová složka"), ("F2", "přejmenovat"), ("Alt+šipka nahoru", "nadřazená složka"), ("Ctrl+L", "adresa"),
                 ("Alt+Enter", "vlastnosti")],
    "outlook": [("Ctrl+N", "nový e-mail"), ("Ctrl+R", "odpovědět"), ("Ctrl+Shift+R", "odpovědět všem"), ("Ctrl+F", "přeposlat"),
                ("Ctrl+Q", "označit jako přečtené")],
    "jarvis": [("Ctrl+Space", "mluvit"), ("pravý Ctrl (držet)", "diktování"), ("Ctrl+Alt+H", "HUD"), ("Ctrl+Alt+X", "STOP všeho")],
}
ALIAS = {"msedge": "edge", "winword": "word", "průzkumník": "explorer", "visual studio code": "code", "olk": "outlook"}


def shortcuts_for(app: str) -> tuple[str, list[tuple[str, str]]]:
    f = fold(app).replace(".exe", "")
    key = next((v for k, v in ALIAS.items() if fold(k) in f), None) or next((k for k in SHORTCUTS if k in f), None)
    return (key or "windows"), SHORTCUTS[key or "windows"]


# ---------------------------------------------------------------------------------------------- 519 crashed apps
def crashed_recently(app_errors: list[dict], running: set[str], minutes: int = 60, now: float | None = None) -> list[str]:
    """From the Application log (event 1000): programs that crashed in the last N minutes and are not running now."""
    import datetime as dt

    now = now or time.time()
    out = []
    for e in app_errors:
        try:
            ts = dt.datetime.fromisoformat(str(e.get("Time"))[:19]).timestamp()
        except ValueError:
            continue
        app = str(e.get("App") or "")
        if now - ts <= minutes * 60 and app and fold(app) not in {fold(r) for r in running} and app not in out:
            out.append(app)
    return out


# ---------------------------------------------------------------------------------------------- 520 command history
def command_history(rt, query: str, limit: int = 15) -> list[dict]:
    q = f"%{query.strip()}%"
    acts = rt.db.all("SELECT ts, tool, args, ok, summary FROM task_actions WHERE tool LIKE ? OR args LIKE ? OR summary LIKE ? ORDER BY ts DESC LIMIT ?",
                     (q, q, q, limit))
    said = rt.db.all("SELECT created AS ts, content FROM messages WHERE role='user' AND content LIKE ? ORDER BY created DESC LIMIT ?", (q, limit))
    out = [{"ts": a["ts"], "kind": "akce", "text": f"{a['tool']} – {a['summary']}", "ok": bool(a["ok"])} for a in acts]
    out += [{"ts": m["ts"], "kind": "příkaz", "text": m["content"][:200], "ok": True} for m in said]
    return sorted(out, key=lambda x: -x["ts"])[:limit]
