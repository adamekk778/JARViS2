import shutil
import subprocess

import pytest

from jarvis import config, tools
from jarvis.tools import dev

tools.load_builtin()
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def proj(tmp_path, ctx):
    root = tmp_path / "Projekty"
    repo = root / "app"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("v1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    ctx.cfg = config.Config.model_validate({"tools": {"allowed_folders": [str(root)]}})
    return repo


def refs(repo):
    out = git(repo, "for-each-ref", "--format=%(refname)", "refs/jarvis/checkpoints")
    return [r for r in out.splitlines() if r]


async def test_outside_allowed_refused(ctx, proj):
    res = await tools.call("git_status", {"project": "/etc"}, ctx)
    assert not res.ok and "povolen" in res.summary


async def test_project_by_name(ctx, proj):
    res = await tools.call("git_status", {"project": "app"}, ctx)
    assert res.ok and "a.txt" not in res.summary


async def test_not_a_repo(ctx, proj):
    plain = proj.parent / "plain"
    plain.mkdir()
    res = await tools.call("git_status", {"project": str(plain)}, ctx)
    assert not res.ok and "není git repozitář" in res.summary


async def test_git_missing(ctx, proj, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    res = await tools.call("git_status", {"project": str(proj)}, ctx)
    assert not res.ok and "winget install Git.Git" in res.summary


async def test_status_and_diff(ctx, proj):
    (proj / "a.txt").write_text("v2\n", encoding="utf-8")
    st = await tools.call("git_status", {"project": str(proj)}, ctx)
    assert st.ok and "a.txt" in st.summary
    df = await tools.call("git_diff", {"project": str(proj)}, ctx)
    assert df.ok and "+v2" in df.summary


async def test_checkpoint_keeps_head_and_tree(ctx, proj):
    head = git(proj, "rev-parse", "HEAD")
    (proj / "a.txt").write_text("v2\n", encoding="utf-8")
    res = await tools.call("checkpoint", {"project": str(proj), "label": "test"}, ctx)
    assert res.ok
    assert git(proj, "rev-parse", "HEAD") == head
    assert (proj / "a.txt").read_text(encoding="utf-8") == "v2\n"
    assert "a.txt" in git(proj, "status", "--porcelain")
    assert git(proj, "diff", "--cached", "--name-only") == ""  # real index untouched
    assert len(refs(proj)) == 1


async def test_restore_checkpoint(ctx, proj):
    (proj / "a.txt").write_text("v2\n", encoding="utf-8")
    cp = (await tools.call("checkpoint", {"project": str(proj)}, ctx)).data["id"]
    (proj / "a.txt").write_text("v3\n", encoding="utf-8")
    spec = tools.REGISTRY["restore_checkpoint"]
    assert any("a.txt" in line for line in spec.details({"project": str(proj), "id": cp}))
    res = await tools.call("restore_checkpoint", {"project": str(proj), "id": cp}, ctx)
    assert res.ok
    assert (proj / "a.txt").read_text(encoding="utf-8") == "v2\n"
    assert len(refs(proj)) == 2  # the automatic backup


async def test_checkpoint_untracked(ctx, proj):
    (proj / "new.txt").write_text("nový\n", encoding="utf-8")
    cp = (await tools.call("checkpoint", {"project": str(proj)}, ctx)).data["id"]
    (proj / "new.txt").write_text("změněno\n", encoding="utf-8")
    (proj / "later.txt").write_text("x", encoding="utf-8")
    await tools.call("restore_checkpoint", {"project": str(proj), "id": cp}, ctx)
    assert (proj / "new.txt").read_text(encoding="utf-8") == "nový\n"
    assert not (proj / "later.txt").exists()


async def test_list_checkpoints(ctx, proj):
    await tools.call("checkpoint", {"project": str(proj), "label": "první"}, ctx)
    res = await tools.call("checkpoints", {"project": str(proj)}, ctx)
    assert res.ok and len(res.data) == 1 and "první" in res.data[0]["label"]


async def test_compare_files(ctx, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("jedna\ndva\n", encoding="utf-8")
    b.write_text("jedna\ntři\n", encoding="utf-8")
    res = await tools.call("compare_files", {"a": str(a), "b": str(b)}, ctx)
    assert res.ok and res.data == {"added": 1, "removed": 1} and "@@" in res.summary


async def test_run_tests_detects_pytest(ctx, proj, monkeypatch):
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    seen = {}

    def fake(cmd, cwd, timeout):
        seen["cmd"] = cmd
        return 0, "3 passed"

    monkeypatch.setattr(dev, "_run_cmd", fake)
    res = await tools.call("run_tests", {"project": str(proj)}, ctx)
    assert res.ok and seen["cmd"] == "python -m pytest -q" and "3 passed" in res.summary


async def test_run_tests_failure_not_ok(ctx, proj, monkeypatch):
    (proj / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dev, "_run_cmd", lambda cmd, cwd, timeout: (1, "1 failed"))
    res = await tools.call("run_tests", {"project": str(proj)}, ctx)
    assert not res.ok and "1 failed" in res.summary


async def test_claude_code_missing(ctx, proj, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    res = await tools.call("claude_code", {"project": str(proj), "task": "oprav chybu"}, ctx)
    assert not res.ok and "Claude Code" in res.summary


def test_claude_code_always_dangerous():
    spec = tools.REGISTRY["claude_code"]
    assert tools.is_dangerous(spec, {}, trusted=["claude_code"])


async def test_auto_checkpoint_once_per_task(rt, tmp_path):
    root = tmp_path / "Projekty"
    repo = root / "app"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("v1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    rt.update_config({"tools": {"allowed_folders": [str(root)]}})
    rt.tasks.begin("uprav soubory", "c1")
    for i in range(2):
        res = await tools.call("write_text_file", {"path": str(repo / f"f{i}.txt"), "content": "x"}, rt)
        assert res.ok
    assert len(refs(repo)) == 1
