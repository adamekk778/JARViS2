"""OMEGA §37 / §19 / §36 / §40 maker workshop and planning: a bill of materials from a parts list (grouped, counted,
priced), electrical compatibility of parts (logic levels, supply, current budget), a serial-port monitor, a chart of
sensor data (drawn with Pillow), a two-link robot arm (reach, inverse kinematics, path), a task dependency plan with
the critical path, a learning prerequisite map, a formula explorer, one search across everything and a search over
the user's own workflows (protocols, automations, skills, recorded web workflows)."""
from __future__ import annotations

import math
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from .comms import fold
from .science import _num, column_nums, read_csv

# ============================================================================================== 469 BOM
def _norm_part(name: str) -> str:
    n = fold(name).replace(",", ".")
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"(\d)\s*(k|m|u|n|p)?\s*(ohm|r)\b", lambda m: f"{m.group(1)}{m.group(2) or ''}ohm", n)
    return n


def bom(path: Path, boards: int = 1) -> dict:
    """Parts CSV (part / value / qty / footprint / price / ref) or KiCad-style export → grouped lines × boards, totals, and
    lines without a price or with conflicting footprints."""
    header, rows, _, _ = read_csv(path)
    h = [fold(x) for x in header]

    def col(*names):
        return next((i for i, x in enumerate(h) if any(n in x for n in names)), None)
    pi, vi, qi = col("part", "soucast", "nazev", "component", "description", "popis"), col("value", "hodnota"), col("qty", "pocet", "ks", "quantity", "mnozstvi")
    fi, ci, ri = col("footprint", "pouzdro", "package"), col("price", "cena"), col("ref", "designator", "oznac")
    if pi is None and vi is None:
        raise ValueError("Potřebuju sloupec se součástkou (part / název) nebo hodnotou (value).")
    groups: dict[str, dict] = {}
    for r in rows:
        get = (lambda i: r[i].strip() if i is not None and i < len(r) else "")  # noqa: E731
        name = " ".join(x for x in (get(pi), get(vi)) if x)
        if not name:
            continue
        refs = [x.strip() for x in re.split(r"[,\s]+", get(ri)) if x.strip()]
        qty = _num(get(qi)) if get(qi) else float(len(refs) or 1)
        key = _norm_part(name)
        g = groups.setdefault(key, {"part": name, "qty": 0.0, "refs": [], "footprints": set(), "price": None})
        g["qty"] += qty or 0
        g["refs"] += refs
        if get(fi):
            g["footprints"].add(get(fi))
        if get(ci):
            p = _num(get(ci))
            if p is not None:
                g["price"] = p
    lines, total, missing, conflicts = [], 0.0, [], []
    for g in groups.values():
        need = g["qty"] * boards
        cost = need * g["price"] if g["price"] is not None else None
        if cost is not None:
            total += cost
        else:
            missing.append(g["part"])
        if len(g["footprints"]) > 1:
            conflicts.append(f"{g['part']}: {', '.join(sorted(g['footprints']))}")
        lines.append({"part": g["part"], "per_board": g["qty"], "qty": need, "refs": sorted(set(g["refs"])), "footprint": ", ".join(sorted(g["footprints"])),
                      "unit_price": g["price"], "cost": round(cost, 2) if cost is not None else None})
    lines.sort(key=lambda x: -(x["cost"] or 0))
    return {"lines": lines, "boards": boards, "total": round(total, 2), "missing_price": missing, "footprint_conflicts": conflicts,
            "unique": len(lines), "pieces": sum(x["qty"] for x in lines)}


# ============================================================================================== 470 compatibility
def compatibility(parts: list[dict], supply_v: float, supply_ma: float = 0) -> dict:
    """Parts [{name, logic_v, vin_min, vin_max, current_ma, five_v_tolerant, role: 'mcu'|'sensor'|'module'|'actuator'}]
    → supply in range, logic levels between the controller and each part, total current vs the supply."""
    issues, ok = [], []
    mcu = next((p for p in parts if p.get("role") == "mcu"), None)
    total = 0.0
    for p in parts:
        name = p.get("name", "?")
        lo, hi = p.get("vin_min"), p.get("vin_max")
        if lo is not None and supply_v < lo:
            issues.append(f"{name}: napájení {supply_v} V je pod minimem {lo} V")
        if hi is not None and supply_v > hi:
            issues.append(f"{name}: napájení {supply_v} V je NAD maximem {hi} V – součástka se zničí (dej stabilizátor)")
        total += float(p.get("current_ma") or 0)
        if mcu and p is not mcu and p.get("logic_v") and mcu.get("logic_v"):
            a, b = float(mcu["logic_v"]), float(p["logic_v"])
            if b > a + 0.3 and not mcu.get("five_v_tolerant"):
                issues.append(f"{name} posílá {b:g} V signály do {mcu.get('name')} ({a:g} V) – potřebuješ převodník úrovní nebo dělič")
            elif a > b + 0.3 and not p.get("five_v_tolerant"):
                issues.append(f"{mcu.get('name')} posílá {a:g} V do {name} ({b:g} V) – převodník úrovní")
            elif b < a * 0.66:
                issues.append(f"{name} ({b:g} V) nemusí {mcu.get('name')} spolehlivě přečíst jako logickou 1")
            else:
                ok.append(f"{name} ↔ {mcu.get('name')}: logické úrovně sedí")
        if p.get("role") == "actuator" and float(p.get("current_ma") or 0) > 40:
            issues.append(f"{name} bere {p['current_ma']} mA – nepřipojuj na pin přímo, použij tranzistor / MOSFET / driver")
    if supply_ma:
        if total > supply_ma:
            issues.append(f"celkový odběr {total:.0f} mA je víc než zdroj {supply_ma:.0f} mA")
        elif total > supply_ma * 0.8:
            issues.append(f"odběr {total:.0f} mA je přes 80 % zdroje ({supply_ma:.0f} mA) – malá rezerva")
        else:
            ok.append(f"odběr {total:.0f} mA z {supply_ma:.0f} mA")
    return {"issues": issues, "ok": ok, "total_ma": round(total, 1), "compatible": not issues}


# ============================================================================================== 471 serial
def serial_ports() -> list[dict]:
    try:
        from serial.tools import list_ports
    except ImportError as e:
        raise ValueError("Sériové porty umím číst jen s balíčkem pyserial (součást verze pro PC).") from e
    return [{"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid, "manufacturer": p.manufacturer} for p in list_ports.comports()]


def serial_read(port: str, baud: int = 115200, seconds: float = 5, max_lines: int = 500, send: str = "", opener=None) -> dict:
    """Read a serial port for a few seconds (optionally send one line first): lines, numbers found per line, rate."""
    try:
        import serial
    except ImportError as e:
        raise ValueError("Sériové porty umím číst jen s balíčkem pyserial (součást verze pro PC).") from e
    s = (opener or (lambda: serial.serial_for_url(port, baudrate=baud, timeout=0.2)))()
    lines, buf = [], b""
    t0 = time.monotonic()
    try:
        if send:
            s.write((send.rstrip("\r\n") + "\n").encode())
        while time.monotonic() - t0 < seconds and len(lines) < max_lines:
            chunk = s.read(256)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lines.append(line.decode("utf-8", errors="replace").strip("\r"))
    finally:
        s.close()
    if buf.strip():
        lines.append(buf.decode("utf-8", errors="replace").strip())
    nums = [[float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", ln)] for ln in lines]
    return {"lines": lines, "numbers": nums, "seconds": round(time.monotonic() - t0, 2), "per_second": round(len(lines) / max(0.01, time.monotonic() - t0), 1)}


# ============================================================================================== 472 sensor chart
PALETTE = [(37, 99, 235), (220, 38, 38), (22, 163, 74), (217, 119, 6), (124, 58, 237), (8, 145, 178)]


def sensor_chart(series: dict[str, list[float]], out: Path, x: list[float] | None = None, title: str = "", width: int = 1000, height: int = 480) -> dict:
    """Line chart (Pillow, no extra libraries) with axes, grid and min / max / mean per series."""
    from PIL import Image, ImageDraw

    clean = {k: [v for v in vs if v is not None and math.isfinite(v)] for k, vs in series.items()}
    clean = {k: v for k, v in clean.items() if len(v) >= 2}
    if not clean:
        raise ValueError("Na graf potřebuju aspoň jednu řadu se 2 a více čísly.")
    lo = min(min(v) for v in clean.values())
    hi = max(max(v) for v in clean.values())
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    pad_l, pad_r, pad_t, pad_b = 70, 20, 40, 40
    im = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(im)
    W, H = width - pad_l - pad_r, height - pad_t - pad_b
    for i in range(6):
        y = pad_t + H * i / 5
        d.line([(pad_l, y), (pad_l + W, y)], fill=(229, 231, 235))
        d.text((8, y - 6), f"{hi - (hi - lo) * i / 5:.3g}", fill=(75, 85, 99))
    d.rectangle([pad_l, pad_t, pad_l + W, pad_t + H], outline=(156, 163, 175))
    stats = {}
    for n, (name, vs) in enumerate(clean.items()):
        col = PALETTE[n % len(PALETTE)]
        pts = [(pad_l + W * i / (len(vs) - 1), pad_t + H * (1 - (v - lo) / (hi - lo))) for i, v in enumerate(vs)]
        d.line(pts, fill=col, width=2)
        d.text((pad_l + 10 + 160 * n, 12), f"■ {name}", fill=col)
        stats[name] = {"min": min(vs), "max": max(vs), "mean": round(sum(vs) / len(vs), 4), "n": len(vs)}
    if title:
        d.text((width - pad_r - 8 * len(title), 12), title, fill=(17, 24, 39))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return {"path": str(out), "stats": stats, "range": [lo, hi]}


def csv_series(path: Path, columns: list[str] | None = None) -> dict[str, list[float]]:
    header, rows, _, _ = read_csv(path)
    out: dict[str, list[float]] = {}
    for i, name in enumerate(header):
        if columns and name not in columns:
            continue
        vals = column_nums([r[i] if i < len(r) else "" for r in rows])
        if sum(v is not None for v in vals) >= max(2, len(vals) * 0.8):
            out[name] = vals
    return out


# ============================================================================================== 476 robot arm
def arm_ik(l1: float, l2: float, x: float, y: float, elbow_up: bool = True) -> dict:
    """Two-link planar arm: joint angles (degrees) to reach (x, y), or why it cannot."""
    r2 = x * x + y * y
    r = math.sqrt(r2)
    if r > l1 + l2 + 1e-9:
        return {"reachable": False, "why": f"bod je {r:.1f} daleko, rameno dosáhne max {l1 + l2:g}"}
    if r < abs(l1 - l2) - 1e-9:
        return {"reachable": False, "why": f"bod je moc blízko ({r:.1f}), minimum je {abs(l1 - l2):g}"}
    c2 = max(-1.0, min(1.0, (r2 - l1 * l1 - l2 * l2) / (2 * l1 * l2)))
    t2 = math.acos(c2) * (-1 if elbow_up else 1)
    t1 = math.atan2(y, x) - math.atan2(l2 * math.sin(t2), l1 + l2 * math.cos(t2))
    fx = l1 * math.cos(t1) + l2 * math.cos(t1 + t2)
    fy = l1 * math.sin(t1) + l2 * math.sin(t1 + t2)
    return {"reachable": True, "shoulder_deg": round(math.degrees(t1), 2), "elbow_deg": round(math.degrees(t2), 2),
            "check": [round(fx, 4), round(fy, 4)], "error": round(math.hypot(fx - x, fy - y), 6)}


def arm_path(l1: float, l2: float, points: list[tuple[float, float]], steps: int = 10, limits: tuple[float, float] = (-180, 180)) -> dict:
    """Straight-line moves between points: joint angles along the way, max joint jump per step, limit violations."""
    path, problems = [], []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        for i in range(steps + 1):
            t = i / steps
            p = arm_ik(l1, l2, ax + (bx - ax) * t, ay + (by - ay) * t)
            if not p["reachable"]:
                problems.append(f"({ax + (bx - ax) * t:.1f}, {ay + (by - ay) * t:.1f}): {p['why']}")
                continue
            for j in ("shoulder_deg", "elbow_deg"):
                if not limits[0] <= p[j] <= limits[1]:
                    problems.append(f"{j} {p[j]}° mimo rozsah {limits}")
            path.append(p)
    jumps = [max(abs(a["shoulder_deg"] - b["shoulder_deg"]), abs(a["elbow_deg"] - b["elbow_deg"])) for a, b in zip(path, path[1:])]
    return {"path": path, "max_jump_deg": round(max(jumps), 2) if jumps else 0, "problems": problems[:20], "ok": not problems}


# ============================================================================================== 201 dependencies
def task_plan(tasks: list[dict]) -> dict:
    """Tasks [{name, days, after: [names]}] → order, earliest start, critical path, slack, cycles and unknown deps."""
    by = {t["name"]: {"days": float(t.get("days", 1)), "after": list(t.get("after") or [])} for t in tasks}
    unknown = sorted({d for t in by.values() for d in t["after"] if d not in by})
    indeg = {n: sum(1 for d in t["after"] if d in by) for n, t in by.items()}
    nxt = defaultdict(list)
    for n, t in by.items():
        for d in t["after"]:
            if d in by:
                nxt[d].append(n)
    q = deque(sorted(n for n, k in indeg.items() if k == 0))
    order, es = [], {}
    while q:
        n = q.popleft()
        order.append(n)
        es[n] = max((es[d] + by[d]["days"] for d in by[n]["after"] if d in by), default=0.0)
        for m in nxt[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    cycle = sorted(n for n in by if n not in order)
    if cycle:
        return {"order": order, "cycle": cycle, "unknown": unknown, "ok": False}
    finish = max((es[n] + by[n]["days"] for n in order), default=0.0)
    lf = {n: finish for n in order}
    for n in reversed(order):
        if nxt[n]:
            lf[n] = min(lf[m] - by[m]["days"] for m in nxt[n])
    slack = {n: round(lf[n] - by[n]["days"] - es[n], 3) for n in order}
    crit, cur = [], next((n for n in order if slack[n] == 0 and not by[n]["after"]), None)
    while cur:
        crit.append(cur)
        cur = next((m for m in nxt[cur] if slack[m] == 0 and abs(es[m] - (es[cur] + by[cur]["days"])) < 1e-9), None)
    return {"order": order, "start": es, "finish_days": finish, "critical": crit, "slack": slack, "cycle": [], "unknown": unknown,
            "parallel": [[n for n in order if es[n] == s] for s in sorted(set(es.values())) if sum(1 for n in order if es[n] == s) > 1],
            "ok": not unknown}


# ============================================================================================== 460 formula explorer
def explore_formula(expr: str, var: str, start: float, stop: float, steps: int = 10, fixed: dict[str, float] | None = None) -> dict:
    """Evaluate a formula over a range of one variable (others fixed): table, min / max, and how sensitive the result
    is (% change of the result per 1 % change of the variable, around the middle)."""
    from .learning import safe_eval

    env = dict(fixed or {})
    rows = []
    for i in range(steps + 1):
        x = start + (stop - start) * i / steps
        env[var] = x
        try:
            y = safe_eval(expr, env)
        except (ValueError, ZeroDivisionError, OverflowError) as e:
            y = None
            if i == 0 and not rows:
                raise ValueError(f"Vzorec nejde spočítat: {e}") from e
        rows.append({var: round(x, 6), "value": None if y is None else round(y, 6)})
    vals = [r["value"] for r in rows if r["value"] is not None]
    mid = (start + stop) / 2
    sens = None
    try:
        env[var] = mid
        y0 = safe_eval(expr, env)
        env[var] = mid * 1.01 if mid else 0.01
        y1 = safe_eval(expr, env)
        sens = round((y1 - y0) / y0 / 0.01, 3) if y0 else None
    except (ValueError, ZeroDivisionError, OverflowError):
        pass
    return {"rows": rows, "min": min(vals) if vals else None, "max": max(vals) if vals else None, "elasticity": sens}


# ============================================================================================== 453 prerequisites
def prerequisites(topics: dict[str, list[str]], goal: str, known: list[str] | None = None) -> dict:
    """What to learn, in which order, to reach `goal` (given what is already known)."""
    known_f = {fold(k) for k in (known or [])}
    keys = {fold(k): k for k in topics}
    g = keys.get(fold(goal))
    if not g:
        raise ValueError(f"Téma „{goal}“ v mapě není.")
    order, seen, stack = [], set(), set()

    def visit(t: str) -> None:
        if fold(t) in seen or fold(t) in known_f:
            return
        if fold(t) in stack:
            raise ValueError(f"Kruhová závislost u „{t}“.")
        stack.add(fold(t))
        for p in topics.get(keys.get(fold(t), t), []):
            visit(p)
        stack.discard(fold(t))
        seen.add(fold(t))
        order.append(keys.get(fold(t), t))
    visit(g)
    missing = sorted({p for ps in topics.values() for p in ps if fold(p) not in keys and fold(p) not in known_f})
    return {"order": order, "steps": len(order), "undefined": missing}


# ============================================================================================== 512 / 524 search
async def search_everything(rt, query: str, limit: int = 5) -> dict:
    out: dict[str, list[dict]] = {}
    try:
        out["paměť a konverzace"] = [{"title": h["title"], "text": h["snippet"], "kind": h["kind"]} for h in rt.knowledge.search(query, limit)]
    except Exception:  # noqa: BLE001
        out["paměť a konverzace"] = []
    try:
        from . import docsearch

        out["dokumenty"] = [{"title": h["file"], "text": h["text"][:160], "loc": h["loc"]} for h in docsearch.search(rt, query, "", limit)]
    except Exception:  # noqa: BLE001
        out["dokumenty"] = []
    q = f"%{query}%"
    try:
        out["kalendář"] = [{"title": r["title"], "text": time.strftime("%d. %m. %Y %H:%M", time.localtime(r["start"]))}
                          for r in rt.db.all("SELECT title, start FROM cal_events WHERE title LIKE ? OR location LIKE ? ORDER BY start DESC LIMIT ?", (q, q, limit))]
    except Exception:  # noqa: BLE001
        out["kalendář"] = []
    try:
        out["seznamy"] = [{"title": r["list"], "text": r["item"]} for r in rt.db.all("SELECT list, item FROM lists WHERE item LIKE ? LIMIT ?", (q, limit))]
    except Exception:  # noqa: BLE001
        out["seznamy"] = []
    mail = getattr(rt, "mail", None)
    if mail is not None and getattr(mail, "accounts", None):
        import asyncio

        def m():
            res = []
            for acc in list(mail.accounts.values()):
                res += [{"title": h["subject"], "text": h["from_name"] or h["from"]} for h in acc.list(limit=limit, query=query)]
            return res
        try:
            out["e-maily"] = await asyncio.wait_for(asyncio.to_thread(m), 20)
        except Exception:  # noqa: BLE001
            out["e-maily"] = []
    out["postupy"] = workflow_search(rt, query)[:limit]
    return {k: v for k, v in out.items() if v}


def workflow_search(rt, query: str) -> list[dict]:
    """The user's own ways of doing things: protocols, automations, skills, recorded web workflows."""
    from . import paths

    from .docsearch import STOP

    filler = STOP | {"jsem", "jsme", "jsi", "delal", "delala", "delali", "minule", "udelat", "udelal", "postup", "postupy", "tim", "tom", "tohle", "jsem"}
    words = [w for w in re.findall(r"\w{3,}", fold(query)) if w not in filler]
    hits = []

    def score(text: str) -> int:
        f = fold(text)
        return sum(1 for w in words if w[:max(4, len(w) - 2)] in f)
    for p in getattr(rt.cfg.stark, "protocols", []) or []:
        text = p.name + " " + " ".join(f"{s.tool or ''} {s.say or ''} {s.ask or ''}" for s in p.steps)
        if (s := score(text)):
            hits.append({"kind": "protokol", "title": p.name, "text": f"{len(p.steps)} kroků", "score": s})
    for a in getattr(rt.cfg.automations, "items", []) or []:
        from .automations import describe_trigger

        text = a.name + " " + describe_trigger(a.trigger) + " " + " ".join(f"{s.tool or ''} {s.say or ''} {s.ask or ''}" for s in a.steps)
        if (s := score(text)):
            hits.append({"kind": "automatizace", "title": a.name, "text": describe_trigger(a.trigger), "score": s})
    try:
        from .tools.skills import list_skills

        for sk in list_skills(rt.cfg.tools.approved_skills):
            if (s := score(sk["name"] + " " + str(sk.get("manifest") or "") + " " + " ".join(sk["tools"]))):
                hits.append({"kind": "dovednost", "title": sk["name"], "text": ", ".join(sk["tools"]), "score": s})
    except Exception:  # noqa: BLE001
        pass
    wf = paths.data_dir() / "workflows"
    if wf.is_dir():
        import json

        for f in wf.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if (s := score(d.get("name", "") + " " + " ".join(d.get("steps", [])) + " " + d.get("url", ""))):
                hits.append({"kind": "nahraný postup", "title": d.get("name", f.stem), "text": f"{len(d.get('steps', []))} kroků na {d.get('url', '')}", "score": s})
    return sorted(hits, key=lambda h: -h["score"])


# ============================================================================================== 517 window groups
def name_window_groups(windows: list[dict]) -> list[dict]:
    """Group open windows by the project / document they are about (shared words in titles across apps) and name the
    group after it."""
    stop = {"google", "chrome", "microsoft", "edge", "word", "excel", "visual", "studio", "code", "mozilla", "firefox", "explorer", "pruzkumnik",
            "new", "tab", "nova", "karta", "untitled", "bez", "nazvu", "dokument", "document", "the", "and", "pro", "jak"}
    toks = []
    for w in windows:
        words = [x for x in re.findall(r"[a-z0-9]{3,}", fold(w.get("title", ""))) if x not in stop]
        toks.append(set(words))
    groups: list[dict] = []
    used = set()
    for i, ti in enumerate(toks):
        if i in used or not ti:
            continue
        members = [i]
        for j in range(i + 1, len(toks)):
            if j not in used and ti & toks[j]:
                members.append(j)
        if len(members) > 1:
            common = set.intersection(*[toks[m] for m in members]) or (ti & toks[members[1]])
            name = " ".join(sorted(common, key=lambda x: -len(x))[:2]).title()
            used.update(members)
            groups.append({"name": name, "windows": [windows[m].get("title") for m in members], "apps": sorted({windows[m].get("app") or windows[m].get("exe") or "" for m in members})})
    return groups

