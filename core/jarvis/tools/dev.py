"""Programming assistant (spec §6): git, checkpoints you can roll back to, file comparison, tests, Claude Code.

Works only inside the user's allowed project folders. Checkpoints are commits under refs/jarvis/checkpoints/*,
built with a temporary index, so the user's branch, index and working tree stay untouched.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool

GIT_MISSING = ToolResult(False, "Git není nainstalovaný. Nainstaluj ho příkazem: winget install Git.Git")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
REF_PREFIX = "refs/jarvis/checkpoints/"
_auto_done: set[tuple[str, str]] = set()


# ---------- helpers ----------
def allowed_roots(ctx) -> list[Path]:
    roots = [Path(p).expanduser() for p in ctx.cfg.tools.allowed_folders]
    return roots or [Path.home() / "Documents" / "Projekty"]


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def resolve_project(ctx, project: str) -> Path | ToolResult:
    roots = allowed_roots(ctx)
    p = Path(os.path.expandvars(os.path.expanduser(project or "")))
    if not p.is_absolute():
        p = next((r / project for r in roots if (r / project).exists()), roots[0] / project)
    if not any(_inside(p, r) for r in roots):
        return ToolResult(False, f"Složka {p} není mezi povolenými složkami projektů "
                                 "(Nastavení → Nástroje → Povolené složky).")
    if not p.is_dir():
        return ToolResult(False, f"Složka {p} neexistuje.")
    return p


def _git_env(extra: dict | None = None) -> dict:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_AUTHOR_NAME", "JARVIS")
    env.setdefault("GIT_AUTHOR_EMAIL", "jarvis@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "JARVIS")
    env.setdefault("GIT_COMMITTER_EMAIL", "jarvis@localhost")
    return {**env, **(extra or {})}


def _git(repo: Path, *args: str, env: dict | None = None, check: bool = True, timeout: int = 60) -> str:
    # quotePath=false: file names with diacritics come back as real names, not "pozn\303\241mky"
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=_git_env(env), creationflags=NO_WINDOW)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:500] or f"git {args[0]} selhal")
    return r.stdout


def _repo_root(p: Path) -> Path | None:
    try:
        return Path(_git(p, "rev-parse", "--show-toplevel").strip())
    except Exception:
        return None


def _repo(ctx, project: str) -> Path | ToolResult:
    if not shutil.which("git"):
        return GIT_MISSING
    p = resolve_project(ctx, project)
    if isinstance(p, ToolResult):
        return p
    root = _repo_root(p)
    return root if root else ToolResult(False, f"{p} není git repozitář.")


def _snapshot_tree(repo: Path) -> str:
    """Tree object of the working directory (tracked + untracked, honours .gitignore) via a temporary index."""
    with tempfile.TemporaryDirectory() as td:
        idx = Path(td) / "index"
        real = Path(_git(repo, "rev-parse", "--git-path", "index").strip())
        real = real if real.is_absolute() else repo / real
        if real.exists():
            shutil.copy2(real, idx)
        env = {"GIT_INDEX_FILE": str(idx)}
        _git(repo, "add", "-A", env=env)
        return _git(repo, "write-tree", env=env).strip()


def _head(repo: Path) -> str | None:
    out = _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
    return out or None


def make_checkpoint(repo: Path, label: str = "") -> str:
    tree = _snapshot_tree(repo)
    parent = _head(repo)
    msg = f"JARVIS checkpoint {label}".strip()
    commit = _git(repo, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", msg).strip()
    cid = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    existing = set(_git(repo, "for-each-ref", "--format=%(refname)", REF_PREFIX).split())
    base, n = cid, 2
    while REF_PREFIX + cid in existing:
        cid, n = f"{base}-{n}", n + 1
    _git(repo, "update-ref", REF_PREFIX + cid, commit)
    return cid


def _changed_files(repo: Path, cid: str) -> list[str]:
    tree = _snapshot_tree(repo)
    out = _git(repo, "diff", "--name-status", REF_PREFIX + cid, tree)
    return [line.replace("\t", " ") for line in out.splitlines() if line.strip()]


COPY_IGNORE = ("node_modules", ".venv", "venv", "__pycache__", ".git", "dist")


def _copy_dir(p: Path, cid: str = "") -> Path:
    base = paths.sub("checkpoints") / p.name
    return base / cid if cid else base


def _tree_files(root: Path) -> set[str]:
    out = set()
    for f in root.rglob("*"):
        rel = f.relative_to(root)
        if f.is_file() and not any(part in COPY_IGNORE for part in rel.parts):
            out.add(rel.as_posix())
    return out


def _copy_changes(p: Path, snap: Path) -> list[str]:
    now, then = _tree_files(p), _tree_files(snap)
    lines = [f"A {f}" for f in sorted(now - then)] + [f"D {f}" for f in sorted(then - now)]
    for f in sorted(now & then):
        if (p / f).read_bytes() != (snap / f).read_bytes():
            lines.append(f"M {f}")
    return lines


def _restore_details(args: dict, ctx=None) -> list[str]:
    if ctx is None:
        return []
    p = resolve_project(ctx, str(args.get("project", "")))
    if isinstance(p, ToolResult):
        return []
    cid = str(args.get("id", ""))
    root = _repo_root(p) if shutil.which("git") else None
    if root:
        return _changed_files(root, cid)
    snap = _copy_dir(p, cid)
    return _copy_changes(p, snap) if snap.is_dir() else []


def _run_cmd(cmd: str, cwd: Path, timeout: int) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _detect_tests(p: Path) -> str | None:
    if any((p / f).exists() for f in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")) or (p / "tests").is_dir():
        return "python -m pytest -q"
    if (p / "package.json").exists():
        return "npm test"
    if (p / "Cargo.toml").exists():
        return "cargo test"
    if any(p.glob("*.sln")) or any(p.glob("*.csproj")):
        return "dotnet test"
    return None


def auto_checkpoint(ctx, path: str | Path) -> str | None:
    """Before JARVIS writes into a git project inside the allowed folders: one checkpoint per task and repo."""
    try:
        target = Path(path)
        if not shutil.which("git") or not any(_inside(target, r) for r in allowed_roots(ctx)):
            return None
        folder = target if target.is_dir() else target.parent
        while not folder.exists():
            folder = folder.parent
        repo = _repo_root(folder)
        if not repo:
            return None
        tasks = getattr(ctx, "tasks", None)
        cur = tasks.current if tasks is not None else None
        key = (cur["id"] if cur else "notask", str(repo))
        if key in _auto_done:
            return None
        _auto_done.add(key)
        return make_checkpoint(repo, "automaticky před úpravou")
    except Exception:
        return None


def _tail(text: str, lines: int = 200) -> str:
    return "\n".join(text.splitlines()[-lines:])


# ---------- tools ----------
@tool("git_status", "Stav git projektu: větev, změněné soubory, náskok/zpoždění proti serveru.",
      category="programování", perm="files_read")
async def git_status(ctx, project: Annotated[str, "cesta nebo název složky projektu"]) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        return repo
    out = await asyncio.to_thread(_git, repo, "status", "--porcelain=v1", "-b")
    return ToolResult(True, out.strip() or "Čisto", data={"repo": str(repo)})


@tool("git_diff", "Ukáže změny v projektu (git diff). staged=true jen připravené ke commitu.",
      category="programování", perm="files_read")
async def git_diff(ctx, project: str, path: str = "", staged: bool = False) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        return repo
    args = ["diff", *(["--cached"] if staged else []), *(["--", path] if path else [])]
    out = await asyncio.to_thread(_git, repo, *args)
    if len(out) > 12000:
        out = out[:12000] + "\n…(zkráceno)"
    return ToolResult(True, out or "Žádné změny")


@tool("git_log", "Historie commitů projektu.", category="programování", perm="files_read")
async def git_log(ctx, project: str, n: int = 15) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        return repo
    out = await asyncio.to_thread(_git, repo, "log", f"-{max(1, min(n, 100))}", "--pretty=format:%h %ad %an: %s",
                                  "--date=short", check=False)
    return ToolResult(True, out or "Zatím žádné commity")


@tool("git_commit", "Uloží změny projektu jako commit.", danger=True, category="programování", perm="files_write",
      details=lambda a: [f"Projekt: {a.get('project', '')}", f"Zpráva: {a.get('message', '')}"])
async def git_commit(ctx, project: str, message: str, add_all: bool = True) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        return repo

    def run():
        if add_all:
            _git(repo, "add", "-A")
        return _git(repo, "commit", "-m", message)

    try:
        out = await asyncio.to_thread(run)
    except RuntimeError as e:
        return ToolResult(False, f"Commit se nepovedl: {e}")
    return ToolResult(True, out.strip().splitlines()[0] if out.strip() else "Commit vytvořen")


@tool("git_push", "Odešle commity na server (GitHub apod.) s přihlášením uživatele.", danger=True,
      category="programování", perm="network")
async def git_push(ctx, project: str) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        return repo
    try:
        out = await asyncio.to_thread(_git, repo, "push", timeout=120)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        return ToolResult(False, f"Push se nepovedl: {e}")
    return ToolResult(True, out.strip() or "Odesláno")


@tool("checkpoint", "Vytvoří záchytný bod projektu (stav všech souborů), ke kterému se jde vrátit. Nemění historii.",
      category="programování", perm="files_write")
async def checkpoint(ctx, project: str, label: str = "") -> ToolResult:
    if shutil.which("git"):
        repo = _repo(ctx, project)
        if not isinstance(repo, ToolResult):
            cid = await asyncio.to_thread(make_checkpoint, repo, label)
            return ToolResult(True, f"Záchytný bod {cid} vytvořen", data={"id": cid, "kind": "git"})
    p = resolve_project(ctx, project)
    if isinstance(p, ToolResult):
        return p
    cid = await asyncio.to_thread(_copy_checkpoint, p)
    return ToolResult(True, f"Záchytný bod {cid} uložen do {_copy_dir(p, cid)}", data={"id": cid, "kind": "copy"})


def _copy_checkpoint(p: Path) -> str:
    cid = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base, n = cid, 2
    while _copy_dir(p, cid).exists():
        cid, n = f"{base}-{n}", n + 1
    shutil.copytree(p, _copy_dir(p, cid), ignore=shutil.ignore_patterns(*COPY_IGNORE))
    return cid


def _copy_restore(p: Path, cid: str) -> str:
    snap = _copy_dir(p, cid)
    if not snap.is_dir():
        raise RuntimeError(f"záchytný bod {cid} neexistuje")
    backup = _copy_checkpoint(p)
    for rel in _tree_files(p) - _tree_files(snap):
        (p / rel).unlink()
    shutil.copytree(snap, p, dirs_exist_ok=True)
    return backup


@tool("checkpoints", "Seznam záchytných bodů projektu.", category="programování", perm="files_read")
async def checkpoints(ctx, project: str) -> ToolResult:
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        p = resolve_project(ctx, project)
        if isinstance(p, ToolResult) or (shutil.which("git") and _repo_root(p)):
            return repo
        base = _copy_dir(p)
        items = [{"id": d.name, "date": d.name, "label": "kopie složky"}
                 for d in sorted(base.iterdir(), reverse=True) if d.is_dir()] if base.is_dir() else []
        return ToolResult(True, f"{len(items)} záchytných bodů", data=items)
    out = await asyncio.to_thread(_git, repo, "for-each-ref", "--sort=-creatordate",
                                  "--format=%(refname:short)\t%(creatordate:iso)\t%(subject)", REF_PREFIX)
    items = []
    for line in out.splitlines():
        ref, date, subject = (line.split("\t") + ["", ""])[:3]
        items.append({"id": ref.rsplit("/", 1)[-1], "date": date, "label": subject.removeprefix("JARVIS checkpoint").strip()})
    return ToolResult(True, f"{len(items)} záchytných bodů", data=items)


@tool("restore_checkpoint", "Vrátí soubory projektu do stavu záchytného bodu (aktuální stav se předtím zálohuje).",
      danger=True, category="programování", perm="files_write", details=_restore_details)
async def restore_checkpoint(ctx, project: str, id: str) -> ToolResult:  # noqa: A002
    repo = _repo(ctx, project)
    if isinstance(repo, ToolResult):
        p = resolve_project(ctx, project)
        if isinstance(p, ToolResult) or (shutil.which("git") and _repo_root(p)):
            return repo
        try:
            backup = await asyncio.to_thread(_copy_restore, p, id)
        except (RuntimeError, OSError) as e:
            return ToolResult(False, f"Obnovení se nepovedlo: {e}")
        return ToolResult(True, f"Obnoveno ze záchytného bodu {id} (předchozí stav zálohován jako {backup})",
                          data={"backup": backup})

    def run():
        ref = REF_PREFIX + id
        _git(repo, "rev-parse", "--verify", ref)
        backup = make_checkpoint(repo, f"před obnovením {id}")
        added = _git(repo, "diff", "--name-only", "--diff-filter=A", ref, REF_PREFIX + backup).splitlines()
        for rel in added:
            f = repo / rel
            if f.is_file():
                f.unlink()
        with tempfile.TemporaryDirectory() as td:
            env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
            _git(repo, "read-tree", ref, env=env)
            _git(repo, "checkout-index", "-a", "-f", env=env)
        return backup

    try:
        backup = await asyncio.to_thread(run)
    except RuntimeError as e:
        return ToolResult(False, f"Obnovení se nepovedlo: {e}")
    return ToolResult(True, f"Obnoveno ze záchytného bodu {id} (předchozí stav zálohován jako {backup})",
                      data={"backup": backup})


@tool("compare_files", "Porovná dva textové soubory a ukáže rozdíly.", category="soubory", perm="files_read")
async def compare_files(ctx, a: str, b: str) -> ToolResult:
    def read(p):
        return Path(os.path.expanduser(p)).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    try:
        la, lb = await asyncio.to_thread(read, a), await asyncio.to_thread(read, b)
    except OSError as e:
        return ToolResult(False, f"Soubor nejde přečíst: {e}")
    diff = list(difflib.unified_diff(la, lb, fromfile=a, tofile=b))
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    text = "".join(diff)
    if len(text) > 12000:
        text = text[:12000] + "\n…(zkráceno)"
    return ToolResult(True, text or "Soubory jsou stejné", data={"added": added, "removed": removed})


@tool("run_tests", "Spustí testy projektu (pytest / npm test / cargo test / dotnet test) a vrátí výsledek.",
      danger=True, category="programování", perm="shell",
      details=lambda a: [f"Projekt: {a.get('project', '')}", f"Příkaz: {a.get('command') or '(automaticky)'}"])
async def run_tests(ctx, project: str, command: str = "") -> ToolResult:
    p = resolve_project(ctx, project)
    if isinstance(p, ToolResult):
        return p
    cmd = command or _detect_tests(p)
    if not cmd:
        return ToolResult(False, "Nevím, jak tu spustit testy – zadej příkaz (command).")
    try:
        code, out = await asyncio.to_thread(_run_cmd, cmd, p, 600)
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Testy běžely déle než 10 minut ({cmd}).")
    return ToolResult(code == 0, f"$ {cmd} → {'OK' if code == 0 else f'chyba ({code})'}\n" + _tail(out),
                      data={"exit_code": code, "command": cmd})


@tool("claude_code", "Předá programátorský úkol Claude Code (oficiální CLI `claude`, pokud je nainstalovaný a "
      "přihlášený) v dané složce projektu. Vrátí výsledek a změněné soubory.", danger=True,
      category="programování", perm="shell",
      details=lambda a: [f"Projekt: {a.get('project', '')}", f"Úkol: {a.get('task', '')}"])
async def claude_code(ctx, project: str, task: str) -> ToolResult:
    exe = shutil.which("claude")
    if not exe:
        return ToolResult(False, "Claude Code není nainstalovaný. Návod: https://docs.claude.com/claude-code "
                                 "(po instalaci se jednou přihlas příkazem `claude`).")
    p = resolve_project(ctx, project)
    if isinstance(p, ToolResult):
        return p
    root = _repo_root(p) if shutil.which("git") else None
    before = _git(root, "status", "--porcelain") if root else ""
    proc = await asyncio.create_subprocess_exec(exe, "-p", task, "--output-format", "json", cwd=str(p),
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                creationflags=NO_WINDOW)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 900)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        raise
    after = _git(root, "status", "--porcelain") if root else ""
    changed = sorted(set(after.splitlines()) - set(before.splitlines()))
    text = out.decode("utf-8", "replace")
    try:
        import json

        result = json.loads(text).get("result", text)
    except ValueError:
        result = text
    ok = proc.returncode == 0
    msg = (result or err.decode("utf-8", "replace"))[:6000]
    return ToolResult(ok, msg, data={"changed": changed, "exit_code": proc.returncode})
