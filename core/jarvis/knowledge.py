"""OMEGA §04 Ultra Memory + §4.4 Personal AI Brain: facts with a category, a source and a project; contradictions
noticed instead of silently overwritten; projects with their own memory and "navaž, kde jsme skončili"; a timeline of
the day; one search over everything JARVIS stores (full text, diacritics-insensitive; by meaning when a local
embedding model is installed in Ollama – never downloaded silently).

Rules: nothing from the private mode is stored or indexed; passwords never become facts (redact.looks_secret);
what JARVIS remembers can always be seen, corrected, exported and deleted.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT UNIQUE, folder TEXT DEFAULT '', note TEXT DEFAULT '',
  created REAL, updated REAL, archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS fact_conflicts (id INTEGER PRIMARY KEY AUTOINCREMENT, old_id INTEGER, new_id INTEGER, created REAL,
  resolved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS search_emb (kind TEXT, ref TEXT, model TEXT, vec BLOB, PRIMARY KEY (kind, ref, model));
"""
FTS = "CREATE VIRTUAL TABLE IF NOT EXISTS search_idx USING fts5(kind, ref UNINDEXED, title, body, ts UNINDEXED, " \
      "tokenize='unicode61 remove_diacritics 2')"

CATEGORIES = [
    ("Rodina", r"\b(manžel|manželk|syn|dcer|máma|mamink|táta|tatínek|babičk|dědeček|děda|sestr|bratr|rodin|přítelkyn|přítel)"),
    ("Zdraví", r"\b(alergi|lék|nemoc|doktor|lékař|zdrav|dieta|vegetarián|vegan|cukrovk|tlak)"),
    ("Práce", r"\b(prac|zaměstn|firm|šéf|kolleg|kolega|projekt|klient|porad|kancelář)"),
    ("Škola", r"\b(škol|studuj|student|univerzit|maturit|zkoušk|tříd)"),
    ("Finance", r"\b(banka|účet|plat|výplat|úspor|hypoték|půjčk|rozpočet|kč\b|korun)"),
    ("Domov", r"\b(bydl|byt\b|dům|domov|adres|ulice|město|zahrad)"),
    ("Kontakty", r"(\+?\d[\d ]{8,}|@\w+\.\w+|\btelefon|\bčíslo na)"),
    ("Technika", r"\b(počítač|notebook|telefon|mobil|windows|android|iphone|monitor|klávesnic|myš|grafick)"),
    ("Preference", r"\b(rád|ráda|nerad|nemám rád|oblíben|preferuj|chci aby|nechci|líbí|nesnáším)"),
    ("Osobní", r"\b(jmenuj|narozen|narozenin|věk|let\b|koníč|hobby|mazlíč|pes|kočk)"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip(" .!?")


def category(text: str) -> str:
    t = text.lower()
    for name, rx in CATEGORIES:
        if re.search(rx, t):
            return name
    return "Ostatní"


# a fact's subject and value: "moje auto je modré" → ("moje auto", "modre"); "jmenuji se Adam" → ("jmenuji se", "adam")
VERBS = r"(je|jsou|bude|byl[ao]?|mam|ma|maji|bydlim|bydli|pracuji|pracuje|studuji|jmenuji se|jmenuje se|narodil[a]? jsem se|" \
        r"chodim|jezdim|pouzivam|preferuji|piju|jim)"


def subject_value(text: str) -> tuple[str, str] | None:
    t = norm(text)
    m = re.match(rf"^(.{{0,40}}?)\s*\b{VERBS}\b\s+(.+)$", t)
    if not m:
        return None
    subj = (m.group(1) + " " + m.group(2)).strip() if m.group(1) else m.group(2)
    value = m.group(3).strip()
    if len(value) > 60:
        return None
    return subj, value


def stem(w: str) -> str:
    """Czech words change their endings (smlouva, smlouvu, smlouvách): search by the start of the word."""
    return w[:max(4, len(w) - 2)] if len(w) >= 6 else w


class Knowledge:
    def __init__(self, rt):
        self.rt = rt
        db = rt.db
        with db.lock:
            db.conn.executescript(SCHEMA)
            cols = {r[1] for r in db.conn.execute("PRAGMA table_info(facts)")}
            for col in ("category", "source", "project"):
                if col not in cols:
                    db.conn.execute(f"ALTER TABLE facts ADD COLUMN {col} TEXT DEFAULT ''")
            try:
                db.conn.execute(FTS)
                self.fts = True
            except Exception:  # noqa: BLE001 – a SQLite without FTS5: fall back to LIKE
                self.fts = False
            db.conn.commit()

    # ------------------------------------------------------------------------------------------ facts
    def add_fact(self, text: str, source: str = "", project: str | None = None) -> dict:
        """Remember with category, source and project. A contradiction with an older fact is recorded and returned,
        both facts stay until the user says which one holds."""
        mem = self.rt.memory
        if mem.private:
            return {"stored": False, "reason": "soukromý režim"}
        text = text.strip()
        if not text:
            return {"stored": False, "reason": "prázdné"}
        project = self.current_project() if project is None else project
        old = self.rt.db.one("SELECT id FROM facts WHERE text=?", (text,))
        if old:
            return {"stored": False, "reason": "už to vím", "id": old["id"]}
        cur = self.rt.db.exec("INSERT INTO facts(text, created, category, source, project) VALUES (?,?,?,?,?)",
                              (text, time.time(), category(text), source[:200], project))
        fid = cur.lastrowid
        conflicts = self._conflicts_for(fid, text, project)
        for c in conflicts:
            self.rt.db.exec("INSERT INTO fact_conflicts(old_id, new_id, created) VALUES (?,?,?)", (c["id"], fid, time.time()))
        return {"stored": True, "id": fid, "category": category(text), "conflicts": conflicts}

    def _conflicts_for(self, fid: int, text: str, project: str) -> list[dict]:
        sv = subject_value(text)
        if not sv:
            return []
        out = []
        for f in self.rt.db.all("SELECT id, text, created FROM facts WHERE id<>? AND project=?", (fid, project)):
            o = subject_value(f["text"])
            if o and o[0] == sv[0] and o[1] != sv[1]:
                out.append(f)
        return out

    def facts(self, project: str | None = None, include_global: bool = True) -> list[dict]:
        if project is None:
            return self.rt.db.all("SELECT id, text, created, category, source, project FROM facts ORDER BY id")
        q = "SELECT id, text, created, category, source, project FROM facts WHERE project=?" + (" OR project=''" if include_global else "")
        return self.rt.db.all(q + " ORDER BY id", (project,))

    def for_prompt(self) -> list[str]:
        """Global facts + the current project's; other projects stay out (per-project isolation)."""
        return [f["text"] for f in self.facts(self.current_project())]

    def open_conflicts(self) -> list[dict]:
        rows = self.rt.db.all("SELECT c.id, c.created, o.id AS old_id, o.text AS old_text, n.id AS new_id, n.text AS new_text "
                              "FROM fact_conflicts c JOIN facts o ON o.id=c.old_id JOIN facts n ON n.id=c.new_id "
                              "WHERE c.resolved=0 ORDER BY c.id")
        return rows

    def resolve_conflict(self, cid: int, keep: str) -> dict:
        c = self.rt.db.one("SELECT * FROM fact_conflicts WHERE id=? AND resolved=0", (cid,))
        if not c:
            raise ValueError("Takový rozpor neexistuje.")
        if keep not in ("new", "old", "both"):
            raise ValueError("keep musí být new, old nebo both")
        drop = {"new": c["old_id"], "old": c["new_id"]}.get(keep)
        if drop:
            self.rt.db.exec("DELETE FROM facts WHERE id=?", (drop,))
            self.rt.db.exec("UPDATE fact_conflicts SET resolved=1 WHERE old_id=? OR new_id=?", (drop, drop))
        self.rt.db.exec("UPDATE fact_conflicts SET resolved=1 WHERE id=?", (cid,))
        return {"kept": keep, "deleted": drop}

    def set_fact_category(self, fid: int, cat: str) -> None:
        self.rt.db.exec("UPDATE facts SET category=? WHERE id=?", (cat[:40], fid))

    def by_category(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for f in self.facts():
            out.setdefault(f["category"] or category(f["text"]), []).append(f)
        return out

    # ------------------------------------------------------------------------------------------ projects
    def projects(self, archived: bool = False) -> list[dict]:
        return self.rt.db.all("SELECT * FROM projects WHERE archived=? ORDER BY updated DESC", (int(archived),))

    def project(self, name: str) -> dict | None:
        return self.rt.db.one("SELECT * FROM projects WHERE lower(name)=lower(?) OR id=?", (name.strip(), name.strip()))

    def create_project(self, name: str, folder: str = "", note: str = "") -> dict:
        name = name.strip()[:60]
        if not name:
            raise ValueError("Projekt potřebuje název.")
        if self.project(name):
            raise ValueError(f"Projekt „{name}“ už existuje.")
        pid = uuid.uuid4().hex[:10]
        now = time.time()
        self.rt.db.exec("INSERT INTO projects(id, name, folder, note, created, updated) VALUES (?,?,?,?,?,?)",
                        (pid, name, folder[:400], note[:2000], now, now))
        return self.project(pid)

    def current_project(self) -> str:
        row = self.rt.db.one("SELECT v FROM kv WHERE k='project_current'")
        return row["v"] if row else ""

    def switch(self, name: str) -> dict | None:
        if not name:
            self.rt.db.exec("DELETE FROM kv WHERE k='project_current'")
            return None
        p = self.project(name)
        if not p:
            raise ValueError(f"Projekt „{name}“ neznám.")
        self.rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('project_current', ?)", (p["name"],))
        self.rt.db.exec("UPDATE projects SET updated=? WHERE id=?", (time.time(), p["id"]))
        return p

    def project_prompt(self) -> str:
        cur = self.current_project()
        if not cur:
            return ""
        p = self.project(cur) or {}
        return f"Aktuální projekt: {cur}." + (f" Poznámka k projektu: {p.get('note')}" if p.get("note") else "") + \
            (f" Složka projektu: {p.get('folder')}." if p.get("folder") else "")

    def resume(self, name: str) -> dict:
        """OMEGA 044: where we left off – the project's conversations, facts, missions, files and the next step."""
        p = self.project(name)
        if not p:
            raise ValueError(f"Projekt „{name}“ neznám.")
        db = self.rt.db
        convs = db.all("SELECT id, title, updated FROM conversations WHERE folder=? ORDER BY updated DESC LIMIT 5", (p["name"],))
        last_answer = ""
        if convs:
            r = db.one("SELECT content FROM messages WHERE conv_id=? AND role='assistant' ORDER BY created DESC LIMIT 1", (convs[0]["id"],))
            last_answer = (r or {}).get("content", "")[:400]
        like = f"%{p['name']}%"
        tasks = db.all("SELECT id, goal, status, created FROM tasks WHERE goal LIKE ? ORDER BY created DESC LIMIT 5", (like,))
        files: list[dict] = []
        if p["folder"]:
            from pathlib import Path

            from .fileuniverse import recent_files

            folder = Path(p["folder"]).expanduser()
            if folder.is_dir():
                files = recent_files([folder], hours=24 * 30, limit=8)
        facts = [f["text"] for f in self.facts(p["name"], include_global=False)]
        open_tasks = [t for t in tasks if t["status"] not in ("done", "cancelled")]
        nxt = (f"Dokončit misi „{open_tasks[0]['goal'][:80]}“" if open_tasks
               else f"Navázat na konverzaci „{convs[0]['title']}“" if convs else "Popsat, co je cílem projektu")
        return {"project": p, "conversations": convs, "last_answer": last_answer, "tasks": tasks, "files": files,
                "facts": facts, "next": nxt}

    # ------------------------------------------------------------------------------------------ timeline
    def timeline(self, day: dt.date | None = None) -> list[dict]:
        """OMEGA 036: what happened on a day – conversations, missions, dictation, recorded calls, apps, notes."""
        day = day or dt.date.today()
        t0 = dt.datetime.combine(day, dt.time()).timestamp()
        t1 = t0 + 86400
        db, ev = self.rt.db, []
        for c in db.all("SELECT c.id, c.title, c.folder, MIN(m.created) AS ts, COUNT(*) AS n FROM messages m "
                        "JOIN conversations c ON c.id=m.conv_id WHERE m.created>=? AND m.created<? GROUP BY c.id", (t0, t1)):
            ev.append({"ts": c["ts"], "kind": "chat", "text": f"Konverzace „{c['title'] or 'bez názvu'}“ ({c['n']} zpráv)"
                       + (f" · projekt {c['folder']}" if c["folder"] else ""), "ref": c["id"]})
        for t in _safe(db, "SELECT id, goal, status, created FROM tasks WHERE created>=? AND created<?", (t0, t1)):
            ev.append({"ts": t["created"], "kind": "mission", "text": f"Mise „{t['goal'][:80]}“ – {t['status']}", "ref": t["id"]})
        for d in _safe(db, "SELECT COUNT(*) AS n, MIN(ts) AS ts, SUM(LENGTH(text)) AS chars FROM dictations WHERE ts>=? AND ts<?", (t0, t1)):
            if d["n"]:
                ev.append({"ts": d["ts"], "kind": "dictation", "text": f"Diktování: {d['n']}× (asi {round((d['chars'] or 0) / 6)} slov)", "ref": ""})
        for n in _safe(db, "SELECT id, title, created, seconds FROM notes WHERE created>=? AND created<?", (t0, t1)):
            ev.append({"ts": n["created"], "kind": "call", "text": f"Nahraný hovor „{n['title']}“ ({round((n['seconds'] or 0) / 60)} min)", "ref": n["id"]})
        for f in self.rt.db.all("SELECT id, text, created FROM facts WHERE created>=? AND created<?", (t0, t1)):
            ev.append({"ts": f["created"], "kind": "fact", "text": f"Zapamatováno: {f['text'][:100]}", "ref": str(f["id"])})
        apps = _safe(db, "SELECT app, seconds FROM app_usage WHERE day=? ORDER BY seconds DESC LIMIT 3", (day.isoformat(),))
        if apps:
            ev.append({"ts": t0 + 86399 if day == dt.date.today() else t1 - 1, "kind": "apps",
                       "text": "Nejvíc času: " + ", ".join(f"{a['app']} {round(a['seconds'] / 60)} min" for a in apps), "ref": ""})
        return sorted(ev, key=lambda e: e["ts"])

    # ------------------------------------------------------------------------------------------ search
    def _last(self, key: str) -> float:
        r = self.rt.db.one("SELECT v FROM kv WHERE k=?", (f"idx_{key}",))
        return float(r["v"]) if r else 0.0

    def _mark(self, key: str, ts: float) -> None:
        self.rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (f"idx_{key}", str(ts)))

    def refresh_index(self) -> int:
        """Incremental: only what is new since the last refresh; facts (small, editable) are re-added in full."""
        if not self.fts:
            return 0
        db, n = self.rt.db, 0

        def add(kind: str, ref: str, title: str, body: str, ts: float) -> None:
            nonlocal n
            db.exec("INSERT INTO search_idx(kind, ref, title, body, ts) VALUES (?,?,?,?,?)", (kind, ref, title, body[:20000], ts))
            n += 1

        last = self._last("msg")
        rows = db.all("SELECT m.id, m.content, m.created, m.role, c.title FROM messages m LEFT JOIN conversations c ON c.id=m.conv_id "
                      "WHERE m.created>? AND m.role IN ('user','assistant') ORDER BY m.created LIMIT 5000", (last,))
        for r in rows:
            add("chat", r["id"], r["title"] or "Konverzace", r["content"] or "", r["created"])
        if rows:
            self._mark("msg", rows[-1]["created"])
        db.exec("DELETE FROM search_idx WHERE kind='fact'")
        for f in db.all("SELECT id, text, created, category FROM facts"):
            add("fact", str(f["id"]), f"Paměť · {f['category'] or 'fakt'}", f["text"], f["created"])
        for kind, sql, key in (
            ("dictation", "SELECT id, text AS body, ts, '' AS title FROM dictations WHERE ts>? ORDER BY ts LIMIT 5000", "dict"),
            ("call", "SELECT id, COALESCE(summary,'') || ' ' || COALESCE(transcript,'') AS body, created AS ts, title FROM notes WHERE created>? ORDER BY created LIMIT 2000", "note"),
            ("mission", "SELECT id, COALESCE(summary,'') AS body, created AS ts, goal AS title FROM tasks WHERE created>? ORDER BY created LIMIT 5000", "task"),
        ):
            rows = _safe(db, sql, (self._last(key),))
            for r in rows:
                add(kind, str(r["id"]), r["title"] or kind, r["body"] or "", r["ts"])
            if rows:
                self._mark(key, rows[-1]["ts"])
        return n

    def search(self, query: str, limit: int = 20, kinds: set[str] | None = None) -> list[dict]:
        """Full text (any word form prefix, no diacritics needed), newest relevant first; plus meaning-based hits when a
        local embedding model is available (see semantic())."""
        self.refresh_index()
        words = re.findall(r"\w{2,}", norm(query))
        if not words:
            return []
        if self.fts:
            match = " ".join(f'"{stem(w)}"*' for w in words)
            rows = self.rt.db.all("SELECT kind, ref, title, snippet(search_idx, 3, '[', ']', '…', 12) AS snip, ts, bm25(search_idx) AS score "
                                  "FROM search_idx WHERE search_idx MATCH ? ORDER BY score LIMIT ?", (match, limit * 3))
        else:
            rows = [{"kind": "chat", "ref": r["id"], "title": "Konverzace", "snip": r["content"][:160], "ts": r["created"], "score": 0}
                    for r in self.rt.db.all("SELECT id, content, created FROM messages WHERE content LIKE ? LIMIT ?", (f"%{query}%", limit))]
        out, seen = [], set()
        for r in rows:
            if kinds and r["kind"] not in kinds:
                continue
            if r["kind"] == "chat" and not self.rt.db.one("SELECT 1 FROM messages WHERE id=?", (r["ref"],)):
                continue   # deleted since it was indexed
            key = (r["kind"], r["ref"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"kind": r["kind"], "ref": r["ref"], "title": r["title"], "snippet": r["snip"], "ts": r["ts"]})
            if len(out) >= limit:
                break
        return out

    async def semantic(self, query: str, limit: int = 10) -> dict:
        """OMEGA 038 by meaning: cosine similarity with a LOCAL embedding model (Ollama). Only models the user already
        installed are used – JARVIS never downloads one by itself."""
        model = await self.embed_model()
        if not model:
            return {"available": False, "hits": []}
        import numpy as np

        self.refresh_index()
        db = self.rt.db
        todo = db.all("SELECT s.kind, s.ref, s.title, s.body FROM search_idx s LEFT JOIN search_emb e ON e.kind=s.kind AND e.ref=s.ref AND e.model=? "
                      "WHERE e.ref IS NULL LIMIT 400", (model,))
        for i in range(0, len(todo), 32):
            batch = todo[i:i + 32]
            vecs = await self._embed(model, [f"{r['title']}\n{r['body'][:2000]}" for r in batch])
            for r, v in zip(batch, vecs):
                db.exec("INSERT OR REPLACE INTO search_emb VALUES (?,?,?,?)", (r["kind"], r["ref"], model, np.asarray(v, dtype=np.float32).tobytes()))
        q = np.asarray((await self._embed(model, [query]))[0], dtype=np.float32)
        rows = db.all("SELECT e.kind, e.ref, e.vec, s.title, s.body, s.ts FROM search_emb e JOIN search_idx s ON s.kind=e.kind AND s.ref=e.ref WHERE e.model=?", (model,))
        if not rows:
            return {"available": True, "model": model, "hits": []}
        m = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
        sims = m @ q / (np.linalg.norm(m, axis=1) * (np.linalg.norm(q) or 1) + 1e-9)
        order = np.argsort(-sims)[:limit]
        return {"available": True, "model": model, "hits": [
            {"kind": rows[i]["kind"], "ref": rows[i]["ref"], "title": rows[i]["title"], "snippet": rows[i]["body"][:160],
             "ts": rows[i]["ts"], "score": round(float(sims[i]), 3)} for i in order if sims[i] > 0.3]}

    async def embed_model(self) -> str:
        want = getattr(self.rt.cfg.memory, "embed_model", "") or ""
        try:
            async with self.rt.http() as c:
                r = await c.get(f"{self.rt.local.base}/api/tags", timeout=3)
            names = [m["name"] for m in r.json().get("models", [])]
        except Exception:  # noqa: BLE001 – Ollama not running → full-text only
            return ""
        if want:
            return want if want in names or f"{want}:latest" in names else ""
        return next((n for n in names if re.search(r"embed|bge|e5|minilm|gte", n, re.I)), "")

    async def _embed(self, model: str, texts: list[str]) -> list[list[float]]:
        async with self.rt.http() as c:
            r = await c.post(f"{self.rt.local.base}/api/embed", json={"model": model, "input": texts}, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"]

    def export(self) -> dict:
        return {"facts": self.facts(), "projects": self.projects() + self.projects(archived=True),
                "conflicts": self.open_conflicts(), "current_project": self.current_project()}


def _safe(db, sql: str, args: tuple) -> list[dict]:
    try:
        return db.all(sql, args)
    except Exception:  # noqa: BLE001 – the table belongs to an optional module that has not created it yet
        return []


def describe(e: dict) -> str:
    return f"{dt.datetime.fromtimestamp(e['ts']):%H:%M} {e['text']}"
