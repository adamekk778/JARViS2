"""Spec 2026-11-20 §5.1: what JARVIS saw on the internet, kept on this PC – news, AI digests, everything it searched or
read, pages from your browser, videos and topic notebooks. Searchable in milliseconds without the internet (FTS5,
diacritics-insensitive, Czech word endings via knowledge.stem).

Rules: nothing is stored in the private mode; every kind has its own retention and the whole store has a size cap;
everything can be seen, exported and forgotten (privacy inventory, "Zapomenout vše z internetu").
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..knowledge import norm, stem
from ..tools.select import _STOP

KINDS = ("news", "digest", "search", "read", "browser", "wiki", "video", "notes")
EXTRA_STOP = {"kdo", "kde", "kdy", "proc", "jaky", "jaka", "jake", "ktery", "byl", "byla", "bylo", "ten", "tom", "tem"}
TRACKING = re.compile(r"^(utm_\w*|fbclid|gclid|dclid|msclkid|yclid|igshid|mc_cid|mc_eid|_hsenc|_hsmi|ref_src|oc)$", re.I)
MAX_TEXT = 15000
NEWS_DUP_S = 3 * 86400        # the same headline from another source within 3 days = the same news
# when the store is over its cap: what goes first (oldest first within each group)
CAP_ORDER = (("news",), ("browser",), ("video",), ("search", "read", "wiki"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS web_docs (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, title TEXT, kind TEXT,
  topic TEXT DEFAULT '', source TEXT DEFAULT '', published REAL, fetched REAL, visited REAL, snippet TEXT DEFAULT '',
  text TEXT DEFAULT '', hash TEXT);
CREATE INDEX IF NOT EXISTS web_docs_kind ON web_docs(kind, fetched);
CREATE INDEX IF NOT EXISTS web_docs_hash ON web_docs(hash);
CREATE VIRTUAL TABLE IF NOT EXISTS web_idx USING fts5(title, body, tokenize='unicode61 remove_diacritics 2');
"""


@dataclass
class Doc:
    url: str
    title: str
    kind: str
    text: str = ""
    snippet: str = ""
    topic: str = ""
    source: str = ""
    published: float | None = None
    visited: float | None = None


def normalize_url(url: str) -> str:
    """No tracking parameters (utm_*, fbclid…), no #fragment, a lowercase scheme and host."""
    url = (url or "").strip()
    if url.startswith("jarvis:"):
        return url
    p = urlparse(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)])
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, p.params, query, ""))


def domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


_domain = domain     # forget() has a parameter called "domain"


def query_stems(text: str) -> list[str]:
    """The words of a question that matter, as stems: no accents, no small words, Czech endings cut."""
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", norm(text or "")):
        if len(w) < 3 or w in _STOP or w in EXTRA_STOP:
            continue
        s = stem(w)
        if s not in out:
            out.append(s)
    return out


def _hash(title: str) -> str:
    return hashlib.sha1(norm(title).encode("utf-8")).hexdigest()


class WebStore:
    def __init__(self, rt):
        self.rt = rt
        self.db = rt.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)

    # ------------------------------------------------------------------------------------------ adding
    def _private(self) -> bool:
        mem = getattr(self.rt, "memory", None)
        return bool(mem is not None and mem.private)

    def _index(self, did: int, title: str, snippet: str, text: str) -> None:
        self.db.exec("DELETE FROM web_idx WHERE rowid=?", (did,))
        self.db.exec("INSERT INTO web_idx (rowid, title, body) VALUES (?,?,?)", (did, title, f"{snippet}\n{text}"))

    def _add(self, doc: Doc) -> tuple[int | None, bool]:
        if self._private():
            return None, False
        if doc.kind not in KINDS:
            raise ValueError(f"Neznámý druh: {doc.kind}")
        url = normalize_url(doc.url)
        title = (doc.title or "").strip()[:300] or url[:300]
        snippet, text = (doc.snippet or "").strip()[:600], (doc.text or "").strip()[:MAX_TEXT]
        now = time.time()
        old = self.db.one("SELECT id, text, snippet FROM web_docs WHERE url=?", (url,))
        if old:
            if len(text) > len(old["text"] or "") or (snippet and not old["snippet"]):
                text, snippet = max(text, old["text"] or "", key=len), snippet or old["snippet"] or ""
                self.db.exec("UPDATE web_docs SET text=?, snippet=? WHERE id=?", (text, snippet, old["id"]))
                self._index(old["id"], title, snippet, text)
            if doc.visited:
                self.db.exec("UPDATE web_docs SET visited=? WHERE id=?", (doc.visited, old["id"]))
            return old["id"], False
        h = _hash(title)
        if doc.kind == "news":
            dup = self.db.one("SELECT id FROM web_docs WHERE hash=? AND kind='news' AND fetched>=?", (h, now - NEWS_DUP_S))
            if dup:
                return dup["id"], False
        cur = self.db.exec("INSERT INTO web_docs (url, title, kind, topic, source, published, fetched, visited, snippet, text, hash) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (url, title, doc.kind, doc.topic or "", doc.source or "", doc.published, now, doc.visited,
                            snippet, text, h))
        did = int(cur.lastrowid)
        self._index(did, title, snippet, text)
        return did, True

    def add(self, doc: Doc) -> int | None:
        return self._add(doc)[0]

    def add_many(self, docs: list[Doc]) -> list[int]:
        out = []
        for d in docs:
            did, new = self._add(d)
            if new and did is not None:
                out.append(did)
        return out

    # ------------------------------------------------------------------------------------------ reading
    def get(self, doc_id: int) -> dict | None:
        return self.db.one("SELECT * FROM web_docs WHERE id=?", (doc_id,))

    def since(self, ts: float, kinds: tuple[str, ...] = ("news",)) -> list[dict]:
        marks = ",".join("?" * len(kinds))
        return self.db.all(f"SELECT * FROM web_docs WHERE fetched>? AND kind IN ({marks}) ORDER BY fetched, id", (ts, *kinds))

    def search(self, query: str, limit: int = 8, kinds: tuple[str, ...] = (), max_age_days: float | None = None) -> list[dict]:
        stems = query_stems(query)
        if not stems:
            return []
        sql = ("SELECT d.*, bm25(web_idx) AS rank FROM web_idx JOIN web_docs d ON d.id = web_idx.rowid "
               "WHERE web_idx MATCH ?")
        args: list = [" OR ".join(f'"{s}"*' for s in stems)]
        if kinds:
            sql += f" AND d.kind IN ({','.join('?' * len(kinds))})"
            args += list(kinds)
        if max_age_days:
            sql += " AND d.fetched >= ?"
            args.append(time.time() - max_age_days * 86400)
        sql += " ORDER BY rank LIMIT ?"
        args.append(max(limit * 4, 20))
        rows = self.db.all(sql, tuple(args))
        for r in rows:
            hay = norm(f"{r['title']} {r['snippet']} {r['text']}")
            r["matched"] = sum(1 for s in stems if s in hay)
            r["score"] = -float(r.pop("rank"))
        rows.sort(key=lambda r: (-r["matched"], -r["score"]))
        return rows[:limit]

    # ------------------------------------------------------------------------------------------ digests and notes
    def add_digest(self, topic: str, text: str) -> int | None:
        key = norm(topic) or "vse"
        return self.add(Doc(url=f"jarvis:digest/{key}/{int(time.time() * 1000)}", kind="digest", topic=topic or "",
                            title="Přehled zpráv" + (f" – {topic}" if topic else ""), text=text, source="JARVIS"))

    def latest_digest(self, topic: str = "") -> dict | None:
        return self.db.one("SELECT * FROM web_docs WHERE kind='digest' AND topic=? ORDER BY fetched DESC, id DESC LIMIT 1",
                           (topic or "",))

    def set_notes(self, topic: str, text: str) -> int | None:
        url = f"jarvis:notes/{norm(topic)}"
        old = self.db.one("SELECT id FROM web_docs WHERE url=?", (url,))
        if old is None:
            return self.add(Doc(url=url, kind="notes", topic=topic, title=f"Sešit: {topic}", text=text, source="JARVIS"))
        if self._private():
            return None
        title = f"Sešit: {topic}"
        self.db.exec("UPDATE web_docs SET text=?, title=?, fetched=? WHERE id=?", (text[:MAX_TEXT], title, time.time(), old["id"]))
        self._index(old["id"], title, "", text[:MAX_TEXT])
        return old["id"]

    def notes(self, topic: str) -> dict | None:
        return self.db.one("SELECT * FROM web_docs WHERE url=?", (f"jarvis:notes/{norm(topic)}",))

    # ------------------------------------------------------------------------------------------ overview and forgetting
    def _bytes(self) -> int:
        r = self.db.one("SELECT COALESCE(SUM(LENGTH(title) + LENGTH(snippet) + LENGTH(text)), 0) AS b FROM web_docs")
        return int(r["b"] if r else 0)

    def stats(self) -> dict:
        by_kind = {r["kind"]: r["n"] for r in self.db.all("SELECT kind, COUNT(*) AS n FROM web_docs GROUP BY kind")}
        row = self.db.one("SELECT v FROM kv WHERE k='webknow_last_study'")
        dig = self.db.one("SELECT MAX(fetched) AS t FROM web_docs WHERE kind='digest'")
        return {"by_kind": by_kind, "bytes": self._bytes(), "last_study": float(row["v"]) if row else 0.0,
                "last_digest": float(dig["t"] or 0) if dig else 0.0}

    def _delete(self, ids: list[int]) -> int:
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            marks = ",".join("?" * len(chunk))
            self.db.exec(f"DELETE FROM web_idx WHERE rowid IN ({marks})", tuple(chunk))
            self.db.exec(f"DELETE FROM web_docs WHERE id IN ({marks})", tuple(chunk))
            if self.db.one("SELECT 1 FROM sqlite_master WHERE name='web_emb'"):
                self.db.exec(f"DELETE FROM web_emb WHERE doc IN ({marks})", tuple(chunk))
        return len(ids)

    def forget(self, domain: str = "", everything: bool = False) -> int:
        if everything:
            return self._delete([r["id"] for r in self.db.all("SELECT id FROM web_docs")])
        d = _domain(domain if "/" in domain else f"https://{domain}") if domain else ""
        if not d:
            return 0
        rows = self.db.all("SELECT id, url FROM web_docs WHERE url LIKE ?", (f"%{d}%",))
        ids = [r["id"] for r in rows if (h := _domain(r["url"])) == d or h.endswith("." + d)]
        return self._delete(ids)

    def prune(self, now: float | None = None, cap_bytes: int | None = None) -> int:
        now = now or time.time()
        c = self.rt.cfg.webknow
        ages = {"news": c.keep_news_days, "search": c.keep_search_days, "read": c.keep_search_days,
                "wiki": c.keep_search_days, "browser": c.keep_browser_days, "video": c.keep_browser_days,
                "digest": c.keep_digest_days}
        ids: list[int] = []
        for kind, days in ages.items():
            ids += [r["id"] for r in self.db.all("SELECT id FROM web_docs WHERE kind=? AND fetched<?", (kind, now - days * 86400))]
        n = self._delete(ids)
        cap = cap_bytes if cap_bytes is not None else c.max_mb * 2 ** 20
        for group in CAP_ORDER:
            marks = ",".join("?" * len(group))
            while self._bytes() > cap:
                batch = [r["id"] for r in self.db.all(f"SELECT id FROM web_docs WHERE kind IN ({marks}) ORDER BY fetched, id LIMIT 20", group)]
                if not batch:
                    break
                n += self._delete(batch)
        return n
