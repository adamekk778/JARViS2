"""What an AI changed, line by line: for Claude Code's edits and writes (from its hooks, before the change lands) and for
JARVIS's own file writes. Each change = file, +added / −removed and a short unified diff (secrets masked), so the notch
can show exactly what was added and what was taken away."""
from __future__ import annotations

import difflib
import time
from pathlib import Path

from .redact import redact

MAX_LINES = 120          # diff lines kept per change
MAX_READ = 400_000       # bytes read from an existing file to diff a full rewrite


def diff_lines(old: str, new: str, context: int = 2, limit: int = MAX_LINES) -> tuple[list[list[str]], int, int]:
    """[(kind, text)] with kind "+", "-", " " or "@" (a new hunk), plus counts of added and removed lines."""
    a, b = (old or "").splitlines(), (new or "").splitlines()
    out: list[list[str]] = []
    add = rem = 0
    for ln in list(difflib.unified_diff(a, b, lineterm="", n=context))[2:]:
        if ln.startswith("@@"):
            kind, text = "@", ln
        elif ln.startswith("+"):
            kind, text = "+", ln[1:]
            add += 1
        elif ln.startswith("-"):
            kind, text = "-", ln[1:]
            rem += 1
        else:
            kind, text = " ", ln[1:]
        if len(out) < limit:
            out.append([kind, redact(text)[:300]])
    return out, add, rem


def _read(path: str) -> str:
    try:
        p = Path(path)
        if p.is_file() and p.stat().st_size <= MAX_READ:
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def from_claude(tool: str, inp: dict) -> dict | None:
    """Claude Code's PreToolUse input → a change record (None for tools that change no file / run no command)."""
    inp = inp if isinstance(inp, dict) else {}
    path = str(inp.get("file_path") or inp.get("notebook_path") or "")
    if tool in ("Edit", "MultiEdit"):
        lines: list[list[str]] = []
        add = rem = 0
        for e in (inp.get("edits") or [inp]):
            if not isinstance(e, dict):
                continue
            d, a, r = diff_lines(str(e.get("old_string", "")), str(e.get("new_string", "")))
            lines += d
            add, rem = add + a, rem + r
        return {"t": time.time(), "kind": "edit", "file": Path(path).name, "path": path, "add": add, "rem": rem, "diff": lines[:MAX_LINES]}
    if tool == "Write":
        old = _read(path)
        d, a, r = diff_lines(old, str(inp.get("content", "")))
        return {"t": time.time(), "kind": "new" if not old else "write", "file": Path(path).name, "path": path, "add": a, "rem": r, "diff": d}
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        return {"t": time.time(), "kind": "cmd", "file": "", "path": "", "add": 0, "rem": 0,
                "diff": [[" ", redact(cmd)[:300]]], "note": str(inp.get("description") or "")[:160]}
    return None


def from_text(path: str, old: str, new: str) -> dict:
    d, a, r = diff_lines(old, new)
    return {"t": time.time(), "kind": "new" if not old else "write", "file": Path(path).name, "path": path, "add": a, "rem": r, "diff": d}
