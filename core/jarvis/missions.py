"""OMEGA §4.5 Mission engine 2: the queue (211), deadlines (220), the shared workspace (215), resume (216 / 225) and
the audit export (687). Missions themselves are rows of `tasks.py`; this module only decides when they run."""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import logging
import time
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
TICK_S = 3
WARN_BEFORE_S = 15 * 60

TEMPLATES = {
    "pc_report": ("Zjisti stav počítače, připrav report a ulož ho", [{"tool": "pc_health_report"}]),
}


def workspace(task_id: str) -> Path:
    """A folder of one mission: files it produces are kept together (Dokumenty\\JARVIS\\Mise\\<id>)."""
    from .pcreport import reports_dir

    d = reports_dir().parent / "Mise" / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class Missions:
    def __init__(self, rt):
        self.rt = rt
        self._task: asyncio.Task | None = None
        self._warned: set[str] = set()

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    # ---------- queue ----------
    def enqueue(self, goal: str, steps: list[dict] | None = None, deadline: float | None = None,
                not_before: float | None = None, priority: str = "") -> str:
        return self.rt.tasks.enqueue(goal, steps, deadline, not_before, self.rt.memory.current_conversation, priority)

    def enqueue_template(self, name: str, deadline: float | None = None, not_before: float | None = None) -> str:
        goal, steps = TEMPLATES[name]
        return self.enqueue(goal, steps, deadline, not_before)

    def cancel_queued(self, task_id: str) -> bool:
        return self.rt.db.exec("UPDATE tasks SET status='cancelled', finished=? WHERE id=? AND status='queued'",
                               (time.time(), task_id)).rowcount > 0

    async def run(self, task: dict) -> None:
        """Start (or continue) one mission now: structured steps without AI, otherwise as a request to the AI."""
        from .config import ProtocolStep

        rt = self.rt
        if task.get("spec"):
            steps = [ProtocolStep(**s) for s in task["spec"]]
            await rt.agent.run_steps(task["goal"], steps, source="mission", task_id=task["id"], track=True)
        else:
            done = [s["title"] for s in task.get("steps", []) if s["status"] == "done"]
            extra = ("Tohle je mise z fronty JARVISe. " +
                     (f"Už hotové kroky (neopakuj je): {'; '.join(done)}. Pokračuj zbytkem." if done else ""))
            await rt.agent.handle(task["goal"], [], "mission", extra_system=extra, task_id=task["id"])

    def resume(self, task_id: str) -> bool:
        """OMEGA 225: an interrupted / failed mission continues after its last finished step (same mission ID)."""
        t = self.rt.tasks.get(task_id)
        if not t or t["status"] in ("running", "paused", "waiting", "verifying"):
            return False
        asyncio.get_running_loop().create_task(self.run(t))
        return True

    # ---------- the loop: start queued missions, watch deadlines ----------
    async def tick(self, now: float | None = None) -> None:
        rt = self.rt
        now = now or time.time()
        q = rt.tasks.queue(now)                          # 009: say once when the order changes because of time
        top = q[0]["id"] if q else None
        if top and getattr(self, "_top", None) not in (None, top) and len(q) > 1:
            rt.notify("Pořadí misí", f"Dopředu jde „{q[0]['goal'][:70]}“ – {', '.join(q[0]['why'])}.", target="all")
        self._top = top
        if not rt.agent.busy and rt.tasks.current is None:
            nxt = rt.tasks.next_queued(now)
            if nxt:
                rt.db.exec("UPDATE tasks SET status='starting' WHERE id=? AND status='queued'", (nxt["id"],))
                asyncio.get_running_loop().create_task(self.run(nxt))
        for t in rt.db.all("SELECT id, goal, deadline, status FROM tasks WHERE deadline IS NOT NULL AND status IN "
                           "('queued','starting','running','paused','waiting','verifying','interrupted','failed')"):
            left = t["deadline"] - now
            key_soon, key_late = t["id"] + ":soon", t["id"] + ":late"
            when = dt.datetime.fromtimestamp(t["deadline"]).strftime("%H:%M")
            if 0 < left <= WARN_BEFORE_S and key_soon not in self._warned:
                self._warned.add(key_soon)
                rt.notify("Termín mise", f"„{t['goal'][:80]}“ má termín v {when} a ještě není hotová.", target="all")
            elif left <= 0 and key_late not in self._warned:
                self._warned.add(key_late)
                rt.notify("Termín mise vypršel", f"„{t['goal'][:80]}“ nestihla termín {when}.", target="all")

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.debug("missions: %s", e)
            await asyncio.sleep(TICK_S)


def export_audit(rt, folder: Path | None = None) -> dict:
    """OMEGA 687: every mission with its steps, actions (already redacted), artifacts and evidence → JSON + CSV."""
    folder = folder or (paths.data_dir() / "Audit")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tasks = [rt.tasks.get(r["id"]) for r in rt.db.all("SELECT id FROM tasks ORDER BY created")]
    js = folder / f"audit_{stamp}.json"
    js.write_text(json.dumps({"exported": stamp, "missions": tasks}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    cs = folder / f"audit_{stamp}.csv"
    with open(cs, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["mise", "cíl", "stav", "čas", "nástroj", "argumenty", "ok", "výsledek", "ms"])
        for t in tasks:
            for a in t["actions"]:
                w.writerow([t["id"], t["goal"], t["status"], dt.datetime.fromtimestamp(a["ts"]).isoformat(timespec="seconds"),
                            a["tool"], a["args"], a["ok"], a["summary"], a["ms"]])
    return {"json": str(js), "csv": str(cs), "missions": len(tasks), "actions": sum(len(t["actions"]) for t in tasks)}
