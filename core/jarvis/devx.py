"""3.20 Programování+ (ideas 301–320): licences that do not fit, a quick review before a commit, the commit message,
CI watch, a README from the code, projects started by voice, regex and SQL from Czech, code by voice in the editor,
"go to login / who calls it", snippets, Czech test data, a change for non-technical people, ports and processes,
Docker, a rename with a preview, old TODOs, tidy JSON/YAML, a git helper that says what will happen, and code in
another language.

Everything that changes something (killing a process, a container, a rename, a git undo) is shown first and asks."""
from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS dx_snippets (id INTEGER PRIMARY KEY, title TEXT, lang TEXT, code TEXT, tags TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS dx_projects (name TEXT PRIMARY KEY, path TEXT, cmd TEXT);
"""
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache",
             ".next", "target", ".idea", ".vscode"}
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".java", ".kt", ".cs", ".go", ".rs", ".php", ".rb", ".c", ".h", ".cpp", ".hpp",
            ".swift", ".dart", ".vue", ".svelte", ".sql", ".sh", ".ps1"}


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_devx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._devx_ready = True
    return rt.db


def code_files(root: Path, limit: int = 4000):
    n = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(dirpath) / f
            if p.suffix.lower() in CODE_EXT:
                yield p
                n += 1
                if n >= limit:
                    return


def git(root: Path, *args: str, timeout: int = 30, runner=subprocess.run) -> tuple[int, str]:
    try:
        r = runner(["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ------------------------------------------------------------------ (301) licences
COPYLEFT = {"AGPL": 3, "GPL": 2, "LGPL": 1, "MPL": 1, "EPL": 1, "CDDL": 1, "EUPL": 2, "OSL": 2, "SSPL": 3, "CC-BY-SA": 2, "CC-BY-NC": 3}
PERMISSIVE = ("MIT", "BSD", "APACHE", "ISC", "ZLIB", "UNLICENSE", "0BSD", "CC0", "PYTHON", "PSF", "BOOST", "BSL-1.0", "WTFPL", "MIT-0")


def license_kind(lic: str) -> tuple[str, int]:
    """('permissive' | 'copyleft' | 'unknown', strength). LGPL / MPL are weak copyleft (fine when linked, not copied in)."""
    u = (lic or "").upper().replace(" ", "-")
    if not u or u in ("UNKNOWN", "NONE", "SEE-LICENSE-IN-LICENSE", "UNLICENSED", "PROPRIETARY"):
        return ("unknown", 0) if u != "UNLICENSED" else ("proprietary", 3)
    if "OR" in u.split("-") or " OR " in (lic or "").upper():                  # dual licence: the friendlier option counts
        parts = re.split(r"\s+OR\s+|/", (lic or "").upper().strip("()"))
        best = min((license_kind(p) for p in parts), key=lambda k: (k[0] != "permissive", k[1]))
        return best
    for key in sorted(COPYLEFT, key=len, reverse=True):
        if u.startswith(key) or f"-{key}" in u or u.startswith(key.replace("-", "")):
            return "copyleft", COPYLEFT[key]
    if any(p in u for p in PERMISSIVE):
        return "permissive", 0
    return "unknown", 0


def license_conflicts(project_license: str, deps: list[dict], distributed: bool = True, network: bool = False) -> list[dict]:
    """Which dependencies do not go with your project's licence. Strong copyleft (GPL) in a closed or permissive project is
    a problem once you distribute it; AGPL already when people use it over the network; weak copyleft only asks you to
    keep its own files open. Not legal advice."""
    pk, _ = license_kind(project_license)
    closed = pk in ("proprietary", "unknown") or pk == "permissive"
    out = []
    for d in deps:
        kind, strength = license_kind(d.get("license", ""))
        why = ""
        if kind == "unknown":
            why = "licence neznámá – bez licence nesmíš kód legálně použít, zjisti ji"
        elif kind == "proprietary":
            why = "uzavřená licence – potřebuješ smlouvu s autorem"
        elif kind == "copyleft" and closed:
            name = (d.get("license") or "").upper()
            if "AGPL" in name or "SSPL" in name:
                if distributed or network:
                    why = "AGPL: i provoz přes síť tě zavazuje zveřejnit zdrojáky celého projektu"
            elif strength >= 2 and distributed:
                why = "GPL: při šíření programu musíš celý projekt zveřejnit pod GPL"
            elif strength == 1:
                why = "slabý copyleft: úpravy přímo v té knihovně musíš zveřejnit, zbytek ne (jen ji nekopíruj do svého kódu)"
        if why:
            out.append({"name": d.get("name", "?"), "license": d.get("license") or "?", "why": why,
                        "severity": "high" if strength >= 2 or kind in ("unknown", "proprietary") else "low"})
    return sorted(out, key=lambda x: x["severity"] != "high")


def scan_licenses(root: Path) -> list[dict]:
    """Licences of the project's dependencies: node_modules/*/package.json, and the installed Python packages named in
    requirements*.txt / pyproject.toml."""
    deps: list[dict] = []
    nm = root / "node_modules"
    pkg = root / "package.json"
    if nm.is_dir() and pkg.is_file():
        try:
            want = {**json.loads(pkg.read_text(encoding="utf-8")).get("dependencies", {})}
        except ValueError:
            want = {}
        for name in want:
            pj = nm / name / "package.json"
            lic = ""
            if pj.is_file():
                try:
                    m = json.loads(pj.read_text(encoding="utf-8"))
                    lic = m.get("license") if isinstance(m.get("license"), str) else (m.get("license") or {}).get("type", "")
                except ValueError:
                    pass
            deps.append({"name": name, "license": lic or "", "eco": "npm"})
    names: set[str] = set()
    for req in list(root.glob("requirements*.txt")):
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)", line)
            if m and not line.strip().startswith(("#", "-")):
                names.add(m.group(1))
    pp = root / "pyproject.toml"
    if pp.is_file():
        try:
            import tomllib

            data = tomllib.loads(pp.read_text(encoding="utf-8"))
            for spec in data.get("project", {}).get("dependencies", []):
                m = re.match(r"\s*([A-Za-z0-9_.\-]+)", spec)
                if m:
                    names.add(m.group(1))
        except (ValueError, OSError):
            pass
    if names:
        from importlib import metadata

        for n in sorted(names):
            try:
                md = metadata.metadata(n)
                lic = md.get("License-Expression") or ""
                if not lic or len(lic) > 60:
                    cls = [c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
                    lic = cls[0] if cls else (md.get("License") or "")[:60]
            except metadata.PackageNotFoundError:
                lic = ""
            deps.append({"name": n, "license": lic.replace(" License", "").strip(), "eco": "pip"})
    return deps


# ------------------------------------------------------------------ (302) review, (303) commit message, (313) for people
REVIEW_RULES = [
    (r"^\+.*\b(console\.log|print\(|debugger;|breakpoint\(\)|import pdb|pdb\.set_trace|var_dump\()", "Zapomenutý ladicí výpis"),
    (r"^\+.*(<<<<<<<|>>>>>>>|^\+=======$)", "Zbytek konfliktu při slučování"),
    (r"^\+.*\b(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{10,})", "Vypadá to na tajný klíč"),
    (r"^\+.*-----BEGIN [A-Z ]*PRIVATE KEY-----", "Soukromý klíč v kódu"),
    (r"^\+.*\b(password|heslo|api_?key|secret|token)\s*[:=]\s*[\"'][^\"']{6,}[\"']", "Heslo nebo klíč napsané přímo v kódu"),
    (r"^\+.*\b(it|describe|test)\.only\(|^\+.*@pytest\.mark\.skip\b|^\+.*\bxit\(", "Test vypnutý nebo jen jeden (.only / skip)"),
    (r"^\+.*\bexcept\s*:\s*(pass)?\s*$|^\+.*except Exception:\s*pass", "Chyba se tiše spolkne"),
    (r"^\+.*\b(TODO|FIXME|XXX|HACK)\b", "Nové TODO"),
    (r"^\+.*\bverify\s*=\s*False\b|rejectUnauthorized:\s*false", "Vypnuté ověřování HTTPS"),
    (r"^\+.*\beval\(|^\+.*\bexec\(|shell\s*=\s*True", "Spouštění textu jako kódu (eval / shell=True)"),
]


def quick_review(diff: str) -> list[dict]:
    """Fast checks of the added lines before a commit – no AI needed for these."""
    out: list[dict] = []
    file = ""
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            file = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if m:
            line_no = int(m.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            line_no += 1
            for pat, label in REVIEW_RULES:
                if re.search(pat, raw):
                    out.append({"file": file, "line": line_no, "issue": label, "code": raw[1:].strip()[:120]})
                    break
        elif not raw.startswith("-"):
            line_no += 1
    big = [f for f, n in diff_stat(diff).items() if n["add"] > 800]
    out += [{"file": f, "line": 0, "issue": "Obří změna v jednom souboru – rozděl ji, nebo je to vygenerovaný soubor?", "code": ""}
            for f in big]
    return out


def diff_stat(diff: str) -> dict[str, dict]:
    stat: dict[str, dict] = {}
    file = ""
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            file = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            stat.setdefault(file, {"add": 0, "del": 0})
        elif raw.startswith("+") and not raw.startswith("+++") and file:
            stat[file]["add"] += 1
        elif raw.startswith("-") and not raw.startswith("---") and file:
            stat[file]["del"] += 1
    return stat


REVIEW_PROMPT = ("Jsi zkušený vývojář a děláš rychlé code review před commitem. Projdi rozdíl níže a napiš česky nejvýš 6 bodů: "
                 "chyby, bezpečnost, chybějící ošetření, chybějící testy. Ke každému soubor:řádek. Nic nevymýšlej; když je to "
                 "v pořádku, napiš to jednou větou.\n\n")
COMMIT_PROMPT = ("Napiš commit zprávu k tomuto rozdílu: první řádek do 72 znaků v rozkazovacím způsobu (co změna dělá), pak prázdný "
                 "řádek a 1–4 odrážky proč. Jazyk podle předchozích commitů: {lang}. Vrať jen zprávu.\n\n")
PEOPLE_PROMPT = ("Vysvětli tuhle změnu v kódu člověku, který neprogramuje (vedoucí, zákazník): 3–5 krátkých vět česky – co se pro "
                 "uživatele změní, co může přestat fungovat, jestli je potřeba něco udělat. Žádné názvy funkcí ani souborů.\n\n")


def commit_fallback(diff: str) -> str:
    """A message without AI: what changed where."""
    st = diff_stat(diff)
    if not st:
        return "Drobné úpravy"
    files = sorted(st, key=lambda f: -(st[f]["add"] + st[f]["del"]))
    areas = sorted({f.split("/")[0] if "/" in f else Path(f).stem for f in files})
    head = f"Úpravy v {', '.join(areas[:3])}" + ("…" if len(areas) > 3 else "")
    body = "\n".join(f"- {f}: +{st[f]['add']} −{st[f]['del']}" for f in files[:6])
    return f"{head[:72]}\n\n{body}"


def commit_lang(log: str) -> str:
    cz = len(re.findall(r"[áčďéěíňóřšťúůýž]", log.lower()))
    return "čeština" if cz >= 3 else "angličtina"


def clip_diff(diff: str, limit: int = 24000) -> str:
    return diff if len(diff) <= limit else diff[:limit] + "\n… (zkráceno)"


# ------------------------------------------------------------------ (304) CI
def parse_runs(data: dict) -> list[dict]:
    out = []
    for r in data.get("workflow_runs", []) or []:
        out.append({"id": r.get("id"), "name": r.get("name") or r.get("display_title") or "", "branch": r.get("head_branch") or "",
                    "status": r.get("status") or "", "conclusion": r.get("conclusion") or "", "url": r.get("html_url") or "",
                    "sha": (r.get("head_sha") or "")[:7], "title": r.get("display_title") or "", "when": r.get("updated_at") or ""})
    return out


def failed_steps(jobs: dict) -> list[str]:
    out = []
    for j in jobs.get("jobs", []) or []:
        if j.get("conclusion") == "failure":
            steps = [s.get("name", "") for s in j.get("steps", []) or [] if s.get("conclusion") == "failure"]
            out.append(f"{j.get('name', '?')}: {', '.join(steps) or 'neznámý krok'}")
    return out


async def ci_check(rt: Any, repo: str, client=None) -> list[dict]:
    """Newly finished failed runs of a GitHub repo since the last check (once each)."""
    import httpx

    from .connectors import value

    token = value("github", "token") or ""          # the GitHub connector's token (Nastavení → Integrace); public repos work without
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    own = client is None
    c = client or httpx.AsyncClient(timeout=15)
    try:
        r = await c.get(f"https://api.github.com/repos/{repo}/actions/runs?per_page=10", headers=headers)
        if r.status_code != 200:
            return []
        runs = parse_runs(r.json())
        key = f"dx_ci_{repo}"
        row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
        seen = set(json.loads(row["v"])) if row else set()
        new = [x for x in runs if x["status"] == "completed" and x["conclusion"] == "failure" and x["id"] not in seen]
        for x in new:
            j = await c.get(f"https://api.github.com/repos/{repo}/actions/runs/{x['id']}/jobs", headers=headers)
            x["failed"] = failed_steps(j.json()) if j.status_code == 200 else []
        seen |= {x["id"] for x in runs if x["status"] == "completed"}
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(sorted(seen)[-200:])))
        return new if row else []          # the first look only remembers what is already there
    finally:
        if own:
            await c.aclose()


# ------------------------------------------------------------------ (305) README from the code
def project_outline(root: Path, limit: int = 60) -> dict:
    """What a README needs, read from the project itself (no AI): name, how to install and run, the main modules."""
    info: dict[str, Any] = {"name": root.name, "scripts": {}, "install": [], "modules": [], "lang": ""}
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            m = json.loads(pkg.read_text(encoding="utf-8"))
            info.update(name=m.get("name") or root.name, description=m.get("description", ""), scripts=m.get("scripts", {}), lang="JavaScript")
            info["install"].append("npm install")
        except ValueError:
            pass
    pp = root / "pyproject.toml"
    if pp.is_file() or list(root.glob("requirements*.txt")):
        info["lang"] = info["lang"] or "Python"
        info["install"].append("pip install -e ." if pp.is_file() else "pip install -r requirements.txt")
        if pp.is_file():
            try:
                import tomllib

                proj = tomllib.loads(pp.read_text(encoding="utf-8")).get("project", {})
                info["name"] = proj.get("name") or info["name"]
                info["description"] = proj.get("description", "") or info.get("description", "")
                info["scripts"].update({k: v for k, v in proj.get("scripts", {}).items()})
            except (ValueError, OSError):
                pass
    for p in sorted(code_files(root, 400))[:limit]:
        if p.suffix != ".py":
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = re.match(r'\s*(?:#.*\n)*\s*(?:"""|\'\'\')(.+?)(?:"""|\'\'\'|\n\n)', src, re.S)
        doc = " ".join(m.group(1).split())[:160] if m else ""
        funcs = re.findall(r"^def ([a-z]\w+)\(", src, re.M)[:6]
        info["modules"].append({"path": str(p.relative_to(root)).replace("\\", "/"), "doc": doc, "functions": funcs})
    return info


def readme_from_outline(o: dict) -> str:
    lines = [f"# {o['name']}", "", o.get("description") or "_Popis doplň: co projekt dělá a pro koho._", ""]
    if o["install"]:
        lines += ["## Instalace", "", "```", *o["install"], "```", ""]
    if o["scripts"]:
        lines += ["## Spuštění", ""] + [f"- `{k}` – `{v}`" for k, v in list(o["scripts"].items())[:10]] + [""]
    mods = [m for m in o["modules"] if m["doc"] or m["functions"]]
    if mods:
        lines += ["## Struktura", ""] + [f"- `{m['path']}` – {m['doc'] or ', '.join(m['functions'])}" for m in mods[:30]] + [""]
    return "\n".join(lines)


# ------------------------------------------------------------------ (306) run projects by voice
def detect_commands(root: Path) -> dict[str, str]:
    """What this project can be started with: package.json scripts, a manage.py, docker compose, a Makefile, main.py."""
    out: dict[str, str] = {}
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            for k in json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}):
                out[k] = f"npm run {k}"
        except ValueError:
            pass
    if (root / "manage.py").is_file():
        out["server"] = "python manage.py runserver"
    for compose in ("docker-compose.yml", "compose.yaml", "compose.yml", "docker-compose.yaml"):
        if (root / compose).is_file():
            out["docker"] = "docker compose up"
            break
    mk = root / "Makefile"
    if mk.is_file():
        for t in re.findall(r"^([a-zA-Z][\w-]*):", mk.read_text(encoding="utf-8", errors="ignore"), re.M)[:12]:
            out.setdefault(t, f"make {t}")
    for main in ("main.py", "app.py", "server.py"):
        if (root / main).is_file():
            out.setdefault("start", f"python {main}")
    if (root / "pyproject.toml").is_file() or (root / "tests").is_dir():
        out.setdefault("test", "python -m pytest -q")
    return out


WHAT = {"backend": ("backend", "server", "api", "serve", "start"), "frontend": ("frontend", "dev", "web", "client", "start"),
        "test": ("test", "tests"), "build": ("build",), "docker": ("docker",)}


def pick_command(cmds: dict[str, str], what: str) -> tuple[str, str] | None:
    w = fold(what)
    for key in WHAT.get(w, (w,)):
        for name, cmd in cmds.items():
            if fold(name) == key or fold(name).startswith(key):
                return name, cmd
    return next(iter(cmds.items()), None) if not w else None


def project_get(rt: Any, name: str) -> dict | None:
    row = db(rt).one("SELECT * FROM dx_projects WHERE name=?", (fold(name),))
    return dict(row) if row else None


def project_set(rt: Any, name: str, path: str, cmd: str = "") -> None:
    db(rt).exec("INSERT OR REPLACE INTO dx_projects VALUES (?,?,?)", (fold(name), path, cmd))


RUNNING: dict[str, subprocess.Popen] = {}


def start_command(key: str, cmd: str, cwd: Path, log_dir: Path, popen=subprocess.Popen) -> Path:
    """Starts a project's command in the background with its output in a log file (stop it with stop_command)."""
    stop_command(key)
    log = log_dir / f"{re.sub(r'[^a-z0-9]+', '-', fold(key))}.log"
    fh = open(log, "w", encoding="utf-8")  # noqa: SIM115 – the child process keeps it open
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    RUNNING[key] = popen(cmd, cwd=str(cwd), shell=True, stdout=fh, stderr=subprocess.STDOUT, creationflags=flags)
    return log


def stop_command(key: str) -> bool:
    p = RUNNING.pop(key, None)
    if not p:
        return False
    try:
        import psutil

        for ch in psutil.Process(p.pid).children(recursive=True):
            ch.terminate()
    except Exception:  # noqa: BLE001
        pass
    p.terminate()
    return True


# ------------------------------------------------------------------ (307) regex
REGEX_LIB = [
    (("e-mail", "email", "mail"), r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    (("telefon", "phone", "cislo mobil"), r"(?:\+420\s?)?[1-9]\d{2}\s?\d{3}\s?\d{3}"),
    (("psc", "postovni"), r"\b\d{3}\s?\d{2}\b"),
    (("ico",), r"\b\d{8}\b"),
    (("rodne cislo", "rodne"), r"\b\d{6}/?\d{3,4}\b"),
    (("datum", "date"), r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b|\b\d{4}-\d{2}-\d{2}\b"),
    (("url", "odkaz", "adresa web", "link"), r"https?://[^\s<>\"']+"),
    (("ip adres", "ipv4", "ip"), r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    (("cas", "hodin", "time"), r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"),
    (("castk", "cena", "kc", "korun"), r"\b\d{1,3}(?:[ .]\d{3})*(?:,\d{1,2})?\s?(?:Kč|CZK|,-)"),
    (("cislo uctu", "ucet", "bankovni"), r"\b(?:\d{1,6}-)?\d{2,10}/\d{4}\b"),
    (("hex barv", "barva", "color"), r"#(?:[0-9a-fA-F]{3}){1,2}\b"),
    (("iban",), r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
    (("spz", "registracni znacka"), r"\b\d[A-Z]\d\s?\d{4}\b|\b\d[A-Z]{2}\s?\d{4}\b"),
]


def regex_offline(description: str) -> str | None:
    d = fold(description)
    for keys, pat in REGEX_LIB:
        if any(re.search(rf"\b{re.escape(k)}", d) for k in keys):
            return pat
    return None


def regex_test(pattern: str, sample: str) -> dict:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "matches": [m.group(0) for m in rx.finditer(sample)][:50]}


REGEX_PROMPT = ("Napiš regulární výraz (Python / JavaScript kompatibilní) pro: {desc}\nVrať PŘESNĚ dva řádky: na prvním jen výraz "
                "bez lomítek, na druhém krátké české vysvětlení.")


# ------------------------------------------------------------------ (308) SQL from Czech
def sqlite_schema(path: Path) -> str:
    import sqlite3

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT sql FROM sqlite_master WHERE type IN ('table','view') AND sql IS NOT NULL").fetchall()
    finally:
        con.close()
    return "\n".join(r[0] for r in rows)


def read_only_sql(sql: str) -> bool:
    s = re.sub(r"--.*?$|/\*.*?\*/", "", sql or "", flags=re.M | re.S).strip().rstrip(";").strip()
    if ";" in s:
        return False
    return bool(re.match(r"(?is)^(select|with|explain|pragma\s+table_info)\b", s)) and not re.search(
        r"(?i)\b(insert|update|delete|drop|alter|create|replace|attach|detach|vacuum)\b", s)


SQL_PROMPT = ("Schéma databáze:\n{schema}\n\nNapiš JEDEN SQL dotaz (SQLite, jen čtení – SELECT) pro: {ask}\nVrať jen SQL, bez ```.")


def extract_code(text: str) -> str:
    m = re.search(r"```[\w+-]*\n(.*?)```", text or "", re.S)
    return (m.group(1) if m else text or "").strip()


# ------------------------------------------------------------------ (309) code by voice
CODE_PROMPT = ("Napiš kód podle zadání. Jazyk: {lang}. Vrať JEN kód bez ``` a bez vysvětlování – vloží se rovnou do editoru "
               "na místo kurzoru.\nZadání: {ask}")


def lang_of(app_title: str, default: str = "Python") -> str:
    t = (app_title or "").lower()
    for ext, lang in ((".py", "Python"), (".tsx", "TypeScript (React)"), (".ts", "TypeScript"), (".jsx", "JavaScript (React)"),
                      (".js", "JavaScript"), (".java", "Java"), (".kt", "Kotlin"), (".cs", "C#"), (".go", "Go"), (".rs", "Rust"),
                      (".cpp", "C++"), (".c ", "C"), (".php", "PHP"), (".sql", "SQL"), (".html", "HTML"), (".css", "CSS")):
        if ext in t:
            return lang
    return default


# ------------------------------------------------------------------ (310) go to a function, who calls it
DEF_RX = (r"^\s*(?:async\s+)?def\s+{n}\b|^\s*class\s+{n}\b|function\s+{n}\b|(?:const|let|var)\s+{n}\s*=\s*(?:async\s*)?\(|"
          r"^\s*(?:public|private|protected|static|\s)*[\w<>\[\],]+\s+{n}\s*\([^;]*$|^\s*func\s+(?:\([^)]*\)\s*)?{n}\b|^\s*fn\s+{n}\b|"
          r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?{n}\s*\([^)]*\)\s*\{{")


NOT_DEF = re.compile(r"\s*(await|return|yield|throw|new|else|if|while|for|case|print|echo|delete|typeof)\b")


def find_symbol(root: Path, name: str) -> list[dict]:
    rx = re.compile(DEF_RX.format(n=re.escape(name)), re.I)
    out = []
    for p in code_files(root):
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line) and not NOT_DEF.match(line):
                    out.append({"file": str(p), "line": i, "code": line.strip()[:140]})
        except OSError:
            continue
    return out


def find_callers(root: Path, name: str) -> list[dict]:
    call = re.compile(rf"(?<![\w.]def )(?<!function )\b{re.escape(name)}\s*\(")
    defs = re.compile(DEF_RX.format(n=re.escape(name)), re.I)
    out = []
    for p in code_files(root):
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        func = ""
        for i, line in enumerate(lines, 1):
            m = re.match(r"\s*(?:async\s+)?(?:def|function|func|fn)\s+(\w+)", line)
            if m:
                func = m.group(1)
            if call.search(line) and (not defs.search(line) or NOT_DEF.match(line)):
                out.append({"file": str(p), "line": i, "in": func, "code": line.strip()[:140]})
    return out


def editor_command(file: str, line: int) -> list[str]:
    exe = shutil.which("code") or shutil.which("code.cmd") or "code"
    return [exe, "-g", f"{file}:{line}"]


# ------------------------------------------------------------------ (311) snippets
def snippet_add(rt: Any, title: str, code: str, lang: str = "", tags: str = "") -> int:
    cur = db(rt).exec("INSERT INTO dx_snippets (title, lang, code, tags, ts) VALUES (?,?,?,?,?)", (title.strip(), lang, code, tags, time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def snippet_find(rt: Any, query: str, limit: int = 5) -> list[dict]:
    words = [w[:5] for w in re.findall(r"[a-z0-9]+", fold(query)) if len(w) > 1]
    rows = [dict(r) for r in db(rt).all("SELECT * FROM dx_snippets")]
    scored = []
    for r in rows:
        hay = fold(f"{r['title']} {r['tags']} {r['lang']} {r['code'][:400]}")
        s = sum(3 if w in fold(r["title"]) else 1 for w in words if w in hay)
        if s:
            scored.append((s, r))
    return [r for _, r in sorted(scored, key=lambda x: -x[0])[:limit]]


# ------------------------------------------------------------------ (312) Czech test data
MEN = ["Jan", "Petr", "Jiří", "Pavel", "Tomáš", "Martin", "Jakub", "Lukáš", "Ondřej", "David", "Michal", "Vojtěch", "Adam", "Filip"]
WOMEN = ["Jana", "Eva", "Hana", "Lucie", "Petra", "Kateřina", "Tereza", "Veronika", "Markéta", "Barbora", "Anna", "Klára", "Ema"]
SURNAMES = [("Novák", "Nováková"), ("Svoboda", "Svobodová"), ("Novotný", "Novotná"), ("Dvořák", "Dvořáková"), ("Černý", "Černá"),
            ("Procházka", "Procházková"), ("Kučera", "Kučerová"), ("Veselý", "Veselá"), ("Horák", "Horáková"), ("Němec", "Němcová"),
            ("Marek", "Marková"), ("Pokorný", "Pokorná"), ("Král", "Králová"), ("Růžička", "Růžičková")]
STREETS = ["Hlavní", "Školní", "Nádražní", "Komenského", "Masarykova", "Husova", "Palackého", "Lipová", "Zahradní", "Krátká", "Polní"]
CITIES = [("Praha", "110 00"), ("Brno", "602 00"), ("Ostrava", "702 00"), ("Plzeň", "301 00"), ("Liberec", "460 01"),
          ("Olomouc", "779 00"), ("České Budějovice", "370 01"), ("Hradec Králové", "500 02"), ("Pardubice", "530 02"),
          ("Zlín", "760 01"), ("Jihlava", "586 01"), ("Kladno", "272 01")]
DOMAINS = ["example.cz", "test.cz", "priklad.cz"]


def ascii_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", fold(s)).strip(".")


def make_ico(r: random.Random) -> str:
    while True:
        base = f"{r.randint(1, 9)}{r.randint(0, 999999):06d}"
        s = sum(int(base[i]) * (8 - i) for i in range(7))
        c = (11 - s % 11) % 10
        if (11 - s % 11) != 10:      # a remainder of 1 has no valid digit in the strict variant – skip it
            return base + str(c)


def make_rc(r: random.Random, born: dt.date, female: bool) -> str:
    """A rodné číslo that passes the check (10 digits, divisible by 11) – fake, for tests only."""
    mm = born.month + (50 if female else 0)
    head = f"{born.year % 100:02d}{mm:02d}{born.day:02d}"
    while True:
        tail = f"{r.randint(0, 999):03d}"
        n = int(head + tail)
        check = n % 11
        if check == 10:
            continue
        return f"{head}/{tail}{check}"


def rc_ok(rc: str) -> bool:
    d = re.sub(r"\D", "", rc or "")
    if len(d) != 10:
        return False
    n = int(d)
    return n % 11 == 0 or (int(d[:9]) % 11 == 10 and d[9] == "0")


ACC_W = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)


def acc_part_ok(num: str) -> bool:
    d = num.zfill(10)
    return sum(int(c) * w for c, w in zip(d, ACC_W, strict=True)) % 11 == 0


def make_account(r: random.Random) -> str:
    banks = ["0100", "0300", "0800", "2010", "3030", "0600", "5500", "6100"]
    while True:
        num = str(r.randint(10 ** 7, 10 ** 10 - 1))
        if acc_part_ok(num):
            return f"{num}/{r.choice(banks)}"


def test_people(n: int = 10, seed: int | None = None) -> list[dict]:
    r = random.Random(seed)
    out = []
    for _ in range(max(1, min(n, 1000))):
        female = r.random() < 0.5
        first = r.choice(WOMEN if female else MEN)
        last = r.choice(SURNAMES)[1 if female else 0]
        born = dt.date(r.randint(1950, 2005), r.randint(1, 12), r.randint(1, 28))
        city, psc = r.choice(CITIES)
        out.append({"jmeno": first, "prijmeni": last, "pohlavi": "ž" if female else "m", "narozeni": born.isoformat(),
                    "rodne_cislo": make_rc(r, born, female), "ulice": f"{r.choice(STREETS)} {r.randint(1, 120)}", "mesto": city,
                    "psc": psc, "telefon": f"+420 {r.choice('67')}{r.randint(0, 99):02d} {r.randint(0, 999):03d} {r.randint(0, 999):03d}",
                    "email": f"{ascii_slug(first)}.{ascii_slug(last)}{r.randint(1, 99)}@{r.choice(DOMAINS)}",
                    "ico": make_ico(r), "ucet": make_account(r)})
    return out


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    keys = list(rows[0])
    return ";".join(keys) + "\n" + "\n".join(";".join(str(x[k]) for k in keys) for x in rows)


# ------------------------------------------------------------------ (314) ports and processes
def who_uses_port(port: int) -> list[dict]:
    import psutil

    out = []
    seen = set()
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        conns = []
    for c in conns:
        if c.laddr and c.laddr.port == port and c.pid and c.pid not in seen:
            seen.add(c.pid)
            try:
                p = psutil.Process(c.pid)
                out.append({"pid": c.pid, "name": p.name(), "cmd": " ".join(p.cmdline())[:160], "status": c.status})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                out.append({"pid": c.pid, "name": "?", "cmd": "", "status": c.status})
    return out


def listening_ports(limit: int = 40) -> list[dict]:
    import psutil

    out = {}
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.pid:
                try:
                    name = psutil.Process(c.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    name = "?"
                out[c.laddr.port] = {"port": c.laddr.port, "pid": c.pid, "name": name}
    except (psutil.AccessDenied, OSError):
        pass
    return sorted(out.values(), key=lambda x: x["port"])[:limit]


PROTECTED = {"system", "svchost.exe", "lsass.exe", "csrss.exe", "wininit.exe", "services.exe", "smss.exe", "winlogon.exe",
             "explorer.exe", "dwm.exe", "systemd", "init", "launchd"}


def kill_pid(pid: int) -> str:
    import psutil

    p = psutil.Process(pid)
    if p.name().lower() in PROTECTED or pid == os.getpid():
        raise ValueError(f"{p.name()} je součást systému (nebo JARVIS) – to neukončím.")
    p.terminate()
    try:
        p.wait(5)
    except psutil.TimeoutExpired:
        p.kill()
    return p.name()


# ------------------------------------------------------------------ (315) Docker
def parse_docker_ps(text: str) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        out.append({"id": d.get("ID", "")[:12], "name": d.get("Names", ""), "image": d.get("Image", ""), "state": d.get("State", ""),
                    "status": d.get("Status", ""), "ports": d.get("Ports", "")})
    return out


def docker(*args: str, timeout: int = 30, runner=subprocess.run) -> tuple[int, str]:
    exe = shutil.which("docker")
    if not exe:
        return 127, "Docker tu není nainstalovaný (nebo Docker Desktop neběží)."
    try:
        r = runner([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def docker_summary(rows: list[dict]) -> str:
    if not rows:
        return "Žádné kontejnery."
    up = [r for r in rows if r["state"] == "running"]
    bad = [r for r in rows if r["state"] in ("exited", "dead", "restarting") and "Exited (0)" not in r["status"]]
    s = f"Běží {len(up)} z {len(rows)}: " + ", ".join(r["name"] for r in up[:8])
    if bad:
        s += ". Problém: " + ", ".join(f"{r['name']} ({r['status']})" for r in bad[:5])
    return s


# ------------------------------------------------------------------ (316) rename with a preview
def rename_preview(root: Path, old: str, new: str, limit: int = 200) -> list[dict]:
    rx = re.compile(rf"\b{re.escape(old)}\b")
    out = []
    for p in code_files(root):
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not rx.search(src):
            continue
        dst = rx.sub(new, src)
        diff = "".join(difflib.unified_diff(src.splitlines(True), dst.splitlines(True), f"a/{p.name}", f"b/{p.name}", n=1))
        out.append({"file": str(p), "count": len(rx.findall(src)), "diff": diff})
        if len(out) >= limit:
            break
    return out


def rename_apply(root: Path, old: str, new: str) -> int:
    rx = re.compile(rf"\b{re.escape(old)}\b")
    n = 0
    for ch in rename_preview(root, old, new, 10_000):
        p = Path(ch["file"])
        p.write_text(rx.sub(new, p.read_text(encoding="utf-8")), encoding="utf-8")
        n += ch["count"]
    return n


# ------------------------------------------------------------------ (317) old TODOs
TODO_RX = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)")


def parse_blame(porcelain: str) -> list[dict]:
    """`git blame --line-porcelain` → lines with their author time."""
    out = []
    cur: dict[str, Any] = {}
    for line in porcelain.splitlines():
        if re.match(r"^[0-9a-f]{40} \d+ (\d+)", line):
            cur = {"line": int(line.split()[2])}
        elif line.startswith("author-time "):
            cur["time"] = int(line.split()[1])
        elif line.startswith("author "):
            cur["author"] = line[7:]
        elif line.startswith("\t"):
            cur["text"] = line[1:]
            out.append(cur)
    return out


def old_todos(root: Path, days: int = 30, now: float | None = None, runner=subprocess.run, limit: int = 40) -> list[dict]:
    now = time.time() if now is None else now
    found = []
    for p in code_files(root):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not TODO_RX.search(txt):
            continue
        rel = str(p.relative_to(root))
        code, out = git(root, "blame", "--line-porcelain", "--", rel, runner=runner)
        if code != 0:
            continue
        for ln in parse_blame(out):
            m = TODO_RX.search(ln.get("text", ""))
            if m and now - ln.get("time", now) > days * 86400:
                found.append({"file": rel, "line": ln["line"], "age_days": int((now - ln["time"]) // 86400),
                              "author": ln.get("author", ""), "text": (m.group(1) + ": " + m.group(2)).strip()[:120]})
        if len(found) >= limit:
            break
    return sorted(found, key=lambda x: -x["age_days"])[:limit]


# ------------------------------------------------------------------ (318) tidy JSON / YAML
def pretty(text: str, to: str = "") -> tuple[str, str]:
    """(formatted text, 'json'/'yaml'). Accepts sloppy JSON too: trailing commas, single quotes, Python dicts, comments."""
    s = (text or "").strip()
    data: Any = None
    kind = ""
    try:
        data, kind = json.loads(s), "json"
    except ValueError:
        cleaned = re.sub(r"//[^\n]*|/\*.*?\*/", "", s, flags=re.S)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            data, kind = json.loads(cleaned), "json"
        except ValueError:
            import ast

            try:
                data, kind = ast.literal_eval(cleaned.replace("true", "True").replace("false", "False").replace("null", "None")), "json"
            except (ValueError, SyntaxError):
                import yaml

                try:
                    data, kind = yaml.safe_load(s), "yaml"
                except yaml.YAMLError as e:
                    raise ValueError(f"Není to platný JSON ani YAML: {str(e).splitlines()[0]}") from e
                if not isinstance(data, (dict, list)):
                    raise ValueError("Není to JSON ani YAML se strukturou.") from None
    target = to or kind
    if target == "yaml":
        import yaml

        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), "yaml"
    return json.dumps(data, ensure_ascii=False, indent=2), "json"


# ------------------------------------------------------------------ (319) git helper
GIT_RECIPES: list[tuple[str, str, list[str], str]] = [
    (r"vrat\w* (posledni )?commit|zrus\w* (posledni )?commit|undo commit", "undo_commit", ["reset", "--soft", "HEAD~1"],
     "Zruší poslední commit, ale tvoje změny zůstanou připravené ke commitu – nic se neztratí."),
    (r"oprav\w* (zpravu|popis)|prejmenuj commit|amend", "amend", ["commit", "--amend", "-m", "{text}"],
     "Přepíše zprávu posledního commitu. Pokud už je odeslaný, budeš muset pushnout se --force-with-lease."),
    (r"zahod\w* (zmeny|upravy)|smaz\w* (zmeny|upravy)|vrat\w* (soubor|zmeny)", "discard", ["restore", "--", "{path}"],
     "Zahodí neuložené změny v souboru – NEJDE vrátit zpátky."),
    (r"odloz\w*|stash|schovej", "stash", ["stash", "push", "-m", "JARVIS {now}"],
     "Schová rozdělanou práci stranou (git stash) – vrátíš ji příkazem „vrať odloženou práci“."),
    (r"vrat\w* odlozen|stash pop|obnov odlozen", "unstash", ["stash", "pop"], "Vrátí naposledy odloženou práci zpátky."),
    (r"vyjm\w* z (pripravenych|commitu)|unstage", "unstage", ["restore", "--staged", "--", "{path}"],
     "Vyndá soubor z připravených ke commitu; změny v něm zůstanou."),
    (r"nov\w* vetev|vytvor\w* vetev|branch", "branch", ["switch", "-c", "{text}"], "Vytvoří novou větev a přepne se na ni."),
    (r"stahn\w*|pull|aktualizuj", "pull", ["pull", "--ff-only"], "Stáhne nové commity ze serveru (jen když nedojde ke konfliktu)."),
]


def git_plan(ask: str, pushed: bool = False, text: str = "", path: str = ".") -> dict | None:
    """What a Czech request means in git, what it will do, and whether it is safe. A commit that is already on the server
    is undone with `git revert` (a new commit), not by rewriting history."""
    a = fold(ask)
    for pat, key, args, why in GIT_RECIPES:
        if re.search(pat, a):
            if key == "undo_commit" and pushed:
                return {"key": "revert", "args": ["revert", "--no-edit", "HEAD"], "risky": False,
                        "why": "Poslední commit už je na serveru, proto ho nepřepíšu – udělám nový commit, který ho vrátí (git revert)."}
            filled = [x.replace("{text}", text or "oprava").replace("{path}", path or ".").replace("{now}", dt.datetime.now().strftime("%d.%m. %H:%M"))
                      for x in args]
            return {"key": key, "args": filled, "risky": key in ("discard", "amend"), "why": why}
    return None


def is_pushed(root: Path, runner=subprocess.run) -> bool:
    code, out = git(root, "status", "-sb", runner=runner)
    if code != 0:
        return False
    head = out.splitlines()[0] if out else ""
    return "..." in head and "ahead" not in head


# ------------------------------------------------------------------ (320) code in another language
TRANSLATE_PROMPT = ("Přepiš tenhle kód z jazyka {src} do jazyka {dst} tak, jak by ho napsal zkušený programátor v cílovém jazyce "
                    "(idiomaticky, ne doslova). Pak pod kód napiš česky 3–6 odrážek: co se v cílovém jazyce dělá jinak a proč.\n\n{code}")
EXT_LANG = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".cs": "C#", ".go": "Go",
            ".rs": "Rust", ".cpp": "C++", ".c": "C", ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".dart": "Dart"}


# ------------------------------------------------------------------ CI watch every 10 minutes
async def tick(rt: Any, now: float | None = None) -> list[str]:
    from .config import DevXCfg

    c = getattr(rt.cfg, "devx", None) or DevXCfg()
    now = time.time() if now is None else now
    if not c.ci_repos or now - getattr(rt, "_devx_ci_at", 0.0) < 600:
        return []
    rt._devx_ci_at = now
    said = []
    for repo in c.ci_repos:
        try:
            runs = await ci_check(rt, repo)
        except Exception:  # noqa: BLE001 – GitHub down or offline; next time
            continue
        for r in runs:
            why = "; ".join(r.get("failed", [])[:3]) or "důvod v logu"
            t = f"{repo}: {r['name']} na větvi {r['branch']} spadl ({why})."
            rt.notify("CI spadlo", t, url=r["url"], actions=[{"label": "Proč?", "action": "ask",
                                                                  "args": {"text": f"vysvětli proč spadl build {r['url']}"}}])
            said.append(t)
    return said
