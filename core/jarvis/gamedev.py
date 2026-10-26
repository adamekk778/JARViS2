"""OMEGA §49 game development studio: a seeded procedural world (fractal value noise → height, moisture, biomes),
dialogue and quest graph checks with a play-through, an economy simulator (sources and sinks over days), loot odds
with pity, spawn fairness, a rooms-and-corridors level generator, save-file validation against rules and against the
previous save, animation state machine checks with a Mermaid export, server capacity, telemetry from an event log, a
colour-blindness check of a screenshot (Machado 2009) and Monte Carlo balance of units."""
from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

# ============================================================================================== 646 world
BIOMES = [("hluboká voda", (24, 56, 120)), ("voda", (45, 105, 180)), ("pláž", (222, 205, 140)), ("poušť", (214, 180, 100)),
          ("louka", (110, 175, 75)), ("les", (40, 115, 55)), ("hory", (125, 115, 105)), ("sníh", (240, 242, 245))]


def _noise(rng: np.random.Generator, w: int, h: int, cell: int) -> np.ndarray:
    gw, gh = w // cell + 2, h // cell + 2
    grid = rng.random((gh, gw))
    ys, xs = np.mgrid[0:h, 0:w] / cell
    x0, y0 = xs.astype(int), ys.astype(int)
    fx, fy = xs - x0, ys - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)            # smoothstep
    a, b = grid[y0, x0], grid[y0, x0 + 1]
    c, d = grid[y0 + 1, x0], grid[y0 + 1, x0 + 1]
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fractal(seed: int, w: int, h: int, scale: int = 32, octaves: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out, amp, total = np.zeros((h, w)), 1.0, 0.0
    for o in range(octaves):
        out += _noise(rng, w, h, max(2, scale >> o)) * amp
        total += amp
        amp /= 2
    out /= total
    lo, hi = out.min(), out.max()
    return (out - lo) / (hi - lo) if hi > lo else out * 0


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q, cells = deque([(y0, x0)]), []
        seen[y0, x0] = True
        while q:
            y, x = q.popleft()
            cells.append((int(y), int(x)))
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        comps.append(cells)
    return sorted(comps, key=len, reverse=True)


def world(seed: int, out: Path, width: int = 128, height: int = 128, scale: int = 32, octaves: int = 4, sea: float = 0.45) -> dict:
    """Seeded world map: height + moisture → biomes, rendered as a PNG; biome shares, islands and a spawn point."""
    from PIL import Image

    hgt = fractal(seed, width, height, scale, octaves)
    moist = fractal(seed + 7919, width, height, max(4, scale), max(1, octaves - 1))
    b = np.zeros(hgt.shape, dtype=int)
    b[hgt < sea] = 1
    b[hgt < sea - 0.12] = 0
    land = hgt >= sea
    b[land] = np.where(moist[land] < 0.35, 3, np.where(moist[land] < 0.62, 4, 5))
    b[land & (hgt < sea + 0.03)] = 2
    b[hgt > 0.78] = 6
    b[hgt > 0.9] = 7
    pal = np.array([c for _, c in BIOMES], dtype=np.uint8)
    img = Image.fromarray(pal[b]).resize((width * 4, height * 4), Image.NEAREST)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    counts = np.bincount(b.ravel(), minlength=len(BIOMES))
    share = {BIOMES[i][0]: round(float(100 * counts[i] / b.size), 1) for i in range(len(BIOMES)) if counts[i]}
    islands = _components(land)
    spawn = None
    if islands:
        cy = sum(c[0] for c in islands[0]) / len(islands[0])
        cx = sum(c[1] for c in islands[0]) / len(islands[0])
        good = [c for c in islands[0] if b[c] in (4, 5)] or islands[0]
        y, x = min(good, key=lambda c: (c[0] - cy) ** 2 + (c[1] - cx) ** 2)
        spawn = [x, y]
    return {"path": str(out), "seed": seed, "size": [width, height], "biomes": share, "land_pct": round(float(100 * land.mean()), 1),
            "islands": len(islands), "largest_island": len(islands[0]) if islands else 0, "spawn": spawn}


# ============================================================================================== 647 dialogue
_VAR = re.compile(r"\{(\w+)\}")


def dialogue_check(tree: dict, variables: list[str] | None = None) -> dict:
    """{start, nodes: {id: {text, end?, choices: [{text, next, if?, set?}]}}} → broken links, unreachable nodes,
    dead ends, traps (loops with no way out), flags tested but never set, unknown text variables."""
    nodes = tree.get("nodes") or {}
    start = tree.get("start")
    issues = []
    if start not in nodes:
        issues.append(f"začátek „{start}“ neexistuje")
    edges = {n: [c.get("next") for c in (d.get("choices") or [])] for n, d in nodes.items()}
    for n, nx in edges.items():
        for t in nx:
            if t not in nodes:
                issues.append(f"{n}: volba vede na neexistující „{t}“")
    seen, q = set(), deque([start] if start in nodes else [])
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        q.extend(t for t in edges[n] if t in nodes)
    unreachable = sorted(set(nodes) - seen)
    dead = sorted(n for n, d in nodes.items() if not d.get("choices") and not d.get("end"))
    ends = {n for n, d in nodes.items() if d.get("end")}
    can_end, changed = set(ends), True                            # nodes from which some end is reachable
    while changed:
        changed = False
        for n, nx in edges.items():
            if n not in can_end and any(t in can_end for t in nx):
                can_end.add(n)
                changed = True
    traps = sorted(n for n in seen if n not in can_end and n not in dead)
    sets = {c.get("set") for d in nodes.values() for c in (d.get("choices") or []) if c.get("set")}
    tests = {c["if"].lstrip("!") for d in nodes.values() for c in (d.get("choices") or []) if c.get("if")}
    never_set = sorted(tests - sets)
    known = set(variables or []) | sets
    unknown = sorted({v for d in nodes.values() for v in _VAR.findall(d.get("text", "")) if v not in known})
    for n in unreachable:
        issues.append(f"{n}: nedá se k němu dojít")
    for n in dead:
        issues.append(f"{n}: slepá větev (žádná volba a není konec)")
    for n in traps:
        issues.append(f"{n}: smyčka bez východu ke konci")
    for f in never_set:
        issues.append(f"podmínka „{f}“ se nikde nenastavuje")
    for v in unknown:
        issues.append(f"proměnná {{{v}}} v textu není známá")
    return {"issues": issues, "nodes": len(nodes), "reachable": len(seen), "ends": sorted(ends), "unreachable": unreachable,
            "dead_ends": dead, "traps": traps, "flags_never_set": never_set, "unknown_vars": unknown, "ok": not issues}


def dialogue_play(tree: dict, picks: list[int], variables: dict[str, str] | None = None, flags: list[str] | None = None) -> dict:
    """Play through: pick the n-th AVAILABLE choice at each node (conditions respected, flags set on the way)."""
    nodes, cur = tree.get("nodes") or {}, tree.get("start")
    have, vars_ = set(flags or []), dict(variables or {})
    log = []
    for step in range(len(picks) + 1):
        if cur not in nodes:
            return {"log": log, "ended": False, "error": f"uzel „{cur}“ neexistuje", "flags": sorted(have)}
        d = nodes[cur]
        log.append({"node": cur, "text": _VAR.sub(lambda m: str(vars_.get(m.group(1), "{" + m.group(1) + "}")), d.get("text", ""))})
        avail = [c for c in (d.get("choices") or [])
                 if not c.get("if") or ((c["if"][1:] not in have) if c["if"].startswith("!") else (c["if"] in have))]
        if d.get("end") or not avail or step == len(picks):
            return {"log": log, "ended": bool(d.get("end")), "choices": [c.get("text") for c in avail], "flags": sorted(have)}
        k = picks[step]
        if not 0 <= k < len(avail):
            return {"log": log, "ended": False, "error": f"v uzlu {cur} je jen {len(avail)} voleb", "flags": sorted(have)}
        c = avail[k]
        log[-1]["chose"] = c.get("text")
        if c.get("set"):
            have.add(c["set"])
        cur = c.get("next")
    return {"log": log, "ended": False, "flags": sorted(have)}


# ============================================================================================== 648 quests
def quest_check(quests: list[dict], xp_per_level: float = 100, start_level: int = 1, start_items: list[str] | None = None) -> dict:
    """Quests [{id, name?, requires: [ids], level, xp, gold, gives: [items], needs: [items]}] → a play order (greedy, the
    lowest level first), level reached, gold earned, and quests that can never be done (and why)."""
    by = {q["id"]: q for q in quests}
    done, order = set(), []
    xp, gold, items = 0.0, 0.0, set(start_items or [])

    def level() -> int:
        return start_level + int(xp // xp_per_level)
    while True:
        ready = [q for q in quests if q["id"] not in done and all(r in done for r in q.get("requires") or [])
                 and q.get("level", 1) <= level() and all(i in items for i in q.get("needs") or [])]
        if not ready:
            break
        q = min(ready, key=lambda q: (q.get("level", 1), q["id"]))
        done.add(q["id"])
        xp += float(q.get("xp", 0))
        gold += float(q.get("gold", 0))
        items |= set(q.get("gives") or [])
        order.append({"id": q["id"], "name": q.get("name", q["id"]), "level_after": level()})
    blocked = []
    given = {i for q in quests for i in q.get("gives") or []} | set(start_items or [])
    for q in quests:
        if q["id"] in done:
            continue
        why = [f"chybí quest {r}" for r in q.get("requires") or [] if r not in by]
        why += [f"předmět {i} nikdo nedá" for i in q.get("needs") or [] if i not in given]
        if q.get("level", 1) > level():
            why.append(f"potřebuje úroveň {q['level']}, hráč dojde jen na {level()}")
        why += [f"čeká na nesplnitelný {r}" for r in q.get("requires") or [] if r in by and r not in done]
        blocked.append({"id": q["id"], "why": why or ["kruhová závislost"]})
    return {"order": order, "final_level": level(), "xp": xp, "gold": gold, "blocked": blocked, "ok": not blocked}


# ============================================================================================== 649 economy
def economy_sim(days: int, players: float, growth_pct: float, sources: list[dict], sinks: list[dict], start_gold: float = 0) -> dict:
    """Gold over days: sources [{name, per_player_day}], sinks [{name, per_player_day} or {name, pct_of_wallet}]
    → money per player each day, the trend (inflation), the biggest source and sink and how big a sink would balance it."""
    wallet = start_gold                                            # average gold per player
    rows = []
    p = players
    for d in range(1, days + 1):
        inflow = sum(float(s.get("per_player_day", 0)) for s in sources)
        fixed = sum(float(s.get("per_player_day", 0)) for s in sinks)
        pct = sum(float(s.get("pct_of_wallet", 0)) for s in sinks) / 100
        out = min(wallet + inflow, fixed + pct * (wallet + inflow))
        wallet = wallet + inflow - out
        p *= 1 + growth_pct / 100
        rows.append({"day": d, "players": round(p), "gold_per_player": round(wallet, 2), "money_supply": round(wallet * p)})
    inflow = sum(float(s.get("per_player_day", 0)) for s in sources)
    fixed = sum(float(s.get("per_player_day", 0)) for s in sinks)
    pct = sum(float(s.get("pct_of_wallet", 0)) for s in sinks) / 100
    first, last = rows[0]["gold_per_player"], rows[-1]["gold_per_player"]
    week = rows[-1]["gold_per_player"] - rows[max(0, len(rows) - 8)]["gold_per_player"]
    verdict = ("stabilní – peněženky se ustálí" if pct and abs(week) < 0.01 * max(1, last) else
               "inflace – zlata přibývá bez konce" if inflow > fixed and not pct else
               "deflace – hráči nemají na výdaje" if inflow < fixed else "vyrovnané")
    steady = (inflow - fixed) / pct if pct and inflow > fixed else None
    return {"days": rows, "verdict": verdict, "net_per_day": round(inflow - fixed, 2), "steady_wallet": round(steady, 1) if steady else None,
            "start": first, "end": last, "biggest_source": max(sources, key=lambda s: s.get("per_player_day", 0))["name"] if sources else None,
            "sink_to_balance": round(inflow - fixed, 2) if inflow > fixed and not pct else 0}


# ============================================================================================== 650 loot
def loot(table: list[dict], tries: int = 10, pity: int = 0) -> dict:
    """Drop table [{item, weight, value?}] (one roll picks one entry by weight) → chance per roll, expected rolls,
    chance within N tries, rolls for a 50 % / 90 % chance, and the expected rolls with a pity counter."""
    total = sum(float(x.get("weight", 0)) for x in table)
    if total <= 0:
        raise ValueError("Váhy v tabulce musí být kladné.")
    out, ev = [], 0.0
    for x in table:
        p = float(x.get("weight", 0)) / total
        ev += p * float(x.get("value", 0))
        if p <= 0:
            out.append({"item": x["item"], "chance": 0, "expected_rolls": None, "within": 0, "for_50": None, "for_90": None})
            continue
        exp = 1 / p
        if pity and pity > 0:
            exp = sum((1 - p) ** k for k in range(pity))             # guaranteed on roll `pity` at the latest
        f50 = math.ceil(math.log(0.5) / math.log(1 - p)) if p < 1 else 1
        f90 = math.ceil(math.log(0.1) / math.log(1 - p)) if p < 1 else 1
        if pity:
            f50, f90 = min(f50, pity), min(f90, pity)
        out.append({"item": x["item"], "chance": round(100 * p, 4), "expected_rolls": round(exp, 2),
                    "within": round(100 * (1 - (1 - p) ** tries), 2) if not pity or tries < pity else 100.0, "for_50": f50, "for_90": f90})
    return {"items": out, "tries": tries, "pity": pity, "value_per_roll": round(ev, 4)}


# ============================================================================================== 651 spawns
def spawn_balance(spawns: list[dict], objectives: list[dict], min_enemy_distance: float = 0) -> dict:
    """Spawns [{team, x, y}] and objectives [{name, x, y}] → each team's nearest distance to every objective, the
    advantage in %, and spawns too close to an enemy spawn."""
    teams = defaultdict(list)
    for s in spawns:
        teams[str(s["team"])].append((float(s["x"]), float(s["y"])))
    per = {}
    for name, pts in teams.items():
        per[name] = {o["name"]: round(min(math.dist(p, (o["x"], o["y"])) for p in pts), 2) for o in objectives}
    issues, unfair = [], []
    for o in objectives:
        ds = {t: per[t][o["name"]] for t in per}
        lo, hi = min(ds.values()), max(ds.values())
        adv = round(100 * (hi - lo) / hi, 1) if hi else 0
        if adv > 10:
            unfair.append({"objective": o["name"], "closer": min(ds, key=ds.get), "advantage_pct": adv, "distances": ds})
    close = []
    names = list(teams)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for p in teams[a]:
                for q in teams[b]:
                    if min_enemy_distance and math.dist(p, q) < min_enemy_distance:
                        close.append({"teams": [a, b], "a": p, "b": q, "distance": round(math.dist(p, q), 2)})
    for u in unfair:
        issues.append(f"{u['objective']}: tým {u['closer']} to má o {u['advantage_pct']} % blíž")
    for c in close:
        issues.append(f"spawny týmů {c['teams'][0]} a {c['teams'][1]} jsou jen {c['distance']} od sebe")
    return {"distances": per, "unfair": unfair, "too_close": close, "issues": issues, "fair": not issues}


# ============================================================================================== 652 level layout
def dungeon(seed: int, width: int = 60, height: int = 40, rooms: int = 10, out: Path | None = None) -> dict:
    """Rooms that do not overlap, joined by corridors along a minimum spanning tree (+ one extra loop); start and exit
    at the two most distant points; checked for connectivity. ASCII map, and a PNG when `out` is given."""
    rng = random.Random(seed)
    grid = [["#"] * width for _ in range(height)]
    placed: list[tuple[int, int, int, int]] = []
    for _ in range(rooms * 30):
        if len(placed) >= rooms:
            break
        w, h = rng.randint(4, 10), rng.randint(3, 7)
        x, y = rng.randint(1, width - w - 2), rng.randint(1, height - h - 2)
        if any(x - 1 < px + pw and px - 1 < x + w and y - 1 < py + ph and py - 1 < y + h for px, py, pw, ph in placed):
            continue
        placed.append((x, y, w, h))
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                grid[yy][xx] = "."
    if len(placed) < 2:
        raise ValueError("Do mapy se nevešly ani dvě místnosti – zvětši ji.")
    centers = [(x + w // 2, y + h // 2) for x, y, w, h in placed]
    in_tree, edges = {0}, []
    while len(in_tree) < len(centers):                              # Prim's MST over room centres
        a, b = min(((i, j) for i in in_tree for j in range(len(centers)) if j not in in_tree), key=lambda e: math.dist(centers[e[0]], centers[e[1]]))
        in_tree.add(b)
        edges.append((a, b))
    if len(centers) > 2:
        extra = [(i, j) for i in range(len(centers)) for j in range(i + 1, len(centers)) if (i, j) not in edges and (j, i) not in edges]
        edges.append(rng.choice(extra))

    def carve(a, b):
        (x1, y1), (x2, y2) = a, b
        for xx in range(min(x1, x2), max(x1, x2) + 1):
            grid[y1][xx] = "." if grid[y1][xx] == "#" else grid[y1][xx]
        for yy in range(min(y1, y2), max(y1, y2) + 1):
            grid[yy][x2] = "." if grid[yy][x2] == "#" else grid[yy][x2]
    for a, b in edges:
        carve(centers[a], centers[b])

    def bfs(src):
        dist = {src: 0}
        q = deque([src])
        while q:
            x, y = q.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] != "#" and (nx, ny) not in dist:
                    dist[(nx, ny)] = dist[(x, y)] + 1
                    q.append((nx, ny))
        return dist
    d0 = bfs(centers[0])
    floor = sum(row.count(".") for row in grid)
    start = max(d0, key=d0.get)
    ds = bfs(start)
    exit_ = max(ds, key=ds.get)
    sx, sy = start
    ex, ey = exit_
    grid[sy][sx], grid[ey][ex] = "S", "E"
    dead_ends = sum(1 for (x, y) in ds if sum(grid[ny][nx] != "#" for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                                              if 0 <= nx < width and 0 <= ny < height) == 1)
    ascii_ = "\n".join("".join(r) for r in grid)
    res = {"seed": seed, "rooms": len(placed), "connected": len(d0) == floor, "path_length": ds[exit_], "floor_pct": round(100 * floor / (width * height), 1),
           "dead_ends": dead_ends, "start": list(start), "exit": list(exit_), "ascii": ascii_}
    if out is not None:
        from PIL import Image

        col = {"#": (30, 30, 36), ".": (200, 196, 180), "S": (34, 197, 94), "E": (239, 68, 68)}
        im = Image.new("RGB", (width, height))
        im.putdata([col[c] for row in grid for c in row])
        out.parent.mkdir(parents=True, exist_ok=True)
        im.resize((width * 8, height * 8), Image.NEAREST).save(out)
        res["path"] = str(out)
    return res


# ============================================================================================== 654 save data
def _walk(data: Any, path: str) -> list[tuple[str, Any]]:
    """'player.inventory[].count' → every matching (concrete path, value); missing → [(path, KeyError)]."""
    parts = [p for p in re.split(r"\.", path) if p]
    cur: list[tuple[str, Any]] = [("", data)]
    for p in parts:
        nxt = []
        many = p.endswith("[]")
        key = p[:-2] if many else p
        for where, v in cur:
            if v is KeyError:
                nxt.append((where, KeyError))
                continue
            w = f"{where}.{key}" if where else key
            if key:
                if not isinstance(v, dict) or key not in v:
                    nxt.append((w, KeyError))
                    continue
                v = v[key]
            if many:
                if not isinstance(v, list):
                    nxt.append((w, KeyError))
                    continue
                nxt += [(f"{w}[{i}]", x) for i, x in enumerate(v)]
            else:
                nxt.append((w, v))
        cur = nxt
    return cur


TYPES = {"int": int, "number": (int, float), "str": str, "bool": bool, "list": list, "dict": dict}


def save_validate(data: Any, rules: dict[str, dict], previous: Any = None, max_jump: float = 10) -> dict:
    """Rules {'player.level': {type: int, min: 1, max: 99, required: true}, 'inventory[].id': {type: str, pattern: ...},
    'x': {unique: true}} → violations; with the previous save also numbers that jumped suspiciously (×max_jump)."""
    errors = []
    for path, r in rules.items():
        vals = _walk(data, path)
        seen = Counter()
        for where, v in vals:
            if v is KeyError:
                if r.get("required", True):
                    errors.append(f"{where}: chybí")
                continue
            t = TYPES.get(r.get("type", ""))
            if t and (not isinstance(v, t) or (r.get("type") in ("int", "number") and isinstance(v, bool))):
                errors.append(f"{where}: má být {r['type']}, je {type(v).__name__}")
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not math.isfinite(v):
                    errors.append(f"{where}: není konečné číslo")
                if "min" in r and v < r["min"]:
                    errors.append(f"{where}: {v} je pod minimem {r['min']}")
                if "max" in r and v > r["max"]:
                    errors.append(f"{where}: {v} je nad maximem {r['max']}")
            if "pattern" in r and isinstance(v, str) and not re.fullmatch(r["pattern"], v):
                errors.append(f"{where}: „{v}“ neodpovídá vzoru")
            if "one_of" in r and v not in r["one_of"]:
                errors.append(f"{where}: {v!r} není povolená hodnota")
            if r.get("unique"):
                seen[repr(v)] += 1
        for k, n in seen.items():
            if n > 1:
                errors.append(f"{path}: hodnota {k} je tam {n}× (má být jedinečná)")
    jumps = []
    if previous is not None:
        def nums(d, pre=""):
            if isinstance(d, dict):
                for k, v in d.items():
                    yield from nums(v, f"{pre}.{k}" if pre else k)
            elif isinstance(d, list):
                for i, v in enumerate(d):
                    yield from nums(v, f"{pre}[{i}]")
            elif isinstance(d, (int, float)) and not isinstance(d, bool):
                yield pre, d
        old = dict(nums(previous))
        for k, v in nums(data):
            o = old.get(k)
            if o is not None and o > 0 and v > o * max_jump:
                jumps.append({"path": k, "before": o, "after": v, "times": round(v / o, 1)})
            elif o is not None and o >= 0 and v < 0:
                jumps.append({"path": k, "before": o, "after": v, "times": None})
    return {"errors": errors, "suspicious": jumps, "ok": not errors and not jumps}


# ============================================================================================== 655 animation FSM
def anim_fsm(states: list[str], transitions: list[dict], entry: str, params: list[str] | None = None, terminal: list[str] | None = None) -> dict:
    """Transitions [{from, to, when}] ('*' = from any state). → unreachable states, states with no way out, two
    transitions from the same state on the same condition, conditions on unknown parameters; plus a Mermaid diagram."""
    ss = set(states)
    issues = []
    expanded = []
    for t in transitions:
        srcs = [s for s in states if s != t["to"]] if t.get("from") == "*" else [t.get("from")]
        for s in srcs:
            expanded.append({"from": s, "to": t["to"], "when": (t.get("when") or "").strip(), "any": t.get("from") == "*"})
    for t in transitions:
        for k in ("from", "to"):
            if t.get(k) != "*" and t.get(k) not in ss:
                issues.append(f"přechod {t.get('from')} → {t.get('to')}: stav „{t.get(k)}“ neexistuje")
    if entry not in ss:
        issues.append(f"vstupní stav „{entry}“ neexistuje")
    reach, q = set(), deque([entry])
    while q:
        s = q.popleft()
        if s in reach:
            continue
        reach.add(s)
        q.extend(t["to"] for t in expanded if t["from"] == s)
    unreachable = sorted(ss - reach)
    # a global "from any state" transition (death, hit) does not get the character out of e.g. a jump that never lands
    stuck = sorted(s for s in states if s not in (terminal or []) and not any(t["from"] == s and not t["any"] for t in expanded))
    dup = Counter((t["from"], t["when"]) for t in expanded if not t["any"])
    conflicts = sorted({f"{s} při „{w or 'vždy'}“" for (s, w), n in dup.items() if n > 1})
    known = set(params or [])
    words = {w for t in transitions for w in re.findall(r"[A-Za-z_]\w*", t.get("when") or "") if w not in ("and", "or", "not", "true", "false")}
    unknown = sorted(words - known) if params is not None else []
    issues += [f"{s}: nedá se do něj dostat" for s in unreachable]
    issues += [f"{s}: nedá se z něj odejít (jen globálním přechodem)" for s in stuck]
    issues += [f"dva přechody ze stavu {c}" for c in conflicts]
    issues += [f"parametr „{w}“ není deklarovaný" for w in unknown]
    mer = ["stateDiagram-v2", f"    [*] --> {entry}"]
    for t in transitions:
        mer.append(f"    {'[*]' if t.get('from') == '*' else t.get('from')} --> {t['to']}" + (f" : {t['when']}" if t.get("when") else ""))
    for s in terminal or []:
        mer.append(f"    {s} --> [*]")
    return {"issues": issues, "unreachable": unreachable, "stuck": stuck, "conflicts": conflicts, "unknown_params": unknown,
            "mermaid": "\n".join(mer), "ok": not issues}


# ============================================================================================== 657 server capacity
def server_capacity(players: int, tick_rate: float, cpu_ms_per_player: float, bytes_per_entity: float, cores: int = 1,
                    uplink_mbps: float = 100, interest_radius_players: int = 0, overhead_ms: float = 1.0) -> dict:
    """Per tick each player gets the state of the others it can see (all, or `interest_radius_players`). → CPU load
    per tick, outgoing bandwidth, the maximum players for CPU and for the uplink, and which runs out first."""
    budget = 1000 / tick_rate

    def seen(n):
        return min(n - 1, interest_radius_players) if interest_radius_players else n - 1

    def cpu(n):
        return overhead_ms + n * cpu_ms_per_player / max(1, cores)

    def mbps(n):
        return n * max(0, seen(n)) * bytes_per_entity * tick_rate * 8 / 1e6
    max_cpu = next((n - 1 for n in range(1, 100001) if cpu(n) > budget), 100000)
    max_net = next((n - 1 for n in range(1, 100001) if mbps(n) > uplink_mbps), 100000)
    return {"tick_budget_ms": round(budget, 2), "cpu_ms_per_tick": round(cpu(players), 2), "cpu_load_pct": round(100 * cpu(players) / budget, 1),
            "uplink_mbps": round(mbps(players), 2), "uplink_pct": round(100 * mbps(players) / uplink_mbps, 1),
            "max_players_cpu": max_cpu, "max_players_network": max_net, "max_players": min(max_cpu, max_net),
            "bottleneck": "procesor" if max_cpu <= max_net else "síť (upload)", "fits": players <= min(max_cpu, max_net)}


# ============================================================================================== 658 telemetry
def telemetry(header: list[str], rows: list[list[str]], cell: float = 10) -> dict:
    """Event log (player, event, level, time, x?, y?) → per level starts, completions, deaths, quits, completion %,
    the funnel of how far players got, and the death hot spots."""
    h = [c.strip().lower() for c in header]

    def col(*names):
        return next((i for i, c in enumerate(h) if c in names), None)
    pi, ei, li = col("player", "hrac", "user", "player_id"), col("event", "udalost", "type"), col("level", "uroven", "map")
    xi, yi, ti = col("x"), col("y"), col("time", "ts", "cas", "timestamp")
    if None in (pi, ei, li):
        raise ValueError("Potřebuju sloupce player, event a level.")
    lv = defaultdict(lambda: Counter())
    furthest: dict[str, str] = {}
    order: list[str] = []
    durations = defaultdict(list)
    started: dict[tuple[str, str], float] = {}
    heat = Counter()
    for r in rows:
        if len(r) <= max(pi, ei, li):
            continue
        p, e, lvl = r[pi].strip(), r[ei].strip().lower(), r[li].strip()
        if lvl not in order:
            order.append(lvl)
        lv[lvl][e] += 1
        if e in ("start", "begin"):
            furthest[p] = max(furthest.get(p, lvl), lvl, key=order.index)
            if ti is not None:
                try:
                    started[(p, lvl)] = float(r[ti])
                except ValueError:
                    pass
        if e in ("complete", "finish", "win") and ti is not None and (p, lvl) in started:
            try:
                durations[lvl].append(float(r[ti]) - started.pop((p, lvl)))
            except ValueError:
                pass
        if e in ("death", "die", "smrt") and xi is not None and yi is not None:
            try:
                heat[(int(float(r[xi]) // cell), int(float(r[yi]) // cell))] += 1
            except ValueError:
                pass
    levels = []
    for lvl in order:
        c = lv[lvl]
        s, done = c.get("start", 0) + c.get("begin", 0), c.get("complete", 0) + c.get("finish", 0) + c.get("win", 0)
        levels.append({"level": lvl, "starts": s, "completions": done, "deaths": c.get("death", 0) + c.get("die", 0) + c.get("smrt", 0),
                       "quits": c.get("quit", 0), "completion_pct": round(100 * done / s, 1) if s else None,
                       "avg_time": round(sum(durations[lvl]) / len(durations[lvl]), 1) if durations[lvl] else None})
    reached = Counter(furthest.values())
    total = len(furthest)
    funnel, left = [], total
    for lvl in order:
        funnel.append({"level": lvl, "players": left, "pct": round(100 * left / total, 1) if total else 0})
        left -= reached.get(lvl, 0)
    hardest = min((x for x in levels if x["completion_pct"] is not None), key=lambda x: x["completion_pct"], default=None)
    return {"levels": levels, "funnel": funnel, "players": total, "hardest": hardest["level"] if hardest else None,
            "death_spots": [{"x": k[0] * cell, "y": k[1] * cell, "deaths": n} for k, n in heat.most_common(5)]}


# ============================================================================================== 659 colour blindness
# Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear RGB
CVD = {"protanopie": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
       "deuteranopie": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
       "tritanopie": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]}


def _lin(c: np.ndarray) -> np.ndarray:
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255


def simulate_cvd(rgb: np.ndarray, kind: str) -> np.ndarray:
    m = np.array(CVD[kind])
    return _srgb(_lin(rgb.astype(float)) @ m.T)


def _lab(rgb: np.ndarray) -> np.ndarray:
    lin = _lin(rgb.astype(float))
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


CONFUSE = 12        # ΔE76 below this: hard to tell apart at a glance


def colorblind(image: Path, out_dir: Path, colors: int = 8) -> dict:
    """Screenshot → how it looks with protanopia / deuteranopia / tritanopia (images), and which of its main colours
    stop being distinguishable (ΔE before > 20, after < CONFUSE)."""
    from PIL import Image

    im = Image.open(image).convert("RGB")
    im.thumbnail((1200, 1200))
    arr = np.asarray(im)
    q = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    pal = np.array(q.getpalette()[: colors * 3]).reshape(-1, 3)
    used = [i for n, i in sorted(q.getcolors(), reverse=True) if n > arr.shape[0] * arr.shape[1] * 0.01]
    pal = pal[used]
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"images": {}, "confusions": {}, "palette": ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in pal]}
    lab0 = _lab(pal)
    for kind in CVD:
        sim = simulate_cvd(arr, kind).astype(np.uint8)
        p = out_dir / f"{Path(image).stem}-{kind}.png"
        Image.fromarray(sim).save(p)
        res["images"][kind] = str(p)
        lab1 = _lab(simulate_cvd(pal, kind))
        bad = []
        for i in range(len(pal)):
            for j in range(i + 1, len(pal)):
                d0, d1 = float(np.linalg.norm(lab0[i] - lab0[j])), float(np.linalg.norm(lab1[i] - lab1[j]))
                if d0 > 20 and d1 < CONFUSE:
                    bad.append({"a": res["palette"][i], "b": res["palette"][j], "before": round(d0, 1), "after": round(d1, 1)})
        res["confusions"][kind] = bad
    res["ok"] = not any(res["confusions"].values())
    return res


def color_pair(a: str, b: str) -> dict:
    """Two colours (#rrggbb) → ΔE normally and with each colour blindness."""
    def rgb(h):
        h = h.lstrip("#")
        return np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)]], dtype=float)
    x, y = rgb(a), rgb(b)
    out = {"normal": round(float(np.linalg.norm(_lab(x) - _lab(y))), 1)}
    for kind in CVD:
        out[kind] = round(float(np.linalg.norm(_lab(simulate_cvd(x, kind)) - _lab(simulate_cvd(y, kind)))), 1)
    return out


# ============================================================================================== 660 balance
def _duel(a: dict, b: dict, rng: random.Random, max_t: float = 300) -> int:
    hp = [float(a["hp"]), float(b["hp"])]
    u = [a, b]
    nxt = [1 / float(a.get("attack_speed", 1)), 1 / float(b.get("attack_speed", 1))]
    t = 0.0
    while t < max_t:
        t = min(nxt)
        hits = [i for i in (0, 1) if abs(nxt[i] - t) < 1e-9]
        for i in hits:
            me, foe = u[i], u[1 - i]
            if rng.random() < float(me.get("accuracy", 1)):
                dmg = max(1.0, float(me["damage"]) - float(foe.get("armor", 0)))
                if rng.random() < float(me.get("crit_chance", 0)):
                    dmg *= float(me.get("crit_mult", 2))
                hp[1 - i] -= dmg
            nxt[i] += 1 / float(me.get("attack_speed", 1))
        if hp[0] <= 0 or hp[1] <= 0:
            return 0 if hp[0] > 0 else 1 if hp[1] > 0 else -1     # -1 = both fell at once
    return -1


def balance_sim(units: list[dict], fights: int = 500, seed: int = 1) -> dict:
    """Units [{name, hp, damage, attack_speed, armor?, accuracy?, crit_chance?, crit_mult?}] → Monte Carlo duels of each
    pair: win matrix, overall win rate, and units that dominate (> 65 %) or are weak (< 35 %)."""
    if len(units) < 2:
        raise ValueError("Na souboj potřebuju aspoň dvě jednotky.")
    rng = random.Random(seed)
    names = [x["name"] for x in units]
    wins = {n: {} for n in names}
    total = Counter()
    games = Counter()
    for i, a in enumerate(units):
        for j, b in enumerate(units):
            if j <= i:
                continue
            w = Counter(_duel(a, b, rng) if k % 2 == 0 else (lambda r: 1 - r if r >= 0 else -1)(_duel(b, a, rng)) for k in range(fights))
            wins[a["name"]][b["name"]] = round(100 * w[0] / fights, 1)
            wins[b["name"]][a["name"]] = round(100 * w[1] / fights, 1)
            total[a["name"]] += w[0]
            total[b["name"]] += w[1]
            games[a["name"]] += fights
            games[b["name"]] += fights
    rate = {n: round(100 * total[n] / games[n], 1) for n in names}
    dps = {x["name"]: round(max(1.0, float(x["damage"])) * float(x.get("attack_speed", 1)) * float(x.get("accuracy", 1))
                            * (1 + float(x.get("crit_chance", 0)) * (float(x.get("crit_mult", 2)) - 1)), 2) for x in units}
    return {"matrix": wins, "win_rate": rate, "dps": dps, "fights": fights,
            "dominant": [n for n, r in rate.items() if r > 65], "weak": [n for n, r in rate.items() if r < 35]}
