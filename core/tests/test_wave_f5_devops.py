"""Wave F5c: CHANGELOG (050), build check (058), release package (060), CI workflow (626), ADR (618), sandbox (345),
Mochi confused after a failed build (744)."""
import json
import subprocess
import zipfile

from jarvis import devops, tools

tools.load_builtin()


def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _repo(tmp_path):
    r = tmp_path / "app"
    r.mkdir()
    (r / "requirements.txt").write_text("flask\n")
    (r / "app.py").write_text("print('ahoj')\n")
    (r / ".env").write_text("SECRET=1\n")
    (r / "node_modules").mkdir()
    (r / "node_modules" / "x.js").write_text("x")
    _git(r, "init", "-q")
    _git(r, "-c", "user.email=a@b", "-c", "user.name=A", "add", "-A")
    _git(r, "-c", "user.email=a@b", "-c", "user.name=A", "commit", "-qm", "feat: první verze")
    return r


def test_changelog_text():
    e = devops.changelog_entry("1.2.0", "# Vydání\n\n### Novinky\n- přidáno X\n")
    assert e.startswith("## 1.2.0 – ") and "- přidáno X" in e and "# Vydání" not in e
    c = devops.prepend_changelog("# Changelog\n\n## 1.1.0 – 2026-01-01\n\nstaré\n", e)
    assert c.index("1.2.0") < c.index("1.1.0") and c.startswith("# Changelog\n\n## 1.2.0")
    assert devops.prepend_changelog("", e).startswith("# Changelog\n\n## 1.2.0")


def test_build_commands(tmp_path):
    n = tmp_path / "n"
    n.mkdir()
    (n / "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "test": "vitest", "lint": "eslint ."}}))
    assert devops.build_commands(n) == ["npm run lint", "npm run build", "npm test"]
    p = tmp_path / "p"
    p.mkdir()
    (p / "pyproject.toml").write_text("")
    (p / "tests").mkdir()
    assert devops.build_commands(p) == ["python -m compileall -q .", "python -m pytest -q"]
    assert devops.build_commands(tmp_path / "nic") == []


def test_package_skips_secrets_and_modules(tmp_path):
    r = _repo(tmp_path)
    out = devops.package(r, "1.0.0", extra_files={"RELEASE.md": "# 1.0.0"})
    names = zipfile.ZipFile(out["zip"]).namelist()
    assert "app-1.0.0/app.py" in names and "app-1.0.0/RELEASE.md" in names
    assert not any(".env" in n or "node_modules" in n or ".git/" in n for n in names)
    assert (r / "dist" / "SHA256SUMS").read_text().startswith(out["sha256"])
    try:
        devops.package(r, "1.0; rm -rf /")
        raise AssertionError
    except ValueError:
        pass


def test_ci_workflow(tmp_path):
    r = _repo(tmp_path)
    wf = devops.ci_workflow(r, {"python": "3.11.4"})
    assert "actions/setup-python@v5" in wf and "python-version: '3.11'" in wf and "pip install -r requirements.txt" in wf
    assert "windows-latest" in wf and "- run: python -m compileall -q ." in wf


def test_adr_numbering(tmp_path):
    d = tmp_path / "docs" / "adr"
    a = devops.adr(d, "Použijeme SQLite", "Potřebujeme lokální úložiště.", "SQLite v souboru.", "Jeden zapisovatel.")
    b = devops.adr(d, "Přechod na Postgres", "Víc uživatelů.", "Postgres.", "Server navíc.", "Navrženo")
    assert a.name == "0001-pouzijeme-sqlite.md" and b.name.startswith("0002-prechod-na-postgres")
    assert "## Rozhodnutí\n\nSQLite v souboru." in a.read_text(encoding="utf-8") and "Navrženo" in b.read_text(encoding="utf-8")


def test_sandbox_and_diff(tmp_path):
    r = _repo(tmp_path)
    box = devops.sandbox_copy(r)
    assert (box / "app.py").exists() and not (box / ".git").exists() and not (box / ".env").exists()
    (box / "app.py").write_text("print('změna')\n")
    (box / "new.txt").write_text("x")
    d = devops.changed_files(r, box)
    assert d["changed"] == ["app.py"] and d["added"] == ["new.txt"]
    assert (r / "app.py").read_text() == "print('ahoj')\n"


async def test_devops_tools_registered_and_guarded(rt):
    for n in ("verify_build", "package_release", "code_sandbox"):
        assert tools.REGISTRY[n].danger
    assert tools.REGISTRY["ci_setup"].danger_if({"write": True}) and not tools.REGISTRY["ci_setup"].danger_if({})
    assert tools.REGISTRY["update_changelog"].danger_if({"write": True})


def test_confused_after_failed_build(rt):
    m = rt.mood
    m.on_event({"type": "assistant_done", "tools": [{"name": "run_tests", "ok": False, "summary": "chyba"}]})
    assert m.reaction["name"] == "confused"
    m.on_event({"type": "assistant_done", "tools": [{"name": "web_search", "ok": False, "summary": "x"}]})
    assert m.reaction["name"] == "confused"          # unchanged by an unrelated failure (no new reaction)
