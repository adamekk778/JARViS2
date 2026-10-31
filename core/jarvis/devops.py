"""Developer chores that leave files a person can read: CHANGELOG.md from commits (050), a build + tests check after
changes (058), a release package with checksums (060), a CI workflow for the project (626), architecture decision
records (618) and a throw-away copy to try code in (345). Nothing here pushes, publishes or deploys."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target", "bin", "obj",
             ".pytest_cache", ".mypy_cache", ".idea", ".vs"}


def kind_of(root: Path) -> str:
    if (root / "package.json").exists():
        return "node"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        return "python"
    if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
        return "dotnet"
    if (root / "Cargo.toml").exists():
        return "rust"
    return ""


# ---------------------------------------------------------------- 050 changelog
def changelog_entry(version: str, notes_md: str, date: dt.date | None = None) -> str:
    body = re.sub(r"^#\s.*\n+", "", notes_md.strip())          # the release notes' own title is replaced by the version line
    return f"## {version} – {(date or dt.date.today()).isoformat()}\n\n{body}\n"


def prepend_changelog(existing: str, entry: str) -> str:
    head = "# Changelog\n\n"
    rest = existing[len(head):] if existing.startswith(head) else existing
    return head + entry + ("\n" + rest.lstrip("\n") if rest.strip() else "")


# ---------------------------------------------------------------- 058 build + tests
def build_commands(root: Path) -> list[str]:
    """How this project is built and checked (in order): the build itself, then the tests."""
    k = kind_of(root)
    if k == "node":
        try:
            scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        out = [f"npm run {s}" for s in ("typecheck", "lint", "build") if s in scripts]
        if "test" in scripts and "no test specified" not in scripts["test"]:
            out.append("npm test")
        return out
    if k == "python":
        out = ["python -m compileall -q ."]
        if (root / "tests").is_dir() or any(root.glob("test_*.py")) or (root / "pytest.ini").exists():
            out.append("python -m pytest -q")
        return out
    if k == "dotnet":
        return ["dotnet build", "dotnet test"]
    if k == "rust":
        return ["cargo build", "cargo test"]
    return []


# ---------------------------------------------------------------- 060 release package
def project_files(root: Path, limit: int = 20000) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS or part.startswith(".env") for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            out.append(p)
            if len(out) >= limit:
                break
    return out


def package(root: Path, version: str, out_dir: Path | None = None, extra_files: dict[str, str] | None = None) -> dict:
    """dist/<name>-<version>.zip with the project's files (no .git, node_modules, .env…), SHA256SUMS and RELEASE.md."""
    if not re.fullmatch(r"[\w.\-+]{1,40}", version):
        raise ValueError("Verze: jen písmena, číslice, tečka, pomlčka (např. 1.2.0).")
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{root.name}-{version}"
    z = out_dir / f"{name}.zip"
    files = project_files(root)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f"{name}/{f.relative_to(root).as_posix()}")
        for rel, text in (extra_files or {}).items():
            zf.writestr(f"{name}/{rel}", text)
    sha = hashlib.sha256(z.read_bytes()).hexdigest()
    (out_dir / "SHA256SUMS").write_text(f"{sha}  {z.name}\n", encoding="utf-8")
    return {"zip": str(z), "files": len(files), "bytes": z.stat().st_size, "sha256": sha}


# ---------------------------------------------------------------- 626 CI workflow
def ci_workflow(root: Path, snap: dict | None = None) -> str:
    """A GitHub Actions workflow that installs, builds and tests the project on every push and pull request."""
    snap = snap or {}
    k = kind_of(root)
    head = ("name: CI\non:\n  push:\n  pull_request:\njobs:\n  build:\n    runs-on: ${{ matrix.os }}\n    strategy:\n"
            "      matrix:\n        os: [ubuntu-latest, windows-latest]\n    steps:\n      - uses: actions/checkout@v4\n")
    if k == "node":
        node = (snap.get("tools", {}).get("node") or "20").lstrip("v").split(".")[0]
        lock = "npm ci" if (root / "package-lock.json").exists() else "npm install"
        steps = [f"      - uses: actions/setup-node@v4\n        with:\n          node-version: {node}\n          cache: npm\n", f"      - run: {lock}\n"]
    elif k == "python":
        py = ".".join((snap.get("python") or "3.12").split(".")[:2])
        inst = "pip install -r requirements.txt" if (root / "requirements.txt").exists() else "pip install -e ."
        steps = [f"      - uses: actions/setup-python@v5\n        with:\n          python-version: '{py}'\n          cache: pip\n",
                 f"      - run: python -m pip install --upgrade pip && {inst} && pip install pytest\n"]
    elif k == "dotnet":
        ver = ".".join((snap.get("tools", {}).get("dotnet") or "8.0").split(".")[:2])
        steps = [f"      - uses: actions/setup-dotnet@v4\n        with:\n          dotnet-version: '{ver}.x'\n"]
    elif k == "rust":
        steps = ["      - uses: dtolnay/rust-toolchain@stable\n"]
    else:
        raise ValueError("Nepoznal jsem druh projektu (package.json, pyproject.toml / requirements.txt, .csproj, Cargo.toml).")
    for c in build_commands(root):
        steps.append(f"      - run: {c}\n")
    return head + "".join(steps)


# ---------------------------------------------------------------- 618 ADR
def adr(folder: Path, title: str, context: str, decision: str, consequences: str, status: str = "Přijato",
        date: dt.date | None = None) -> Path:
    """docs/adr/NNNN-nazev.md in the usual Michael Nygard shape; numbers continue from the existing records."""
    folder.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for f in folder.glob("*.md") if (m := re.match(r"(\d{4})-", f.name))]
    n = max(nums, default=0) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(title).lower()).strip("-")[:50] or "rozhodnuti"
    p = folder / f"{n:04d}-{slug}.md"
    p.write_text(f"# {n}. {title}\n\nDatum: {(date or dt.date.today()).isoformat()}\n\n## Stav\n\n{status}\n\n## Kontext\n\n{context.strip()}\n\n"
                 f"## Rozhodnutí\n\n{decision.strip()}\n\n## Důsledky\n\n{consequences.strip()}\n", encoding="utf-8")
    return p


def _ascii(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


# ---------------------------------------------------------------- 345 sandbox
def sandbox_copy(root: Path) -> Path:
    """A throw-away copy of the project (without .git, node_modules, venvs) to try things in."""
    dst = Path(tempfile.mkdtemp(prefix="jarvis-sandbox-")) / root.name
    shutil.copytree(root, dst, ignore=shutil.ignore_patterns(*SKIP_DIRS - {"bin", "obj"}, ".env*"))
    return dst


def changed_files(a: Path, b: Path) -> dict:
    """What differs between the original and the sandbox after the experiment."""
    def index(r: Path) -> dict[str, str]:
        return {f.relative_to(r).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in project_files(r)}
    ia, ib = index(a), index(b)
    return {"added": sorted(set(ib) - set(ia)), "removed": sorted(set(ia) - set(ib)),
            "changed": sorted(k for k in set(ia) & set(ib) if ia[k] != ib[k])}


# ---------------------------------------------------------------- 768 notebooks
MARK = "@@JARVIS-CELL@@"


def notebook_script(nb: dict) -> tuple[str, list[int]]:
    """The code cells as one script (shared state like in Jupyter), each announcing itself; %magics and !shell lines are
    left out (they need IPython). Returns the script and the indexes of the code cells."""
    lines, idx = ["import sys"], []
    for i, c in enumerate(nb.get("cells") or []):
        if c.get("cell_type") != "code":
            continue
        src = c.get("source") or ""
        src = "".join(src) if isinstance(src, list) else src
        body = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("%", "!"))]
        idx.append(i)
        lines.append(f"print({MARK!r} + {str(i)!r}, flush=True)")
        lines.append("try:")
        lines.append("    exec(compile(" + repr("\n".join(body) or "pass") + f", 'cell {i}', 'exec'))")
        lines.append("except Exception as _e:")
        lines.append("    import traceback; traceback.print_exc(); print('@@JARVIS-FAILED@@', flush=True); sys.exit(1)")
    return "\n".join(lines) + "\n", idx


def split_outputs(out: str) -> dict[int, str]:
    res: dict[int, str] = {}
    cur = None
    for ln in out.splitlines():
        if ln.startswith(MARK):
            cur = int(ln[len(MARK):])
            res[cur] = ""
        elif cur is not None:
            res[cur] += ln + "\n"
    return res


def notebook_with_outputs(nb: dict, outs: dict[int, str]) -> dict:
    import copy as _copy

    nb2 = _copy.deepcopy(nb)
    for i, c in enumerate(nb2.get("cells") or []):
        if c.get("cell_type") == "code" and i in outs:
            c["outputs"] = [{"output_type": "stream", "name": "stdout", "text": outs[i].replace("@@JARVIS-FAILED@@\n", "")}]
    return nb2
