"""SQLite memory: conversations, messages, facts (+ tables used by attachments/scheduler)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL,
  folder TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conv_id TEXT, role TEXT, content TEXT,
  attachments TEXT, source TEXT, created REAL, meta TEXT);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conv_id, created);
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, conv_id TEXT, name TEXT, mime TEXT, size INTEGER,
  kind TEXT, path TEXT, text TEXT, error TEXT, created REAL);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, spec TEXT, payload TEXT, next_run REAL,
  enabled INTEGER, created REAL, title TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class DB:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute("PRAGMA journal_mode=WAL")
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(conversations)")}
            if "folder" not in cols:  # 2.0 database
                self.conn.execute("ALTER TABLE conversations ADD COLUMN folder TEXT DEFAULT ''")
                self.conn.commit()

    def exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None


def _msg(row: dict) -> dict:
    return {"id": row["id"], "conv_id": row["conv_id"], "role": row["role"], "text": row["content"],
            "attachments": json.loads(row["attachments"] or "[]"), "source": row["source"],
            "created": row["created"], "meta": json.loads(row["meta"] or "{}")}


PRIVATE = "private"   # OMEGA 041: the conversation of the private mode lives only in RAM


class Memory:
    def __init__(self, db: DB):
        self.db = db
        row = db.one("SELECT v FROM kv WHERE k='current_conv'")
        self.current_conversation = row["v"] if row else self.new_conversation()
        self._private: list[dict] = []
        self._before_private = ""

    # ---------- private mode: nothing is written to disk ----------
    @property
    def private(self) -> bool:
        return self.current_conversation == PRIVATE

    def set_private(self, on: bool) -> None:
        if on and not self.private:
            self._before_private = self.current_conversation
            self.current_conversation = PRIVATE
            self._private = []
        elif not on and self.private:
            self._private = []
            back = self._before_private
            if back and self.db.one("SELECT id FROM conversations WHERE id=?", (back,)):
                self.current_conversation = back
            else:
                self.new_conversation()

    def new_conversation(self, title: str = "Nová konverzace") -> str:
        if getattr(self, "current_conversation", "") == PRIVATE:   # a new chat in the private mode stays private
            self._private = []
            return PRIVATE
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.exec("INSERT INTO conversations (id, title, created, updated, folder) VALUES (?,?,?,?,'')",
                     (cid, title, now, now))
        self.db.exec("INSERT OR REPLACE INTO kv VALUES ('current_conv', ?)", (cid,))
        self.current_conversation = cid
        return cid

    def switch(self, conv_id: str) -> bool:
        if self.private:
            return False
        if not self.db.one("SELECT id FROM conversations WHERE id=?", (conv_id,)):
            return False
        self.current_conversation = conv_id
        self.db.exec("INSERT OR REPLACE INTO kv VALUES ('current_conv', ?)", (conv_id,))
        return True

    def add_message(self, role: str, text: str, attachments: list[str] | None = None, source: str = "",
                    meta: dict | None = None, conv_id: str | None = None) -> dict:
        cid = conv_id or self.current_conversation
        mid = uuid.uuid4().hex[:16]
        now = time.time()
        if cid == PRIVATE:
            m = {"id": mid, "conv_id": PRIVATE, "role": role, "text": text, "attachments": attachments or [],
                 "source": source, "created": now, "meta": meta or {}}
            self._private = (self._private + [m])[-200:]
            return m
        self.db.exec("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                     (mid, cid, role, text, json.dumps(attachments or []), source, now, json.dumps(meta or {})))
        conv = self.db.one("SELECT title FROM conversations WHERE id=?", (cid,))
        if role == "user" and conv and conv["title"] == "Nová konverzace" and text.strip():
            title = text.strip().splitlines()[0][:60]
            self.db.exec("UPDATE conversations SET title=?, updated=? WHERE id=?", (title, now, cid))
        else:
            self.db.exec("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
        return _msg(self.db.one("SELECT * FROM messages WHERE id=?", (mid,)))

    def recent(self, n: int = 20, conv_id: str | None = None) -> list[dict]:
        if (conv_id or self.current_conversation) == PRIVATE:
            return list(self._private[-n:])
        rows = self.db.all("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT ?",
                           (conv_id or self.current_conversation, n))
        return [_msg(r) for r in reversed(rows)]

    def history(self, conv_id: str | None = None, before: float | None = None, limit: int = 50) -> list[dict]:
        cid = conv_id or self.current_conversation
        if cid == PRIVATE:
            items = [m for m in self._private if not before or m["created"] < before]
            return items[-limit:]
        if before:
            rows = self.db.all("SELECT * FROM messages WHERE conv_id=? AND created<? ORDER BY created DESC LIMIT ?",
                               (cid, before, limit))
        else:
            rows = self.db.all("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT ?", (cid, limit))
        return [_msg(r) for r in reversed(rows)]

    def delete_last_assistant(self, conv_id: str | None = None) -> dict | None:
        """For 'regenerate': drop the last assistant message, return the last user message."""
        cid = conv_id or self.current_conversation
        if cid == PRIVATE:
            if self._private and self._private[-1]["role"] == "assistant":
                self._private.pop()
            return next((m for m in reversed(self._private) if m["role"] == "user"), None)
        last = self.db.one("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT 1", (cid,))
        if last and last["role"] == "assistant":
            self.db.exec("DELETE FROM messages WHERE id=?", (last["id"],))
        u = self.db.one("SELECT * FROM messages WHERE conv_id=? AND role='user' ORDER BY created DESC LIMIT 1", (cid,))
        return _msg(u) if u else None

    def truncate_from(self, msg_id: str) -> dict | None:
        """For editing a message: removes it and everything after it in its conversation; returns the removed one."""
        if self.private:
            i = next((i for i, m in enumerate(self._private) if m["id"] == msg_id), None)
            if i is None:
                return None
            m, self._private = self._private[i], self._private[:i]
            return m
        row = self.db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
        if not row:
            return None
        self.db.exec("DELETE FROM messages WHERE conv_id=? AND created>=?", (row["conv_id"], row["created"]))
        return _msg(row)

    def rename(self, conv_id: str, title: str) -> bool:
        title = (title or "").strip()[:120]
        return bool(title) and self.db.exec("UPDATE conversations SET title=? WHERE id=?", (title, conv_id)).rowcount > 0

    def move(self, conv_id: str, folder: str) -> bool:
        return self.db.exec("UPDATE conversations SET folder=? WHERE id=?",
                            ((folder or "").strip()[:60], conv_id)).rowcount > 0

    def export(self, include_conversations: bool = False) -> dict:
        import datetime as dt

        out: dict = {"version": 1, "exported": dt.datetime.now().isoformat(timespec="seconds"),
                     "facts": [{"text": f["text"], "created": f["created"]} for f in self.facts()]}
        if include_conversations:
            convs = []
            for c in self.db.all("SELECT * FROM conversations ORDER BY created"):
                msgs = self.db.all("SELECT role, content, created FROM messages WHERE conv_id=? ORDER BY created", (c["id"],))
                convs.append({"id": c["id"], "title": c["title"], "folder": c.get("folder") or "", "created": c["created"],
                              "messages": [{"role": m["role"], "text": m["content"], "ts": m["created"]} for m in msgs]})
            out["conversations"] = convs
        return out

    def import_data(self, data: dict, merge: bool = True) -> dict:
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("facts", []), list):
            raise ValueError("Neplatný soubor paměti")
        if not merge:
            self.db.exec("DELETE FROM facts")
        added = skipped = convs = 0
        for f in data.get("facts", []):
            text = (f.get("text") if isinstance(f, dict) else str(f) if f else "") or ""
            if not text.strip():
                continue
            if self.db.one("SELECT id FROM facts WHERE text=?", (text,)):
                skipped += 1
            else:
                self.db.exec("INSERT INTO facts(text, created) VALUES (?,?)",
                             (text, (f.get("created") if isinstance(f, dict) else None) or time.time()))
                added += 1
        for c in data.get("conversations") or []:
            cid = str(c.get("id") or uuid.uuid4().hex[:12])
            if self.db.one("SELECT id FROM conversations WHERE id=?", (cid,)):
                continue
            created = c.get("created") or time.time()
            self.db.exec("INSERT INTO conversations (id, title, created, updated, folder) VALUES (?,?,?,?,?)",
                         (cid, c.get("title") or "Importováno", created, created, c.get("folder") or ""))
            for m in c.get("messages") or []:
                self.db.exec("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                             (uuid.uuid4().hex[:16], cid, m.get("role", "user"), m.get("text", ""), "[]", "import",
                              m.get("ts") or created, "{}"))
            convs += 1
        return {"facts_added": added, "facts_skipped": skipped, "conversations_added": convs}

    def list_conversations(self, limit: int = 100) -> list[dict]:
        return self.db.all("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,))

    def delete_conversation(self, conv_id: str) -> None:
        self.db.exec("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        self.db.exec("DELETE FROM conversations WHERE id=?", (conv_id,))
        if conv_id == self.current_conversation:
            self.new_conversation()

    def search(self, q: str, limit: int = 30) -> list[dict]:
        rows = self.db.all("SELECT * FROM messages WHERE content LIKE ? ORDER BY created DESC LIMIT ?", (f"%{q}%", limit))
        return [_msg(r) for r in rows]

    def facts(self) -> list[dict]:
        return self.db.all("SELECT id, text, created FROM facts ORDER BY id")

    def remember(self, text: str) -> None:
        if self.private:
            return
        if not self.db.one("SELECT id FROM facts WHERE text=?", (text,)):
            self.db.exec("INSERT INTO facts(text, created) VALUES (?,?)", (text, time.time()))

    def forget(self, text: str) -> int:
        return self.db.exec("DELETE FROM facts WHERE text LIKE ?", (f"%{text}%",)).rowcount

    def update_fact(self, fid: int, text: str) -> None:
        self.db.exec("UPDATE facts SET text=? WHERE id=?", (text, fid))

    def delete_fact(self, fid: int) -> None:
        self.db.exec("DELETE FROM facts WHERE id=?", (fid,))

    def wipe(self) -> None:
        for t in ("messages", "conversations", "facts"):
            self.db.exec(f"DELETE FROM {t}")
        self.new_conversation()
