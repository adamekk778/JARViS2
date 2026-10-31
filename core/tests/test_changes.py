"""3.12.1: what Claude Code / JARVIS changed, line by line, for the notch's Průběh view."""
from jarvis import changes


def test_diff_lines_counts_and_kinds():
    d, add, rem = changes.diff_lines("a\nb\nc\n", "a\nB\nc\nd\n")
    kinds = [k for k, _ in d]
    assert add == 2 and rem == 1 and kinds[0] == "@" and ["-", "b"] in d and ["+", "B"] in d and ["+", "d"] in d


def test_secrets_masked_in_diffs():
    d, _a, _r = changes.diff_lines("", "API_KEY = sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789")
    assert "abcdefghijklmnop" not in str(d)


def test_from_claude_edit_write_bash(tmp_path):
    e = changes.from_claude("Edit", {"file_path": str(tmp_path / "a.py"), "old_string": "x = 1", "new_string": "x = 2\ny = 3"})
    assert e["kind"] == "edit" and e["file"] == "a.py" and e["add"] == 2 and e["rem"] == 1
    f = tmp_path / "b.txt"
    f.write_text("jedna\ndva\n", encoding="utf-8")
    w = changes.from_claude("Write", {"file_path": str(f), "content": "jedna\ntři\n"})
    assert w["kind"] == "write" and w["add"] == 1 and w["rem"] == 1
    n = changes.from_claude("Write", {"file_path": str(tmp_path / "nový.md"), "content": "# Ahoj\n"})
    assert n["kind"] == "new" and n["add"] == 1 and n["rem"] == 0
    b = changes.from_claude("Bash", {"command": "npm test", "description": "Testy"})
    assert b["kind"] == "cmd" and b["note"] == "Testy"
    assert changes.from_claude("Read", {"file_path": "x"}) is None


async def test_claude_session_keeps_changes(rt):
    await rt.claude.handle("UserPromptSubmit", {"session_id": "s", "cwd": "/p/web", "prompt": "Uprav web"})
    await rt.claude.handle("PreToolUse", {"session_id": "s", "tool_name": "Edit",
                                          "tool_input": {"file_path": "/p/web/index.html", "old_string": "<h1>A</h1>", "new_string": "<h1>B</h1>"}})
    s = rt.claude.list()[0]
    assert s["changes"][0]["file"] == "index.html" and s["changes"][0]["add"] == 1 and s["changes"][0]["rem"] == 1
