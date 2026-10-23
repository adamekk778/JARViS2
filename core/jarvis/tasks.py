"""Tasks (spec §4): every agent reply that uses tools becomes a task with a plan, steps and an action log.

Stored in SQLite next to (but separate from) the conversation memory. The UI follows `task_update` events.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Literal

from .redact import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, conv_id TEXT, goal TEXT, status TEXT, created REAL,
  finished REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS task_steps (task_id TEXT, idx INT, title TEXT, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS task_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts REAL, tool TEXT,
  args TEXT, ok INT, summary TEXT, ms INT);
"""
THROTTLE_S = 0.25  # task_update at most 4× per second for action-only changes


class TaskManager:
    def __init__(self, rt: Any):
        self.rt = rt
        self.db = rt.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
        self._id: str | None = None
        self._running = asyncio.Event()
        self._running.set()
        self._current_action = ""
        self._last_pub = 0.0
        self._pending: asyncio.TimerHandle | None = None

    # ---------- lifecycle ----------
    @property
    def current(self) -> dict | None:
        return self.get(self._id) if self._id else None

    def begin(self, goal: str, conv_id: str) -> str:
        self._id = uuid.uuid4().hex[:12]
        self._current_action = ""
        self._running.set()
        self.db.exec("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
                     (self._id, conv_id, goal[:500], "running", time.time(), None, ""))
        self._publish(force=True)
        return self._id

    def set_plan(self, steps: list[str], current: int = 0, note: str = "") -> None:
        if not self._id:
            return
        steps = [str(s)[:200] for s in steps if str(s).strip()][:30]
        current = max(0, min(int(current), len(steps)))
        self.db.exec("DELETE FROM task_steps WHERE task_id=?", (self._id,))
        for i, title in enumerate(steps):
            status = "done" if i < current else "running" if i == current else "pending"
            self.db.exec("INSERT INTO task_steps VALUES (?,?,?,?,?)",
                         (self._id, i, title, status, note[:300] if i == current else ""))
        self._publish(force=True)

    def log_action(self, tool: str, args: dict, ok: bool, summary: str, ms: int) -> None:
        if not self._id:
            return
        a = redact(json.dumps(args, ensure_ascii=False, default=str))[:500]
        self.db.exec("INSERT INTO task_actions (task_id, ts, tool, args, ok, summary, ms) VALUES (?,?,?,?,?,?,?)",
                     (self._id, time.time(), tool, a, int(bool(ok)), redact(summary or "")[:500], int(ms)))
        self._publish()

    def action_started(self, label: str) -> None:
        self._current_action = label
        self._publish()

    def finish(self, status: Literal["done", "failed", "cancelled"], summary: str = "") -> None:
        if not self._id:
            return
        if status == "done":
            self.db.exec("UPDATE task_steps SET status='done' WHERE task_id=? AND status IN ('pending','running')", (self._id,))
        else:
            self.db.exec("UPDATE task_steps SET status=? WHERE task_id=? AND status='running'",
                         ("failed" if status == "failed" else "skipped", self._id))
        self.db.exec("UPDATE tasks SET status=?, finished=?, summary=? WHERE id=?",
                     (status, time.time(), redact(summary)[:500], self._id))
        self._current_action = ""
        self._publish(force=True)
        self._id = None
        self._running.set()

    # ---------- pause / resume ----------
    def pause(self) -> bool:
        if not self._id or not self._running.is_set():
            return False
        self._running.clear()
        self._set_status("paused")
        return True

    def resume(self) -> bool:
        if not self._id or self._running.is_set():
            return False
        self._running.set()
        self._set_status("running")
        return True

    async def checkpoint(self) -> None:
        """Called by the agent between steps; blocks while the task is paused (cancellable)."""
        await self._running.wait()

    def set_waiting(self, waiting: bool) -> None:
        if self._id and self._running.is_set():
            self._set_status("waiting" if waiting else "running")

    def _set_status(self, status: str) -> None:
        self.db.exec("UPDATE tasks SET status=? WHERE id=?", (status, self._id))
        self._publish(force=True)

    # ---------- queries ----------
    def get(self, task_id: str | None) -> dict | None:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,)) if task_id else None
        if not row:
            return None
        steps = self.db.all("SELECT idx, title, status, note FROM task_steps WHERE task_id=? ORDER BY idx", (task_id,))
        actions = self.db.all("SELECT ts, tool, args, ok, summary, ms FROM task_actions WHERE task_id=? ORDER BY id",
                              (task_id,))
        return {**row, "steps": steps, "actions": actions, "total": len(steps),
                "done": sum(s["status"] == "done" for s in steps),
                "current_action": self._current_action if task_id == self._id else ""}

    def list(self, limit: int = 50, q: str = "", status: str = "") -> list[dict]:
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        if q:
            sql += " AND lower(goal) LIKE ?"
            args.append(f"%{q.lower()}%")
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY created DESC LIMIT ?"
        args.append(int(limit))
        return self.db.all(sql, tuple(args))

    def clear(self) -> int:
        keep = self._id or ""
        n = self.db.exec("DELETE FROM tasks WHERE id != ?", (keep,)).rowcount
        self.db.exec("DELETE FROM task_steps WHERE task_id != ?", (keep,))
        self.db.exec("DELETE FROM task_actions WHERE task_id != ?", (keep,))
        return n

    # ---------- events ----------
    def _publish(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pub < THROTTLE_S:
            if self._pending is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                self._pending = loop.call_later(THROTTLE_S, self._flush, self._id)
            return
        self._emit(self._id)

    def _flush(self, task_id: str | None) -> None:
        self._pending = None
        self._emit(task_id)

    def _emit(self, task_id: str | None) -> None:
        t = self.get(task_id)
        if t:
            self._last_pub = time.monotonic()
            self.rt.bus.publish("task_update", task=t)
