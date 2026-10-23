"""SQLite memory: conversations, messages, facts (+ tables used by attachments/scheduler)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
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


class Memory:
    def __init__(self, db: DB):
        self.db = db
        row = db.one("SELECT v FROM kv WHERE k='current_conv'")
        self.current_conversation = row["v"] if row else self.new_conversation()

    def new_conversation(self, title: str = "Nová konverzace") -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.exec("INSERT INTO conversations VALUES (?,?,?,?)", (cid, title, now, now))
        self.db.exec("INSERT OR REPLACE INTO kv VALUES ('current_conv', ?)", (cid,))
        self.current_conversation = cid
        return cid

    def switch(self, conv_id: str) -> bool:
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
        rows = self.db.all("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT ?",
                           (conv_id or self.current_conversation, n))
        return [_msg(r) for r in reversed(rows)]

    def history(self, conv_id: str | None = None, before: float | None = None, limit: int = 50) -> list[dict]:
        cid = conv_id or self.current_conversation
        if before:
            rows = self.db.all("SELECT * FROM messages WHERE conv_id=? AND created<? ORDER BY created DESC LIMIT ?",
                               (cid, before, limit))
        else:
            rows = self.db.all("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT ?", (cid, limit))
        return [_msg(r) for r in reversed(rows)]

    def delete_last_assistant(self, conv_id: str | None = None) -> dict | None:
        """For 'regenerate': drop the last assistant message, return the last user message."""
        cid = conv_id or self.current_conversation
        last = self.db.one("SELECT * FROM messages WHERE conv_id=? ORDER BY created DESC LIMIT 1", (cid,))
        if last and last["role"] == "assistant":
            self.db.exec("DELETE FROM messages WHERE id=?", (last["id"],))
        u = self.db.one("SELECT * FROM messages WHERE conv_id=? AND role='user' ORDER BY created DESC LIMIT 1", (cid,))
        return _msg(u) if u else None

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
