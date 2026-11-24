"""3.15 Dílna – deník projektů (návrh C5): každý projekt má cíl, stav, časovou osu (poznámky, fotky, verze, tisky,
sestavení firmwaru), díly s cenami a z chybějících dílů nákupní seznam.

"Založ projekt meteostanice", "zapiš do projektu: pájení hotové", "přidej díly: 2× BME280, ESP32, 3 m kabelu",
"co mi chybí na meteostanici?" → na nákupní seznam. Fotky z telefonu / kamery se ukládají k projektu. Aktivní projekt
(ten poslední, na kterém se dělalo) dostává i záznamy o tiscích a z hlídání tiskárny.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from . import paths

SQL = """CREATE TABLE IF NOT EXISTS ws_projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, goal TEXT,
           status TEXT DEFAULT 'rozpracováno', version TEXT DEFAULT '0.1.0', created REAL, updated REAL);
         CREATE TABLE IF NOT EXISTS ws_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, project INTEGER, kind TEXT, text TEXT,
           path TEXT, version TEXT, ts REAL);
         CREATE TABLE IF NOT EXISTS ws_parts (id INTEGER PRIMARY KEY AUTOINCREMENT, project INTEGER, part TEXT, qty REAL,
           unit TEXT, have REAL DEFAULT 0, price REAL DEFAULT 0, link TEXT DEFAULT '');
         CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);"""
STATUSES = ("nápad", "plán", "rozpracováno", "čeká na díly", "testování", "hotovo", "odloženo")
KIND_ICON = {"note": "note-pencil", "photo": "camera", "version": "git-commit", "print": "printer", "build": "cpu", "cad": "cube",
             "status": "flag", "parts": "package"}


def _db(rt):
    rt.db.conn.executescript(SQL)
    return rt.db


def _fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)).strip()


def find(rt, name: str = "") -> dict | None:
    """By name (exact, then a part of it, ignoring diacritics), or the active one when name is empty."""
    db = _db(rt)
    if not name.strip():
        kv = db.one("SELECT v FROM kv WHERE k='workshop.active'")
        pid = kv["v"] if kv else None
        r = db.one("SELECT * FROM ws_projects WHERE id=?", (int(pid),)) if pid else None
        return dict(r) if r else (dict(x) if (x := db.one("SELECT * FROM ws_projects ORDER BY updated DESC LIMIT 1")) else None)
    rows = [dict(r) for r in db.all("SELECT * FROM ws_projects ORDER BY updated DESC")]
    f = _fold(name)
    for r in rows:
        if _fold(r["name"]) == f:
            return r
    for r in rows:
        if f in _fold(r["name"]) or _fold(r["name"]) in f:
            return r
    return None


def set_active(rt, pid: int) -> None:
    _db(rt).exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('workshop.active', ?)", (str(pid),))


def create(rt, name: str, goal: str = "") -> dict:
    db = _db(rt)
    old = find(rt, name)
    if old and _fold(old["name"]) == _fold(name):
        set_active(rt, old["id"])
        return old
    now = time.time()
    db.exec("INSERT INTO ws_projects (name, goal, status, created, updated) VALUES (?,?,?,?,?)", (name.strip()[:80], goal[:500], "plán", now, now))
    p = find(rt, name) or {}
    set_active(rt, p["id"])
    add_entry(rt, p, "status", "Projekt založen" + (f": {goal}" if goal else ""))
    return p


def touch(rt, p: dict) -> None:
    _db(rt).exec("UPDATE ws_projects SET updated=? WHERE id=?", (time.time(), p["id"]))
    set_active(rt, p["id"])


def add_entry(rt, p: dict, kind: str, text: str, path: str | Path | None = None, version: str = "") -> dict:
    stored = ""
    if path:
        src = Path(path)
        if src.exists():
            dst_dir = paths.sub("workshop") / "projects" / re.sub(r"[^a-z0-9]+", "-", _fold(p["name"])).strip("-")
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{src.name}"
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            stored = str(dst)
    _db(rt).exec("INSERT INTO ws_entries (project, kind, text, path, version, ts) VALUES (?,?,?,?,?,?)",
                 (p["id"], kind, text[:2000], stored, version or p.get("version", ""), time.time()))
    touch(rt, p)
    rt.bus.publish("workshop_journal", project=p["name"], kind=kind, text=text[:200])
    return {"kind": kind, "text": text, "path": stored}


def log_active(rt, kind: str, text: str, photo: Path | None = None) -> None:
    """A print / a build / a failed print → the active project's journal (if there is one)."""
    p = find(rt)
    if p and p.get("status") not in ("hotovo", "odloženo"):
        add_entry(rt, p, kind, text, photo)


def set_status(rt, p: dict, status: str) -> str:
    st = next((s for s in STATUSES if _fold(s).startswith(_fold(status)[:5])), "")
    if not st:
        return ""
    _db(rt).exec("UPDATE ws_projects SET status=? WHERE id=?", (st, p["id"]))
    add_entry(rt, p, "status", f"Stav: {st}")
    return st


def new_version(rt, p: dict, part: str = "minor", note: str = "") -> str:
    from .hwlab import bump

    v = bump(p.get("version") or "0.1.0", part)
    _db(rt).exec("UPDATE ws_projects SET version=? WHERE id=?", (v, p["id"]))
    p["version"] = v
    add_entry(rt, p, "version", f"Verze {v}" + (f": {note}" if note else ""), version=v)
    return v


def timeline(rt, p: dict, limit: int = 50) -> list[dict]:
    return [dict(r) for r in _db(rt).all("SELECT * FROM ws_entries WHERE project=? ORDER BY ts DESC LIMIT ?", (p["id"], limit))]


# ------------------------------------------------------------------------------------------ parts → shopping list
_QTY = re.compile(r"^\s*(?:(\d+(?:[.,]\d+)?)\s*(x|×|ks|kus\w*|m|cm|mm|g|kg|bal\w*)?\s*)?(.+?)\s*(?:(?:za|à|a)\s*(\d+(?:[.,]\d+)?)\s*(?:kc|kč|czk)\b.*)?$", re.I)


def parse_parts(text: str) -> list[dict]:
    """"2× BME280, ESP32, 3 m kabelu, 10 ks M3 šroubů za 2 Kč" → [{part, qty, unit, price}]"""
    out = []
    for chunk in re.split(r",|;|\n|\ba\b(?=\s*\d)", text):
        chunk = chunk.strip(" .-")
        if not chunk:
            continue
        m = _QTY.match(chunk)
        if not m:
            continue
        qty = float(m.group(1).replace(",", ".")) if m.group(1) else 1.0
        unit = (m.group(2) or "").lower()
        unit = "ks" if unit in ("x", "×", "") or unit.startswith("kus") else unit
        price = float(m.group(4).replace(",", ".")) if m.group(4) else 0.0
        part = re.sub(r"\s+", " ", m.group(3)).strip()
        if part:
            out.append({"part": part[:80], "qty": qty, "unit": unit, "price": price})
    return out


def add_parts(rt, p: dict, items: list[dict], have: bool = False) -> list[str]:
    db = _db(rt)
    added = []
    for it in items:
        row = db.one("SELECT * FROM ws_parts WHERE project=? AND lower(part)=lower(?)", (p["id"], it["part"]))
        if row:
            db.exec("UPDATE ws_parts SET qty=qty+?, have=have+?, price=CASE WHEN ?>0 THEN ? ELSE price END WHERE id=?",
                    (it["qty"], it["qty"] if have else 0, it["price"], it["price"], row["id"]))
        else:
            db.exec("INSERT INTO ws_parts (project, part, qty, unit, have, price) VALUES (?,?,?,?,?,?)",
                    (p["id"], it["part"], it["qty"], it["unit"], it["qty"] if have else 0, it["price"]))
        added.append(f"{_fmt(it['qty'])} {it['unit']} {it['part']}".replace(" ks ", "× ").strip())
    if added:
        add_entry(rt, p, "parts", "Díly: " + ", ".join(added))
    return added


def mark_have(rt, p: dict, names: list[str]) -> list[str]:
    db = _db(rt)
    done = []
    for n in names:
        row = db.one("SELECT * FROM ws_parts WHERE project=? AND lower(part) LIKE lower(?)", (p["id"], f"%{n.strip()}%"))
        if row:
            db.exec("UPDATE ws_parts SET have=qty WHERE id=?", (row["id"],))
            done.append(row["part"])
    return done


def parts(rt, p: dict) -> list[dict]:
    return [dict(r) for r in _db(rt).all("SELECT * FROM ws_parts WHERE project=? ORDER BY id", (p["id"],))]


def missing(rt, p: dict) -> list[dict]:
    return [r | {"need": r["qty"] - r["have"]} for r in parts(rt, p) if r["qty"] - r["have"] > 1e-9]


def _fmt(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def bom_summary(rt, p: dict) -> dict:
    ps = parts(rt, p)
    total = sum(r["qty"] * r["price"] for r in ps)
    miss = missing(rt, p)
    to_buy = sum(r["need"] * r["price"] for r in miss)
    return {"parts": len(ps), "total_czk": round(total), "missing": len(miss), "to_buy_czk": round(to_buy),
            "no_price": [r["part"] for r in ps if not r["price"]]}


def to_shopping(rt, p: dict, list_name: str = "dílna") -> list[str]:
    """The missing parts → a shopping list (default "dílna", so they don't mix with groceries)."""
    from .tools import list_tools

    items = [f"{_fmt(r['need'])} {r['unit']} {r['part']} ({p['name']})".replace(" ks ", "× ") for r in missing(rt, p)]
    if items:
        list_tools.add_items(rt, list_name, items)
        list_tools._changed(rt)
    return items


def overview(rt, p: dict) -> dict:
    tl = timeline(rt, p, 200)
    photos = [e["path"] for e in tl if e["path"] and e["path"].lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    from . import cad

    models = [c["name"] for c in cad.parts(rt) if c.get("project") == p["name"]]
    return {"name": p["name"], "goal": p.get("goal", ""), "status": p.get("status", ""), "version": p.get("version", ""),
            "entries": len(tl), "photos": photos[:12], "models": models, "bom": bom_summary(rt, p),
            "last": [{"kind": e["kind"], "text": e["text"][:140], "ts": e["ts"]} for e in tl[:8]]}


def projects(rt) -> list[dict]:
    return [dict(r) for r in _db(rt).all("SELECT * FROM ws_projects ORDER BY updated DESC")]
