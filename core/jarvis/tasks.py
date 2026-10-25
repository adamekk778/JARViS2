"""Tasks = missions (spec §4, OMEGA §4.5): every agent reply that uses tools becomes a task with a plan, steps and an
action log (the audit trail). A mission may also carry acceptance criteria, artifacts (files it produced, with their
SHA-256) and evidence (what was measured or checked, from which source, when).

States: running → (paused | waiting) → verifying → done / failed / cancelled; a restart turns anything unfinished into
"interrupted" (it can be run again with Zopakovat). Stored in SQLite next to the conversation memory; the UI follows
`task_update` events.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from .redact import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, conv_id TEXT, goal TEXT, status TEXT, created REAL,
  finished REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS task_steps (task_id TEXT, idx INT, title TEXT, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS task_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts REAL, tool TEXT,
  args TEXT, ok INT, summary TEXT, ms INT);
CREATE TABLE IF NOT EXISTS task_artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts REAL, title TEXT,
  path TEXT, sha256 TEXT, bytes INT);
CREATE TABLE IF NOT EXISTS task_evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, ts REAL, source TEXT,
  claim TEXT, value TEXT, ok INT);
"""
UNFINISHED = ("running", "paused", "waiting", "verifying", "starting")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
THROTTLE_S = 0.25  # task_update at most 4× per second for action-only changes


class TaskManager:
    def __init__(self, rt: Any):
        self.rt = rt
        self.db = rt.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.db.conn.execute("PRAGMA table_info(tasks)")}
            if "criteria" not in cols:     # 3.6 missions: acceptance criteria
                self.db.conn.execute("ALTER TABLE tasks ADD COLUMN criteria TEXT DEFAULT '[]'")
            for col, typ in (("deadline", "REAL"), ("spec", "TEXT"), ("not_before", "REAL")):   # 3.7 queue
                if col not in cols:
                    self.db.conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ}")
        self._id: str | None = None
        self._running = asyncio.Event()
        self._running.set()
        self._current_action = ""
        self._last_pub = 0.0
        self._pending: asyncio.TimerHandle | None = None
        self._started = time.time()
        self.recover()

    def recover(self) -> int:
        """After a crash or restart nothing is "running" any more: mark it interrupted (it can be repeated)."""
        return self.db.exec(
            f"UPDATE tasks SET status='interrupted', finished=?, summary=CASE WHEN summary='' OR summary IS NULL "
            f"THEN 'Přerušeno ukončením nebo restartem JARVISe. Spusť znovu tlačítkem Zopakovat.' ELSE summary END "
            f"WHERE status IN ({','.join('?' * len(UNFINISHED))})", (time.time(), *UNFINISHED)).rowcount

    # ---------- lifecycle ----------
    @property
    def current(self) -> dict | None:
        return self.get(self._id) if self._id else None

    def begin(self, goal: str, conv_id: str, task_id: str | None = None) -> str:
        """A new mission – or, with `task_id`, a queued / interrupted one that starts (again) now."""
        self._current_action = ""
        self._running.set()
        self._started = time.time()
        if task_id and self.db.one("SELECT id FROM tasks WHERE id=?", (task_id,)):
            self._id = task_id
            self.db.exec("UPDATE tasks SET status='running', finished=NULL WHERE id=?", (task_id,))
        else:
            self._id = uuid.uuid4().hex[:12]
            self.db.exec("INSERT INTO tasks (id, conv_id, goal, status, created, finished, summary) VALUES (?,?,?,?,?,?,?)",
                         (self._id, conv_id, goal[:500], "running", time.time(), None, ""))
        self._publish(force=True)
        return self._id

    # ---------- 3.7 queue, deadlines, budget ----------
    def enqueue(self, goal: str, steps: list[dict] | None = None, deadline: float | None = None,
                not_before: float | None = None, conv_id: str = "") -> str:
        """OMEGA 211 / 220: a mission waiting its turn (optionally not before a time, with a deadline)."""
        tid = uuid.uuid4().hex[:12]
        self.db.exec("INSERT INTO tasks (id, conv_id, goal, status, created, finished, summary, deadline, spec, not_before) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (tid, conv_id, goal[:500], "queued", time.time(), None, "", deadline,
                      json.dumps(steps, ensure_ascii=False) if steps else None, not_before))
        self.rt.bus.publish("task_update", task=self.get(tid))
        return tid

    def next_queued(self, now: float | None = None) -> dict | None:
        now = now or time.time()
        row = self.db.one("SELECT id FROM tasks WHERE status='queued' AND (not_before IS NULL OR not_before<=?) "
                          "ORDER BY COALESCE(deadline, 9e18), created LIMIT 1", (now,))
        return self.get(row["id"]) if row else None

    def queue(self) -> list[dict]:
        return self.db.all("SELECT id, goal, created, deadline, not_before FROM tasks WHERE status='queued' "
                           "ORDER BY COALESCE(deadline, 9e18), created")

    def set_spec(self, steps: list[dict]) -> None:
        """A structured mission remembers its steps, so an interrupted run can continue where it stopped."""
        if self._id:
            self.db.exec("UPDATE tasks SET spec=? WHERE id=?", (json.dumps(steps, ensure_ascii=False), self._id))

    def done_steps(self, task_id: str) -> set[int]:
        return {r["idx"] for r in self.db.all("SELECT idx FROM task_steps WHERE task_id=? AND status='done'", (task_id,))}

    def over_budget(self, limits: Any) -> str:
        """OMEGA 221: "" or why the running mission must stop (too many actions / too long)."""
        if not self._id or limits is None:
            return ""
        n = self.db.one("SELECT COUNT(*) n FROM task_actions WHERE task_id=?", (self._id,))["n"]
        if limits.mission_max_actions and n >= limits.mission_max_actions:
            return f"Rozpočet mise vyčerpán: {n} akcí (limit {limits.mission_max_actions})."
        mins = (time.time() - getattr(self, "_started", time.time())) / 60
        if limits.mission_max_minutes and mins >= limits.mission_max_minutes:
            return f"Rozpočet mise vyčerpán: běží {mins:.0f} min (limit {limits.mission_max_minutes})."
        return ""

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

    def set_step_states(self, titles: list[str], states: list[str], notes: list[str] | None = None) -> None:
        """Steps with their own states (a mission whose steps run in waves, some at the same time)."""
        if not self._id:
            return
        notes = notes or [""] * len(titles)
        self.db.exec("DELETE FROM task_steps WHERE task_id=?", (self._id,))
        for i, (t, st, n) in enumerate(zip(titles, states, notes)):
            self.db.exec("INSERT INTO task_steps VALUES (?,?,?,?,?)", (self._id, i, str(t)[:200], st, str(n)[:300]))
        self._publish(force=True)

    def log_action(self, tool: str, args: dict, ok: bool, summary: str, ms: int) -> None:
        if not self._id:
            return
        a = redact(json.dumps(args, ensure_ascii=False, default=str))[:500]
        self.db.exec("INSERT INTO task_actions (task_id, ts, tool, args, ok, summary, ms) VALUES (?,?,?,?,?,?,?)",
                     (self._id, time.time(), tool, a, int(bool(ok)), redact(summary or "")[:500], int(ms)))
        self._publish()

    # ---------- mission: criteria, artifacts, evidence ----------
    def set_criteria(self, criteria: list[str]) -> None:
        if self._id:
            self.db.exec("UPDATE tasks SET criteria=? WHERE id=?",
                         (json.dumps([str(c)[:200] for c in criteria][:20], ensure_ascii=False), self._id))
            self._publish(force=True)

    def add_artifact(self, path: Path, title: str = "") -> dict:
        """A file the mission produced; its SHA-256 lets anyone check it later."""
        path = Path(path)
        art = {"title": title or path.name, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        if self._id:
            self.db.exec("INSERT INTO task_artifacts (task_id, ts, title, path, sha256, bytes) VALUES (?,?,?,?,?,?)",
                         (self._id, time.time(), art["title"][:200], art["path"], art["sha256"], art["bytes"]))
            self._publish()
        return art

    def add_evidence(self, source: str, claim: str, value: Any = "", ok: bool = True) -> None:
        """What was measured / checked: the source (tool, command, file), the claim, the value, and whether it holds."""
        if self._id:
            self.db.exec("INSERT INTO task_evidence (task_id, ts, source, claim, value, ok) VALUES (?,?,?,?,?,?)",
                         (self._id, time.time(), source[:200], redact(claim)[:300], redact(str(value))[:500], int(bool(ok))))
            self._publish()

    def set_verifying(self) -> None:
        if self._id:
            self._set_status("verifying")

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
        arts = self.db.all("SELECT ts, title, path, sha256, bytes FROM task_artifacts WHERE task_id=? ORDER BY id", (task_id,))
        ev = self.db.all("SELECT ts, source, claim, value, ok FROM task_evidence WHERE task_id=? ORDER BY id", (task_id,))
        try:
            criteria = json.loads(row.get("criteria") or "[]")
        except ValueError:
            criteria = []
        try:
            spec = json.loads(row.get("spec") or "null")
        except ValueError:
            spec = None
        return {**row, "criteria": criteria, "spec": spec, "steps": steps, "actions": actions, "artifacts": arts, "evidence": ev,
                "total": len(steps),
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
        self.db.exec("DELETE FROM task_artifacts WHERE task_id != ?", (keep,))
        self.db.exec("DELETE FROM task_evidence WHERE task_id != ?", (keep,))
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
