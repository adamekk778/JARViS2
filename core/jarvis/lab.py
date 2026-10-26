"""OMEGA §57 / §36 / §37 / §19 lab and simulation: what a data series says (trend, break, outliers, period,
correlations), column lineage of SQLite views and queries (SQLite's own authorizer), physics models with parameter
sweeps (RK4), a citation check against Crossref (exists, title, year, retracted), experiment designs (full / half
factorial, randomised, power), a prototype test plan from requirements (success-run sample size, Cpk) and a circuit
tutor whose level follows the student's answers."""
from __future__ import annotations

import difflib
import itertools
import json
import math
import random
import re
import sqlite3
import statistics
import time
from pathlib import Path

from .comms import fold


# ============================================================================================== 770 chart insights
def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx if sxx else 0.0
    r2 = (sxy * sxy / (sxx * syy)) if sxx and syy else 0.0
    return slope, my - slope * mx, r2


def _change_point(ys: list[float]) -> dict | None:
    n = len(ys)
    if n < 8:
        return None
    best, at = None, None
    for k in range(3, n - 2):
        a, b = ys[:k], ys[k:]
        sse = sum((y - sum(a) / len(a)) ** 2 for y in a) + sum((y - sum(b) / len(b)) ** 2 for y in b)
        if best is None or sse < best:
            best, at = sse, k
    a, b = ys[:at], ys[at:]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sd = math.sqrt(best / max(1, n - 2))
    if sd == 0 or abs(mb - ma) / sd < 2:
        return None
    return {"index": at, "before": round(ma, 4), "after": round(mb, 4), "change_pct": round(100 * (mb - ma) / abs(ma), 1) if ma else None}


def _period(ys: list[float]) -> dict | None:
    n = len(ys)
    if n < 12:
        return None
    m = sum(ys) / n
    d = [y - m for y in ys]
    var = sum(v * v for v in d)
    if not var:
        return None
    best = None
    for lag in range(2, n // 2 + 1):
        ac = sum(d[i] * d[i + lag] for i in range(n - lag)) / var * n / (n - lag)
        if ac > 0.5 and (best is None or ac > best[1] + 0.05):
            best = (lag, ac)
            break                                                   # the first strong peak is the period
    return {"lag": best[0], "strength": round(best[1], 2)} if best else None


def chart_insights(series: dict[str, list[float]], labels: list[str] | None = None) -> dict:
    """Plain-language reading of one or more series: trend, a level shift, outliers, a repeating period, and how the
    series move together."""
    out, sentences = {}, []
    for name, raw in series.items():
        ys = [float(v) for v in raw if v is not None and math.isfinite(float(v))]
        if len(ys) < 3:
            continue
        med = statistics.median(ys)
        mad = statistics.median([abs(y - med) for y in ys]) or 0
        outl = [i for i, y in enumerate(ys) if mad and abs(0.6745 * (y - med) / mad) > 3.5]
        clean = [med if i in outl else y for i, y in enumerate(ys)]       # one wild value must not hide the trend or a shift
        xs = list(range(len(ys)))
        slope, _, r2 = _linreg(xs, clean)
        span = max(clean) - min(clean) or 1
        trend = "stagnuje"
        if r2 >= 0.3 and abs(slope) * len(ys) > 0.1 * span:
            trend = "roste" if slope > 0 else "klesá"
        cp, per = _change_point(clean), _period(clean)
        lab = (lambda i: labels[i] if labels and i < len(labels) else str(i + 1))
        info = {"n": len(ys), "first": ys[0], "last": ys[-1], "change_pct": round(100 * (ys[-1] - ys[0]) / abs(ys[0]), 1) if ys[0] else None,
                "min": {"value": min(ys), "at": lab(ys.index(min(ys)))}, "max": {"value": max(ys), "at": lab(ys.index(max(ys)))},
                "trend": trend, "slope": round(slope, 4), "r2": round(r2, 3), "outliers": [{"at": lab(i), "value": ys[i]} for i in outl],
                "change_point": dict(cp, at=lab(cp["index"])) if cp else None, "period": per}
        out[name] = info
        s = f"{name} {trend}"
        if info["change_pct"] is not None:
            s += f" ({ys[0]:g} → {ys[-1]:g}, {info['change_pct']:+g} %)"
        s += f", nejvýš {info['max']['value']:g} v {info['max']['at']}, nejníž {info['min']['value']:g} v {info['min']['at']}"
        if cp:
            s += f"; od {lab(cp['index'])} skok z průměru {cp['before']:.4g} na {cp['after']:.4g}"
        if per:
            s += f"; opakuje se po {per['lag']} bodech"
        if outl:
            s += "; výkyvy: " + ", ".join(f"{lab(i)} ({ys[i]:g})" for i in outl[:4])
        sentences.append(s + ".")
    corr = []
    names = list(out)
    for a, b in itertools.combinations(names, 2):
        xa, xb = [float(v) for v in series[a]], [float(v) for v in series[b]]
        n = min(len(xa), len(xb))
        if n >= 4:
            try:
                r = statistics.correlation(xa[:n], xb[:n])
            except statistics.StatisticsError:
                continue
            if abs(r) >= 0.7:
                corr.append({"a": a, "b": b, "r": round(r, 3)})
                sentences.append(f"{a} a {b} se pohybují {'spolu' if r > 0 else 'proti sobě'} (r = {r:.2f}) – to ale neznamená, že jedno způsobuje druhé.")
    return {"series": out, "correlations": corr, "text": " ".join(sentences)}


# ============================================================================================== 771 lineage
def _split_top(s: str, sep: str = ",") -> list[str]:
    out, depth, cur, q = [], 0, [], None
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"`[":
            q = "]" if ch == "[" else ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _top_from(sql: str) -> tuple[str, str, str] | None:
    """('WITH … SELECT ' prefix, select list, 'FROM …' rest) of the first SELECT at depth 0."""
    low, depth, q, i = sql.lower(), 0, None, 0
    sel = frm = None
    while i < len(sql):
        ch = sql[i]
        if q:
            if ch == q:
                q = None
        elif ch in "'\"`":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and re.match(r"\bselect\b", low[i:i + 7]) and (i == 0 or not low[i - 1].isalnum()) and sel is None:
            sel = i + 6
            if re.match(r"\s+distinct\b", low[sel:sel + 10]):
                sel += len(re.match(r"\s+distinct", low[sel:]).group(0))
        elif depth == 0 and sel is not None and re.match(r"\bfrom\b", low[i:i + 5]) and not low[i - 1].isalnum():
            frm = i
            break
        i += 1
    if sel is None or frm is None:
        return None
    return sql[:sel], sql[sel:frm], sql[frm:]


def _alias(expr: str) -> str:
    """The output name of a select-list item: its AS alias, an implicit alias, or the bare column name."""
    m = re.search(r"\s+as\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|\w+)\s*$", expr, re.I)
    if m:
        return m.group(1).strip("\"`[]")
    m = re.fullmatch(r"\s*(?:\w+\.)?\"?(\w+)\"?\s*", expr)
    if m:
        return m.group(1)
    m = re.search(r"[)\w\"]\s+(\w+)\s*$", expr)
    return m.group(1) if m else expr.strip()


def _strip_alias(expr: str) -> str:
    """'sum(a) AS total' / 'c.city mesto' → the expression without its output name."""
    e = expr.strip()
    m = re.fullmatch(r"(?is)(.+?)\s+as\s+\S+", e)
    if m:
        return m.group(1)
    m = re.fullmatch(r"(?s)(.*[)\w\"])\s+(\w+)", e)
    if m and m.group(2).lower() not in ("end", "null", "asc", "desc") and not re.search(r"(?i)\b(case|and|or|not|is|in|between|like|then|else|when)\s*$", m.group(1)):
        return m.group(1)
    return e


def lineage(db: Path, name: str = "", sql: str = "", _depth: int = 0) -> dict:
    """Which base-table columns every output column of a view (or a query) comes from, and which columns only filter /
    join / group. Uses SQLite's authorizer on the user's real schema, read-only; views used by the view are followed."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        views = {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='view'")}
        if name:
            if name not in views:
                raise ValueError(f"Pohled „{name}“ v databázi není. Pohledy: {', '.join(views) or 'žádné'}.")
            sql = re.sub(r"(?is)^\s*create\s+(temp\w*\s+)?view\s+(if\s+not\s+exists\s+)?[\w\"`\[\].]+\s*(\([^)]*\))?\s+as\s+", "", views[name])
        sql = sql.strip().rstrip(";")
        parts = _top_from(sql)
        if not parts:
            raise ValueError("Dotaz nemá SELECT … FROM.")
        prefix, cols, rest = parts
        reads: list[tuple[str, str]] = []

        def auth(action, a1, a2, _db, inside_view):
            # only what this query reads itself – reads made inside a view it uses are that view's business
            if action == sqlite3.SQLITE_READ and inside_view is None and a2 and (a1 in tables or a1 in views):
                reads.append((a1, a2))
            return sqlite3.SQLITE_OK
        conn.set_authorizer(auth)
        try:
            conn.execute(f"{prefix} 1 {rest} LIMIT 0")
        except sqlite3.Error as e:
            raise ValueError(f"Dotaz nejde přeložit: {e}") from e
        base = set(reads)
        out = []
        for expr in _split_top(cols):
            reads.clear()
            if expr.strip() == "*" or expr.strip().endswith(".*"):
                out.append({"column": expr.strip(), "from": [], "expression": expr.strip(), "note": "hvězdička – všechny sloupce"})
                continue
            try:
                conn.execute(f"{prefix} {expr} {rest} LIMIT 0")
            except sqlite3.Error as e:
                out.append({"column": _alias(expr), "from": [], "expression": expr, "note": f"nejde přeložit: {e}"})
                continue
            alias = _alias(expr)
            core = _strip_alias(expr)
            used = {w.lower() for w in re.findall(r"\w+", core)}
            mine = (set(reads) - base) | {r for r in reads if r[1].lower() in used}
            out.append({"column": alias, "from": sorted(f"{t}.{c}" for t, c in mine), "expression": expr.strip(),
                        "computed": not re.fullmatch(r"\s*(?:\w+\.)?\"?\w+\"?\s*", core)})
        conn.set_authorizer(None)
    finally:
        conn.close()
    inner: dict[str, dict] = {}

    def resolve(refs: list[str]) -> list[str]:
        res = set()
        for ref in refs:
            v, c = ref.split(".", 1)
            if v in views and _depth < 8:
                if v not in inner:
                    inner[v] = {x["column"].lower(): x["from"] for x in lineage(db, v, _depth=_depth + 1)["columns"]}
                res |= set(inner[v].get(c.lower(), [ref]))
            else:
                res.add(ref)
        return sorted(res)
    for o in out:
        o["from"] = resolve(o["from"])
    filt = resolve([f"{t}.{c}" for t, c in sorted(base)])
    return {"name": name or "dotaz", "columns": out, "filters_and_joins": filt, "via_views": sorted(inner),
            "sources": sorted({c.split(".")[0] for o in out for c in o["from"]} | {f.split(".")[0] for f in filt})}


def all_lineage(db: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
    finally:
        conn.close()
    res = []
    for n in names:
        try:
            res.append(lineage(db, n))
        except ValueError as e:
            res.append({"name": n, "error": str(e)})
    return res


# ============================================================================================== 776 physics
def _rk4(f, y, t, dt):
    k1 = f(t, y)
    k2 = f(t + dt / 2, [a + dt / 2 * b for a, b in zip(y, k1)])
    k3 = f(t + dt / 2, [a + dt / 2 * b for a, b in zip(y, k2)])
    k4 = f(t + dt, [a + dt * b for a, b in zip(y, k3)])
    return [a + dt / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(y, k1, k2, k3, k4)]


def simulate(model: str, p: dict) -> dict:
    g = float(p.get("g", 9.81))
    if model == "projectile":
        v0, ang, h0, k = float(p["v0"]), math.radians(float(p.get("angle", 45))), float(p.get("h0", 0)), float(p.get("drag", 0))

        def f(_t, s):
            x, y, vx, vy = s
            v = math.hypot(vx, vy)
            return [vx, vy, -k * v * vx, -g - k * v * vy]
        s, t, dt, top = [0.0, h0, v0 * math.cos(ang), v0 * math.sin(ang)], 0.0, 0.002, h0
        while t < 600:
            n = _rk4(f, s, t, dt)
            if n[1] < 0 and n[3] < 0:
                frac = s[1] / (s[1] - n[1])                              # land exactly at y = 0
                s = [a + (b - a) * frac for a, b in zip(s, n)]
                t += dt * frac
                break
            s, t = n, t + dt
            top = max(top, s[1])
        return {"range_m": round(s[0], 3), "max_height_m": round(top, 3), "flight_s": round(t, 3), "impact_speed": round(math.hypot(s[2], s[3]), 3)}
    if model == "pendulum":
        L, a0, c = float(p["length"]), math.radians(float(p.get("angle", 10))), float(p.get("damping", 0))

        def f(_t, s):
            return [s[1], -g / L * math.sin(s[0]) - c * s[1]]
        s, t, dt, cross, prev = [a0, 0.0], 0.0, 0.0005, [], a0
        while t < 120 and len(cross) < 3:
            s, t = _rk4(f, s, t, dt), t + dt
            if prev > 0 >= s[0]:
                cross.append(t)
            prev = s[0]
        period = (cross[2] - cross[1]) if len(cross) >= 3 else None
        small = 2 * math.pi * math.sqrt(L / g)
        return {"period_s": round(period, 4) if period else None, "small_angle_period_s": round(small, 4),
                "difference_pct": round(100 * (period - small) / small, 2) if period else None}
    if model == "spring":
        m, k, c = float(p["mass"]), float(p["k"]), float(p.get("c", 0))
        x0, v0 = float(p.get("x0", 0.1)), float(p.get("v0", 0))
        wn = math.sqrt(k / m)
        zeta = c / (2 * math.sqrt(k * m))

        def f(_t, s):
            return [s[1], -(c * s[1] + k * s[0]) / m]
        s, t, dt, peak, settle = [x0, v0], 0.0, min(0.001, 0.02 / wn), 0.0, None
        horizon = 50 / max(zeta * wn, 0.05)
        last_out = 0.0
        while t < horizon:
            s, t = _rk4(f, s, t, dt), t + dt
            if s[0] * x0 < 0:
                peak = max(peak, abs(s[0]))
            if abs(s[0]) > 0.02 * abs(x0):
                last_out = t
        settle = round(last_out, 3) if zeta > 0 else None
        kind = "netlumené" if zeta == 0 else "podtlumené (kmitá)" if zeta < 1 else "kriticky tlumené" if abs(zeta - 1) < 1e-9 else "přetlumené"
        return {"natural_hz": round(wn / (2 * math.pi), 4), "damping_ratio": round(zeta, 4), "kind": kind,
                "overshoot_pct": round(100 * peak / abs(x0), 2) if x0 else None, "settling_s": settle}
    if model == "rc":
        r, cap, v = float(p["r"]), float(p["c"]), float(p.get("v", 5))
        tau = r * cap
        return {"tau_s": tau, "t63_s": tau, "t99_s": round(tau * math.log(100), 6), "v_after_tau": round(v * (1 - math.exp(-1)), 4)}
    if model == "cooling":
        t0, env, k = float(p["t0"]), float(p["env"]), float(p["k"])
        target = float(p.get("target", env + (t0 - env) / 2))
        if (target - env) * (t0 - env) <= 0:
            raise ValueError("Cílová teplota musí ležet mezi počáteční a okolím.")
        return {"time_to_target": round(math.log((t0 - env) / (target - env)) / k, 4), "half_life": round(math.log(2) / k, 4)}
    raise ValueError("Model: projectile, pendulum, spring, rc nebo cooling.")


def sweep(model: str, params: dict, var: str, values: list[float], output: str) -> dict:
    rows = []
    for v in values:
        r = simulate(model, dict(params, **{var: v}))
        if output not in r:
            raise ValueError(f"Výstup „{output}“ model {model} nemá. Má: {', '.join(r)}.")
        rows.append({var: v, output: r[output]})
    ys = [r[output] for r in rows if isinstance(r[output], (int, float))]
    best = max(rows, key=lambda r: r[output] if isinstance(r[output], (int, float)) else -math.inf)
    return {"rows": rows, "best": best, "min": min(ys) if ys else None, "max": max(ys) if ys else None}


# ============================================================================================== 777 citations
DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)


def references(text: str) -> list[dict]:
    """Reference lines and their DOIs (one per line / numbered entry)."""
    out = []
    for line in [x.strip() for x in re.split(r"\n+", text) if x.strip()]:
        m = DOI.search(line)
        doi = m.group(0).rstrip(".,;)]") if m else None
        if doi or re.search(r"\(?\b(19|20)\d{2}\b\)?", line) and len(line) > 40:
            out.append({"line": line, "doi": doi})
    return out


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", fold(s))}


async def check_citations(rt, text: str, limit: int = 20) -> list[dict]:
    refs = references(text)[:limit]
    res = []
    async with rt.http() as c:
        for r in refs:
            item = {"line": r["line"][:200], "doi": r["doi"]}
            try:
                if r["doi"]:
                    resp = await c.get(f"https://api.crossref.org/works/{r['doi']}", headers={"User-Agent": "JARVIS-desktop"}, timeout=20)
                    if resp.status_code == 404:
                        item.update(status="neexistuje", problems=["DOI v Crossrefu není – překlep nebo vymyšlená citace"])
                        res.append(item)
                        continue
                    resp.raise_for_status()
                    w = resp.json()["message"]
                else:
                    resp = await c.get("https://api.crossref.org/works", params={"query.bibliographic": r["line"][:300], "rows": 1},
                                       headers={"User-Agent": "JARVIS-desktop"}, timeout=20)
                    resp.raise_for_status()
                    found = resp.json()["message"].get("items") or []
                    if not found:
                        item.update(status="nenalezeno", problems=["bez DOI a v Crossrefu jsem ji nenašel"])
                        res.append(item)
                        continue
                    w = found[0]
                title = (w.get("title") or [""])[0]
                year = ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0]
                authors = [a.get("family", "") for a in (w.get("author") or [])][:3]
                problems = []
                tw = _words(title)
                overlap = len(tw & _words(r["line"])) / len(tw) if tw else 0
                if overlap < 0.6:
                    problems.append(f"název nesedí (v Crossrefu: „{title[:90]}“)")
                years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", r["line"])]
                if year and years and year not in years:
                    problems.append(f"rok {years[0]} ≠ {year}")
                if authors and authors[0] and fold(authors[0]) not in fold(r["line"]):
                    problems.append(f"první autor v Crossrefu je {authors[0]}")
                doi = w.get("DOI") or r["doi"]
                upd = await c.get("https://api.crossref.org/works", params={"filter": f"updates:{doi}", "rows": 5},
                                  headers={"User-Agent": "JARVIS-desktop"}, timeout=20)
                retracted = False
                if upd.status_code == 200:
                    for u in upd.json()["message"].get("items") or []:
                        for t in u.get("update-to") or []:
                            if fold(t.get("DOI", "")) == fold(doi) and t.get("type") in ("retraction", "withdrawal", "removal"):
                                retracted = True
                if retracted:
                    problems.insert(0, "ČLÁNEK BYL STAŽEN (retraction)")
                item.update(status="nalezeno" if r["doi"] else "dohledáno", title=title, year=year, authors=authors, doi=doi,
                            journal=(w.get("container-title") or [""])[0], retracted=retracted, problems=problems,
                            match=round(difflib.SequenceMatcher(None, fold(title), fold(r["line"])).ratio(), 2) if not r["doi"] else None)
            except Exception as e:  # noqa: BLE001 – one failing lookup does not stop the rest
                item.update(status="chyba", problems=[f"Crossref neodpověděl: {type(e).__name__}"])
            res.append(item)
    return res


# ============================================================================================== 208 experiment design
def _z(p: float) -> float:
    return statistics.NormalDist().inv_cdf(p)


def experiment_design(factors: list[dict], replicates: int = 1, seed: int = 1, half_fraction: bool = False, blocks: int = 1,
                      effect: float | None = None, sd: float | None = None, alpha: float = 0.05, power: float = 0.8) -> dict:
    """Factors [{name, levels: [...]}] → runs (full factorial, or a half fraction for 2-level factors: the last factor =
    product of the others), replicated, split into blocks and randomised within blocks; with effect + sd the replicates
    needed to see a main effect."""
    names = [f["name"] for f in factors]
    levels = [list(f["levels"]) for f in factors]
    if any(len(lv) < 2 for lv in levels):
        raise ValueError("Každý faktor potřebuje aspoň 2 úrovně.")
    need = None
    if effect and sd:
        n_total = 4 * (_z(1 - alpha / 2) + _z(power)) ** 2 * sd * sd / (effect * effect)
        need = {"runs_total": math.ceil(n_total)}
    if half_fraction:
        if any(len(lv) != 2 for lv in levels) or len(levels) < 3:
            raise ValueError("Poloviční plán jde jen se 3 a více faktory o 2 úrovních.")
        base = list(itertools.product([-1, 1], repeat=len(levels) - 1))
        coded = [list(b) + [math.prod(b)] for b in base]
        cells = [[levels[i][0 if c < 0 else 1] for i, c in enumerate(row)] for row in coded]
        resolution = len(levels)
    else:
        cells = [list(c) for c in itertools.product(*levels)]
        resolution = None
    if need:
        replicates = max(replicates, math.ceil(need["runs_total"] / len(cells)))
        need["replicates"] = replicates
    rng = random.Random(seed)
    runs = []
    for rep in range(replicates):
        for i, c in enumerate(cells):
            runs.append({"cell": i + 1, "replicate": rep + 1, **dict(zip(names, c))})
    blocks = max(1, min(blocks, replicates))
    out = []
    for b in range(blocks):
        part = [r for r in runs if (r["replicate"] - 1) % blocks == b]
        rng.shuffle(part)
        out += [dict(r, block=b + 1) for r in part]
    for i, r in enumerate(out, 1):
        r["run"] = i
    return {"runs": out, "cells": len(cells), "replicates": replicates, "total": len(out), "resolution": resolution, "power": need,
            "csv": "run;block;" + ";".join(names) + ";výsledek\n" + "\n".join(f"{r['run']};{r['block']};" + ";".join(str(r[n]) for n in names) + ";" for r in out) + "\n"}


# ============================================================================================== 480 prototype test plan
def success_run(confidence: float, reliability: float, failures: int = 0) -> int:
    """Samples needed to show `reliability` with `confidence` (zero failures: n = ln(1−C) / ln R; with failures the
    binomial sum)."""
    if failures == 0:
        return math.ceil(math.log(1 - confidence) / math.log(reliability))
    n = failures + 1
    while sum(math.comb(n, i) * (1 - reliability) ** i * reliability ** (n - i) for i in range(failures + 1)) > 1 - confidence:
        n += 1
    return n


def test_plan(reqs: list[dict], confidence: float = 0.9, reliability: float = 0.9) -> dict:
    n = success_run(confidence, reliability)
    ordered = sorted(reqs, key=lambda r: (bool(r.get("destructive")), r.get("name", "")))
    plan = []
    for i, r in enumerate(ordered, 1):
        lim = " – ".join(x for x in (f"min {r['min']}" if "min" in r else "", f"max {r['max']}" if "max" in r else "") if x)
        plan.append({"id": f"T{i:02d}", "requirement": r["name"], "limits": lim, "unit": r.get("unit", ""), "method": r.get("method", ""),
                     "samples": n if not r.get("samples") else int(r["samples"]), "destructive": bool(r.get("destructive"))})
    sheet = "test;požadavek;vzorek;naměřeno;jednotka\n" + "\n".join(f"{p['id']};{p['requirement']};{k};;{p['unit']}" for p in plan for k in range(1, p["samples"] + 1))
    return {"plan": plan, "samples_per_test": n, "confidence": confidence, "reliability": reliability, "sheet": sheet + "\n",
            "note": "Nedestruktivní zkoušky jdou první, ať stejné vzorky projdou víc testy."}


def evaluate_tests(reqs: list[dict], results: list[dict], confidence: float = 0.9) -> list[dict]:
    """Results [{requirement, value}] → per requirement pass rate, mean, sd, Cpk, and the reliability shown."""
    out = []
    for r in reqs:
        vals = [float(x["value"]) for x in results if x.get("requirement") == r["name"] and x.get("value") not in (None, "")]
        if not vals:
            out.append({"requirement": r["name"], "n": 0, "verdict": "neměřeno"})
            continue
        lo, hi = r.get("min"), r.get("max")
        ok = [v for v in vals if (lo is None or v >= lo) and (hi is None or v <= hi)]
        mu = statistics.fmean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        cpk = None
        if sd > 0:
            sides = [x for x in ((hi - mu) / (3 * sd) if hi is not None else None, (mu - lo) / (3 * sd) if lo is not None else None) if x is not None]
            cpk = round(min(sides), 2) if sides else None
        fails = len(vals) - len(ok)
        shown = round((1 - confidence) ** (1 / len(vals)), 4) if not fails else None
        out.append({"requirement": r["name"], "n": len(vals), "passed": len(ok), "failed": fails, "mean": round(mu, 4), "sd": round(sd, 4), "cpk": cpk,
                    "reliability_shown": shown, "verdict": "vyhověl" if not fails and (cpk is None or cpk >= 1.33) else
                    "vyhověl, ale těsně (Cpk < 1,33)" if not fails else "nevyhověl"})
    return out


# ============================================================================================== 456 / 451 circuit tutor
TUTOR_SQL = """CREATE TABLE IF NOT EXISTS tutor_progress (subject TEXT PRIMARY KEY, level INTEGER NOT NULL, streak INTEGER NOT NULL,
  recent TEXT NOT NULL, answered INTEGER NOT NULL, correct INTEGER NOT NULL, current TEXT, updated REAL);"""
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]


def _r(rng, lo=100, hi=10000):
    while True:
        v = rng.choice(E12) * 10 ** rng.randint(2, 4)
        if lo <= v <= hi:
            return v


def problem(level: int, rng: random.Random) -> dict:
    """A circuit exercise of level 1–5 with the exact answer and the worked solution."""
    if level <= 1:
        u, r = rng.choice([3.3, 5, 9, 12, 24]), _r(rng)
        i = u / r
        return {"level": 1, "question": f"Na rezistoru {r:g} Ω je napětí {u:g} V. Jaký jím teče proud?", "answer": i, "unit": "A",
                "solution": f"Ohmův zákon: I = U / R = {u:g} / {r:g} = {i * 1000:.3g} mA."}
    if level == 2:
        u, r1, r2 = rng.choice([5, 9, 12]), _r(rng), _r(rng)
        i = u / (r1 + r2)
        return {"level": 2, "question": f"Rezistory {r1:g} Ω a {r2:g} Ω jsou v sérii na {u:g} V. Jaké napětí je na {r2:g} Ω?", "answer": i * r2, "unit": "V",
                "solution": f"Sériově se odpory sčítají: {r1 + r2:g} Ω, proud {i * 1000:.3g} mA, na R2: U = I·R2 = {i * r2:.3g} V (dělič napětí)."}
    if level == 3:
        r1, r2 = _r(rng), _r(rng)
        rp = r1 * r2 / (r1 + r2)
        return {"level": 3, "question": f"Jaký je výsledný odpor {r1:g} Ω a {r2:g} Ω zapojených paralelně?", "answer": rp, "unit": "Ω",
                "solution": f"Paralelně: R = R1·R2 / (R1 + R2) = {r1 * r2:g} / {r1 + r2:g} = {rp:.4g} Ω (vždy menší než nejmenší z nich)."}
    if level == 4:
        u, r1, r2, r3 = rng.choice([5, 12, 24]), _r(rng), _r(rng), _r(rng)
        rp = r2 * r3 / (r2 + r3)
        it = u / (r1 + rp)
        i3 = it * rp / r3
        return {"level": 4, "question": f"Zdroj {u:g} V, R1 = {r1:g} Ω v sérii s paralelní dvojicí R2 = {r2:g} Ω a R3 = {r3:g} Ω. Jaký proud teče přes R3?",
                "answer": i3, "unit": "A",
                "solution": f"R2∥R3 = {rp:.4g} Ω, celkem {r1 + rp:.4g} Ω, proud ze zdroje {it * 1000:.4g} mA, napětí na dvojici {it * rp:.4g} V, přes R3: {i3 * 1000:.4g} mA."}
    u, vf, ma = rng.choice([5, 9, 12]), rng.choice([1.8, 2.0, 2.1, 3.0, 3.2]), rng.choice([5, 10, 15, 20])
    r = (u - vf) / (ma / 1000)
    p = (u - vf) * ma / 1000
    return {"level": 5, "question": f"LED ({vf:g} V, {ma} mA) na zdroji {u:g} V. Jaký výkon se ztratí v předřadném rezistoru?", "answer": p, "unit": "W",
            "solution": f"Na rezistoru zbývá {u - vf:g} V, R = {u - vf:g} / {ma / 1000:g} = {r:.4g} Ω, výkon P = U·I = {u - vf:g} · {ma / 1000:g} = {p * 1000:.4g} mW."}


PREFIX = {"k": 1e3, "M": 1e6, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "": 1.0}


def parse_answer(text: str) -> tuple[float, str] | None:
    t = text.strip().replace(",", ".").replace("ohmů", "ohm").replace("ohmy", "ohm")
    m = re.fullmatch(r"(\d+)([kMR])(\d+)\s*(?:Ω|ohm)?", t)                        # 2k2, 4M7, 4R7
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * (1.0 if m.group(2) == "R" else PREFIX[m.group(2)]), "Ω"
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(k|M|m|u|µ)?\s*(Ω|[oO]hm|[AaVvWw])?", t)
    if not m:
        return None
    unit = "Ω" if (m.group(3) or "").lower() in ("ohm", "ω") else (m.group(3) or "").upper()
    return float(m.group(1)) * PREFIX[m.group(2) or ""], unit


class Tutor:
    """Staircase: three right in a row → harder; two wrong out of the last three → easier."""

    def __init__(self, rt, subject: str = "obvody"):
        self.rt, self.subject = rt, subject
        rt.db.conn.executescript(TUTOR_SQL)

    def state(self) -> dict:
        row = self.rt.db.one("SELECT * FROM tutor_progress WHERE subject=?", (self.subject,))
        if row:
            return dict(row)
        return {"subject": self.subject, "level": 1, "streak": 0, "recent": "", "answered": 0, "correct": 0, "current": None}

    def _save(self, s: dict) -> None:
        self.rt.db.exec("INSERT OR REPLACE INTO tutor_progress(subject, level, streak, recent, answered, correct, current, updated) VALUES (?,?,?,?,?,?,?,?)",
                        (self.subject, s["level"], s["streak"], s["recent"], s["answered"], s["correct"], s["current"], time.time()))

    def next(self, seed: int | None = None) -> dict:
        s = self.state()
        p = problem(s["level"], random.Random(seed if seed is not None else time.time_ns()))
        s["current"] = json.dumps(p)
        self._save(s)
        return p

    def answer(self, text: str) -> dict:
        s = self.state()
        if not s["current"]:
            raise ValueError("Teď nemáš zadaný příklad – řekni „dej mi příklad“.")
        p = json.loads(s["current"])
        got = parse_answer(text)
        if got is None:
            raise ValueError("Odpověď napiš jako číslo s jednotkou, např. „12 mA“, „4,7 kΩ“, „2k2“ nebo „0,15 W“.")
        val, unit = got
        unit_ok = not unit or unit == p["unit"]
        right = unit_ok and math.isclose(val, p["answer"], rel_tol=0.02)
        s["answered"] += 1
        s["correct"] += int(right)
        s["recent"] = (s["recent"] + ("1" if right else "0"))[-3:]
        before = s["level"]
        if right:
            s["streak"] += 1
            if s["streak"] >= 3 and s["level"] < 5:
                s["level"], s["streak"], s["recent"] = s["level"] + 1, 0, ""
        else:
            s["streak"] = 0
            if s["recent"].count("0") >= 2 and s["level"] > 1:
                s["level"], s["recent"] = s["level"] - 1, ""
        s["current"] = None
        self._save(s)
        return {"correct": right, "unit_ok": unit_ok, "expected": p["answer"], "unit": p["unit"], "solution": p["solution"], "level_before": before,
                "level": s["level"], "accuracy": round(100 * s["correct"] / s["answered"]), "answered": s["answered"]}
