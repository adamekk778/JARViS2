"""3.20 Propojení+ (421, 423, 424, 425): two-way sync of JARVIS's own calendar with Google Calendar and of a JARVIS list
with Todoist or Microsoft To Do (no duplicates: each pair is remembered, and an item already on the other side by the
same name and time is paired instead of copied), an Obsidian vault (notes and open tasks), and Spotify control.

The sync works on adapters (list / add / delete / done) so the tests run it on fakes and the real services only supply
those few calls."""
from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Awaitable, Callable

SCHEMA = "CREATE TABLE IF NOT EXISTS sy_map (kind TEXT, local TEXT, remote TEXT, sig TEXT, PRIMARY KEY (kind, local));"


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_syncx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._syncx_ready = True
    return rt.db


def pairs(rt: Any, kind: str) -> dict[str, str]:
    return {r["local"]: r["remote"] for r in db(rt).all("SELECT local, remote FROM sy_map WHERE kind=?", (kind,))}


def pair(rt: Any, kind: str, local: str, remote: str, sig: str = "") -> None:
    db(rt).exec("INSERT OR REPLACE INTO sy_map VALUES (?,?,?,?)", (kind, local, remote, sig))


def unpair(rt: Any, kind: str, local: str) -> None:
    db(rt).exec("DELETE FROM sy_map WHERE kind=? AND local=?", (kind, local))


def sig_of(ev: dict) -> str:
    return f"{fold(ev['title'])}|{int(ev['start']) // 60}"


# ------------------------------------------------------------------ (421) JARVIS calendar ↔ Google Calendar
Remote = dict      # {"id", "title", "start" (ts), "end" (ts), "location", "jarvis" (local id or "")}


async def sync_calendar(rt: Any, remote_list: Callable[[], Awaitable[list[Remote]]], remote_add: Callable[[dict], Awaitable[str]],
                        remote_delete: Callable[[str], Awaitable[None]], days: int = 60, now: float | None = None) -> dict:
    """One pass both ways for the next `days` days. A deleted pair disappears on the other side too; an event moved in
    Google moves in JARVIS (JARVIS's copy keeps your reminder settings)."""
    now = time.time() if now is None else now
    kind = "gcal"
    a, b = now - 86400, now + days * 86400
    local = {r["id"]: dict(r) for r in rt.db.all("SELECT * FROM cal_events WHERE end >= ? AND start <= ?", (a, b))}
    remote = {r["id"]: r for r in await remote_list()}
    mp = pairs(rt, kind)
    rev = {v: k for k, v in mp.items()}
    stats = {"pushed": 0, "pulled": 0, "paired": 0, "deleted_remote": 0, "deleted_local": 0, "updated_local": 0}
    by_sig = {sig_of(r): rid for rid, r in remote.items() if rid not in rev}
    # pairs that lost one side
    for lid, rid in list(mp.items()):
        lid_alive = lid in local or rt.db.one("SELECT 1 FROM cal_events WHERE id=?", (lid,)) is not None
        if not lid_alive and rid in remote:
            await remote_delete(rid)
            remote.pop(rid, None)
            unpair(rt, kind, lid)
            stats["deleted_remote"] += 1
        elif lid_alive and rid not in remote and lid in local:
            rt.db.exec("DELETE FROM cal_events WHERE id=?", (lid,))
            local.pop(lid, None)
            unpair(rt, kind, lid)
            stats["deleted_local"] += 1
        elif lid in local and rid in remote:
            r, lo = remote[rid], local[lid]
            if (int(r["start"]) // 60, fold(r["title"])) != (int(lo["start"]) // 60, fold(lo["title"])):
                rt.db.exec("UPDATE cal_events SET title=?, start=?, end=?, location=? WHERE id=?",
                           (r["title"], r["start"], r["end"], r.get("location", ""), lid))
                stats["updated_local"] += 1
    mp = pairs(rt, kind)
    rev = {v: k for k, v in mp.items()}
    # JARVIS → Google
    for lid, ev in local.items():
        if lid in mp:
            continue
        rid = by_sig.pop(sig_of(ev), None)
        if rid:
            pair(rt, kind, lid, rid)
            stats["paired"] += 1
            continue
        rid = await remote_add({"title": ev["title"], "start": ev["start"], "end": ev["end"], "location": ev.get("location") or "", "jarvis": lid})
        pair(rt, kind, lid, rid)
        stats["pushed"] += 1
    rev = {v: k for k, v in pairs(rt, kind).items()}
    # Google → JARVIS
    for rid, r in remote.items():
        if rid in rev or (r.get("jarvis") and r["jarvis"] in local):
            continue
        start = dt.datetime.fromtimestamp(r["start"])
        e = rt.calendar.add(r["title"], start, max(1, int((r["end"] - r["start"]) / 60)), r.get("location", ""))
        pair(rt, kind, e["id"], rid)
        stats["pulled"] += 1
    return stats


def google_event(ev: dict) -> dict:
    """A Google Calendar API event → the sync's shape."""
    def ts(x: dict) -> float:
        if x.get("dateTime"):
            return dt.datetime.fromisoformat(x["dateTime"].replace("Z", "+00:00")).timestamp()
        return dt.datetime.combine(dt.date.fromisoformat(x["date"]), dt.time()).timestamp()

    return {"id": ev["id"], "title": ev.get("summary", "(bez názvu)"), "start": ts(ev.get("start") or {}), "end": ts(ev.get("end") or {}),
            "location": ev.get("location", ""), "jarvis": ((ev.get("extendedProperties") or {}).get("private") or {}).get("jarvis", "")}


def google_body(ev: dict) -> dict:
    tz = dt.datetime.now().astimezone().tzinfo

    def iso(t: float) -> str:
        return dt.datetime.fromtimestamp(t, tz).isoformat()

    return {"summary": ev["title"], "location": ev.get("location", ""), "start": {"dateTime": iso(ev["start"])}, "end": {"dateTime": iso(ev["end"])},
            "extendedProperties": {"private": {"jarvis": ev.get("jarvis", "")}}}


async def google_adapters(days: int = 60):
    from .connectors import google, http

    async def lst() -> list[dict]:
        now = dt.datetime.now(dt.timezone.utc)
        r = await google._get(google.CAL, timeMin=(now - dt.timedelta(days=1)).isoformat(), timeMax=(now + dt.timedelta(days=days)).isoformat(),
                              singleEvents="true", maxResults=250)
        return [google_event(e) for e in r.get("items", []) if e.get("status") != "cancelled"]

    async def add(ev: dict) -> str:
        r = await google._post(google.CAL, google_body(ev))
        return str(r.get("id", ""))

    async def delete(rid: str) -> None:
        async with http() as c:
            r = await c.delete(f"{google.CAL}/{rid}", headers=await google._auth())
            if r.status_code not in (200, 204, 404, 410):
                r.raise_for_status()

    return lst, add, delete


# ------------------------------------------------------------------ (424) a JARVIS list ↔ Todoist / Microsoft To Do
async def sync_list(rt: Any, list_name: str, service: str, remote_open: Callable[[], Awaitable[list[dict]]],
                    remote_add: Callable[[str], Awaitable[str]], remote_done: Callable[[str], Awaitable[None]]) -> dict:
    """The JARVIS list `list_name` and one remote list kept equal: new on either side → added to the other; ticked off in
    the service → removed from the list; removed from the list → ticked off in the service."""
    from .tools.list_tools import _db as list_db
    from .tools.list_tools import add_items

    kind = f"list:{service}:{fold(list_name)}"
    local = {str(r["id"]): r["item"] for r in list_db(rt).all("SELECT id, item FROM lists WHERE list=?", (list_name,))}
    remote = {r["id"]: r["title"] for r in await remote_open()}
    mp = pairs(rt, kind)
    stats = {"pushed": 0, "pulled": 0, "paired": 0, "done_remote": 0, "removed_local": 0}
    for lid, rid in list(mp.items()):
        if lid not in local and rid in remote:
            await remote_done(rid)
            remote.pop(rid)
            unpair(rt, kind, lid)
            stats["done_remote"] += 1
        elif lid in local and rid not in remote:
            list_db(rt).exec("DELETE FROM lists WHERE id=?", (int(lid),))
            local.pop(lid)
            unpair(rt, kind, lid)
            stats["removed_local"] += 1
        elif lid not in local and rid not in remote:
            unpair(rt, kind, lid)
    mp = pairs(rt, kind)
    rev = {v: k for k, v in mp.items()}
    free_remote = {fold(t): rid for rid, t in remote.items() if rid not in rev}
    for lid, item in local.items():
        if lid in mp:
            continue
        rid = free_remote.pop(fold(item), None)
        if rid:
            pair(rt, kind, lid, rid)
            stats["paired"] += 1
        else:
            pair(rt, kind, lid, await remote_add(item))
            stats["pushed"] += 1
    rev = {v: k for k, v in pairs(rt, kind).items()}
    for rid, title in remote.items():
        if rid in rev:
            continue
        add_items(rt, list_name, [title])
        row = list_db(rt).one("SELECT id FROM lists WHERE list=? ORDER BY id DESC LIMIT 1", (list_name,))
        if row:
            pair(rt, kind, str(row["id"]), rid)
            stats["pulled"] += 1
    return stats


async def todoist_adapters(project: str):
    from .connectors import todoist

    projects = await todoist._all("/projects")
    pid = next((p["id"] for p in projects if fold(p.get("name", "")) == fold(project)), None)
    if pid is None:
        pid = (await todoist._api("POST", "/projects", {"name": project}))["id"]

    async def lst() -> list[dict]:
        return [{"id": str(t["id"]), "title": t.get("content", "")} for t in await todoist._all("/tasks", project_id=pid)]

    async def add(title: str) -> str:
        return str((await todoist._api("POST", "/tasks", {"content": title, "project_id": pid}))["id"])

    async def done(rid: str) -> None:
        await todoist._api("POST", f"/tasks/{rid}/close")

    return lst, add, done


async def mstodo_adapters(list_title: str):
    from .connectors import microsoft

    lists = await microsoft._lists()
    lst_id = next((x["id"] for x in lists if fold(x.get("displayName", "")) == fold(list_title)), None)
    if lst_id is None:
        lst_id = (await microsoft._api("POST", "/me/todo/lists", json={"displayName": list_title}))["id"]

    async def lst() -> list[dict]:
        r = await microsoft._api("GET", f"/me/todo/lists/{lst_id}/tasks", params={"$filter": "status ne 'completed'", "$top": 100})
        return [{"id": t["id"], "title": t.get("title", "")} for t in r.get("value", [])]

    async def add(title: str) -> str:
        return str((await microsoft._api("POST", f"/me/todo/lists/{lst_id}/tasks", json={"title": title}))["id"])

    async def done(rid: str) -> None:
        await microsoft._api("PATCH", f"/me/todo/lists/{lst_id}/tasks/{rid}", json={"status": "completed"})

    return lst, add, done


# ------------------------------------------------------------------ (423) Obsidian vault
TASK_RX = re.compile(r"^(\s*[-*]\s+\[)( )(\]\s+)(.+)$")


def vault_files(vault: Path, limit: int = 5000):
    n = 0
    for p in vault.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(vault).parts):
            continue
        yield p
        n += 1
        if n >= limit:
            return


def vault_search(vault: Path, query: str, limit: int = 10) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9]+", fold(query)) if len(w) > 2]
    out = []
    for p in vault_files(vault):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hay = fold(p.stem + " " + text)
        score = sum(3 if w in fold(p.stem) else 1 for w in words if w in hay)
        if score:
            line = next((ln.strip() for ln in text.splitlines() if any(w in fold(ln) for w in words)), "")
            out.append((score, {"note": str(p.relative_to(vault).with_suffix("")).replace("\\", "/"), "line": line[:160]}))
    return [x for _, x in sorted(out, key=lambda x: -x[0])[:limit]]


def vault_tasks(vault: Path, limit: int = 50) -> list[dict]:
    out = []
    for p in vault_files(vault):
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            m = TASK_RX.match(ln)
            if m:
                out.append({"note": str(p.relative_to(vault).with_suffix("")).replace("\\", "/"), "line": i, "task": m.group(4).strip()})
                if len(out) >= limit:
                    return out
    return out


def vault_done(vault: Path, task: str) -> dict | None:
    """Ticks the first open task containing the words (- [ ] → - [x])."""
    t = fold(task)
    for p in vault_files(vault):
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        for i, ln in enumerate(lines):
            m = TASK_RX.match(ln.rstrip("\n"))
            if m and t in fold(m.group(4)):
                lines[i] = ln.replace("[ ]", "[x]", 1)
                p.write_text("".join(lines), encoding="utf-8")
                return {"note": p.stem, "task": m.group(4).strip()}
    return None


def vault_append(vault: Path, text: str, note: str = "", today: dt.date | None = None, task: bool = False) -> Path:
    """To a named note, or to today's daily note (Obsidian's default name YYYY-MM-DD.md in the vault root)."""
    name = note.strip() or (today or dt.date.today()).isoformat()
    if ".." in name or name.startswith(("/", "\\")):
        raise ValueError("Neplatný název poznámky.")
    p = vault / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [ ] {text.strip()}" if task else f"- {dt.datetime.now():%H:%M} {text.strip()}"
    prev = p.read_text(encoding="utf-8") if p.exists() else ""
    p.write_text(prev + ("" if not prev or prev.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    return p


# ------------------------------------------------------------------ (425) Spotify control
SPOTIFY_SCOPES = ("user-read-currently-playing user-read-playback-state user-modify-playback-state playlist-read-private "
                  "user-library-modify")
SPOTIFY_CMD = {"pauz": ("PUT", "/me/player/pause"), "zastav": ("PUT", "/me/player/pause"), "pokrac": ("PUT", "/me/player/play"),
               "pust": ("PUT", "/me/player/play"), "dalsi": ("POST", "/me/player/next"), "predchoz": ("POST", "/me/player/previous")}


def best_playlist(items: list[dict], query: str) -> dict | None:
    q = set(re.findall(r"[a-z0-9]+", fold(query))) - {"playlist", "playlistu", "pust", "muj", "moje"}
    best, score = None, 0
    for p in items:
        words = set(re.findall(r"[a-z0-9]+", fold(p.get("name", ""))))
        s = len(q & words) + (2 if fold(p.get("name", "")) == fold(query) else 0)
        if s > score:
            best, score = p, s
    return best


async def spotify(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    from .connectors import http, spotify as sp

    async with http(transport=transport) as c:
        r = await c.request(method, "https://api.spotify.com/v1" + path, headers=await sp._auth(transport), json=body, params=params or None)
        if r.status_code == 403:
            raise ValueError("Spotify ovládání přehrávání dovoluje jen s Premium účtem (a po novém přihlášení se širším oprávněním).")
        if r.status_code == 404:
            raise ValueError("Spotify teď nemá aktivní přehrávač – pusť Spotify na některém zařízení.")
        r.raise_for_status()
        return r.json() if r.content else {}


# ------------------------------------------------------------------ every 15 minutes
async def tick(rt: Any, now: float | None = None) -> list[str]:
    from .config import LinkXCfg
    from .connectors import configured

    c = getattr(rt.cfg, "linkx", None) or LinkXCfg()
    now = time.time() if now is None else now
    if now - getattr(rt, "_syncx_at", 0.0) < 900 or not (c.calendar_sync or c.list_sync):
        return []
    rt._syncx_at = now
    said = []
    if c.calendar_sync and configured("google"):
        try:
            st = await sync_calendar(rt, *(await google_adapters()))
            if st["pulled"] or st["pushed"]:
                said.append(f"Kalendář: {st['pushed']} do Googlu, {st['pulled']} z Googlu.")
        except Exception:  # noqa: BLE001 – offline; next time
            pass
    for name, target in c.list_sync.items():
        svc, _, remote = target.partition(":")
        try:
            if svc == "todoist" and configured("todoist"):
                await sync_list(rt, name, "todoist", *(await todoist_adapters(remote or name)))
            elif svc == "mstodo" and configured("microsoft"):
                await sync_list(rt, name, "mstodo", *(await mstodo_adapters(remote or name)))
        except Exception:  # noqa: BLE001
            continue
    return said
