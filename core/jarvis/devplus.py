"""Wave 36 – more for developers and testers.

* migrations (OMEGA 051): the SQL that turns database A into the shape of B (new tables, columns, indexes; removals
  only as commented-out lines – data is never dropped by a generated script)
* backend performance (053): slowest endpoints from an access log or from timing your own local URLs
* staging deployment (056): Dockerfile, compose file and checklist for a test environment, secrets left as placeholders
* canary decisions (622): is the new version's error rate / latency worse than the old one's? promote, wait or roll back
* property-based tests (632): random inputs for a Python function and the property it must keep
* crash reproduction (637): a traceback → where it broke, the call chain in your code and a pytest skeleton
* battery profiler (640): drain per hour and which programs used the processor while on battery
* browser compatibility (536): the page in Chromium, Firefox and WebKit – errors per engine and visual differences
* file relationships (321): which files belong together (same name, mentioned inside, used by, identical copies)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- 051 migrations
def _master(path: Path) -> dict[str, dict]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        out: dict[str, dict] = {}
        for typ, name, tbl, sql in con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"):
            if typ == "table":
                cols = {r[1]: {"type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
                        for r in con.execute(f'PRAGMA table_info("{name}")')}
                out.setdefault(name, {"indexes": {}})
                out[name].update(sql=sql, columns=cols)
            elif typ == "index" and sql:
                out.setdefault(tbl, {"indexes": {}})["indexes"][name] = sql
        return out
    finally:
        con.close()


def migration_sql(current: Path, target: Path) -> dict:
    """SQL that brings `current` to the structure of `target`. Destructive steps are only listed, commented out."""
    a, b = _master(current), _master(target)
    up, risky = [], []
    for name in sorted(set(b) - set(a)):
        up.append(b[name]["sql"].rstrip(";") + ";")
        up += [s.rstrip(";") + ";" for s in b[name]["indexes"].values()]
    for name in sorted(set(a) & set(b)):
        ca, cb = a[name]["columns"], b[name]["columns"]
        for col in [c for c in cb if c not in ca]:
            c = cb[col]
            line = f'ALTER TABLE "{name}" ADD COLUMN "{col}" {c["type"]}'
            if c["default"] is not None:
                line += f" DEFAULT {c['default']}"
            if c["notnull"]:
                if c["default"] is None:
                    risky.append(f'-- "{name}"."{col}" je NOT NULL bez výchozí hodnoty: přidávám bez NOT NULL, doplň data a tabulku přestav.')
                else:
                    line += " NOT NULL"
            up.append(line + ";")
        for col in [c for c in ca if c not in cb]:
            risky.append(f'-- ALTER TABLE "{name}" DROP COLUMN "{col}";   -- smaže data, odkomentuj jen po záloze')
        for col in [c for c in ca if c in cb and ca[c]["type"] != cb[c]["type"]]:
            risky.append(f'-- "{name}"."{col}": typ {ca[col]["type"]} → {cb[col]["type"]} – SQLite typ sloupce nezmění, je potřeba tabulku přestavět')
        for idx, sql in b[name]["indexes"].items():
            if idx not in a[name]["indexes"]:
                up.append(sql.rstrip(";") + ";")
        for idx in a[name]["indexes"]:
            if idx not in b[name]["indexes"]:
                risky.append(f'-- DROP INDEX "{idx}";')
    for name in sorted(set(a) - set(b)):
        risky.append(f'-- DROP TABLE "{name}";   -- tabulka v cíli není; smaže data, odkomentuj jen po záloze')
    script = "BEGIN;\n" + "\n".join(up) + ("\n" if up else "") + "\n".join(risky) + ("\n" if risky else "") + "COMMIT;\n"
    return {"statements": len(up), "risky": len(risky), "sql": script, "same": not up and not risky}


# ---------------------------------------------------------------- 053 backend performance
LOG = re.compile(r'"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3})'
                 r'(?:.*?(?:rt=|request_time=|\s)(?P<rt>\d+\.\d+)\s*(?:s|ms)?\s*$)?')


def normalize_path(p: str) -> str:
    p = p.split("?")[0]
    p = re.sub(r"/\d+(?=/|$)", "/{id}", p)
    p = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{27,}(?=/|$)", "/{uuid}", p, flags=re.I)
    return re.sub(r"/[0-9a-f]{16,}(?=/|$)", "/{hash}", p, flags=re.I)


def endpoint_stats(lines: list[str], ms: bool = False) -> dict:
    times: dict[str, list[float]] = defaultdict(list)
    errors: Counter = Counter()
    count: Counter = Counter()
    for ln in lines:
        m = LOG.search(ln)
        if not m:
            continue
        key = f"{m.group('method')} {normalize_path(m.group('path'))}"
        count[key] += 1
        if m.group("status").startswith("5"):
            errors[key] += 1
        if m.group("rt"):
            t = float(m.group("rt"))
            times[key].append(t if ms else t * 1000)
    rows = []
    for key, n in count.items():
        ts = sorted(times.get(key, []))
        p95 = ts[min(len(ts) - 1, math.ceil(0.95 * len(ts)) - 1)] if ts else None
        rows.append({"endpoint": key, "requests": n, "errors": errors[key], "error_pct": round(100 * errors[key] / n, 1),
                     "p50_ms": round(statistics.median(ts), 1) if ts else None, "p95_ms": round(p95, 1) if p95 is not None else None,
                     "total_s": round(sum(ts) / 1000, 2) if ts else None})
    rows.sort(key=lambda r: (r["total_s"] or 0, r["p95_ms"] or 0), reverse=True)
    return {"endpoints": rows, "parsed": sum(count.values()), "with_times": sum(len(v) for v in times.values())}


async def time_urls(client, urls: list[str], repeat: int = 5) -> list[dict]:
    from .testlab import local_only

    out = []
    for u in urls:
        local_only(u)
        ts, codes = [], Counter()
        for _ in range(repeat):
            t = time.perf_counter()
            try:
                r = await client.get(u, timeout=30)
                codes[r.status_code] += 1
            except Exception as e:  # noqa: BLE001
                codes[type(e).__name__] += 1
                continue
            ts.append((time.perf_counter() - t) * 1000)
        out.append({"url": u, "best_ms": round(min(ts), 1) if ts else None, "median_ms": round(statistics.median(ts), 1) if ts else None,
                    "codes": dict(codes)})
    out.sort(key=lambda r: r["median_ms"] or 1e9, reverse=True)
    return out


# ---------------------------------------------------------------- 056 staging deployment
def detect_stack(root: Path) -> dict:
    has = lambda n: (root / n).exists()  # noqa: E731
    if has("package.json"):
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8") or "{}")
        scripts = pkg.get("scripts", {})
        return {"kind": "node", "start": "npm start" if "start" in scripts else "node index.js",
                "build": "npm run build" if "build" in scripts else "", "port": 3000}
    if has("pyproject.toml") or has("requirements.txt"):
        text = ""
        for n in ("pyproject.toml", "requirements.txt"):
            if has(n):
                text += (root / n).read_text(encoding="utf-8", errors="replace").lower()
        if "fastapi" in text or "uvicorn" in text:
            return {"kind": "python", "start": "uvicorn app:app --host 0.0.0.0 --port 8000", "port": 8000}
        if "flask" in text:
            return {"kind": "python", "start": "flask run --host 0.0.0.0 --port 8000", "port": 8000}
        if "django" in text:
            return {"kind": "python", "start": "python manage.py runserver 0.0.0.0:8000", "port": 8000}
        return {"kind": "python", "start": "python main.py", "port": 8000}
    if has("index.html"):
        return {"kind": "static", "start": "", "port": 80}
    return {"kind": "unknown", "start": "", "port": 8080}


def env_names(root: Path) -> list[str]:
    """Names of settings the code reads from the environment (values are never copied)."""
    names: set[str] = set()
    for p in list(root.rglob("*.py"))[:2000] + list(root.rglob("*.js"))[:2000] + list(root.rglob("*.ts"))[:2000]:
        if "node_modules" in p.parts or ".venv" in p.parts:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(re.findall(r"os\.environ(?:\.get)?[\[(]\s*[\"']([A-Z][A-Z0-9_]+)", t))
        names.update(re.findall(r"getenv\(\s*[\"']([A-Z][A-Z0-9_]+)", t))
        names.update(re.findall(r"process\.env\.([A-Z][A-Z0-9_]+)", t))
    for f in (".env.example", ".env.sample"):
        if (root / f).is_file():
            names.update(re.findall(r"^([A-Z][A-Z0-9_]+)=", (root / f).read_text(encoding="utf-8", errors="replace"), re.M))
    return sorted(names)


def staging_files(root: Path, name: str = "") -> dict[str, str]:
    st = detect_stack(root)
    name = re.sub(r"[^a-z0-9-]", "-", (name or root.name).lower()).strip("-") or "app"
    port = st["port"]
    if st["kind"] == "node":
        docker = ("FROM node:20-slim\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci\nCOPY . .\n"
                  + (f"RUN {st['build']}\n" if st["build"] else "") + f"EXPOSE {port}\nCMD {json.dumps(st['start'].split())}\n")
    elif st["kind"] == "python":
        req = "COPY requirements.txt ./\nRUN pip install --no-cache-dir -r requirements.txt\n" if (root / "requirements.txt").exists() \
            else "COPY pyproject.toml ./\nRUN pip install --no-cache-dir .\n"
        docker = f"FROM python:3.12-slim\nWORKDIR /app\n{req}COPY . .\nEXPOSE {port}\nCMD {json.dumps(st['start'].split())}\n"
    else:
        docker = f"FROM nginx:alpine\nCOPY . /usr/share/nginx/html\nEXPOSE {port}\n"
    envs = env_names(root)
    compose = (f"services:\n  {name}-staging:\n    build: .\n    ports:\n      - \"{port + 1}:{port}\"\n    env_file: .env.staging\n"
               "    restart: unless-stopped\n    healthcheck:\n"
               f"      test: [\"CMD-SHELL\", \"wget -qO- http://localhost:{port}/ || exit 1\"]\n      interval: 30s\n")
    env = "# Testovací prostředí – vyplň hodnoty (nikdy sem nedávej ostrá hesla ani produkční databázi)\n" + \
          "".join(f"{n}=\n" for n in envs) or "# (kód nečte žádné proměnné prostředí)\n"
    checklist = (f"# Testovací nasazení – {name}\n\n1. Zkopíruj produkční data jen anonymizovaná (JARVIS: „anonymizuj kopii databáze“).\n"
                 "2. Vyplň `.env.staging` – testovací klíče, testovací databáze, žádné ostré platby a e-maily.\n"
                 f"3. `docker compose -f docker-compose.staging.yml up --build` → http://localhost:{port + 1}\n"
                 "4. Projdi hlavní scénáře (JARVIS: „otestuj průchod webem“) a zátěž (jen na tomto prostředí).\n"
                 "5. Teprve pak nasazuj do ostrého provozu – ideálně postupně (canary).\n")
    return {"Dockerfile.staging": docker, "docker-compose.staging.yml": compose, ".env.staging.example": env, "STAGING.md": checklist,
            "_stack": json.dumps(st, ensure_ascii=False), "_env": json.dumps(envs)}


# ---------------------------------------------------------------- 622 canary
def canary_decision(base: dict, canary: dict, max_latency_ratio: float = 1.2, alpha_z: float = 2.33) -> dict:
    """base / canary: {requests, errors, p95_ms}. Errors compared with a one-sided two-proportion z-test (≈ 99 %)."""
    n1, e1, n2, e2 = int(base["requests"]), int(base["errors"]), int(canary["requests"]), int(canary["errors"])
    if n2 < 200:
        return {"decision": "počkat", "reason": f"Málo provozu na nové verzi ({n2} požadavků, chci aspoň 200).", "z": None}
    p1, p2 = e1 / max(1, n1), e2 / max(1, n2)
    p = (e1 + e2) / max(1, n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / max(1, n1) + 1 / max(1, n2))) or 1e-9
    z = (p2 - p1) / se
    ratio = (canary.get("p95_ms") or 0) / max(1e-9, base.get("p95_ms") or 0) if base.get("p95_ms") else 1.0
    if z > alpha_z:
        d, why = "vrátit", f"Nová verze má víc chyb ({p2:.2%} proti {p1:.2%}, z = {z:.1f})."
    elif ratio > max_latency_ratio:
        d, why = "vrátit", f"Nová verze je pomalejší (p95 {canary.get('p95_ms')} ms proti {base.get('p95_ms')} ms)."
    elif z > alpha_z / 2 or ratio > (1 + max_latency_ratio) / 2:
        d, why = "počkat", "Rozdíl zatím není jistý – nech běžet déle se stejným podílem provozu."
    else:
        d, why = "pustit dál", f"Chyby {p2:.2%} proti {p1:.2%}, p95 {ratio:.2f}× – můžeš zvýšit podíl provozu."
    return {"decision": d, "reason": why, "z": round(z, 2), "latency_ratio": round(ratio, 2), "error_base": p1, "error_canary": p2}


CANARY_STEPS = [1, 5, 25, 50, 100]


def canary_next(current_pct: float, decision: str) -> float:
    if decision == "vrátit":
        return 0
    if decision != "pustit dál":
        return current_pct
    return next((s for s in CANARY_STEPS if s > current_pct), 100)


# ---------------------------------------------------------------- 632 property-based testing
HARNESS = r'''
import importlib.util, json, random, sys, traceback, inspect, typing
spec = importlib.util.spec_from_file_location("target", sys.argv[1]); mod = importlib.util.module_from_spec(spec)
sys.path.insert(0, sys.argv[4]); spec.loader.exec_module(mod)
fn = getattr(mod, sys.argv[2]); prop = sys.argv[3]; inv = getattr(mod, sys.argv[6]) if sys.argv[6] else None
rnd = random.Random(int(sys.argv[5]))
def gen(t, depth=0):
    o = typing.get_origin(t); a = typing.get_args(t)
    if t is int: return rnd.choice([0, 1, -1, rnd.randint(-10**6, 10**6), 2**31, -2**31])
    if t is float: return rnd.choice([0.0, -0.0, 1e-9, -1.5, rnd.uniform(-1e6, 1e6), 1e300])
    if t is bool: return rnd.random() < .5
    if t is str: return rnd.choice(["", " ", "a", "Žluťoučký kůň", "x" * 1000, "\n\t", "'\"", "😀", str(rnd.random())])
    if t is bytes: return bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 20)))
    if o in (list, typing.List) or t is list: return [gen(a[0] if a else int, depth + 1) for _ in range(rnd.randint(0, 5 if depth else 8))]
    if o in (dict, typing.Dict) or t is dict: return {gen(a[0] if a else str, depth + 1): gen(a[1] if a else int, depth + 1) for _ in range(rnd.randint(0, 4))}
    if o is typing.Union: return gen(rnd.choice(a), depth)
    if o is tuple: return tuple(gen(x, depth + 1) for x in a if x is not Ellipsis)
    return rnd.choice([0, "", None, 1.5])
hints = typing.get_type_hints(fn); params = [p for p in inspect.signature(fn).parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
fails, runs = [], 0
for i in range(int(sys.argv[7])):
    args = [gen(hints.get(p.name, int)) for p in params]
    runs += 1
    try:
        r = fn(*args)
        if prop == "idempotent" and fn(r) != r: fails.append({"args": repr(args)[:300], "problem": f"f(f(x)) != f(x): {repr(fn(r))[:120]} vs {repr(r)[:120]}"})
        if prop == "roundtrip" and inv(r) != args[0]: fails.append({"args": repr(args)[:300], "problem": f"inverze nevrátila vstup: {repr(inv(r))[:120]}"})
        if prop == "sorted" and list(r) != sorted(r): fails.append({"args": repr(args)[:300], "problem": "výsledek není seřazený"})
    except Exception as e:
        if prop != "no_crash" and isinstance(e, (TypeError, ValueError)): continue
        fails.append({"args": repr(args)[:300], "problem": f"{type(e).__name__}: {str(e)[:200]}"})
    if len(fails) >= 5: break
print(json.dumps({"runs": runs, "fails": fails}))
'''

PROPERTIES = {"no_crash": "nespadne pro žádný vstup", "idempotent": "f(f(x)) = f(x)", "roundtrip": "inverze(f(x)) = x",
              "sorted": "výsledek je seřazený"}


def property_test(file: Path, func: str, prop: str = "no_crash", inverse: str = "", runs: int = 300, seed: int = 1,
                  runner: Callable | None = None) -> dict:
    import subprocess
    import sys
    import tempfile

    if prop not in PROPERTIES:
        raise ValueError(f"Neznámá vlastnost. Umím: {', '.join(PROPERTIES)}.")
    if not re.fullmatch(r"[A-Za-z_]\w*", func) or (inverse and not re.fullmatch(r"[A-Za-z_]\w*", inverse)):
        raise ValueError("Název funkce může obsahovat jen písmena, číslice a podtržítka.")
    if prop == "roundtrip" and not inverse:
        raise ValueError("Pro kontrolu inverze zadej i inverzní funkci.")
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "harness.py"
        h.write_text(HARNESS, encoding="utf-8")
        run = runner or subprocess.run
        r = run([sys.executable, "-I", "-X", "utf8", str(h), str(file), func, prop, str(file.parent), str(seed), inverse, str(runs)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=tmp, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "error": (r.stderr or r.stdout or "")[-600:], "runs": 0, "fails": []}
    return {"ok": not out["fails"], "property": PROPERTIES[prop], **out}


# ---------------------------------------------------------------- 637 crash reproduction
PY_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
JS_FRAME = re.compile(r"at (?:(?P<func>[\w.$<>]+) )?\(?(?P<file>[^\s()]+?):(?P<line>\d+):(?P<col>\d+)\)?")


def parse_crash(text: str, project: Path | None = None) -> dict:
    lines = (text or "").strip().splitlines()
    frames = [{"file": m["file"], "line": int(m["line"]), "func": m["func"]} for m in PY_FRAME.finditer(text or "")]
    lang = "python"
    if not frames:
        frames = [{"file": m["file"], "line": int(m["line"]), "func": m["func"] or "(anonymní)"} for m in JS_FRAME.finditer(text or "")]
        frames.reverse()          # JS lists the innermost call first
        lang = "javascript" if frames else "?"
    exc = next((ln.strip() for ln in reversed(lines) if re.match(r"^\s*(\w+\.)*\w*(Error|Exception|Warning|Interrupt|Exit)\b", ln.strip())), lines[-1] if lines else "")
    if lang == "javascript":
        exc = next((ln.strip() for ln in lines if re.match(r"^\s*\w*Error\b", ln.strip())), exc)
    root = str(project.resolve()) if project else None

    def mine(f):
        p = f["file"].replace("\\", "/")
        return not re.search(r"site-packages|node_modules|/lib/python\d|<frozen|internal/", p) and (not root or p.startswith(root.replace("\\", "/")) or not os.path.isabs(p))
    own = [f for f in frames if mine(f)]
    culprit = own[-1] if own else (frames[-1] if frames else None)
    context = []
    if culprit:
        p = Path(culprit["file"]) if os.path.isabs(culprit["file"]) or not project else project / culprit["file"]
        if p.is_file():
            src = p.read_text(encoding="utf-8", errors="replace").splitlines()
            lo = max(0, culprit["line"] - 4)
            context = [f"{i + 1:>5}{'→' if i + 1 == culprit['line'] else ' '} {src[i]}" for i in range(lo, min(len(src), culprit["line"] + 3))]
    test = ""
    if culprit and lang == "python":
        mod = Path(culprit["file"]).stem
        etype = exc.split(":")[0].split(".")[-1] if exc else "Exception"
        test = (f"# Reprodukce pádu: {exc[:100]}\nimport pytest\n\nfrom {mod} import {culprit['func'] if culprit['func'] != '<module>' else '*'}\n\n\n"
                f"def test_repro_{re.sub(r'[^a-z0-9_]', '_', culprit['func'].lower())}():\n"
                f"    # TODO: doplň vstup, se kterým to spadlo (z logu / od uživatele)\n"
                f"    with pytest.raises({etype if re.fullmatch(r'[A-Za-z]+', etype) else 'Exception'}):\n"
                f"        {culprit['func']}(...)\n")
    return {"language": lang, "exception": exc, "frames": frames, "own_frames": own, "culprit": culprit, "context": context, "test": test}


# ---------------------------------------------------------------- 640 battery profiler
def battery_profile(samples: list[dict]) -> dict:
    """samples: [{t, percent, plugged, procs: {name: cpu_seconds_total}}] taken over time while on battery."""
    on_bat = [s for s in samples if not s.get("plugged")]
    if len(on_bat) < 2:
        return {"ok": False, "reason": "Potřebuji měření na baterii (odpoj nabíječku) aspoň ve dvou bodech."}
    hours = (on_bat[-1]["t"] - on_bat[0]["t"]) / 3600
    drop = on_bat[0]["percent"] - on_bat[-1]["percent"]
    rate = drop / hours if hours > 0 else 0
    cpu: Counter = Counter()
    first, last = on_bat[0]["procs"], on_bat[-1]["procs"]
    for name, total in last.items():
        cpu[name] += max(0.0, total - first.get(name, 0.0))
    all_cpu = sum(cpu.values()) or 1
    top = [{"app": n, "cpu_s": round(v, 1), "share_pct": round(100 * v / all_cpu, 1), "est_pct_per_h": round(rate * v / all_cpu, 2)}
           for n, v in cpu.most_common(8) if v > 0]
    left_h = on_bat[-1]["percent"] / rate if rate > 0 else None
    return {"ok": True, "hours": round(hours, 2), "drop_pct": round(drop, 1), "pct_per_hour": round(rate, 1),
            "hours_left": round(left_h, 1) if left_h else None, "top": top}


def battery_sample() -> dict:
    import psutil

    b = psutil.sensors_battery()
    procs: dict[str, float] = defaultdict(float)
    for p in psutil.process_iter(["name", "cpu_times"]):
        ct = p.info.get("cpu_times")
        if ct and p.info.get("name"):
            procs[p.info["name"]] += ct.user + ct.system
    return {"t": time.time(), "percent": b.percent if b else None, "plugged": b.power_plugged if b else True, "procs": dict(procs)}


# ---------------------------------------------------------------- 536 browser compatibility
async def engine_matrix(url: str, out_dir: Path, engines: tuple[str, ...] = ("chromium", "firefox", "webkit")) -> dict:
    from playwright.async_api import async_playwright

    from .testlab import page_url

    target = page_url(url)
    res: dict[str, Any] = {}
    shots: dict[str, Path] = {}
    async with async_playwright() as pw:
        for eng in engines:
            try:
                kw = {"executable_path": os.environ["JARVIS_CHROMIUM"]} if eng == "chromium" and os.environ.get("JARVIS_CHROMIUM") else {}
                b = await getattr(pw, eng).launch(headless=True, **kw)
            except Exception as e:  # noqa: BLE001 – engine not installed
                res[eng] = {"available": False, "note": str(e).splitlines()[0][:160]}
                continue
            errs, console, failed = [], [], []
            try:
                page = await b.new_page(viewport={"width": 1280, "height": 800})
                page.on("pageerror", lambda e: errs.append(str(e)[:200]))
                page.on("console", lambda m: m.type == "error" and console.append(m.text[:200]))
                page.on("requestfailed", lambda r: failed.append(r.url[:160]))
                t = time.perf_counter()
                await page.goto(target, wait_until="load", timeout=30000)
                await page.wait_for_timeout(600)
                shot = out_dir / f"{eng}.png"
                await page.screenshot(path=str(shot), full_page=False)
                shots[eng] = shot
                res[eng] = {"available": True, "load_ms": round((time.perf_counter() - t) * 1000), "errors": errs, "console": console,
                            "failed_requests": failed}
            except Exception as e:  # noqa: BLE001
                res[eng] = {"available": True, "error": str(e)[:200]}
            finally:
                await b.close()
    diffs = {}
    from .design import visual_diff

    base = next(iter(shots), None)
    for eng, shot in shots.items():
        if eng != base:
            d = visual_diff(shots[base], shot, out_dir / f"diff-{base}-{eng}.png")
            diffs[f"{base}↔{eng}"] = d.get("changed_pct")
    return {"url": target, "engines": res, "visual_diff_pct": diffs, "screenshots": [str(p) for p in shots.values()]}


# ---------------------------------------------------------------- 321 file relationships
TEXT_EXT = {".md", ".txt", ".html", ".htm", ".css", ".js", ".ts", ".py", ".json", ".csv", ".tex", ".xml", ".yml", ".yaml", ".ini", ".toml"}


def file_relations(root: Path, limit: int = 3000) -> dict:
    files = [p for p in root.rglob("*") if p.is_file() and not any(x.startswith(".") or x in ("node_modules", "__pycache__") for x in p.relative_to(root).parts)][:limit]
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    edges: list[dict] = []
    by_stem: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        by_stem[p.stem.lower()].append(p)
    for stem, group in by_stem.items():
        if len(group) > 1 and len({p.suffix for p in group}) > 1:
            for p in group[1:]:
                edges.append({"a": rel(group[0]), "b": rel(p), "kind": "stejný název (jiný formát)"})
    names = {p.name.lower(): p for p in files}
    for p in files:
        if p.suffix.lower() not in TEXT_EXT or p.stat().st_size > 2_000_000:
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        for name, other in names.items():
            if other != p and len(name) > 4 and name in text:
                kind = "používá" if p.suffix.lower() in (".html", ".htm", ".css", ".js", ".ts", ".md") else "zmiňuje"
                edges.append({"a": rel(p), "b": rel(other), "kind": kind})
    sizes: dict[int, list[Path]] = defaultdict(list)
    for p in files:
        sizes[p.stat().st_size].append(p)
    for group in sizes.values():
        if len(group) < 2 or group[0].stat().st_size == 0:
            continue
        hashes: dict[str, list[Path]] = defaultdict(list)
        for p in group:
            hashes[hashlib.sha256(p.read_bytes()).hexdigest()].append(p)
        for same in hashes.values():
            for p in same[1:]:
                edges.append({"a": rel(same[0]), "b": rel(p), "kind": "stejný obsah"})
    linked = {e["a"] for e in edges} | {e["b"] for e in edges}
    degree = Counter([e["a"] for e in edges] + [e["b"] for e in edges])
    return {"files": len(files), "edges": edges[:2000], "hubs": [{"file": f, "links": n} for f, n in degree.most_common(8)],
            "lonely": sorted(rel(p) for p in files if rel(p) not in linked)[:50]}


def relations_svg(r: dict, max_nodes: int = 40) -> str:
    nodes = [h["file"] for h in r["hubs"]]
    for e in r["edges"]:
        for n in (e["a"], e["b"]):
            if n not in nodes and len(nodes) < max_nodes:
                nodes.append(n)
    pos = {n: (400 + 300 * math.cos(2 * math.pi * i / max(1, len(nodes))), 400 + 300 * math.sin(2 * math.pi * i / max(1, len(nodes))))
           for i, n in enumerate(nodes)}
    col = {"stejný název (jiný formát)": "#2e86ab", "používá": "#76b041", "zmiňuje": "#f18f01", "stejný obsah": "#e4572e"}
    lines = "".join(f'<line x1="{pos[e["a"]][0]:.0f}" y1="{pos[e["a"]][1]:.0f}" x2="{pos[e["b"]][0]:.0f}" y2="{pos[e["b"]][1]:.0f}" '
                    f'stroke="{col.get(e["kind"], "#999")}" stroke-width="1.6" opacity=".7"/>' for e in r["edges"] if e["a"] in pos and e["b"] in pos)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="#334"/><text x="{x + 8:.0f}" y="{y + 4:.0f}" font-size="11">{esc(n[-40:])}</text>'
                   for n, (x, y) in pos.items())
    legend = "".join(f'<text x="20" y="{20 + 16 * i}" font-size="12" fill="{c}">■ {k}</text>' for i, (k, c) in enumerate(col.items()))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="820" font-family="Segoe UI, sans-serif"><rect width="100%" height="100%" fill="#fff"/>{legend}{lines}{dots}</svg>'
