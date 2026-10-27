"""Wave 38 – more for games.

* test scenes (OMEGA 119): a generated level as a Godot 4 scene (.tscn) with walls, spawn, exit and test enemies
* environment concepts (120): a mood board – palette, layout sketch and notes for a theme
* game logs (121): Unity / Unreal / Godot logs → errors grouped, hitches, memory warnings, first occurrence
* asset organisation (122): unused, oversized, non-power-of-two, duplicate and badly named assets; a rename plan
* automated game tests (123): a Godot project run headless – script errors, crashes, missing resources
* mods (124): Minecraft mods (Fabric / Forge / Quilt jars) – versions, missing dependencies, duplicates, conflicts
* FPS by settings (125): frame-time captures per preset compared – average, 1 % lows, stutter, the best trade-off
* anti-exploit tests (653): tampered save variants for your game's validation, impossible movement in telemetry
* voxels (656): a house / tower / tree / pyramid as MagicaVoxel .vox and Minecraft commands
* game settings advice (P12.07): a preset for this PC's graphics card, memory and the screen
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 119 Godot test scene
def godot_scene(level: dict, tile: int = 32, enemies: int = 3, seed: int = 1) -> str:
    """level: the dungeon dict (ascii, start, exit). Walls as merged horizontal runs of ColorRect + StaticBody2D."""
    import random

    rows = level["ascii"].splitlines()
    nodes = ['[gd_scene format=3]\n', '[node name="TestLevel" type="Node2D"]\n']
    runs = 0
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x] != "#":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == "#":
                x += 1
            runs += 1
            w = (x - start) * tile
            nodes.append(f'[node name="Wall{runs}" type="StaticBody2D" parent="."]\nposition = Vector2({start * tile}, {y * tile})\n')
            nodes.append(f'[node name="Shape" type="CollisionShape2D" parent="Wall{runs}"]\nposition = Vector2({w / 2}, {tile / 2})\n')
            nodes.append(f'[node name="Look" type="ColorRect" parent="Wall{runs}"]\noffset_right = {w}.0\noffset_bottom = {tile}.0\n'
                         'color = Color(0.16, 0.17, 0.2, 1)\n')
    sx, sy = level["start"]
    ex, ey = level["exit"]
    nodes.append(f'[node name="PlayerSpawn" type="Marker2D" parent="."]\nposition = Vector2({sx * tile + tile / 2}, {sy * tile + tile / 2})\n')
    nodes.append(f'[node name="Exit" type="Area2D" parent="."]\nposition = Vector2({ex * tile + tile / 2}, {ey * tile + tile / 2})\n')
    floor = [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "."]
    rng = random.Random(seed)
    far = [p for p in floor if abs(p[0] - sx) + abs(p[1] - sy) > 8] or floor
    for i, (x, y) in enumerate(rng.sample(far, min(enemies, len(far))), 1):
        nodes.append(f'[node name="TestEnemy{i}" type="Marker2D" parent="."]\nposition = Vector2({x * tile + tile / 2}, {y * tile + tile / 2})\n')
    text = "\n".join(nodes)
    # shapes: one RectangleShape2D per wall run (sub-resources must come before nodes)
    subs = []
    for i, m in enumerate(re.finditer(r'\[node name="Look" type="ColorRect" parent="Wall(\d+)"\]\noffset_right = ([\d.]+)', text), 1):
        subs.append(f'[sub_resource type="RectangleShape2D" id="S{m.group(1)}"]\nsize = Vector2({m.group(2)}, {tile})\n')
    text = re.sub(r'(\[node name="Shape" type="CollisionShape2D" parent="Wall(\d+)"\]\nposition = Vector2\([^)]*\)\n)',
                  lambda m: m.group(1) + f'shape = SubResource("S{m.group(2)}")\n', text)
    head = f'[gd_scene load_steps={len(subs) + 1} format=3]\n\n' + "\n".join(subs)
    return head + "\n" + text.replace('[gd_scene format=3]\n', "", 1)


# ---------------------------------------------------------------- 120 environment concepts
THEMES = {
    "les": {"palette": ["#1f3b2d", "#2f5d3a", "#4f8a4b", "#a4c36b", "#d9c48a", "#6b4a2f"], "props": "staré stromy, mech, kořeny, potok, mlha",
            "light": "měkké světlo pronikající korunami, ranní mlha", "seed": 11},
    "poušť": {"palette": ["#f2d7a3", "#e3b878", "#c98f4f", "#9c5e34", "#6e3b23", "#b8d8e8"], "props": "duny, skalní oblouky, ruiny, oáza",
              "light": "ostré polední slunce, dlouhé stíny při západu", "seed": 23},
    "sci-fi": {"palette": ["#0b1020", "#17264d", "#2e5bff", "#35e0ff", "#c9d6ff", "#ff3e8a"], "props": "kovové chodby, hologramy, kabely, průzory",
               "light": "studené neonové světlo, kontrastní stíny", "seed": 31},
    "zima": {"palette": ["#e9f2fb", "#bcd3ea", "#7da3c9", "#46658a", "#2a3b52", "#f6c66b"], "props": "zasněžené jehličnany, led, srub, polární záře",
             "light": "nízké zimní slunce, modré stíny", "seed": 47},
    "jeskyně": {"palette": ["#120f14", "#2b2230", "#4a3a52", "#7a5c86", "#3fd6c9", "#e2a14a"], "props": "krápníky, krystaly, podzemní jezero, pochodně",
                "light": "tma, ostrůvky světla od krystalů a pochodní", "seed": 59},
}


def concept_board(theme: str, out: Path, seed: int | None = None) -> dict:
    from PIL import Image, ImageDraw

    from .gamedev import world

    t = THEMES.get(theme.lower())
    if not t:
        raise ValueError(f"Téma neznám. Umím: {', '.join(THEMES)}.")
    tmp = out.with_suffix(".map.png")
    w = world(seed if seed is not None else t["seed"], tmp, 96, 64, 24)
    layout = Image.open(tmp).convert("RGB").resize((768, 512))
    # recolour the generated map into the theme's palette by brightness
    pal = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in t["palette"]]
    import numpy as np

    g = np.asarray(layout.convert("L"))
    lut = np.array([pal[min(len(pal) - 1, v * len(pal) // 256)] for v in range(256)], dtype=np.uint8)
    tinted = Image.fromarray(lut[g])
    board = Image.new("RGB", (1024, 640), (18, 18, 22))
    board.paste(tinted, (16, 16))
    d = ImageDraw.Draw(board)
    for i, c in enumerate(pal):
        d.rectangle([800, 16 + i * 74, 1008, 80 + i * 74], fill=c)
        d.text((808, 64 + i * 74), t["palette"][i], fill=(255, 255, 255) if sum(c) < 380 else (0, 0, 0))
    d.text((16, 540), f"Téma: {theme}", fill=(240, 240, 240))
    d.text((16, 562), f"Rekvizity: {t['props']}", fill=(200, 200, 200))
    d.text((16, 584), f"Světlo: {t['light']}", fill=(200, 200, 200))
    board.save(out)
    tmp.unlink(missing_ok=True)
    return {"theme": theme, "palette": t["palette"], "props": t["props"], "light": t["light"], "spawn": w["spawn"],
            "prompt": f"{theme}, herní prostředí, {t['props']}, {t['light']}, barevná paleta {', '.join(t['palette'])}"}


# ---------------------------------------------------------------- 121 game logs
LOG_RULES = [
    ("chyba", re.compile(r"(NullReferenceException|IndexOutOfRangeException|MissingReferenceException|Exception:|\bERROR\b|Error:|"
                         r"SCRIPT ERROR|LogScript: Error|Fatal error|Assertion failed)", re.I)),
    ("varování", re.compile(r"(\bWARNING\b|Warning:|LogWarning|\bwarn\b)", re.I)),
    ("zásek", re.compile(r"(Hitch detected|hitch|took \d+(\.\d+)?ms|Spike|long frame)", re.I)),
    ("paměť", re.compile(r"(out of memory|OutOfMemory|memory leak|Low memory|GC\.Collect|allocation failed)", re.I)),
    ("chybějící soubor", re.compile(r"(Failed to load|Cannot load|not found|missing (texture|asset|resource)|Couldn't open)", re.I)),
]


def _norm_msg(s: str) -> str:
    s = re.sub(r"0x[0-9a-fA-F]+", "0x…", s)
    s = re.sub(r"\d+(\.\d+)?", "#", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


def game_log(text: str) -> dict:
    lines = text.splitlines()
    engine = "Unity" if re.search(r"UnityEngine|\(Unity\)|\bUnity\b|Initialize engine version", text[:200000]) else "Unreal" if re.search(r"^\[\d{4}\.\d{2}\.\d{2}-", text, re.M) or "LogInit" in text \
        else "Godot" if "Godot Engine" in text or "SCRIPT ERROR" in text else "?"
    groups: dict[tuple[str, str], dict] = {}
    for i, ln in enumerate(lines, 1):
        for kind, rx in LOG_RULES:
            if rx.search(ln):
                key = (kind, _norm_msg(ln))
                g = groups.setdefault(key, {"kind": kind, "message": ln.strip()[:200], "count": 0, "first_line": i})
                g["count"] += 1
                break
    by_kind = Counter()
    for g in groups.values():
        by_kind[g["kind"]] += g["count"]
    order = {"chyba": 0, "paměť": 1, "chybějící soubor": 2, "zásek": 3, "varování": 4}
    top = sorted(groups.values(), key=lambda g: (order[g["kind"]], -g["count"]))[:15]
    return {"engine": engine, "lines": len(lines), "counts": dict(by_kind), "top": top}


# ---------------------------------------------------------------- 122 assets
ASSET_KINDS = {"textura": {".png", ".jpg", ".jpeg", ".tga", ".psd", ".dds", ".webp", ".exr", ".hdr"},
               "model": {".fbx", ".obj", ".blend", ".gltf", ".glb", ".dae"}, "zvuk": {".wav", ".ogg", ".mp3", ".flac"},
               "skript": {".cs", ".gd", ".lua", ".cpp", ".h", ".js", ".ts", ".py"}, "scéna": {".unity", ".tscn", ".scn", ".umap", ".prefab", ".tres", ".asset", ".mat"}}
TEXT_REFS = {".cs", ".gd", ".lua", ".cpp", ".h", ".js", ".ts", ".py", ".unity", ".tscn", ".tres", ".prefab", ".mat", ".asset", ".json", ".meta", ".scn", ".cfg", ".ini"}


def _kind(p: Path) -> str:
    return next((k for k, ex in ASSET_KINDS.items() if p.suffix.lower() in ex), "ostatní")


def assets_report(root: Path, limit: int = 20000) -> dict:
    from PIL import Image

    files = [p for p in root.rglob("*") if p.is_file() and not any(x.startswith(".") or x in ("Library", "Temp", "obj", "Build", "builds") for x in p.relative_to(root).parts)][:limit]
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    refs_text = ""
    for p in files:
        if p.suffix.lower() in TEXT_REFS and p.stat().st_size < 5_000_000:
            refs_text += p.read_text(encoding="utf-8", errors="replace").lower() + "\n"
    guids = set(re.findall(r"guid: ([0-9a-f]{32})", refs_text))
    kinds, unused, big, npot, badname = Counter(), [], [], [], []
    by_hash: dict[str, list[str]] = defaultdict(list)
    for p in files:
        k = _kind(p)
        kinds[k] += 1
        if k in ("textura", "model", "zvuk"):
            meta = p.with_name(p.name + ".meta")
            guid = re.search(r"guid: ([0-9a-f]{32})", meta.read_text(errors="replace")) if meta.is_file() else None
            used = p.name.lower() in refs_text or p.stem.lower() in refs_text or (guid and refs_text.count(guid.group(1)) > 1)
            if not used:
                unused.append(rel(p))
            if p.stat().st_size < 64_000_000:
                by_hash[hashlib.sha256(p.read_bytes()).hexdigest()].append(rel(p))
        if k == "textura" and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".tga", ".webp"):
            try:
                with Image.open(p) as im:
                    w, h = im.size
            except Exception:  # noqa: BLE001
                continue
            if max(w, h) > 4096:
                big.append(f"{rel(p)} ({w}×{h})")
            if w & (w - 1) or h & (h - 1):
                npot.append(f"{rel(p)} ({w}×{h})")
        if re.search(r"\s|[áčďéěíňóřšťúůýž]|copy|kopie|final|\(\d\)", p.stem, re.I):
            badname.append(rel(p))
    dups = [v for v in by_hash.values() if len(v) > 1]
    plan = []
    for f in badname[:50]:
        p = Path(f)
        clean = re.sub(r"\s*\(\d+\)|[-_ ]?(copy|kopie|final)\b", "", p.stem, flags=re.I)
        clean = re.sub(r"[^\w]+", "_", clean.translate(str.maketrans("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ", "acdeeinorstuuyzACDEEINORSTUUYZ"))).strip("_")
        if clean and clean != p.stem:
            plan.append({"from": f, "to": str(p.with_name(clean + p.suffix).as_posix())})
    return {"files": len(files), "kinds": dict(kinds), "unused": unused[:200], "oversized": big[:100], "not_power_of_two": npot[:100],
            "duplicates": dups[:50], "bad_names": badname[:100], "rename_plan": plan,
            "unity_guids": len(guids)}


# ---------------------------------------------------------------- 123 automated game tests (Godot)
def godot_exe() -> str | None:
    import os
    import shutil

    for n in ("godot", "godot4", "Godot_v4", "godot.exe"):
        if found := shutil.which(n):
            return found
    env = os.environ.get("GODOT_BIN")
    return env if env and Path(env).is_file() else None


def godot_check(output: str, code: int | None) -> dict:
    errors = [ln.strip() for ln in output.splitlines() if re.search(r"(SCRIPT ERROR|ERROR:|Parse Error|Invalid call|Cannot open|crash)", ln, re.I)]
    found = re.findall(r"(res://[^\s'\"]+)", "\n".join(e for e in errors if re.search(r"load|open|resource|not found", e, re.I)))
    missing = sorted({m.rstrip(".,;:)") for m in found})
    crashed = code is not None and code not in (0,) and not errors
    return {"ok": code == 0 and not errors, "exit_code": code, "errors": errors[:30], "missing": missing, "crashed": crashed or "crash" in output.lower()}


def godot_run(project: Path, seconds: int = 20, runner=subprocess.run) -> dict:
    exe = godot_exe()
    if not exe:
        raise FileNotFoundError("Nevidím Godot – přidej ho do PATH nebo nastav proměnnou GODOT_BIN (JARVIS ho sám nestahuje).")
    if not (project / "project.godot").is_file():
        raise ValueError("Ve složce není project.godot.")
    r = runner([exe, "--headless", "--path", str(project), "--quit-after", str(max(60, seconds * 60))], capture_output=True, text=True, encoding="utf-8", errors="replace",
               timeout=seconds + 60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "") + (r.stderr or "")
    return {**godot_check(out, r.returncode), "log_tail": out[-3000:]}


# ---------------------------------------------------------------- 124 mods (Minecraft)
def _mod_info(jar: Path) -> dict | None:
    try:
        with zipfile.ZipFile(jar) as z:
            names = set(z.namelist())
            if "fabric.mod.json" in names or "quilt.mod.json" in names:
                d = json.loads(z.read("fabric.mod.json" if "fabric.mod.json" in names else "quilt.mod.json").decode("utf-8", "replace"))
                if "quilt_loader" in d:
                    q = d["quilt_loader"]
                    deps = {x["id"] if isinstance(x, dict) else x: (x.get("versions", "*") if isinstance(x, dict) else "*") for x in q.get("depends", [])}
                    return {"id": q.get("id"), "version": q.get("version", "?"), "loader": "quilt", "depends": deps, "file": jar.name}
                return {"id": d.get("id"), "version": str(d.get("version", "?")), "loader": "fabric",
                        "depends": {k: v if isinstance(v, str) else ",".join(v) for k, v in (d.get("depends") or {}).items()},
                        "breaks": d.get("breaks") or {}, "file": jar.name}
            if "META-INF/mods.toml" in names or "META-INF/neoforge.mods.toml" in names:
                t = z.read("META-INF/neoforge.mods.toml" if "META-INF/neoforge.mods.toml" in names else "META-INF/mods.toml").decode("utf-8", "replace")
                mid = re.search(r'modId\s*=\s*"([^"]+)"', t)
                ver = re.search(r'^\s*version\s*=\s*"([^"]+)"', t, re.M)
                deps = {}
                for block in re.split(r"\[\[dependencies\.[^\]]+\]\]", t)[1:]:
                    did = re.search(r'modId\s*=\s*"([^"]+)"', block)
                    rng = re.search(r'versionRange\s*=\s*"([^"]+)"', block)
                    mand = re.search(r"(mandatory\s*=\s*(true|false)|type\s*=\s*\"(required|optional)\")", block)
                    if did and (not mand or "true" in mand.group(0) or "required" in mand.group(0)):
                        deps[did.group(1)] = rng.group(1) if rng else "*"
                return {"id": mid.group(1) if mid else jar.stem, "version": ver.group(1) if ver else "?", "loader": "forge", "depends": deps, "file": jar.name}
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError):
        return None
    return None


BUILTIN_DEPS = {"minecraft", "java", "fabricloader", "fabric-loader", "forge", "neoforge", "quilt_loader", "fabric", "fabric-api-base"}


def _mc_ok(spec: str, mc: str) -> bool:
    if not mc or not spec or spec in ("*", "") or "${" in spec:
        return True
    for part in re.split(r"\s*\|\|\s*|,(?![^\[(]*[\])])", spec):
        part = part.strip()
        if m := re.fullmatch(r"[\[(]([\d.]*),\s*([\d.]*)[\])]", part):
            lo, hi = m.groups()
            if (not lo or _v(mc) >= _v(lo)) and (not hi or _v(mc) < _v(hi) or (part.endswith("]") and _v(mc) == _v(hi))):
                return True
            continue
        p = part.lstrip("~^>=<").replace("x", "0").rstrip(".*")
        if part.startswith((">=", ">")):
            if _v(mc) >= _v(p):
                return True
        elif part.startswith("<"):
            if _v(mc) < _v(p):
                return True
        elif part.startswith("~"):          # ~1.20.4 = at least 1.20.4, still 1.20.x
            if _v(mc) >= _v(p) and _v(mc)[:2] == _v(p)[:2]:
                return True
        elif part.endswith(".x") or part.endswith("*"):
            if mc.startswith(p):
                return True
        elif mc == p or mc.startswith(p + "."):
            return True
    return False


def _v(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4])


def mods_report(folder: Path, mc_version: str = "") -> dict:
    mods = [m for m in (_mod_info(j) for j in sorted(folder.glob("*.jar"))) if m]
    unreadable = [j.name for j in folder.glob("*.jar") if not _mod_info(j)]
    ids = defaultdict(list)
    for m in mods:
        ids[m["id"]].append(m)
    loaders = Counter(m["loader"] for m in mods)
    problems = []
    if len(loaders) > 1:
        problems.append(f"Míchají se zavaděče: {', '.join(f'{k} ({v})' for k, v in loaders.items())} – ve hře poběží jen jeden typ.")
    for mid, group in ids.items():
        if len(group) > 1:
            problems.append(f"{mid} je tam {len(group)}× ({', '.join(g['file'] for g in group)}) – nech jen nejnovější.")
    present = set(ids) | BUILTIN_DEPS | {"fabric-api"} if "fabric-api" in ids else set(ids) | BUILTIN_DEPS
    for m in mods:
        for dep, spec in m["depends"].items():
            if dep == "minecraft" and mc_version and not _mc_ok(str(spec), mc_version):
                problems.append(f"{m['id']} {m['version']} chce Minecraft {spec}, máš {mc_version}.")
            elif dep not in present and not dep.startswith("fabric-") and dep not in ("java", "minecraft"):
                problems.append(f"{m['id']} potřebuje {dep} ({spec}), který chybí.")
        for other in (m.get("breaks") or {}):
            if other in ids:
                problems.append(f"{m['id']} je nekompatibilní s {other}.")
    return {"mods": [{k: m[k] for k in ("id", "version", "loader", "file")} for m in mods], "count": len(mods), "unreadable": unreadable,
            "problems": problems, "loaders": dict(loaders)}


# ---------------------------------------------------------------- 125 FPS by settings
def compare_settings(runs: dict[str, list[float]], target_fps: float = 60) -> dict:
    from .pccare import frame_report

    rows = []
    for name, ms in runs.items():
        r = frame_report(ms, target_fps)
        rows.append({"settings": name, **{k: r[k] for k in ("avg_fps", "low_1pct_fps", "stutters_per_min", "over_budget_pct", "verdict")}})
    good = [r for r in rows if r["low_1pct_fps"] >= target_fps * 0.85 and r["stutters_per_min"] <= 2]
    pick = good[-1] if good else max(rows, key=lambda r: r["low_1pct_fps"])
    # order by quality as given (the order of the runs = from lowest to highest settings)
    return {"runs": rows, "recommended": pick["settings"], "target_fps": target_fps,
            "reason": (f"Nejvyšší nastavení, kde 1 % nejhorších snímků drží aspoň {target_fps * 0.85:.0f} FPS a nesekne se víc než 2× za minutu."
                       if good else "Žádné nastavení cíl nesplní – vybírám to s nejlepšími 1 % low.")}


# ---------------------------------------------------------------- 653 anti-exploit
def _numeric_paths(data: Any, path: str = "") -> list[str]:
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            out += _numeric_paths(v, f"{path}.{k}" if path else str(k))
    elif isinstance(data, list):
        for i, v in enumerate(data[:20]):
            out += _numeric_paths(v, f"{path}[{i}]")
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        out.append(path)
    return out


def _set(data: Any, path: str, value: Any) -> None:
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    cur = data
    for p in parts[:-1]:
        cur = cur[int(p[1:-1])] if p.startswith("[") else cur[p]
    last = parts[-1]
    if last.startswith("["):
        cur[int(last[1:-1])] = value
    else:
        cur[last] = value


def tampered_saves(save: Any, limit: int = 40) -> list[dict]:
    """Variants a cheater would try: huge / negative / NaN-like numbers, duplicated inventory items."""
    out = []
    for path in _numeric_paths(save)[:limit // 4 or 1]:
        for label, val in (("obrovská hodnota", 2_147_483_647), ("záporná hodnota", -999999), ("desetinná místo celé", 0.5), ("text místo čísla", "999999")):
            d = copy.deepcopy(save)
            _set(d, path, val)
            out.append({"change": f"{path} → {label}", "data": d})
    if isinstance(save, dict):
        for k, v in save.items():
            if isinstance(v, list) and v and len(out) < limit:
                d = copy.deepcopy(save)
                d[k] = v + v * 50
                out.append({"change": f"{k} → předměty zkopírované 50×", "data": d})
    return out[:limit]


def impossible_moves(rows: list[dict], max_speed: float) -> list[dict]:
    """rows: {player, t, x, y}; flags moves faster than max_speed (units per second) – speed hacks and teleports."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[str(r["player"])].append(r)
    out = []
    for pl, rs in by.items():
        rs.sort(key=lambda r: float(r["t"]))
        for a, b in zip(rs, rs[1:]):
            dt = float(b["t"]) - float(a["t"])
            if dt <= 0:
                continue
            v = math.dist((float(a["x"]), float(a["y"])), (float(b["x"]), float(b["y"]))) / dt
            if v > max_speed:
                out.append({"player": pl, "t": float(b["t"]), "speed": round(v, 1), "times_max": round(v / max_speed, 1)})
    return sorted(out, key=lambda x: -x["speed"])[:50]


# ---------------------------------------------------------------- 656 voxels
PALETTE = {"kámen": (128, 128, 128), "dřevo": (139, 94, 52), "střecha": (164, 52, 44), "sklo": (170, 220, 240), "list": (52, 140, 60),
           "kmen": (101, 67, 33), "písek": (222, 196, 140), "zlato": (230, 190, 60)}
MC_BLOCK = {"kámen": "stone_bricks", "dřevo": "oak_planks", "střecha": "red_terracotta", "sklo": "glass_pane", "list": "oak_leaves",
            "kmen": "oak_log", "písek": "sandstone", "zlato": "gold_block"}


def voxel_model(kind: str, size: int = 9, seed: int = 1) -> dict[tuple[int, int, int], str]:
    import random

    rng = random.Random(seed)
    v: dict[tuple[int, int, int], str] = {}
    n = max(5, min(size, 48))
    if kind == "dům":
        h = max(4, n // 2)
        for x in range(n):
            for y in range(n):
                v[(x, y, 0)] = "kámen"
                for z in range(1, h):
                    if x in (0, n - 1) or y in (0, n - 1):
                        door = y == 0 and x == n // 2 and z <= 2
                        window = z == 2 and ((y in (0, n - 1) and x in (2, n - 3)) or (x in (0, n - 1) and y == n // 2))
                        if not door:
                            v[(x, y, z)] = "sklo" if window else "dřevo"
        for k in range(n // 2 + 1):
            for x in range(k, n - k):
                for y in range(-1 + 0, n):
                    if x in (k, n - 1 - k) or k == n // 2:
                        v[(x, y, h + k)] = "střecha"
    elif kind == "věž":
        r, h = n / 2, n * 2
        for z in range(h):
            for x in range(n):
                for y in range(n):
                    d = math.hypot(x - r + 0.5, y - r + 0.5)
                    if d < r and (d > r - 1.5 or z == 0) and not (z % 6 == 3 and x == n // 2):
                        v[(x, y, z)] = "kámen"
                    if z == h - 1 and d < r and (x + y) % 2 == 0 and d > r - 1.5:
                        v[(x, y, z + 1)] = "kámen"
    elif kind == "strom":
        trunk = max(4, n // 2)
        c = n // 2
        for z in range(trunk):
            v[(c, c, z)] = "kmen"
        for x in range(n):
            for y in range(n):
                for z in range(trunk - 1, trunk + n // 2 + 1):
                    if math.dist((x, y, z), (c, c, trunk + 1)) < n / 2 - rng.random() * 0.8 and (x, y, z) not in v:
                        v[(x, y, z)] = "list"
    elif kind == "pyramida":
        for z in range(n // 2 + 1):
            for x in range(z, n - z):
                for y in range(z, n - z):
                    v[(x, y, z)] = "zlato" if z == n // 2 else "písek"
    else:
        raise ValueError("Umím: dům, věž, strom, pyramida.")
    return {k: m for k, m in v.items() if k[1] >= 0}


def vox_bytes(model: dict[tuple[int, int, int], str]) -> bytes:
    """MagicaVoxel .vox (version 150): SIZE + XYZI + RGBA chunks."""
    xs, ys, zs = zip(*model)
    mx, my, mz = min(xs), min(ys), min(zs)
    names = sorted(set(model.values()))
    idx = {n: i + 1 for i, n in enumerate(names)}
    sx, sy, sz = max(xs) - mx + 1, max(ys) - my + 1, max(zs) - mz + 1
    if max(sx, sy, sz) > 256:
        raise ValueError("Model je větší než 256 kostek.")
    xyzi = struct.pack("<I", len(model)) + b"".join(struct.pack("<BBBB", x - mx, y - my, z - mz, idx[m]) for (x, y, z), m in model.items())
    rgba = b"".join(struct.pack("<BBBB", *PALETTE[n], 255) for n in names) + b"\0\0\0\xff" * (256 - len(names))

    def chunk(cid: bytes, content: bytes) -> bytes:
        return cid + struct.pack("<II", len(content), 0) + content
    children = chunk(b"SIZE", struct.pack("<III", sx, sy, sz)) + chunk(b"XYZI", xyzi) + chunk(b"RGBA", rgba)
    return b"VOX " + struct.pack("<I", 150) + b"MAIN" + struct.pack("<II", 0, len(children)) + children


def mcfunction(model: dict[tuple[int, int, int], str]) -> str:
    """Minecraft commands relative to the player (~): z of the model is up."""
    return "".join(f"setblock ~{x} ~{z} ~{y} minecraft:{MC_BLOCK[m]}\n" for (x, y, z), m in sorted(model.items(), key=lambda k: (k[0][2], k[0][0], k[0][1])))


# ---------------------------------------------------------------- P12.07 game settings advice
GPU_TIERS = [  # (pattern, tier 1–5)
    (r"rtx\s*50[89]0|rtx\s*4090|rtx\s*4080|rx\s*7900", 5), (r"rtx\s*50[67]0|rtx\s*40[67]0|rtx\s*3080|rtx\s*3090|rx\s*7800|rx\s*6800|rx\s*9070", 4),
    (r"rtx\s*3060|rtx\s*3070|rtx\s*2080|rtx\s*4060|rx\s*6600|rx\s*6700|rx\s*7600|arc\s*a7", 3),
    (r"gtx\s*16|rtx\s*2060|rtx\s*3050|gtx\s*1070|gtx\s*1080|rx\s*5[67]00|rx\s*580|arc\s*a[35]", 2),
    (r"gtx\s*10[56]0|gtx\s*9|rx\s*[45][67]0|radeon\s*(vega|780m|890m)|iris\s*xe|arc\s*graphics", 1),
    (r"uhd|hd graphics|vega\s*[38]|radeon graphics", 0),
]
PRESETS = ["velmi nízké", "nízké", "střední", "vysoké", "velmi vysoké", "ultra"]


def settings_advice(gpu: str, vram_gb: float, ram_gb: float, screen: tuple[int, int], refresh: int = 60, cpu_cores: int = 8) -> dict:
    tier = next((t for rx, t in GPU_TIERS if re.search(rx, gpu or "", re.I)), 2)
    pixels = screen[0] * screen[1]
    tier -= 1 if pixels > 2560 * 1440 else 0
    tier -= 1 if pixels > 3840 * 2160 * 0.9 else 0
    tier -= 1 if vram_gb and vram_gb < 6 else 0
    tier -= 1 if ram_gb and ram_gb < 16 else 0
    tier = max(0, min(5, tier))
    upscale = "DLSS / FSR v režimu Kvalita" if pixels >= 2560 * 1440 and tier <= 3 else ("DLSS / FSR Výkon" if tier <= 1 else "vypnuto nebo Kvalita")
    tips = [f"Předvolba: {PRESETS[tier]}.", f"Rozlišení {screen[0]}×{screen[1]}, upscaling: {upscale}."]
    if refresh > 60:
        tips.append(f"Monitor má {refresh} Hz – omez FPS na {refresh - 3} (méně trhání, nižší spotřeba) a zapni G-Sync / FreeSync.")
    else:
        tips.append("Zapni V-Sync nebo omez FPS na 60.")
    if vram_gb and vram_gb < 8:
        tips.append("Textury drž na střední – víc paměti grafiky nemáš a přetečení způsobuje záseky.")
    if ram_gb and ram_gb < 16:
        tips.append("Zavři prohlížeč a Discord overlay – 8–12 GB RAM je pro dnešní hry těsně.")
    if cpu_cores and cpu_cores <= 4:
        tips.append("Stíny a dohled (draw distance) dej níž – zatěžují procesor.")
    tips.append("Nejvíc výkonu bere obvykle: stíny, volumetrické mraky/mlha, ray tracing a odrazy.")
    return {"tier": tier, "preset": PRESETS[tier], "upscaling": upscale, "tips": tips}
