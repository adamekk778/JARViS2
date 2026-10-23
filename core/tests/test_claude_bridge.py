"""3.0 Claude Code in the notch: settings.json merge/backup, sessions, approvals that never allow without a click."""
import asyncio
import json

import pytest
from conftest import drain

from jarvis import claude_bridge as cb


def test_merge_keeps_everything_else_and_is_idempotent():
    existing = {"model": "opus", "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "other.exe"}]}],
                                           "Custom": "keep"}}
    once = cb.merged(existing, 8765)
    twice = cb.merged(once, 8765)
    assert once == twice and once["model"] == "opus" and once["hooks"]["Custom"] == "keep"
    pre = once["hooks"]["PreToolUse"]
    assert pre[0]["hooks"][0]["command"] == "other.exe" and len(pre) == 2
    perm = once["hooks"]["PermissionRequest"][0]["hooks"][0]
    assert perm["timeout"] == 120 and cb.MARKER in perm["command"] and "|| true" in perm["command"]
    assert cb.without_ours(once) == existing


def test_merge_refuses_unexpected_shapes():
    with pytest.raises(ValueError):
        cb.merged({"hooks": [1, 2]}, 8765)
    with pytest.raises(ValueError):
        cb.merged({"hooks": {"Stop": {"not": "a list"}}}, 8765)


def test_preview_apply_backup_and_fingerprint(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text('{"theme": "dark"}', encoding="utf-8")
    pv = cb.preview(8765, path=path)
    assert "+" in pv["diff"] and cb.MARKER in pv["diff"]
    path.write_text('{"theme": "light"}', encoding="utf-8")       # changed after the preview
    with pytest.raises(ValueError):
        cb.apply(8765, pv["fingerprint"], path=path)
    pv = cb.preview(8765, path=path)
    res = cb.apply(8765, pv["fingerprint"], path=path)
    assert json.loads(open(res["backup"], encoding="utf-8").read()) == {"theme": "light"}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["theme"] == "light" and cb.status(path)["installed"]
    pv = cb.preview(8765, remove=True, path=path)
    cb.apply(8765, pv["fingerprint"], remove=True, path=path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "light"} and not cb.status(path)["installed"]


def test_invalid_json_is_never_touched(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ broken", encoding="utf-8")
    with pytest.raises(ValueError):
        cb.preview(8765, path=path)
    assert path.read_text(encoding="utf-8") == "{ broken"


def test_describe_tools():
    assert cb.describe("Edit", {"file_path": "C:/p/app/main.py", "old_string": "a", "new_string": "b\nc"})[0] == "Upravuje main.py (+2 −1)"
    label, details = cb.describe("Bash", {"command": "npm test", "description": "Run tests"})
    assert label == "Spouští: npm test" and details == ["npm test", "Run tests"]


P = {"session_id": "s1", "cwd": "C:/Projekty/web"}


async def test_session_steps(rt):
    q = rt.bus.subscribe()
    await rt.claude.handle("UserPromptSubmit", {**P, "prompt": "oprav přihlášení"})
    await rt.claude.handle("PreToolUse", {**P, "tool_name": "Edit", "tool_input": {"file_path": "x/login.ts", "old_string": "a", "new_string": "b"}})
    s = rt.claude.list()[0]
    assert s["project"] == "web" and s["state"] == "working" and s["step"] == "Upravuje login.ts (+1 −1)" and s["edits"] == 1
    await rt.claude.handle("Stop", P)
    assert rt.claude.list()[0]["state"] == "done"
    assert any(e["type"] == "notify" for e in drain(q))
    await rt.claude.handle("SessionEnd", P)
    assert rt.claude.list() == []


async def _ask(rt, tool="Bash", inp=None):
    task = asyncio.create_task(rt.claude.handle("PermissionRequest", {**P, "tool_name": tool, "tool_input": inp or {"command": "rm -rf build"}}))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if rt.claude.pending:
            break
    return task


async def test_allow_and_deny_only_after_a_click(rt):
    task = await _ask(rt)
    aid = next(iter(rt.claude.pending))
    assert not task.done()
    assert rt.claude.decide(aid, "allow")
    assert await task == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    task = await _ask(rt)
    rt.claude.decide(next(iter(rt.claude.pending)), "deny")
    assert (await task)["hookSpecificOutput"]["decision"]["behavior"] == "deny"


async def test_no_decision_means_terminal(rt, monkeypatch):
    monkeypatch.setattr(cb, "DECISION_TIMEOUT", 0.05)
    task = await _ask(rt)
    assert await task is None and not rt.claude.pending
    task = await _ask(rt)
    rt.claude.decide(next(iter(rt.claude.pending)), "terminal")
    assert await task is None


async def test_always_remembers_the_tool(rt):
    rt.update_config({"claude": {"always_allow": []}})
    task = await _ask(rt, "Read", {"file_path": "a.txt"})
    rt.claude.decide(next(iter(rt.claude.pending)), "always")
    assert (await task)["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert rt.cfg.claude.always_allow == ["Read"]
    assert (await rt.claude.handle("PermissionRequest", {**P, "tool_name": "Read", "tool_input": {}}))["hookSpecificOutput"]


async def test_questions_plans_and_disabled_stay_in_terminal(rt):
    assert await rt.claude.handle("PermissionRequest", {**P, "tool_name": "AskUserQuestion", "tool_input": {}}) is None
    rt.update_config({"claude": {"approvals": False}})
    assert await rt.claude.handle("PermissionRequest", {**P, "tool_name": "Bash", "tool_input": {}}) is None
    rt.update_config({"claude": {"enabled": False}})
    assert await rt.claude.handle("PreToolUse", P) is None and rt.claude.list() == []


def test_http_route_local_only(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        r = c.post("/api/hooks/claude/PreToolUse", json={**P, "tool_name": "Read", "tool_input": {"file_path": "a.md"}})
        assert r.status_code == 204 and r.content == b""
    with TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.5", 5000)) as c:
        assert c.post("/api/hooks/claude/PreToolUse", json=P).status_code == 403
