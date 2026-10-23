"""Claude Code in the notch (3.0): live sessions, what Claude reads, edits and runs, and Allow / Deny from the
notch or the phone.

Claude Code calls a hook command on each event; ours is a `curl` to this server, so nothing extra is installed.
The hooks are added to ~/.claude/settings.json only after the user saw the exact diff and confirmed it, with a
dated backup first; everything else in the file is kept as it is.

Safety rule: nothing is ever allowed without a human click. Without a decision (timeout, JARVIS closed, a question
we cannot answer) the reply is empty and Claude Code asks in its own terminal exactly as if JARVIS were not there.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import hashlib
import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MARKER = "jarvis-claude-hook"
DECISION_TIMEOUT = 110         # the PermissionRequest hook gets 120 s
EVENTS: list[tuple[str, int]] = [
    ("SessionStart", 10), ("SessionEnd", 10), ("UserPromptSubmit", 10), ("PreToolUse", 10), ("PostToolUse", 10),
    ("PostToolUseFailure", 10), ("PermissionRequest", 120), ("Notification", 10), ("Stop", 10), ("StopFailure", 10),
]
TOOL_LABEL = {
    "Read": "Čte", "Edit": "Upravuje", "MultiEdit": "Upravuje", "Write": "Zapisuje", "Bash": "Spouští",
    "Grep": "Hledá", "Glob": "Hledá soubory", "WebFetch": "Čte web", "WebSearch": "Hledá na webu",
    "Task": "Spouští pomocníka", "TodoWrite": "Plánuje", "NotebookEdit": "Upravuje notebook",
}


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def hook_command(event: str, port: int) -> str:
    # Claude Code on Windows runs hooks through Git Bash (curl is there and in System32). `|| true`: when
    # JARVIS is not running the hook ends quietly and Claude Code carries on.
    return (f"curl -s -m {DECISION_TIMEOUT + 5 if event == 'PermissionRequest' else 5} -H \"Content-Type: application/json\" "
            f"--data-binary @- \"http://127.0.0.1:{port}/api/hooks/claude/{event}?src={MARKER}\" || true")


def _is_ours(entry: Any) -> bool:
    return isinstance(entry, dict) and any(MARKER in str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict))


def merged(existing: dict, port: int) -> dict:
    """The settings with our hooks added (or refreshed); everything else untouched."""
    root = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    hooks = root.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.json: „hooks“ má nečekaný tvar – nesahám na něj.")
    for event, timeout in EVENTS:
        lst = hooks.get(event, [])
        if not isinstance(lst, list):
            raise ValueError(f"settings.json: „hooks.{event}“ má nečekaný tvar – nesahám na něj.")
        lst = [e for e in lst if not _is_ours(e)]
        lst.append({"hooks": [{"type": "command", "command": hook_command(event, port), "timeout": timeout}]})
        hooks[event] = lst
    root["hooks"] = hooks
    return root


def without_ours(existing: dict) -> dict:
    root = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    hooks = root.get("hooks")
    if not isinstance(hooks, dict):
        return root
    out = {}
    for ev, lst in hooks.items():
        if isinstance(lst, list):
            lst = [e for e in lst if not _is_ours(e)]
            if lst:
                out[ev] = lst
        else:
            out[ev] = lst
    if out:
        root["hooks"] = out
    else:
        root.pop("hooks", None)
    return root


def _read(path: Path) -> tuple[str, dict]:
    if not path.exists():
        return "", {}
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"settings.json není platný JSON ({e}) – nesahám na něj.") from e
    if not isinstance(data, dict):
        raise ValueError("settings.json nemá tvar objektu – nesahám na něj.")
    return raw, data


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def status(path: Path | None = None) -> dict:
    path = path or settings_path()
    try:
        _, data = _read(path)
        hooks = data.get("hooks", {}) if isinstance(data.get("hooks"), dict) else {}
        installed = all(any(_is_ours(e) for e in hooks.get(ev, []) if isinstance(hooks.get(ev), list)) for ev, _ in EVENTS)
        partial = any(_is_ours(e) for lst in hooks.values() if isinstance(lst, list) for e in lst)
        return {"installed": installed, "partial": partial and not installed, "path": str(path), "error": ""}
    except Exception as e:
        return {"installed": False, "partial": False, "path": str(path), "error": str(e)}


def preview(port: int, remove: bool = False, path: Path | None = None) -> dict:
    """The exact change, shown to the user before anything is written."""
    path = path or settings_path()
    raw, data = _read(path)
    new = _dump(without_ours(data) if remove else merged(data, port))
    # compact or hand-formatted files: show the change against the same layout, say it gets reformatted
    reformat = bool(raw.strip()) and raw.strip() != _dump(data).strip()
    old = _dump(data) if reformat else raw
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "settings.json (teď)", "settings.json (po změně)"))
    return {"diff": diff or "(beze změny)", "fingerprint": hashlib.sha256(raw.encode()).hexdigest()[:16], "path": str(path),
            "remove": remove, "reformat": reformat}


def apply(port: int, fingerprint: str, remove: bool = False, path: Path | None = None) -> dict:
    """Write only what the user looked at: the file must still be the one the preview was made from."""
    path = path or settings_path()
    raw, data = _read(path)
    if hashlib.sha256(raw.encode()).hexdigest()[:16] != fingerprint:
        raise ValueError("settings.json se mezitím změnil. Zobraz změnu znovu.")
    backup = ""
    if path.exists():
        backup = str(path.with_name(f"settings.json.jarvis-backup-{datetime.now():%Y%m%d-%H%M%S}"))
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jarvis-tmp")
    tmp.write_text(_dump(without_ours(data) if remove else merged(data, port)), encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "backup": backup}


# ---------- live sessions and approvals ----------
def _short(s: str, n: int = 80) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(tool: str, inp: dict) -> tuple[str, list[str]]:
    """One line for the notch ('Upravuje main.py') and detail lines for an approval card."""
    inp = inp if isinstance(inp, dict) else {}
    verb = TOOL_LABEL.get(tool, tool)
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    name = Path(path).name if path else ""
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        return f"{verb}: {_short(cmd, 60)}", [cmd[:2000]] + ([inp["description"]] if inp.get("description") else [])
    if tool in ("Edit", "MultiEdit"):
        edits = inp.get("edits") or [inp]
        add = sum(str(e.get("new_string", "")).count("\n") + 1 for e in edits if isinstance(e, dict))
        rem = sum(str(e.get("old_string", "")).count("\n") + 1 for e in edits if isinstance(e, dict))
        return f"{verb} {name} (+{add} −{rem})", [path]
    if tool == "Write":
        return f"{verb} {name}", [path, f"{str(inp.get('content', '')).count(chr(10)) + 1} řádků"]
    if tool in ("WebFetch", "WebSearch"):
        return f"{verb}: {_short(inp.get('url') or inp.get('query') or '', 60)}", [str(inp.get("url") or inp.get("query") or "")]
    if name:
        return f"{verb} {name}", [path]
    return verb, [_short(json.dumps(inp, ensure_ascii=False), 300)] if inp else []


class ClaudeBridge:
    def __init__(self, rt: Any):
        self.rt = rt
        self.sessions: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}       # approval id -> {future, session, tool, ...}

    def _session(self, p: dict) -> dict:
        sid = str(p.get("session_id") or "claude")
        s = self.sessions.get(sid)
        if s is None:
            cwd = str(p.get("cwd") or "")
            s = self.sessions[sid] = {"id": sid, "project": Path(cwd).name if cwd else "Claude Code", "cwd": cwd,
                                      "state": "idle", "step": "", "prompt": "", "started": time.time(),
                                      "updated": time.time(), "edits": 0, "commands": 0, "steps": []}
        s["updated"] = time.time()
        return s

    def _publish(self) -> None:
        self.rt.bus.publish("claude_sessions", items=self.list())

    def list(self) -> list[dict]:
        if not self.rt.cfg.claude.enabled:
            return []
        cutoff = time.time() - 6 * 3600
        for sid in [k for k, v in self.sessions.items() if v["updated"] < cutoff]:
            self.sessions.pop(sid, None)
        return sorted(({k: v for k, v in s.items() if k != "steps"} | {"steps": s["steps"][-8:]} for s in self.sessions.values()),
                      key=lambda s: -s["updated"])

    def _step(self, s: dict, text: str) -> None:
        s["step"] = text
        s["steps"].append({"t": time.time(), "text": text})
        del s["steps"][:-30]

    async def handle(self, event: str, p: dict) -> dict | None:
        """Returns the JSON Claude Code should read, or None (= no opinion, it carries on / asks in its terminal)."""
        if not self.rt.cfg.claude.enabled:
            self.sessions.clear()
            return None
        s = self._session(p)
        tool = str(p.get("tool_name", ""))
        inp = p.get("tool_input") or {}
        if event == "SessionStart":
            s["state"] = "idle"
        elif event == "UserPromptSubmit":
            s["state"], s["prompt"] = "thinking", _short(p.get("prompt", ""), 140)
            self._step(s, "Přemýšlí…")
        elif event == "PreToolUse":
            s["state"] = "working"
            self._step(s, describe(tool, inp)[0])
            if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
                s["edits"] += 1
            if tool == "Bash":
                s["commands"] += 1
        elif event == "PostToolUseFailure":
            self._step(s, f"Chyba: {describe(tool, inp)[0]}")
        elif event == "Notification":
            msg = str(p.get("message", ""))
            if "waiting for your input" in msg.lower() or "needs your" in msg.lower():
                s["state"] = "waiting"
        elif event in ("Stop", "StopFailure"):
            s["state"] = "done" if event == "Stop" else "error"
            self._step(s, "Hotovo" if event == "Stop" else "Skončil s chybou")
            if self.rt.cfg.claude.notify_done:
                self.rt.notify(f"Claude Code · {s['project']}", "Hotovo, můžeš pokračovat." if event == "Stop" else "Skončil s chybou.", speak=False)
        elif event == "SessionEnd":
            self.sessions.pop(s["id"], None)
            self._publish()
            return None
        elif event == "PermissionRequest":
            self._publish()
            return await self._ask(s, tool, inp)
        self._publish()
        return None

    async def _ask(self, s: dict, tool: str, inp: dict) -> dict | None:
        if not self.rt.cfg.claude.approvals or tool in ("AskUserQuestion", "ExitPlanMode"):
            return None      # questions and plans stay in the terminal
        if tool in self.rt.cfg.claude.always_allow:
            return _decision("allow")
        label, details = describe(tool, inp)
        aid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        prev_state = s["state"]
        s["state"] = "waiting"
        card = {"id": aid, "session": s["id"], "project": s["project"], "tool": tool, "label": label,
                "details": details[:6], "timeout": DECISION_TIMEOUT, "asked": time.time()}
        self.pending[aid] = {"future": fut, **card}
        self.rt.bus.publish("claude_permission", **card)
        self.rt.notify(f"Claude Code · {s['project']} čeká", label, speak=False, target="mobile")
        self._publish()
        try:
            decision = await asyncio.wait_for(fut, DECISION_TIMEOUT)
        except asyncio.TimeoutError:
            decision = None
        finally:
            self.pending.pop(aid, None)
            s["state"] = "working" if prev_state != "waiting" else "thinking"
            self.rt.bus.publish("claude_permission_resolved", id=aid, decision=decision or "terminal")
            self._publish()
        if decision == "always":
            if tool not in self.rt.cfg.claude.always_allow:
                self.rt.update_config({"claude": {"always_allow": [*self.rt.cfg.claude.always_allow, tool]}})
            return _decision("allow")
        if decision in ("allow", "deny"):
            return _decision(decision)
        return None

    def pending_public(self) -> list[dict]:
        return [{k: v for k, v in p.items() if k != "future"} for p in self.pending.values()]

    def decide(self, aid: str, decision: str) -> bool:
        p = self.pending.get(aid)
        if not p or p["future"].done() or decision not in ("allow", "deny", "always", "terminal"):
            return False
        p["future"].set_result(None if decision == "terminal" else decision)
        return True


def _decision(behavior: str) -> dict:
    d: dict = {"behavior": "allow" if behavior == "allow" else "deny"}
    if behavior == "deny":
        d["message"] = "Zamítnuto v JARVISovi"
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": d}}
