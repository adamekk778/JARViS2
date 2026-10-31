"""OMEGA §28 / §47 developer lab: dependencies (risks, known vulnerabilities, SBOM, an update plan), test coverage from
reports, mutation testing, API contracts and breaking changes, a migration preview on a copy, code ownership,
regressions and flaky tests from JUnit results, why a build failed, environment snapshots, release notes, feature
flags, the module dependency graph with cycles, and the packages of a monorepo.

Reading a project never changes it. Mutation testing and the migration preview work on copies in TEMP; only feature
flags write (into the flags file the user names)."""
from __future__ import annotations

import ast
import copy
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".tox", ".mypy_cache",
             ".pytest_cache", ".next", "target", "bin", "obj", ".idea", ".vscode", "coverage", ".gradle"}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def walk(root: Path, exts: tuple[str, ...], limit: int = 5000) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(exts):
                out.append(Path(dirpath) / f)
                if len(out) >= limit:
                    return out
    return out


# ============================================================================================== 333 / 624 / 625 deps
def _req_line(line: str) -> tuple[str, str] | None:
    line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()     # pip: a comment needs whitespace before '#'
    if not line or line.startswith(("-", "--")):
        return None
    if "://" in line or line.startswith("git+"):
        m = re.search(r"#egg=([\w.\-]+)", line) or re.match(r"([\w.\-]+)\s*@", line)
        return ((m.group(1) if m else line[:60]), line)
    m = re.match(r"([A-Za-z0-9][\w.\-]*)(\[[^\]]*\])?\s*(.*)", line)
    if not m:
        return None
    return m.group(1), m.group(3).split(";", 1)[0].strip()


def _pin(spec: str) -> str | None:
    m = re.fullmatch(r"==\s*([\w.\-+]+)", spec.strip())
    if m:
        return m.group(1)
    m = re.fullmatch(r"\^?~?([0-9][\w.\-+]*)", spec.strip())          # npm "1.2.3", "^1.2.3", "~1.2.3"
    return m.group(1) if m else None


def dependencies(root: Path) -> list[dict]:
    """Declared dependencies from requirements*.txt, pyproject.toml, package.json – with the locked version from
    package-lock.json / poetry.lock where there is one."""
    out: list[dict] = []

    def add(eco, name, spec, src, dev=False):
        out.append({"ecosystem": eco, "name": name, "spec": spec, "version": _pin(spec), "dev": dev, "file": src})
    for req in sorted(root.glob("requirements*.txt")):
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            r = _req_line(line)
            if r:
                add("pypi", r[0], r[1], req.name, dev="dev" in req.name or "test" in req.name)
    py = root / "pyproject.toml"
    if py.is_file():
        data = tomllib.loads(py.read_text(encoding="utf-8"))
        for line in data.get("project", {}).get("dependencies", []):
            r = _req_line(line)
            if r:
                add("pypi", r[0], r[1], "pyproject.toml")
        for group, lines in data.get("project", {}).get("optional-dependencies", {}).items():
            for line in lines:
                r = _req_line(line)
                if r:
                    add("pypi", r[0], r[1], f"pyproject.toml [{group}]", dev=group in ("dev", "test", "tests"))
        poetry = data.get("tool", {}).get("poetry", {})
        for key, dev in (("dependencies", False), ("dev-dependencies", True)):
            for name, spec in poetry.get(key, {}).items():
                if name.lower() != "python":
                    add("pypi", name, spec if isinstance(spec, str) else json.dumps(spec), "pyproject.toml (poetry)", dev)
    pj = root / "package.json"
    if pj.is_file():
        data = json.loads(pj.read_text(encoding="utf-8"))
        for key, dev in (("dependencies", False), ("devDependencies", True), ("optionalDependencies", False)):
            for name, spec in (data.get(key) or {}).items():
                add("npm", name, str(spec), "package.json", dev)
    lock = npm_lock(root)
    for d in out:
        if d["ecosystem"] == "npm" and d["name"] in lock:
            d["version"] = lock[d["name"]]["version"] or d["version"]
            d["locked"] = True
    plock = root / "poetry.lock"
    if plock.is_file():
        pkgs = {p["name"].lower(): p.get("version") for p in tomllib.loads(plock.read_text(encoding="utf-8")).get("package", [])}
        for d in out:
            if d["ecosystem"] == "pypi" and d["name"].lower() in pkgs:
                d["version"], d["locked"] = pkgs[d["name"].lower()], True
    return out


def npm_lock(root: Path) -> dict[str, dict]:
    """Top-level packages of package-lock.json v2/v3: version, resolved URL, install scripts, licence."""
    f = root / "package-lock.json"
    if not f.is_file():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for key, p in (data.get("packages") or {}).items():
        if not key.startswith("node_modules/") or "/node_modules/" in key[len("node_modules/"):]:
            continue
        out[key[len("node_modules/"):]] = {"version": p.get("version"), "resolved": p.get("resolved", ""),
                                           "install_script": bool(p.get("hasInstallScript")), "license": p.get("license")}
    return out


POPULAR = {"pypi": ["requests", "numpy", "pandas", "django", "flask", "fastapi", "urllib3", "setuptools", "pillow", "boto3",
                    "matplotlib", "scipy", "pytest", "sqlalchemy", "pydantic", "httpx", "cryptography", "pyyaml", "beautifulsoup4",
                    "selenium", "openai", "anthropic", "colorama", "jinja2", "click", "six", "python-dateutil", "certifi"],
           "npm": ["react", "react-dom", "lodash", "express", "axios", "vue", "typescript", "webpack", "vite", "eslint", "jquery",
                   "moment", "chalk", "commander", "next", "dotenv", "uuid", "debug", "electron", "prettier", "jest", "socket.io"]}


def _lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def dep_risks(root: Path, deps: list[dict] | None = None) -> list[dict]:
    """OMEGA 333 / 625: unpinned versions, code straight from git/URL, install scripts, look-alike names of popular
    packages (typosquatting), missing licence."""
    deps = deps if deps is not None else dependencies(root)
    lock = npm_lock(root)
    out = []
    for d in deps:
        n, spec = d["name"], d["spec"].strip()
        if "://" in spec or spec.startswith(("git+", "github:", "file:")):
            out.append({**d, "risk": "vysoké", "why": "instaluje se přímo z git/URL – obsah se může kdykoli změnit"})
        elif not d.get("locked") and (not spec or spec in ("*", "latest") or re.fullmatch(r">=?\s*[\w.]+", spec)):
            out.append({**d, "risk": "střední", "why": "verze není omezená shora – při instalaci může přijít cokoli nového"})
        pop = POPULAR.get(d["ecosystem"], [])
        nl = n.lower().replace("_", "-")
        if nl not in pop:
            near = [p for p in pop if _lev(nl, p) <= (1 if len(p) <= 5 else 2)]
            if near:
                out.append({**d, "risk": "vysoké", "why": f"název se podobá populárnímu balíčku {near[0]} – ověř, že to není podvrh"})
        li = lock.get(n)
        if li and li["install_script"]:
            out.append({**d, "risk": "střední", "why": "spouští při instalaci vlastní skript"})
        if li and li["resolved"] and not li["resolved"].startswith("https://registry.npmjs.org/"):
            out.append({**d, "risk": "střední", "why": f"stahuje se odjinud než z registru npm ({li['resolved'][:60]})"})
    return out


def sbom(root: Path, name: str = "") -> dict:
    """OMEGA 624: a CycloneDX 1.5 software bill of materials (JSON)."""
    deps = dependencies(root)
    lock = npm_lock(root)
    comps = []
    seen = set()
    for d in deps:
        key = (d["ecosystem"], d["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        purl = f"pkg:{d['ecosystem']}/{d['name']}" + (f"@{d['version']}" if d["version"] else "")
        c = {"type": "library", "name": d["name"], "purl": purl, "scope": "optional" if d["dev"] else "required"}
        if d["version"]:
            c["version"] = d["version"]
        lic = (lock.get(d["name"]) or {}).get("license")
        if lic:
            c["licenses"] = [{"license": {"id" if re.fullmatch(r"[\w.\-+]+", lic) else "name": lic}}]
        comps.append(c)
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "tools": [{"name": "JARVIS"}], "component": {"type": "application", "name": name or root.name}},
            "components": comps}


async def osv_check(client, deps: list[dict]) -> list[dict]:
    """Known vulnerabilities from the public OSV database (osv.dev) for pinned / locked versions."""
    q = [d for d in deps if d["version"]]
    if not q:
        return []
    eco = {"pypi": "PyPI", "npm": "npm"}
    r = await client.post("https://api.osv.dev/v1/querybatch", json={"queries": [
        {"package": {"name": d["name"], "ecosystem": eco[d["ecosystem"]]}, "version": d["version"]} for d in q]})
    r.raise_for_status()
    out = []
    for d, res in zip(q, r.json().get("results", [])):
        ids = [v["id"] for v in res.get("vulns") or []]
        if ids:
            out.append({"name": d["name"], "version": d["version"], "ecosystem": d["ecosystem"], "vulns": ids})
    return out


def _vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def bump(cur: str, new: str) -> str:
    a, b = _vt(cur) + (0, 0, 0), _vt(new) + (0, 0, 0)
    if b[:3] <= a[:3]:
        return "aktuální"
    return "major" if b[0] != a[0] else "minor" if b[1] != a[1] else "patch"


async def latest_versions(client, deps: list[dict]) -> dict[str, str]:
    out = {}
    for d in deps[:80]:
        try:
            if d["ecosystem"] == "pypi":
                r = await client.get(f"https://pypi.org/pypi/{d['name']}/json")
                out[d["name"]] = r.json()["info"]["version"] if r.status_code == 200 else ""
            else:
                r = await client.get(f"https://registry.npmjs.org/{d['name']}/latest")
                out[d["name"]] = r.json().get("version", "") if r.status_code == 200 else ""
        except Exception:  # noqa: BLE001 – one unreachable package does not stop the plan
            out[d["name"]] = ""
    return out


def update_plan(deps: list[dict], latest: dict[str, str]) -> dict:
    """OMEGA 341: patches first (safe), then minor, then major one by one with a test run after each."""
    groups: dict[str, list] = {"patch": [], "minor": [], "major": [], "aktuální": [], "neznámé": []}
    for d in deps:
        new = latest.get(d["name"]) or ""
        if not d["version"] or not new:
            groups["neznámé"].append({"name": d["name"], "current": d["version"], "latest": new})
            continue
        groups[bump(d["version"], new)].append({"name": d["name"], "current": d["version"], "latest": new})
    steps = []
    if groups["patch"]:
        steps.append("1. Opravné verze (patch) najednou: " + ", ".join(x["name"] for x in groups["patch"]) + " → spustit testy.")
    if groups["minor"]:
        steps.append(f"{len(steps) + 1}. Menší verze (minor) najednou: " + ", ".join(x["name"] for x in groups["minor"]) + " → testy.")
    for x in groups["major"]:
        steps.append(f"{len(steps) + 1}. {x['name']} {x['current']} → {x['latest']} (velká změna: přečíst changelog, samostatně, testy).")
    return {"groups": groups, "steps": steps}


# ============================================================================================== 334 coverage
def coverage(path: Path) -> dict:
    """Reads an existing report: Cobertura coverage.xml, lcov.info or coverage.py JSON."""
    text = path.read_text(encoding="utf-8", errors="replace")
    files: dict[str, dict] = {}
    if path.suffix == ".json":
        data = json.loads(text)
        for f, d in data.get("files", {}).items():
            s = d.get("summary", {})
            files[f] = {"lines": s.get("num_statements", 0), "covered": s.get("covered_lines", 0), "missing": d.get("missing_lines", [])}
    elif text.lstrip().startswith("<"):
        for cls in ET.fromstring(text).iter("class"):
            f = cls.get("filename", "?")
            lines = cls.findall("./lines/line")
            ent = files.setdefault(f, {"lines": 0, "covered": 0, "missing": []})
            for ln in lines:
                ent["lines"] += 1
                if int(ln.get("hits", "0")) > 0:
                    ent["covered"] += 1
                else:
                    ent["missing"].append(int(ln.get("number", "0")))
    else:
        cur = None
        for line in text.splitlines():
            if line.startswith("SF:"):
                cur = files.setdefault(line[3:], {"lines": 0, "covered": 0, "missing": []})
            elif line.startswith("DA:") and cur is not None:
                n, hits = line[3:].split(",")[:2]
                cur["lines"] += 1
                if int(hits) > 0:
                    cur["covered"] += 1
                else:
                    cur["missing"].append(int(n))
    if not files:
        raise ValueError("V souboru nevidím report pokrytí (coverage.xml, lcov.info nebo coverage.json).")
    rows = []
    for f, d in files.items():
        pct = round(100 * d["covered"] / d["lines"], 1) if d["lines"] else 100.0
        rows.append({"file": f, "pct": pct, "lines": d["lines"], "missing": len(d["missing"]), "ranges": _ranges(sorted(d["missing"]))[:8]})
    tl, tc = sum(d["lines"] for d in files.values()), sum(d["covered"] for d in files.values())
    return {"total_pct": round(100 * tc / tl, 1) if tl else 100.0, "files": sorted(rows, key=lambda r: (r["pct"], -r["lines"]))}


def _ranges(nums: list[int]) -> list[str]:
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}" if start == prev else f"{start}–{prev}")
            start = prev = n
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}–{prev}")
    return out


# ============================================================================================== 335 mutation testing
SWAP_CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
SWAP_OP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.Div: ast.Mult, ast.FloorDiv: ast.Mult, ast.Mod: ast.Mult}


def mutants(source: str, limit: int | None = None) -> list[dict]:
    """Every single-point mutation of a Python file: comparisons flipped, arithmetic swapped, and/or swapped,
    True/False and numeric constants changed, `return x` → `return None`."""
    tree = ast.parse(source)
    spots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in SWAP_CMP:
                    spots.append((node, "cmp", i, f"{type(op).__name__} → {SWAP_CMP[type(op)].__name__}"))
        elif isinstance(node, ast.BinOp) and type(node.op) in SWAP_OP:
            spots.append((node, "op", None, f"{type(node.op).__name__} → {SWAP_OP[type(node.op)].__name__}"))
        elif isinstance(node, ast.BoolOp):
            spots.append((node, "bool", None, "and ↔ or"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            spots.append((node, "const", None, f"{node.value} → {not node.value}"))
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float) and not isinstance(node.value, bool):
            spots.append((node, "num", None, f"{node.value} → {node.value + 1}"))
        elif isinstance(node, ast.Return) and node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            spots.append((node, "ret", None, "return … → return None"))
    order = {id(n): k for k, n in enumerate(ast.walk(tree))}
    total = len(spots)
    if limit and total > limit:                       # spread over the whole file, not just its top
        spots = [spots[round(k * (total - 1) / max(1, limit - 1))] for k in range(limit)]
    out = []
    for idx, (node, kind, i, label) in enumerate(spots):
        t2 = copy.deepcopy(tree)
        target = list(ast.walk(t2))[order[id(node)]]
        if kind == "cmp":
            target.ops[i] = SWAP_CMP[type(target.ops[i])]()
        elif kind == "op":
            target.op = SWAP_OP[type(target.op)]()
        elif kind == "bool":
            target.op = ast.Or() if isinstance(target.op, ast.And) else ast.And()
        elif kind == "const":
            target.value = not target.value
        elif kind == "num":
            target.value = target.value + 1
        elif kind == "ret":
            target.value = ast.Constant(None)
        out.append({"id": idx, "line": getattr(node, "lineno", 0), "change": label, "source": ast.unparse(t2), "of": total})
    return out


def _copy_project(root: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-mut-"))
    dst = tmp / root.name
    shutil.copytree(root, dst, ignore=shutil.ignore_patterns(*SKIP_DIRS - {"bin", "obj", "build", "dist", "target"}))
    return dst


def run_cmd(cmd: list[str] | str, cwd: Path, timeout: float) -> tuple[int | None, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return None, "časový limit"


def mutation_test(root: Path, target: Path, test_cmd: str, max_mutants: int = 25, timeout: float = 120) -> dict:
    """OMEGA 335: on a COPY of the project – the tests must pass first, then each mutant is written in and the tests
    run again. A mutant that survives (tests still pass) shows a place the tests do not really check."""
    rel = target.resolve().relative_to(root.resolve())
    work = _copy_project(root)
    try:
        code, out = run_cmd(test_cmd, work, timeout)
        if code != 0:
            return {"ok": False, "error": "Testy neprošly už bez úprav – nejdřív je oprav.", "output": out[-1500:]}
        chosen = mutants(target.read_text(encoding="utf-8"), max_mutants)
        f = work / rel
        original = f.read_text(encoding="utf-8")
        results = []
        for m in chosen:
            f.write_text(m["source"], encoding="utf-8")
            c, _ = run_cmd(test_cmd, work, timeout)
            results.append({"line": m["line"], "change": m["change"], "killed": c != 0})
        f.write_text(original, encoding="utf-8")
        killed = sum(r["killed"] for r in results)
        return {"ok": True, "total": chosen[0]["of"] if chosen else 0, "tested": len(results), "killed": killed,
                "score": round(100 * killed / len(results)) if results else 100, "survived": [r for r in results if not r["killed"]]}
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)


# ============================================================================================== 336 / 627 API contracts
def load_spec(path: Path) -> dict:
    import yaml

    text = path.read_text(encoding="utf-8")
    spec = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(spec, dict) or "paths" not in spec:
        raise ValueError(f"{path.name} není specifikace OpenAPI (chybí „paths“).")
    return spec


def _ref(spec: dict, node: Any, depth: int = 0) -> Any:
    while isinstance(node, dict) and "$ref" in node and depth < 20:
        cur: Any = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part.replace("~1", "/").replace("~0", "~")]
        node, depth = cur, depth + 1
    return node


TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate(spec: dict, schema: Any, value: Any, where: str = "$") -> list[str]:
    """A small JSON-Schema check (type, required, properties, additionalProperties: false, items, enum, nullable,
    allOf / anyOf / oneOf, min/max length)."""
    s = _ref(spec, schema) or {}
    errs: list[str] = []
    if value is None:
        return [] if s.get("nullable") or s.get("type") == "null" or not s.get("type") else [f"{where}: je null"]
    for key in ("anyOf", "oneOf"):
        if key in s:
            if not any(not validate(spec, sub, value, where) for sub in s[key]):
                errs.append(f"{where}: neodpovídá žádné variantě ({key})")
            return errs
    for sub in s.get("allOf", []):
        errs += validate(spec, sub, value, where)
    t = s.get("type")
    if t in TYPES and (not isinstance(value, TYPES[t]) or (t in ("integer", "number") and isinstance(value, bool))):
        return errs + [f"{where}: čekám {t}, je {type(value).__name__}"]
    if "enum" in s and value not in s["enum"]:
        errs.append(f"{where}: hodnota {value!r} není v {s['enum']}")
    if isinstance(value, str):
        if "minLength" in s and len(value) < s["minLength"]:
            errs.append(f"{where}: kratší než {s['minLength']}")
        if "maxLength" in s and len(value) > s["maxLength"]:
            errs.append(f"{where}: delší než {s['maxLength']}")
    if isinstance(value, dict):
        props = s.get("properties", {})
        for r in s.get("required", []):
            if r not in value:
                errs.append(f"{where}.{r}: chybí (povinné)")
        for k, v in value.items():
            if k in props:
                errs += validate(spec, props[k], v, f"{where}.{k}")
            elif s.get("additionalProperties") is False:
                errs.append(f"{where}.{k}: pole navíc, které kontrakt nezná")
    if isinstance(value, list) and "items" in s:
        for i, v in enumerate(value[:200]):
            errs += validate(spec, s["items"], v, f"{where}[{i}]")
    return errs


def _match_path(spec: dict, url_path: str) -> tuple[str, dict] | None:
    for p, ops in spec.get("paths", {}).items():
        rx = "^" + re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(p)) + "/?$"
        if re.match(rx, url_path):
            return p, ops
    return None


def response_schema(spec: dict, url_path: str, method: str, status: int) -> tuple[str, Any]:
    m = _match_path(spec, url_path)
    if not m:
        raise ValueError(f"Cesta {url_path} ve specifikaci není.")
    p, ops = m
    op = ops.get(method.lower())
    if not op:
        raise ValueError(f"{method.upper()} {p} ve specifikaci není.")
    res = op.get("responses", {})
    r = _ref(spec, res.get(str(status)) or res.get(f"{str(status)[0]}XX") or res.get("default"))
    if r is None:
        raise ValueError(f"Kontrakt nezná odpověď {status} pro {method.upper()} {p}.")
    content = (r.get("content") or {})
    schema = (content.get("application/json") or next(iter(content.values()), {})).get("schema") if content else r.get("schema")
    return p, schema


def check_response(spec: dict, url_path: str, method: str, status: int, body: Any) -> dict:
    p, schema = response_schema(spec, url_path, method, status)
    errs = validate(spec, schema, body) if schema is not None else []
    return {"path": p, "method": method.upper(), "status": status, "ok": not errs, "errors": errs[:50]}


def _props(spec: dict, schema: Any, depth: int = 0) -> dict[str, tuple[str, bool]]:
    """Flattened properties: 'a.b' → (type, required)."""
    s = _ref(spec, schema) or {}
    out: dict[str, tuple[str, bool]] = {}
    if depth > 6:
        return out
    for sub in s.get("allOf", []):
        out.update(_props(spec, sub, depth + 1))
    if s.get("type") == "array" and "items" in s:
        return {f"[]{'.' + k if k else ''}": v for k, v in _props(spec, s["items"], depth + 1).items()} or {"[]": (str(_ref(spec, s["items"]).get("type")), True)}
    req = set(s.get("required", []))
    for k, v in (s.get("properties") or {}).items():
        vv = _ref(spec, v) or {}
        out[k] = (str(vv.get("type", "object")), k in req)
        for kk, t in _props(spec, vv, depth + 1).items():
            out[f"{k}.{kk}"] = t
    return out


def breaking_changes(old: dict, new: dict) -> dict:
    """OMEGA 336 / 627: what in the NEW contract breaks existing clients (and what was only added)."""
    breaking, added = [], []
    for p, ops in old.get("paths", {}).items():
        nops = new.get("paths", {}).get(p)
        for m, op in ops.items():
            if m not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue
            if not nops or m not in nops:
                breaking.append(f"{m.upper()} {p}: endpoint odstraněn")
                continue
            nop = nops[m]
            oldp = {(x.get("in"), x.get("name")): x for x in map(lambda y: _ref(old, y), op.get("parameters", []))}
            for x in map(lambda y: _ref(new, y), nop.get("parameters", [])):
                k = (x.get("in"), x.get("name"))
                if x.get("required") and (k not in oldp or not oldp[k].get("required")):
                    breaking.append(f"{m.upper()} {p}: nový povinný parametr {x.get('name')}")
            ob = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
            nb = ((nop.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
            if nb is not None:
                op_props = _props(old, ob) if ob is not None else {}
                for k, (t, req) in _props(new, nb).items():
                    if req and (k not in op_props or not op_props[k][1]):
                        breaking.append(f"{m.upper()} {p}: tělo požadavku – nové povinné pole {k}")
            for code, r in (op.get("responses") or {}).items():
                if not str(code).startswith("2"):
                    continue
                nr = (nop.get("responses") or {}).get(code)
                if nr is None:
                    breaking.append(f"{m.upper()} {p}: odpověď {code} odstraněna")
                    continue
                os_ = ((_ref(old, r).get("content") or {}).get("application/json") or {}).get("schema")
                ns_ = ((_ref(new, nr).get("content") or {}).get("application/json") or {}).get("schema")
                if os_ is None or ns_ is None:
                    continue
                po, pn = _props(old, os_), _props(new, ns_)
                for k, (t, _) in po.items():
                    if k not in pn:
                        breaking.append(f"{m.upper()} {p}: v odpovědi {code} chybí pole {k}")
                    elif pn[k][0] != t:
                        breaking.append(f"{m.upper()} {p}: pole {k} změnilo typ {t} → {pn[k][0]}")
                added += [f"{m.upper()} {p}: nové pole {k} v odpovědi" for k in pn if k not in po]
    for p, ops in new.get("paths", {}).items():
        for m in ops:
            if m in ("get", "post", "put", "patch", "delete") and m not in old.get("paths", {}).get(p, {}):
                added.append(f"{m.upper()} {p}: nový endpoint")
    return {"breaking": breaking, "added": added, "compatible": not breaking}


# ============================================================================================== 337 migration preview
def migration_preview(db: Path, sql: str) -> dict:
    """Runs the migration on a COPY of the SQLite database and shows what it would do – the original stays."""
    import sqlite3

    from . import dbintel

    tmp = Path(tempfile.mkdtemp(prefix="jarvis-mig-"))
    copy_ = tmp / db.name
    try:
        src = dbintel.ro(db)
        try:
            dst = sqlite3.connect(str(copy_))
            src.backup(dst)
            dst.close()
        finally:
            src.close()
        before = dbintel.schema(copy_)
        con = sqlite3.connect(str(copy_))
        t0 = time.perf_counter()
        try:
            con.executescript(sql)
            error = None
        except sqlite3.Error as e:
            error = str(e)
        finally:
            con.close()
        secs = round(time.perf_counter() - t0, 3)
        after = dbintel.schema(copy_)
        rows_b = {t["name"]: t["rows"] for t in before["tables"]}
        rows_a = {t["name"]: t["rows"] for t in after["tables"]}
        integ = dbintel.integrity(copy_)
        return {"ok": error is None and integ["ok"], "error": error, "seconds": secs, "drift": dbintel.drift(db, copy_),
                "rows": {t: {"before": rows_b.get(t), "after": rows_a.get(t)} for t in set(rows_a) & set(rows_b) if rows_a[t] != rows_b[t]},
                "integrity": integ["ok"]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================================== 338 ownership
def git(repo: Path, *args: str, timeout: int = 60) -> str:
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip()[:300] or f"git {args[0]} selhal")
    return r.stdout


def ownership(repo: Path, commits: int = 2000) -> dict:
    """OMEGA 338: who changes which files and folders most (by commits), and the "bus factor" – how many people hold
    half of the work."""
    out = git(repo, "log", f"-{commits}", "--no-merges", "--format=\x01%aN", "--name-only")
    per_file: dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    for block in out.split("\x01")[1:]:
        lines = [x for x in block.splitlines() if x.strip()]
        if not lines:
            continue
        who, files = lines[0], lines[1:]
        total[who] += 1
        for f in files:
            per_file[f][who] += 1
    existing = {f for f in per_file if (repo / f).exists()}
    folders: dict[str, Counter] = defaultdict(Counter)
    for f in existing:
        folders[f.split("/", 1)[0] if "/" in f else "."].update(per_file[f])
    def owner(c: Counter) -> dict:
        who, n = c.most_common(1)[0]
        return {"owner": who, "share": round(100 * n / sum(c.values())), "authors": len(c)}
    acc, bus = 0, 0
    for _, n in total.most_common():
        acc += n
        bus += 1
        if acc >= sum(total.values()) / 2:
            break
    single = sorted(f for f in existing if len(per_file[f]) == 1 and sum(per_file[f].values()) >= 3)
    return {"authors": dict(total.most_common()), "bus_factor": bus,
            "folders": {k: owner(v) for k, v in sorted(folders.items())},
            "files": {f: owner(per_file[f]) for f in sorted(existing)}, "single_owner": single[:50]}


# ============================================================================================== 339 / 636 test results
def junit(path: Path) -> dict[str, dict]:
    """JUnit XML (pytest --junitxml, jest-junit, Maven, .NET …) → {test id: {status, seconds, message}}."""
    root = ET.parse(path).getroot()
    out = {}
    for tc in root.iter("testcase"):
        tid = f"{tc.get('classname') or tc.get('file') or ''}::{tc.get('name')}".lstrip(":")
        status, msg = "passed", ""
        for tag in ("failure", "error"):
            el = tc.find(tag)
            if el is not None:
                status, msg = "failed", (el.get("message") or el.text or "").strip()[:300]
        if tc.find("skipped") is not None:
            status = "skipped"
        out[tid] = {"status": status, "seconds": float(tc.get("time") or 0), "message": msg}
    if not out:
        raise ValueError(f"{path.name}: žádné testy (čekám JUnit XML).")
    return out


def regressions(before: dict[str, dict], after: dict[str, dict], slow_factor: float = 2.0) -> dict:
    """OMEGA 339: what newly fails, what got fixed, what vanished, what is much slower."""
    newly = [t for t, r in after.items() if r["status"] == "failed" and before.get(t, {}).get("status") == "passed"]
    fixed = [t for t, r in after.items() if r["status"] == "passed" and before.get(t, {}).get("status") == "failed"]
    still = [t for t, r in after.items() if r["status"] == "failed" and before.get(t, {}).get("status") == "failed"]
    gone = [t for t in before if t not in after]
    new = [t for t in after if t not in before]
    slower = [{"test": t, "before": before[t]["seconds"], "after": r["seconds"]} for t, r in after.items()
              if t in before and before[t]["seconds"] >= 0.05 and r["seconds"] >= before[t]["seconds"] * slow_factor]
    return {"regressions": [{"test": t, "message": after[t]["message"]} for t in newly], "fixed": fixed, "still_failing": still,
            "removed": gone, "new": new, "slower": slower}


def flaky(runs: list[dict[str, dict]]) -> list[dict]:
    """OMEGA 636: tests that both passed and failed across runs of the same code."""
    seen: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        for t, v in r.items():
            if v["status"] != "skipped":
                seen[t].append(v["status"])
    out = []
    for t, st in seen.items():
        f = st.count("failed")
        if 0 < f < len(st):
            out.append({"test": t, "failed": f, "runs": len(st), "rate": round(100 * f / len(st))})
    return sorted(out, key=lambda x: -x["rate"])


# ============================================================================================== 340 build failure
BUILD_RULES: list[tuple[str, str, str]] = [
    (r"ModuleNotFoundError: No module named '([^']+)'", "chybí Python balíček {0}", "pip install {0} (a přidej ho do requirements / pyproject)"),
    (r"Cannot find module '([^']+)'", "chybí balíček nebo soubor {0} (Node)", "npm install; když je to tvůj soubor, zkontroluj cestu importu"),
    (r"npm ERR! code ERESOLVE", "konflikt verzí závislostí (npm)", "srovnej verze v package.json, nouzově npm install --legacy-peer-deps"),
    (r"(\S+\.tsx?)\((\d+),\d+\): error (TS\d+): (.+)|(\S+\.tsx?):(\d+):\d+ - error (TS\d+): (.+)", "chyba TypeScriptu", "oprav typ na uvedeném místě"),
    (r"SyntaxError: (.+)", "syntaktická chyba: {0}", "oprav syntaxi na uvedeném řádku"),
    (r"error\[E\d+\]: (.+)", "chyba Rustu: {0}", "oprav kód podle hlášky kompilátoru"),
    (r"error CS\d+: (.+)", "chyba C#: {0}", "oprav kód podle hlášky kompilátoru"),
    (r"(JavaScript heap out of memory|MemoryError|OutOfMemoryError|Killed\s+signal 9|exit code 137)", "došla paměť", "víc paměti (NODE_OPTIONS=--max-old-space-size=4096) nebo menší build"),
    (r"(No space left on device|ENOSPC)", "došlo místo na disku", "uvolni místo / smaž cache"),
    (r"(ETIMEDOUT|ECONNRESET|Could not resolve host|Temporary failure in name resolution|getaddrinfo ENOTFOUND|Read timed out)", "síť nebo registr balíčků nedostupný", "zopakuj; když trvá, zkontroluj proxy / výpadek registru"),
    (r"(EACCES|Permission denied|Access is denied)", "chybí oprávnění k souboru", "zkontroluj, jestli soubor nedrží jiný program nebo antivir"),
    (r"(\d+) failed(, \d+ passed)?", "neprošly testy ({0})", "podívej se na první neprošlý test výše"),
    (r"FAILED (\S+)", "neprošel test {0}", "spusť jen ten test a oprav ho"),
    (r"(The operation was canceled|exceeded the maximum execution time|timed out after)", "vypršel čas", "najdi krok, který visí (bez výstupu), a dej mu limit"),
    (r"(?i)\berror\b[: ](.+)", "chyba: {0}", "podívej se na první chybu ve výpisu"),
]


def build_failure(log: str) -> dict:
    """OMEGA 340: the FIRST real error in a build / CI log, what it means and what to do, with its file:line."""
    lines = log.splitlines()
    for rx, what, fix in BUILD_RULES:
        for i, line in enumerate(lines):
            m = re.search(rx, line)
            if m:
                g = [x for x in m.groups() if x] or [m.group(0)]
                loc = re.search(r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|rs|cs|go|java|kt|cpp|c|h))[:(](\d+)", line) or \
                      next((re.search(r'File "([^"]+)", line (\d+)', lines[j]) for j in range(i, max(-1, i - 15), -1)
                            if re.search(r'File "([^"]+)", line (\d+)', lines[j])), None)
                return {"found": True, "what": what.format(*g), "fix": fix.format(*g), "line_no": i + 1, "line": line.strip()[:300],
                        "where": f"{loc.group(1)}:{loc.group(2)}" if loc else "", "context": lines[max(0, i - 3): i + 4]}
    return {"found": False, "what": "ve výpisu nevidím chybu", "fix": "", "line_no": 0, "line": "", "where": "", "context": lines[-8:]}


# ============================================================================================== 342 environment
def env_snapshot() -> dict:
    """OMEGA 342: what the code runs on – OS, Python and its packages, Node, npm, git, .NET versions. No environment
    variables (they can hold secrets)."""
    from importlib import metadata

    tools = {}
    for name, cmd in (("node", ["node", "--version"]), ("npm", ["npm", "--version"]), ("git", ["git", "--version"]),
                      ("dotnet", ["dotnet", "--version"]), ("java", ["java", "-version"])):
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        code, out = run_cmd([exe, *cmd[1:]], Path.cwd(), 15)
        m = re.search(r"\d+(\.\d+)+", out or "")
        tools[name] = m.group(0) if m else (out or "").strip()[:40]
    pkgs = {}
    for d in metadata.distributions():
        try:
            pkgs[d.metadata["Name"].lower()] = d.version
        except Exception:  # noqa: BLE001 – a broken install entry
            continue
    return {"os": f"{platform.system()} {platform.release()} ({platform.version()[:40]})", "machine": platform.machine(),
            "python": platform.python_version(), "tools": tools, "packages": dict(sorted(pkgs.items())),
            "taken": time.strftime("%Y-%m-%d %H:%M:%S")}


def env_diff(a: dict, b: dict) -> dict:
    out = {"os": [a.get("os"), b.get("os")] if a.get("os") != b.get("os") else None,
           "python": [a.get("python"), b.get("python")] if a.get("python") != b.get("python") else None, "tools": {}, "packages": {}}
    for k in set(a.get("tools", {})) | set(b.get("tools", {})):
        if a.get("tools", {}).get(k) != b.get("tools", {}).get(k):
            out["tools"][k] = [a.get("tools", {}).get(k), b.get("tools", {}).get(k)]
    pa, pb = a.get("packages", {}), b.get("packages", {})
    for k in set(pa) | set(pb):
        if pa.get(k) != pb.get(k):
            out["packages"][k] = [pa.get(k), pb.get(k)]
    out["same"] = not (out["os"] or out["python"] or out["tools"] or out["packages"])
    return out


def requirements_lock(snap: dict, only: list[str] | None = None) -> str:
    pk = snap.get("packages", {})
    names = [n.lower() for n in only] if only else sorted(pk)
    return "\n".join(f"{n}=={pk[n]}" for n in names if n in pk) + "\n"


# ============================================================================================== 343 release notes
KINDS = [("breaking", "Zásadní změny"), ("feat", "Novinky"), ("fix", "Opravy"), ("perf", "Rychlost"), ("security", "Bezpečnost"),
         ("docs", "Dokumentace"), ("refactor", "Úpravy kódu"), ("test", "Testy"), ("build", "Sestavení a CI"), ("other", "Ostatní")]
WORDS = [("security", r"(?i)\b(security|bezpečn|cve|xss|injection)"), ("fix", r"(?i)^(fix|oprav|bug|hotfix)|\bfix(es|ed)?\b|oprava"),
         ("feat", r"(?i)^(add|přid|nov[ýáé]|feature|implement|wave|vlna)"), ("perf", r"(?i)(perf|rychl|faster|speed|optimi)"),
         ("docs", r"(?i)^(docs?|readme|dokument)"), ("test", r"(?i)^(tests?|testy)\b"), ("build", r"(?i)^(ci|build|release|bump|chore\(deps\))"),
         ("refactor", r"(?i)^(refactor|clean|rename|přejmen|úklid)")]


def classify_commit(subject: str, body: str = "") -> tuple[str, str]:
    m = re.match(r"(\w+)(\([^)]*\))?(!)?:\s*(.+)", subject)
    if m:
        kind = m.group(1).lower()
        text = m.group(4)
        if m.group(3) or "BREAKING CHANGE" in body:
            return "breaking", text
        kind = {"feature": "feat", "bugfix": "fix", "chore": "build", "ci": "build", "style": "refactor", "sec": "security"}.get(kind, kind)
        return (kind if kind in dict(KINDS) else "other"), text
    if "BREAKING CHANGE" in body:
        return "breaking", subject
    return next((k for k, rx in WORDS if re.search(rx, subject)), "other"), subject


def release_notes(repo: Path, since: str = "", until: str = "HEAD", title: str = "") -> dict:
    """OMEGA 343: from the commits since the last tag (or `since`), grouped into what users care about."""
    if not since:
        try:
            since = git(repo, "describe", "--tags", "--abbrev=0", f"{until}^").strip()
        except ValueError:
            since = ""
    rng = f"{since}..{until}" if since else until
    out = git(repo, "log", rng, "--no-merges", "--format=%h\x1f%s\x1f%aN\x1f%b\x1e")
    groups: dict[str, list[str]] = defaultdict(list)
    authors: Counter = Counter()
    n = 0
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        h, s, a, b = (rec.split("\x1f") + ["", "", "", ""])[:4]
        kind, text = classify_commit(s, b)
        groups[kind].append(f"{text[0].upper() + text[1:] if text else text} ({h})")
        authors[a] += 1
        n += 1
    md = [f"# {title or ('Změny od ' + since if since else 'Změny')}", ""]
    for k, label in KINDS:
        if groups.get(k):
            md += [f"## {label}", *[f"- {x}" for x in groups[k]], ""]
    md.append("Autoři: " + ", ".join(f"{a} ({c})" for a, c in authors.most_common()))
    return {"since": since, "commits": n, "groups": dict(groups), "markdown": "\n".join(md) + "\n"}


# ============================================================================================== 344 feature flags
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".java", ".kt", ".go", ".rs", ".vue", ".svelte", ".php", ".rb")
FLAG_CALL = r"""(?:isEnabled|is_enabled|feature_enabled|featureEnabled|flag|useFlag|use_flag|getFlag|get_flag|FLAGS|flags)\s*[\(\[]\s*['"]([\w.\-]+)['"]"""


def flags_load(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: čekám objekt {{název: true/false}}.")
    return data


def flag_value(v: Any) -> bool:
    return bool(v.get("enabled")) if isinstance(v, dict) else bool(v)


def flags_report(root: Path, flags_file: Path) -> dict:
    """OMEGA 344: every flag, whether it is on, where the code uses it; flags nobody uses any more (stale) and flags
    the code asks for that are not defined."""
    flags = flags_load(flags_file)
    used: dict[str, list[str]] = defaultdict(list)
    called: dict[str, list[str]] = defaultdict(list)
    for f in walk(root, CODE_EXT):
        if f.resolve() == flags_file.resolve():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(text.splitlines(), 1):
            for name in flags:
                if re.search(rf"""['"]{re.escape(name)}['"]""", line):
                    used[name].append(f"{rel}:{i}")
            for m in re.finditer(FLAG_CALL, line):
                called[m.group(1)].append(f"{rel}:{i}")
    rows = [{"name": n, "on": flag_value(v), "uses": used.get(n, [])[:20], "count": len(used.get(n, []))} for n, v in flags.items()]
    return {"flags": rows, "stale": [r["name"] for r in rows if not r["count"]],
            "undefined": {n: w[:5] for n, w in called.items() if n not in flags}}


def flag_set(flags_file: Path, name: str, on: bool) -> dict:
    flags = flags_load(flags_file)
    if not re.fullmatch(r"[\w.\-]{1,80}", name):
        raise ValueError("Název přepínače: písmena, číslice, tečka, pomlčka, podtržítko.")
    old = flags.get(name)
    flags[name] = {**old, "enabled": on} if isinstance(old, dict) else on
    tmp = flags_file.with_suffix(flags_file.suffix + ".tmp")
    tmp.write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, flags_file)
    return {"name": name, "before": None if old is None else flag_value(old), "after": on}


# ============================================================================================== 332 module graph / 619 monorepo
def _py_imports(f: Path, root: Path, modules: dict[str, Path]) -> set[str]:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    me = _modname(f, root)
    pkg = me.rsplit(".", 1)[0] if f.name != "__init__.py" else me
    out = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
            names = [base] + [f"{base}.{a.name}" for a in node.names]
        for n in names:
            while n:
                if n in modules and n != me:
                    out.add(n)
                    break
                n = n.rsplit(".", 1)[0] if "." in n else ""
    return out


def _modname(f: Path, root: Path) -> str:
    rel = f.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or root.name


def _js_imports(f: Path, root: Path, files: dict[str, str]) -> set[str]:
    text = f.read_text(encoding="utf-8", errors="replace")
    out = set()
    for m in re.finditer(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*|export\s[^'"]*?from\s*)['"](\.{1,2}/[^'"]+)['"]""", text):
        target = (f.parent / m.group(1)).resolve()
        for cand in (target, *(target.with_name(target.name + e) for e in (".ts", ".tsx", ".js", ".jsx")),
                     *(target / f"index{e}" for e in (".ts", ".tsx", ".js"))):
            key = str(cand)
            if key in files:
                out.add(files[key])
                break
    return out


def module_graph(root: Path) -> dict:
    """OMEGA 332: who imports whom (Python and TS/JS), dependency cycles, the most-depended-on modules, the biggest
    files – and a refactoring plan from that."""
    py = walk(root, (".py",))
    js = [f for f in walk(root, (".ts", ".tsx", ".js", ".jsx")) if not f.name.endswith(".d.ts")]
    edges: dict[str, set[str]] = {}
    lines: dict[str, int] = {}
    modules = {_modname(f, root): f for f in py}
    for name, f in modules.items():
        edges[name] = _py_imports(f, root, modules)
        lines[name] = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
    jsnames = {str(f.resolve()): str(f.relative_to(root)).replace("\\", "/") for f in js}
    for f in js:
        n = jsnames[str(f.resolve())]
        edges[n] = _js_imports(f, root, jsnames)
        lines[n] = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
    cycles = _sccs(edges)
    fan_in = Counter(t for ts in edges.values() for t in ts)
    plan = []
    for c in cycles:
        plan.append(f"Rozbít cyklus {' ↔ '.join(sorted(c)[:6])}: společnou část vytáhnout do samostatného modulu, nebo import přesunout do funkce.")
    for n, ln in sorted(lines.items(), key=lambda x: -x[1])[:5]:
        if ln >= 800:
            plan.append(f"{n} má {ln} řádků – rozdělit podle odpovědností.")
    for n, k in fan_in.most_common(3):
        if k >= max(8, len(edges) // 4) and lines.get(n, 0) > 300:
            plan.append(f"Na {n} závisí {k} modulů a má {lines[n]} řádků – změny v něm jsou riskantní; stabilizovat rozhraní a pokrýt testy.")
    return {"modules": len(edges), "edges": sum(len(v) for v in edges.values()), "cycles": [sorted(c) for c in cycles],
            "fan_in": fan_in.most_common(10), "fan_out": sorted(((n, len(v)) for n, v in edges.items()), key=lambda x: -x[1])[:10],
            "largest": sorted(lines.items(), key=lambda x: -x[1])[:10], "plan": plan, "graph": {k: sorted(v) for k, v in edges.items()}}


def _sccs(g: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan (iterative) – only components with more than one module are cycles."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on, stack, out, i = set(), [], [], 0
    for start in g:
        if start in index:
            continue
        work = [(start, iter(g.get(start, ())))]
        index[start] = low[start] = i
        i += 1
        stack.append(start)
        on.add(start)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in g:
                    continue
                if w not in index:
                    index[w] = low[w] = i
                    i += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(g.get(w, ()))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = set()
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.add(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        out.append(comp)
    return out


def monorepo(root: Path) -> dict:
    """OMEGA 619: the packages / apps in a repository and which of them depend on each other."""
    pkgs = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if Path(dirpath).relative_to(root).parts.__len__() > 4:
            dirs[:] = []
            continue
        p = Path(dirpath)
        rel = str(p.relative_to(root)).replace("\\", "/") or "."
        if "package.json" in files:
            try:
                d = json.loads((p / "package.json").read_text(encoding="utf-8"))
                deps = {**(d.get("dependencies") or {}), **(d.get("devDependencies") or {})}
                pkgs.append({"name": d.get("name") or rel, "kind": "npm", "path": rel, "deps": list(deps),
                             "scripts": sorted((d.get("scripts") or {}))[:12], "workspaces": d.get("workspaces")})
            except (json.JSONDecodeError, OSError):
                pass
        if "pyproject.toml" in files:
            try:
                d = tomllib.loads((p / "pyproject.toml").read_text(encoding="utf-8"))
                deps = [r[0] for r in map(_req_line, d.get("project", {}).get("dependencies", [])) if r]
                pkgs.append({"name": d.get("project", {}).get("name") or rel, "kind": "python", "path": rel, "deps": deps})
            except (tomllib.TOMLDecodeError, OSError):
                pass
        if "Cargo.toml" in files:
            try:
                d = tomllib.loads((p / "Cargo.toml").read_text(encoding="utf-8"))
                pkgs.append({"name": d.get("package", {}).get("name") or rel, "kind": "rust", "path": rel, "deps": list(d.get("dependencies", {}))})
            except (tomllib.TOMLDecodeError, OSError):
                pass
        for f in files:
            if f.endswith(".csproj"):
                pkgs.append({"name": f[:-7], "kind": ".net", "path": rel, "deps": []})
    names = {p["name"] for p in pkgs}
    for p in pkgs:
        p["internal"] = sorted(d for d in p["deps"] if d in names and d != p["name"])
        p["external"] = len([d for d in p["deps"] if d not in names])
        del p["deps"]
    return {"packages": pkgs, "count": len(pkgs)}


def python_exe() -> str:
    return sys.executable


# ---------------------------------------------------------------- 342 a container that matches "it works on my PC"
def container_files(project: Path, snap: dict | None = None) -> dict:
    """A Dockerfile, .dockerignore and .devcontainer/devcontainer.json for the project, with the same Python / Node major
    versions as this PC (from the environment snapshot). Answers {files: {rel: text}, kind, notes}; writes nothing."""
    snap = snap or {}
    has = lambda n: (project / n).exists()            # noqa: E731
    py = ".".join((snap.get("python") or "3.12").split(".")[:2])
    node = (snap.get("tools", {}).get("node") or "20").lstrip("v").split(".")[0]
    notes: list[str] = []
    if has("package.json") and not (has("pyproject.toml") or has("requirements.txt")):
        kind = "node"
        if has("pnpm-lock.yaml"):
            install = "corepack enable && pnpm install --frozen-lockfile"
        elif has("yarn.lock"):
            install = "corepack enable && yarn install --frozen-lockfile"
        elif has("package-lock.json"):
            install = "npm ci"
        else:
            install = "npm install"
            notes.append("Chybí package-lock.json – verze balíčků se v kontejneru můžou lišit; spusť jednou npm install a lock ulož do gitu.")
        try:
            pkg = json.loads((project / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pkg = {}
        start = "npm start" if (pkg.get("scripts") or {}).get("start") else "node ."
        docker = (f"FROM node:{node}-slim\nWORKDIR /app\nCOPY package*.json pnpm-lock.yaml* yarn.lock* ./\nRUN {install}\nCOPY . .\n"
                  f"CMD {json.dumps(start.split())}\n")
        image = f"mcr.microsoft.com/devcontainers/javascript-node:{node}"
    elif has("pyproject.toml") or has("requirements.txt"):
        kind = "python"
        if has("requirements.txt"):
            install = "pip install --no-cache-dir -r requirements.txt"
            copy_req = "COPY requirements.txt ./\n"
        else:
            install = "pip install --no-cache-dir ."
            copy_req = "COPY . .\n"
            notes.append("Bez requirements.txt se instaluje z pyproject.toml; pro přesné verze použij zámek (environment_snapshot → requirements_lock).")
        main = next((n for n in ("main.py", "app.py", "manage.py", "run.py") if has(n)), "")
        cmd = '["python", "' + main + '"]' if main else '["python"]'
        if not main:
            notes.append("Nenašel jsem main.py / app.py – uprav poslední řádek CMD na to, co se má spustit.")
        docker = (f"FROM python:{py}-slim\nENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\nWORKDIR /app\n{copy_req}RUN {install}\n"
                  + ("COPY . .\n" if copy_req != "COPY . .\n" else "") + f"CMD {cmd}\n")
        image = f"mcr.microsoft.com/devcontainers/python:{py}"
    elif any(project.glob("*.csproj")) or any(project.glob("*.sln")):
        kind = "dotnet"
        ver = ".".join((snap.get("tools", {}).get("dotnet") or "8.0").split(".")[:2])
        docker = (f"FROM mcr.microsoft.com/dotnet/sdk:{ver} AS build\nWORKDIR /src\nCOPY . .\nRUN dotnet publish -c Release -o /out\n\n"
                  f"FROM mcr.microsoft.com/dotnet/runtime:{ver}\nWORKDIR /app\nCOPY --from=build /out .\n"
                  'ENTRYPOINT ["dotnet", "' + next(project.glob("*.csproj")).stem + '.dll"]\n' if any(project.glob("*.csproj"))
                  else f"FROM mcr.microsoft.com/dotnet/sdk:{ver}\nWORKDIR /src\nCOPY . .\nRUN dotnet build -c Release\n")
        image = f"mcr.microsoft.com/devcontainers/dotnet:{ver}"
    else:
        raise ValueError("Nepoznal jsem druh projektu (chybí package.json, pyproject.toml / requirements.txt nebo .csproj).")
    ignore = "\n".join([".git", "node_modules", "__pycache__", "*.pyc", ".venv", "venv", "dist", "build", "bin", "obj", ".env", ".env.*", "*.log"]) + "\n"
    dev = json.dumps({"name": project.name, "image": image, "postCreateCommand": install if kind != "dotnet" else "dotnet restore"},
                     ensure_ascii=False, indent=2) + "\n"
    notes.append(".env se do obrazu nekopíruje (mohou v něm být hesla) – předávej ho při spuštění (docker run --env-file .env).")
    return {"kind": kind, "files": {"Dockerfile": docker, ".dockerignore": ignore, ".devcontainer/devcontainer.json": dev}, "notes": notes}
