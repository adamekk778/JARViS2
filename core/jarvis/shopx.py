"""3.20 Dílna+ (ideas 321–340): filament drying, what a print costs, spools in stock, a library of your models with
pictures, STL edits by voice, the forgotten soldering iron, several printers, calibration, laser and CNC G-code, tools
and where they are, workshop units, lent things, a cutting plan, paint, the workshop's climate, screws and anchors,
tool maintenance, splitting a model that does not fit the bed, safety, and a package for Printables.

The house parts (iron, climate) use Home Assistant; the rest works on its own."""
from __future__ import annotations

import datetime as dt
import io
import math
import re
import shutil
import struct
import subprocess
import time
import unicodedata
import zipfile
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS sx_spools (id INTEGER PRIMARY KEY, material TEXT, color TEXT, brand TEXT, total_g REAL, left_g REAL,
  price REAL, opened TEXT, dried TEXT);
CREATE TABLE IF NOT EXISTS sx_parts (path TEXT PRIMARY KEY, name TEXT, words TEXT, dims TEXT, size INTEGER, mtime REAL);
CREATE TABLE IF NOT EXISTS sx_queue (id INTEGER PRIMARY KEY, file TEXT, material TEXT, hours REAL, size TEXT, printer TEXT, state TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS sx_tools (id INTEGER PRIMARY KEY, name TEXT, place TEXT, qty INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS sx_lent (id INTEGER PRIMARY KEY, item TEXT, person TEXT, since TEXT, back TEXT, reminded TEXT);
CREATE TABLE IF NOT EXISTS sx_maint (id INTEGER PRIMARY KEY, tool TEXT, task TEXT, every_days INTEGER, last TEXT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_shopx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._shopx_ready = True
    return rt.db


def cfg(rt: Any) -> Any:
    from .config import ShopXCfg

    return getattr(rt.cfg, "shopx", None) or ShopXCfg()


def kc(v: float) -> str:
    return f"{v:,.0f} Kč".replace(",", " ") if abs(v) >= 100 else f"{v:.2f} Kč".replace(".", ",")


# ------------------------------------------------------------------ (321) drying, (323) spools
# material → (dry °C, dry hours, max humidity %, density g/cm³, how badly it takes water)
MATERIALS: dict[str, tuple[int, str, int, float, str]] = {
    "PLA": (45, "4–6", 50, 1.24, "málo"), "PETG": (65, "4–6", 40, 1.27, "středně"), "ABS": (80, "4", 40, 1.04, "středně"),
    "ASA": (80, "4", 40, 1.07, "středně"), "TPU": (50, "4–8", 30, 1.21, "hodně"), "PA": (80, "8–12", 20, 1.14, "velmi"),
    "PC": (80, "8", 20, 1.20, "hodně"), "PVA": (50, "6–8", 20, 1.23, "extrémně"), "PP": (60, "6", 50, 0.90, "málo"),
    "PLA-CF": (55, "6", 40, 1.30, "středně"), "PETG-CF": (65, "6", 35, 1.30, "středně"), "PA-CF": (80, "12", 15, 1.20, "velmi"),
}
ALIASES = {"NYLON": "PA", "PA6": "PA", "PA12": "PA", "PETG CF": "PETG-CF", "PLA CF": "PLA-CF", "PA CF": "PA-CF", "PLA+": "PLA"}


def material(name: str) -> str:
    u = (name or "").upper().strip()
    return ALIASES.get(u, u if u in MATERIALS else next((m for m in sorted(MATERIALS, key=len, reverse=True) if m in u), u))


def dry_advice(name: str, humidity: float | None = None, opened_days: int | None = None) -> dict:
    m = material(name)
    if m not in MATERIALS:
        return {"ok": False, "text": f"{name} neznám – sušení najdeš na štítku cívky."}
    temp, hours, max_h, _, hygro = MATERIALS[m]
    need = (humidity is not None and humidity > max_h) or (opened_days is not None and opened_days > {"málo": 60, "středně": 21}.get(hygro, 7))
    why = []
    if humidity is not None:
        why.append(f"vlhkost {humidity:.0f} % (limit {max_h} %)")
    if opened_days is not None:
        why.append(f"otevřená {opened_days} dní")
    text = (f"{m}: {'usuš' if need else 'zatím netřeba sušit'} – {temp} °C, {hours} h" + (f" ({', '.join(why)})" if why else "")
            + f". Vodu bere {hygro}; skladuj v boxu se silikagelem.")
    return {"ok": True, "material": m, "need": need, "temp": temp, "hours": hours, "text": text}


def spool_add(rt: Any, mat: str, color: str = "", brand: str = "", total_g: float = 1000, price: float = 0, left_g: float | None = None) -> int:
    cur = db(rt).exec("INSERT INTO sx_spools (material, color, brand, total_g, left_g, price, opened, dried) VALUES (?,?,?,?,?,?,?,?)",
                      (material(mat), color, brand, total_g, total_g if left_g is None else left_g, price, dt.date.today().isoformat(), ""))
    return int(getattr(cur, "lastrowid", 0) or 0)


def spools(rt: Any) -> list[dict]:
    return [dict(r) for r in db(rt).all("SELECT * FROM sx_spools WHERE left_g > 0 ORDER BY material, color")]


def spool_find(rt: Any, text: str) -> dict | None:
    t = fold(text)
    best = None
    for s in spools(rt):
        score = (fold(s["material"]) in t) * 2 + (bool(s["color"]) and fold(s["color"])[:4] in t) * 3 + (str(s["id"]) == t.strip()) * 9
        if score and (best is None or score > best[0]):
            best = (score, s)
    return best[1] if best else None


def spool_use(rt: Any, spool_id: int, grams: float, low_g: float = 150) -> dict:
    row = db(rt).one("SELECT * FROM sx_spools WHERE id=?", (spool_id,))
    if not row:
        raise ValueError("Takovou cívku nemám.")
    left = max(0.0, float(row["left_g"]) - grams)
    db(rt).exec("UPDATE sx_spools SET left_g=? WHERE id=?", (left, spool_id))
    return {"left": round(left), "low": left < low_g, "name": f"{row['material']} {row['color']}".strip()}


def reorder_list(rt: Any, low_g: float = 150) -> list[dict]:
    return [s for s in spools(rt) if s["left_g"] < low_g] + [dict(r) for r in db(rt).all("SELECT * FROM sx_spools WHERE left_g <= 0")]


# ------------------------------------------------------------------ (322) what a print costs
def print_cost(grams: float, hours: float, price_per_kg: float = 500, watts: float = 120, kwh_price: float = 6.0,
               wear_per_hour: float = 2.0, fail_pct: float = 5) -> dict:
    mat = grams / 1000 * price_per_kg
    power = watts / 1000 * hours * kwh_price
    wear = hours * wear_per_hour
    total = (mat + power + wear) * (1 + fail_pct / 100)
    return {"material": round(mat, 2), "power": round(power, 2), "wear": round(wear, 2), "total": round(total, 2),
            "text": f"Materiál {kc(mat)}, elektřina {kc(power)}, opotřebení {kc(wear)} → asi {kc(total)} (s {fail_pct:g} % na nepovedené tisky)."}


# ------------------------------------------------------------------ (324) model library, (325) STL edits
def stl_read(path: Path) -> np.ndarray:
    """Triangles of an STL file as an (n, 3, 3) array (binary or ASCII)."""
    data = path.read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            return rec["v"].astype(np.float64)
    nums = re.findall(rb"vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)", data)
    if not nums:
        raise ValueError("Tohle není čitelné STL.")
    return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)


def stl_write(path: Path, tris: np.ndarray) -> Path:
    tris = tris.astype(np.float32)
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, ln, out=np.zeros_like(nrm), where=ln > 0)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = nrm, tris
    with open(path, "wb") as f:
        f.write(b"JARVIS STL".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())
    return path


def dims(tris: np.ndarray) -> list[float]:
    pts = tris.reshape(-1, 3)
    return [round(float(x), 1) for x in pts.max(0) - pts.min(0)]


def volume_cm3(tris: np.ndarray) -> float:
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    return abs(float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum()) / 6) / 1000


def thumbnail(tris: np.ndarray, size: int = 320) -> bytes:
    """A simple shaded picture of the model from above at an angle (no 3D library needed)."""
    from PIL import Image, ImageDraw

    pts = tris.reshape(-1, 3) - tris.reshape(-1, 3).mean(0)
    a, b = math.radians(35), math.radians(-30)
    rz = np.array([[math.cos(b), -math.sin(b), 0], [math.sin(b), math.cos(b), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    p = (pts @ rz.T @ rx.T).reshape(-1, 3, 3)
    xy = p[:, :, [0, 2]]
    span = float(np.ptp(xy.reshape(-1, 2), axis=0).max()) or 1.0
    xy = (xy - xy.reshape(-1, 2).min(0)) / span * (size * 0.86) + size * 0.07
    nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    light = np.clip(np.abs(nrm[:, 1]) / np.where(ln > 0, ln, 1), 0.15, 1)
    order = np.argsort(p[:, :, 1].mean(1))[::-1]
    img = Image.new("RGB", (size, size), (16, 22, 30))
    d = ImageDraw.Draw(img)
    step = max(1, len(order) // 60000)
    for i in order[::step]:
        c = int(60 + 170 * light[i])
        d.polygon([(float(x), size - float(y)) for x, y in xy[i]], fill=(c // 3, int(c * 0.8), c))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


MODEL_EXT = {".stl", ".3mf", ".step", ".stp", ".obj", ".scad", ".f3d"}


def library_index(rt: Any, folders: list[str]) -> int:
    n = 0
    for folder in folders:
        root = Path(folder).expanduser()
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in MODEL_EXT or not p.is_file():
                continue
            st = p.stat()
            row = db(rt).one("SELECT mtime FROM sx_parts WHERE path=?", (str(p),))
            if row and float(row["mtime"]) == st.st_mtime:
                continue
            d = ""
            if p.suffix.lower() == ".stl" and st.st_size < 80_000_000:
                try:
                    d = "×".join(f"{x:g}" for x in dims(stl_read(p)))
                except (ValueError, OSError):
                    d = ""
            words = fold(" ".join(re.split(r"[\W_]+", str(p.relative_to(root).with_suffix("")))))
            db(rt).exec("INSERT OR REPLACE INTO sx_parts VALUES (?,?,?,?,?,?)", (str(p), p.stem, words, d, st.st_size, st.st_mtime))
            n += 1
    return n


def library_find(rt: Any, query: str, limit: int = 8) -> list[dict]:
    words = [w[:5] for w in re.findall(r"[a-z0-9]+", fold(query)) if len(w) > 2]
    out = []
    for r in db(rt).all("SELECT * FROM sx_parts"):
        s = sum(1 for w in words if w in r["words"])
        if s:
            out.append((s, dict(r)))
    return [r for _, r in sorted(out, key=lambda x: (-x[0], x[1]["name"]))[:limit]]


def parse_edit(text: str) -> dict:
    """„zvětši o 10 %“, „zmenši na 80 %“, „otoč o 90° kolem Z“, „zrcadli podle X“, „posuň nahoru o 5 mm“, „díra 5 mm“."""
    t = fold(text)
    m = re.search(r"(zvets\w*|zmens\w*|scale|meritko)\D*?(o|na)?\s*([\d.,]+)\s*(%|x|×)?", t)
    if m:
        v = float(m.group(3).replace(",", "."))
        if m.group(4) in ("x", "×"):
            f = v
        elif m.group(2) == "na":
            f = v / 100
        else:
            f = 1 + (v / 100 if "zvets" in m.group(1) or "scale" in m.group(1) else -v / 100)
        return {"op": "scale", "factor": f}
    m = re.search(r"(otoc\w*|rotuj\w*)\D*?(-?\d+)\s*(°|stup\w*)?(?:.*?\b([xyz])\b)?", t)
    if m:
        return {"op": "rotate", "deg": float(m.group(2)), "axis": m.group(4) or "z"}
    m = re.search(r"zrcad\w*.*?\b([xyz])\b", t)
    if m:
        return {"op": "mirror", "axis": m.group(1)}
    m = re.search(r"(dir\w*|otvor\w*)\D*([\d.,]+)\s*mm", t)
    if m:
        return {"op": "hole", "d": float(m.group(2).replace(",", "."))}
    return {"op": ""}


def stl_edit(tris: np.ndarray, edit: dict) -> np.ndarray:
    pts = tris.reshape(-1, 3).copy()
    c = (pts.max(0) + pts.min(0)) / 2
    if edit["op"] == "scale":
        f = float(edit["factor"])
        if not 0.01 <= f <= 100:
            raise ValueError("Takové měřítko nedává smysl.")
        pts = (pts - c) * f + c
    elif edit["op"] == "rotate":
        a = math.radians(edit["deg"])
        ax = "xyz".index(edit.get("axis", "z"))
        i, j = [k for k in range(3) if k != ax]
        r = np.eye(3)
        r[i, i], r[i, j], r[j, i], r[j, j] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
        pts = (pts - c) @ r.T + c
    elif edit["op"] == "mirror":
        ax = "xyz".index(edit["axis"])
        pts[:, ax] = 2 * c[ax] - pts[:, ax]
        out = pts.reshape(-1, 3, 3)
        return out[:, [0, 2, 1]]                               # mirrored → flip the winding so the normals point out
    else:
        raise ValueError("Tohle umím jen přes OpenSCAD.")
    pts[:, 2] -= pts[:, 2].min()                               # back on the bed
    return pts.reshape(-1, 3, 3)


def openscad() -> str | None:
    for c in ("openscad", "openscad.com", r"C:\Program Files\OpenSCAD\openscad.exe", r"C:\Program Files\OpenSCAD\openscad.com"):
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    return None


def hole_scad(stl: Path, d: float, dims_: list[float], at: tuple[float, float] | None = None) -> str:
    x, y = at if at else (0.0, 0.0)
    h = dims_[2] + 2
    return (f'difference() {{\n  import("{stl.as_posix()}", convexity=10);\n'
            f"  translate([{x}, {y}, -1]) cylinder(d={d}, h={h}, $fn=64);\n}}\n")


def run_openscad(scad: str, out: Path, runner=subprocess.run) -> tuple[bool, str]:
    exe = openscad()
    if not exe:
        return False, "Na díry a řezy potřebuju OpenSCAD (openscad.org, zdarma) – nainstaluj ho a zkus to znovu."
    src = out.with_suffix(".scad")
    src.write_text(scad, encoding="utf-8")
    r = runner([exe, "-o", str(out), str(src)], capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and out.exists(), (r.stderr or "")[-400:]


# ------------------------------------------------------------------ (326) forgotten soldering iron, (335) workshop climate
async def ha_tick(rt: Any, st: list[dict], now: float, service: Any) -> list[str]:
    """Called from the house watch every minute with Home Assistant's states."""
    c = cfg(rt)
    said: list[str] = []
    by_id = {e["id"]: e for e in st}
    if c.iron_plug and c.iron_plug in by_id:
        plug = by_id[c.iron_plug]
        key_on, key_warn = "sx_iron_on", "sx_iron_warned"
        on = plug["state"] == "on"
        row = rt.db.one("SELECT v FROM kv WHERE k=?", (key_on,))
        since = float(row["v"]) if row else None
        if not on:
            rt.db.exec("DELETE FROM kv WHERE k IN (?,?)", (key_on, key_warn))
        else:
            if since is None:
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key_on, str(now)))
                since = now
            moving = False
            if c.workshop_motion and c.workshop_motion in by_id:
                m = by_id[c.workshop_motion]
                moving = m["state"] == "on"
                if moving:
                    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key_on, str(now)))     # someone works → the clock starts again
                    rt.db.exec("DELETE FROM kv WHERE k=?", (key_warn,))
            idle_min = (now - since) / 60
            warned = rt.db.one("SELECT v FROM kv WHERE k=?", (key_warn,))
            if not moving and idle_min >= c.iron_minutes and not warned:
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key_warn, str(now)))
                said.append(f"Páječka je zapnutá {idle_min:.0f} min bez pohybu v dílně – za 5 minut ji vypnu.")
            elif warned and not moving and now - float(warned["v"]) >= 300:
                await service("switch", "turn_off", {"entity_id": c.iron_plug})
                rt.db.exec("DELETE FROM kv WHERE k IN (?,?)", (key_on, key_warn))
                said.append("Páječku jsem vypnul (nikdo u ní nebyl).")
    temp = by_id.get(c.workshop_temp, {}).get("value") if c.workshop_temp else None
    hum = by_id.get(c.workshop_humidity, {}).get("value") if c.workshop_humidity else None
    msg = climate_advice(temp, hum)
    if msg:
        key = "sx_climate_" + dt.date.fromtimestamp(now).isoformat()
        if not rt.db.one("SELECT v FROM kv WHERE k=?", (key,)):
            rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, "1"))
            said.append(msg)
    return said


def climate_advice(temp: float | None, hum: float | None) -> str:
    bits = []
    if temp is not None and temp < 12:
        bits.append(f"v dílně je {temp:.0f} °C – ABS/ASA se bude kroutit, lepidla a barvy pod 10 °C nevytvrdnou")
    if temp is not None and temp > 32:
        bits.append(f"v dílně je {temp:.0f} °C – PLA může měknout už v tiskárně, větrej")
    if hum is not None and hum > 60:
        bits.append(f"vlhkost {hum:.0f} % – filament zavři do boxu, nářadí může rezavět")
    return ("Dílna: " + "; ".join(bits) + ".") if bits else ""


# ------------------------------------------------------------------ (327) several printers
def queue_add(rt: Any, file: str, mat: str = "PLA", hours: float = 1, size: str = "") -> int:
    cur = db(rt).exec("INSERT INTO sx_queue (file, material, hours, size, printer, state, ts) VALUES (?,?,?,?,?,?,?)",
                      (file, material(mat), hours, size, "", "waiting", time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def fits(size: str, bed: list[float]) -> bool:
    nums = [float(x) for x in re.findall(r"[\d.]+", size or "")]
    if len(nums) < 2 or not bed:
        return True
    a = sorted(nums[:2])
    b = sorted(bed[:2])
    return a[0] <= b[0] and a[1] <= b[1] and (len(nums) < 3 or len(bed) < 3 or nums[2] <= bed[2])


def plan_queue(jobs: list[dict], printers: list[dict]) -> list[dict]:
    """Longest jobs first, each to the printer that can print it and is free soonest (materials + bed size)."""
    free = {p["name"]: float(p.get("busy_h", 0)) for p in printers}
    plan = []
    for j in sorted(jobs, key=lambda j: -float(j["hours"])):
        ok = [p for p in printers if (not p.get("materials") or j["material"] in [material(m) for m in p["materials"]])
              and fits(j.get("size", ""), p.get("bed", []))]
        if not ok:
            plan.append({**j, "printer": "", "start_h": None, "why": "žádná tiskárna na tenhle materiál / velikost"})
            continue
        best = min(ok, key=lambda p: free[p["name"]])
        start = free[best["name"]]
        free[best["name"]] = start + float(j["hours"])
        plan.append({**j, "printer": best["name"], "start_h": round(start, 1), "end_h": round(free[best["name"]], 1)})
    return plan


# ------------------------------------------------------------------ (328) calibration
CALIBRATION = {
    "esteps": ["Ohřej trysku na tiskovou teplotu.", "Na filamentu udělej značku 120 mm nad vstupem do extruderu.",
               "Pošli G-code: M83 a G1 E100 F100 (vytlačí 100 mm).", "Změř, kolik zbylo ke značce: vytlačeno = 120 − zbytek.",
               "Nová hodnota = stará × 100 / vytlačeno. Řekni mi stará a změřenou a spočítám ji.", "Ulož: M92 E<nová> a M500."],
    "flow": ["Vytiskni kostku s jednou stěnou (vase mode), šířka čáry třeba 0,45 mm.", "Posuvným měřítkem změř stěnu na 4 stranách.",
             "Nový průtok = starý × 0,45 / průměr změřené stěny.", "Zadej ho do profilu filamentu."],
    "pa": ["Vytiskni test Pressure Advance (Orca: Kalibrace → Pressure advance, PrusaSlicer: Linear advance test).",
           "Vyber čáru s nejostřejšími rohy a stejnou šířkou.", "Hodnotu zadej do profilu filamentu (Klipper: pressure_advance)."],
    "temp": ["Vytiskni teplotní věž (krok 5 °C v rozsahu filamentu).", "Vyber patro s nejlepšími převisy a bez vláken.",
             "Tu teplotu nastav do profilu."],
    "retraction": ["Vytiskni test retrakcí (věžičky).", "Zvyšuj délku po 0,2 mm (direct drive) nebo 0,5 mm (bowden), dokud vlásky zmizí.",
                   "Moc dlouhá retrakce ucpává – zastav se u první čisté hodnoty."],
    "first_layer": ["Vyrovnej podložku (mesh / auto bed leveling).", "Vytiskni čtverec první vrstvy.",
                    "Čáry se mají dotýkat a být lehce zploštělé; mezery = blíž (Z offset dolů), hřebínky = dál."],
}


def esteps(old: float, requested: float, extruded: float) -> float:
    if extruded <= 0:
        raise ValueError("Změřená délka musí být kladná.")
    return round(old * requested / extruded, 2)


def flow(old: float, expected: float, measured: float) -> float:
    if measured <= 0:
        raise ValueError("Změřená stěna musí být kladná.")
    return round(old * expected / measured, 3)


# ------------------------------------------------------------------ (329) laser and CNC
def laser_gcode(shape: str, w: float, h: float = 0, power_pct: float = 80, speed: float = 600, passes: int = 1,
                max_s: int = 1000) -> list[str]:
    """G-code for GRBL lasers (M4 dynamic power): a rectangle w×h or a circle of diameter w, from the origin."""
    s = int(max_s * max(0.0, min(power_pct, 100)) / 100)
    g = ["; JARVIS laser", "G21", "G90", "M5", "G0 X0 Y0"]
    for _ in range(max(1, passes)):
        if shape == "circle":
            r = w / 2
            g += [f"G0 X{w:.3f} Y{r:.3f}", f"M4 S{s}", f"G2 X{w:.3f} Y{r:.3f} I{-r:.3f} J0 F{speed:.0f}", "M5"]
        else:
            g += ["G0 X0 Y0", f"M4 S{s}", f"G1 X{w:.3f} Y0 F{speed:.0f}", f"G1 X{w:.3f} Y{h:.3f}", f"G1 X0 Y{h:.3f}", "G1 X0 Y0", "M5"]
    return g + ["G0 X0 Y0", "M2"]


def cnc_profile(shape: str, w: float, h: float, depth: float, step: float = 1.0, tool_d: float = 3.175, feed: float = 600,
                plunge: float = 150, safe_z: float = 5) -> list[str]:
    """A cut-out outside a rectangle / circle in depth steps (tool radius offset outside the shape)."""
    r = tool_d / 2
    g = ["; JARVIS CNC profile", "G21", "G90", f"G0 Z{safe_z}", "M3 S12000"]
    layers = max(1, math.ceil(depth / step))
    for i in range(1, layers + 1):
        z = -min(depth, i * step)
        if shape == "circle":
            rr = w / 2 + r
            g += [f"G0 X{w / 2 + rr:.3f} Y{w / 2:.3f}", f"G1 Z{z:.3f} F{plunge:.0f}", f"G2 X{w / 2 + rr:.3f} Y{w / 2:.3f} I{-rr:.3f} J0 F{feed:.0f}"]
        else:
            g += [f"G0 X{-r:.3f} Y{-r:.3f}", f"G1 Z{z:.3f} F{plunge:.0f}", f"G1 X{w + r:.3f} Y{-r:.3f} F{feed:.0f}",
                  f"G1 X{w + r:.3f} Y{h + r:.3f}", f"G1 X{-r:.3f} Y{h + r:.3f}", f"G1 X{-r:.3f} Y{-r:.3f}"]
    return g + [f"G0 Z{safe_z}", "M5", "G0 X0 Y0", "M2"]


def gcode_time(lines: list[str]) -> float:
    """Rough minutes: cut moves at their feed, rapids at 3000 mm/min."""
    x = y = z = 0.0
    feed = 600.0
    minutes = 0.0
    for ln in lines:
        m = re.match(r"\s*G([0-3])\b", ln)
        if not m:
            continue
        vals = {k: float(v) for k, v in re.findall(r"([XYZFIJ])(-?[\d.]+)", ln)}
        feed = vals.get("F", feed)
        nx, ny, nz = vals.get("X", x), vals.get("Y", y), vals.get("Z", z)
        if m.group(1) in "23" and "I" in vals:
            dist = 2 * math.pi * math.hypot(vals.get("I", 0), vals.get("J", 0))
        else:
            dist = math.dist((x, y, z), (nx, ny, nz))
        minutes += dist / (3000 if m.group(1) == "0" else max(feed, 1))
        x, y, z = nx, ny, nz
    return round(minutes, 1)


# ------------------------------------------------------------------ (330) tools, (332) lent things, (337) maintenance
def tool_add(rt: Any, name: str, place: str = "", qty: int = 1, note: str = "") -> int:
    cur = db(rt).exec("INSERT INTO sx_tools (name, place, qty, note) VALUES (?,?,?,?)", (name.strip(), place.strip(), qty, note))
    return int(getattr(cur, "lastrowid", 0) or 0)


def tool_where(rt: Any, what: str) -> list[dict]:
    w = [x[:5] for x in re.findall(r"[a-z0-9]+", fold(what)) if len(x) > 2]
    return [dict(r) for r in db(rt).all("SELECT * FROM sx_tools") if w and all(x in fold(r["name"] + " " + (r["note"] or "")) for x in w)]


def tools_missing(rt: Any, needed: list[str]) -> list[str]:
    return [n for n in needed if n.strip() and not tool_where(rt, n)]


def lend(rt: Any, item: str, person: str, back: str = "") -> int:
    cur = db(rt).exec("INSERT INTO sx_lent (item, person, since, back, reminded) VALUES (?,?,?,?,?)",
                      (item.strip(), person.strip(), dt.date.today().isoformat(), back, ""))
    return int(getattr(cur, "lastrowid", 0) or 0)


def returned(rt: Any, item: str) -> bool:
    rows = [r for r in db(rt).all("SELECT * FROM sx_lent") if fold(item)[:5] in fold(r["item"])]
    for r in rows:
        db(rt).exec("DELETE FROM sx_lent WHERE id=?", (r["id"],))
    return bool(rows)


def lent_due(rt: Any, today: dt.date, days: int = 30) -> list[dict]:
    out = []
    for r in db(rt).all("SELECT * FROM sx_lent"):
        since = dt.date.fromisoformat(r["since"])
        due = dt.date.fromisoformat(r["back"]) if r["back"] else since + dt.timedelta(days=days)
        if today >= due and r["reminded"] != today.isoformat():
            out.append({**dict(r), "days": (today - since).days})
    return out


def maint_add(rt: Any, tool: str, task: str, every_days: int, last: str = "") -> int:
    cur = db(rt).exec("INSERT INTO sx_maint (tool, task, every_days, last) VALUES (?,?,?,?)",
                      (tool, task, every_days, last or dt.date.today().isoformat()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def maint_due(rt: Any, today: dt.date) -> list[dict]:
    out = []
    for r in db(rt).all("SELECT * FROM sx_maint"):
        due = dt.date.fromisoformat(r["last"]) + dt.timedelta(days=int(r["every_days"]))
        if due <= today:
            out.append({**dict(r), "late": (today - due).days})
    return out


def maint_done(rt: Any, mid: int, today: dt.date | None = None) -> bool:
    cur = db(rt).exec("UPDATE sx_maint SET last=? WHERE id=?", ((today or dt.date.today()).isoformat(), mid))
    return bool(getattr(cur, "rowcount", 1))


MAINT_DEFAULTS = [("Aku baterie", "nabít na 40–60 % (skladování)", 90), ("3D tiskárna", "promazat vodicí tyče a šrouby osy Z", 60),
                  ("3D tiskárna", "zkontrolovat napnutí řemenů", 90), ("Kotoučová pila", "očistit a zkontrolovat kotouč", 60),
                  ("Vrtačka", "vyfoukat prach z motoru", 180), ("Kompresor", "vypustit vodu z nádrže", 14)]


# ------------------------------------------------------------------ (331) units
def parse_len(text: str) -> float | None:
    """'3/8"', '1 1/4 in', '25,4 mm', '2 cm' → millimetres."""
    t = (text or "").strip().lower().replace(",", ".")
    m = re.match(r"^(\d+)?\s*(\d+/\d+)?\s*(\"|in|inch|palc\w*|''|mm|cm|m)?$", t)
    if not m or not (m.group(1) or m.group(2)):
        try:
            return float(t)
        except ValueError:
            return None
    val = float(m.group(1) or 0) + (float(Fraction(m.group(2))) if m.group(2) else 0)
    unit = m.group(3) or "mm"
    return val * {"mm": 1, "cm": 10, "m": 1000}.get(unit, 25.4)


def inch_fraction(mm: float, denom: int = 64) -> str:
    inches = mm / 25.4
    whole = int(inches)
    frac = Fraction(round((inches - whole) * denom), denom)
    if frac == 1:
        whole, frac = whole + 1, Fraction(0)
    return (f"{whole} " if whole else "") + (f"{frac.numerator}/{frac.denominator}" if frac else "") + '"' if (whole or frac) else '0"'


# metric coarse: (pitch, tap drill), tightening torque Nm for 8.8 (dry, roughly 70 % of yield)
METRIC = {3: (0.5, 2.5, 1.2), 4: (0.7, 3.3, 2.9), 5: (0.8, 4.2, 5.7), 6: (1.0, 5.0, 9.9), 8: (1.25, 6.8, 24), 10: (1.5, 8.5, 48),
          12: (1.75, 10.2, 83), 14: (2.0, 12.0, 132), 16: (2.0, 14.0, 200), 20: (2.5, 17.5, 390)}
UNC = {"#4-40": 2.35, "#6-32": 2.85, "#8-32": 3.45, "#10-24": 3.8, "1/4-20": 5.1, "5/16-18": 6.6, "3/8-16": 8.0, "1/2-13": 10.8}


def thread_info(text: str) -> str:
    t = text.strip().upper().replace(" ", "")
    m = re.match(r"M(\d+)(?:X([\d.]+))?", t)
    if m and int(m.group(1)) in METRIC:
        d = int(m.group(1))
        pitch, drill, nm = METRIC[d]
        if m.group(2):
            pitch = float(m.group(2))
            drill = round(d - pitch, 2)
        return (f"M{d}: stoupání {pitch:g} mm, vrták pod závit {drill:g} mm, průchozí díra {d + (0.5 if d < 8 else 1):g} mm, "
                f"utahovací moment (8.8) asi {nm:g} Nm.")
    for k, v in UNC.items():
        if k.upper().replace(" ", "") == t:
            return f"{k} UNC: vrták pod závit {v:g} mm."
    return "Ten závit nemám v tabulce."


def torque(value: float, unit: str) -> dict:
    u = fold(unit).replace(" ", "")
    nm = value * {"nm": 1, "lbft": 1.35582, "ftlb": 1.35582, "lbin": 0.112985, "inlb": 0.112985, "kgm": 9.80665, "kgcm": 0.0980665}.get(u, 1)
    return {"Nm": round(nm, 2), "lb·ft": round(nm / 1.35582, 2), "lb·in": round(nm / 0.112985, 1), "kg·cm": round(nm / 0.0980665, 1)}


AWG = {10: 5.26, 12: 3.31, 14: 2.08, 16: 1.31, 18: 0.823, 20: 0.518, 22: 0.326, 24: 0.205, 26: 0.129, 28: 0.081}


# ------------------------------------------------------------------ (333) cutting plan
def cut_plan(stock: float, cuts: list[float], kerf: float = 3.0) -> dict:
    """1D: boards of length `stock`, pieces `cuts` (first fit, longest first) → boards with their pieces and the waste."""
    if any(c > stock for c in cuts):
        raise ValueError(f"Kus delší než deska ({max(cuts):g} > {stock:g}).")
    boards: list[list[float]] = []
    left: list[float] = []
    for c in sorted(cuts, reverse=True):
        for i, room in enumerate(left):
            need = c + (kerf if boards[i] else 0)
            if need <= room + 1e-9:
                boards[i].append(c)
                left[i] = room - need
                break
        else:
            boards.append([c])
            left.append(stock - c)
    used = sum(cuts)
    waste = len(boards) * stock - used
    return {"boards": [{"pieces": b, "rest": round(r, 1)} for b, r in zip(boards, left, strict=True)], "count": len(boards),
            "waste_pct": round(100 * waste / (len(boards) * stock), 1) if boards else 0}


def sheet_plan(sheet: tuple[float, float], parts: list[tuple[float, float]], kerf: float = 3.0, rotate: bool = True) -> dict:
    """2D: rectangles on sheets in shelves (tallest first) – simple and cuttable with straight saw cuts."""
    W, H = sheet
    items = []
    for w, h in parts:
        if rotate and (w > W or h > H) and h <= W and w <= H:
            w, h = h, w
        if rotate and w < h and h <= W:
            w, h = h, w                                       # lie flat → lower shelves
        if w > W or h > H:
            raise ValueError(f"Díl {w:g}×{h:g} se na desku {W:g}×{H:g} nevejde.")
        items.append((w, h))
    sheets: list[list[dict]] = []
    shelves: list[list[list[float]]] = []                      # per sheet: [y, height, x used]
    for w, h in sorted(items, key=lambda x: (-x[1], -x[0])):
        placed = False
        for si, sh in enumerate(shelves):
            for shelf in sh:
                if h <= shelf[1] and shelf[2] + w <= W:
                    sheets[si].append({"x": shelf[2], "y": shelf[0], "w": w, "h": h})
                    shelf[2] += w + kerf
                    placed = True
                    break
            if not placed:
                y = (sh[-1][0] + sh[-1][1] + kerf) if sh else 0
                if y + h <= H:
                    sh.append([y, h, w + kerf])
                    sheets[si].append({"x": 0, "y": y, "w": w, "h": h})
                    placed = True
            if placed:
                break
        if not placed:
            shelves.append([[0, h, w + kerf]])
            sheets.append([{"x": 0, "y": 0, "w": w, "h": h}])
    area = sum(w * h for w, h in items)
    return {"sheets": sheets, "count": len(sheets), "waste_pct": round(100 * (1 - area / (len(sheets) * W * H)), 1) if sheets else 0}


# ------------------------------------------------------------------ (334) paint
PAINTS = {"interier": (8, 2, "2 h mezi vrstvami"), "fasad": (6, 2, "4–6 h"), "lak": (12, 3, "4 h, přebrus 240"),
          "lazura": (12, 2, "12 h"), "email": (10, 2, "8–12 h"), "sprej": (2, 3, "10–20 min, po 1 h přetřít jen do 1 h nebo po 24 h"),
          "zakladni": (8, 1, "4 h")}


def paint_need(area_m2: float, kind: str = "interier", coats: int = 0, coverage: float = 0) -> dict:
    k = next((key for key in PAINTS if key in fold(kind)), "interier")
    cov, default_coats, drying = PAINTS[k]
    coats = coats or default_coats
    liters = area_m2 * coats / (coverage or cov) * 1.1          # +10 % on edges and the roller
    return {"liters": round(liters, 1), "coats": coats, "drying": drying,
            "text": f"{area_m2:g} m², {coats}× → asi {liters:.1f} l (vydatnost {coverage or cov:g} m²/l). Schnutí: {drying}."}


def wall_area(length: float, width: float, height: float, doors: int = 1, windows: int = 1, ceiling: bool = False) -> float:
    return round(2 * (length + width) * height - doors * 1.6 - windows * 1.5 + (length * width if ceiling else 0), 1)


# ------------------------------------------------------------------ (336) screws and anchors
WALLS = {
    "beton": ("nylonová hmoždinka (univerzální nebo rozpěrná), na těžké chemická kotva", "SDS / s příklepem, vrták do betonu"),
    "plna cihla": ("rozpěrná nylonová hmoždinka", "s příklepem, vrták do zdiva"),
    "dutinova cihla": ("dlouhá hmoždinka pro dutinové zdivo (nebo chemická kotva se sítkem)", "BEZ příklepu, vrták do zdiva"),
    "sadrokarton": ("kovová sádrokartonová (Molly) nebo motýlková hmoždinka; těžké věci jen do profilu", "bez příklepu, vrták do dřeva / kovu"),
    "porobeton": ("hmoždinka pro pórobeton (spirálová)", "bez příklepu, menší vrták než hmoždinka"),
    "drevo": ("bez hmoždinky – vrut do dřeva, předvrtej 70 % průměru vrutu", "vrták do dřeva"),
}


def anchor_advice(wall: str, load_kg: float = 5) -> str:
    w = fold(wall)
    key = next((k for k in WALLS if k.split()[0][:5] in w), "")
    if not key:
        return "Řekni, jaká je zeď: beton, plná cihla, děrovaná cihla, sádrokarton, pórobeton nebo dřevo."
    anchor, drill = WALLS[key]
    size = 6 if load_kg <= 10 else 8 if load_kg <= 25 else 10
    screw = {6: "4–5 mm", 8: "5–6 mm", 10: "6–8 mm"}[size]
    return (f"{key.capitalize()}: {anchor}. Vrtání: {drill}. Na {load_kg:g} kg hmoždinka {size} mm (vrták {size} mm), vrut {screw}, "
            f"délka vrutu = hmoždinka + tloušťka věci. Před vrtáním zkontroluj detektorem kabely a trubky.")


# ------------------------------------------------------------------ (338) split a model
def split_plan(model_dims: list[float], bed: list[float], margin: float = 5) -> dict:
    """How many pieces along X, Y, Z so each one fits the bed, and the cut positions."""
    counts = [max(1, math.ceil(d / max(b - margin, 1))) for d, b in zip(model_dims, bed, strict=True)]
    cuts = [[round(d * (i + 1) / n, 1) for i in range(n - 1)] for d, n in zip(model_dims, counts, strict=True)]
    return {"pieces": counts[0] * counts[1] * counts[2], "counts": counts, "cuts": cuts}


def split_scad(stl: Path, model_min: list[float], model_dims: list[float], counts: list[int], ix: int, iy: int, iz: int,
               pin_d: float = 4.0) -> str:
    """One piece: the model cut to its box; dowel holes (⌀ pin_d + 0.3) on the faces that touch the next piece."""
    sx, sy, sz = (model_dims[i] / counts[i] for i in range(3))
    x0, y0, z0 = model_min[0] + ix * sx, model_min[1] + iy * sy, model_min[2] + iz * sz
    holes = []
    hd = pin_d + 0.3
    if ix < counts[0] - 1:
        holes.append(f"translate([{x0 + sx - 6:.2f}, {y0 + sy / 2:.2f}, {z0 + sz / 2:.2f}]) rotate([0,90,0]) cylinder(d={hd}, h=12, $fn=32);")
    if iy < counts[1] - 1:
        holes.append(f"translate([{x0 + sx / 2:.2f}, {y0 + sy - 6:.2f}, {z0 + sz / 2:.2f}]) rotate([-90,0,0]) cylinder(d={hd}, h=12, $fn=32);")
    if ix > 0:
        holes.append(f"translate([{x0 - 6:.2f}, {y0 + sy / 2:.2f}, {z0 + sz / 2:.2f}]) rotate([0,90,0]) cylinder(d={hd}, h=12, $fn=32);")
    if iy > 0:
        holes.append(f"translate([{x0 + sx / 2:.2f}, {y0 - 6:.2f}, {z0 + sz / 2:.2f}]) rotate([-90,0,0]) cylinder(d={hd}, h=12, $fn=32);")
    return ("difference() {\n  intersection() {\n"
            f'    import("{stl.as_posix()}", convexity=10);\n'
            f"    translate([{x0:.2f}, {y0:.2f}, {z0:.2f}]) cube([{sx:.2f}, {sy:.2f}, {sz:.2f}]);\n  }}\n  "
            + "\n  ".join(holes) + "\n}\n")


# ------------------------------------------------------------------ (339) safety
SAFETY = [
    (r"laser", "Brýle přesně pro vlnovou délku laseru (např. OD4+ na 445 nm), odsávání kouře, nikdy neodcházej od běžícího laseru, "
               "hasicí přístroj na dosah. PVC a vinyl neřež (chlor)."),
    (r"bruska|brousi|flex|rozbrus", "Brýle nebo štít, chrániče sluchu, respirátor P2; rukavice ne u rotujícího kotouče; kryt nechej na místě."),
    (r"pryskyric|resin|sla|msla", "Nitrilové rukavice, větrání nebo odsávání, brýle; nevylévej zbytky do odpadu – vytvrď je na slunci."),
    (r"pajk|pajen|cin", "Odsávání výparů (tavidlo), brýle při stříhání vývodů, páječku odkládej do stojánku; olovnatá pájka = umýt ruce."),
    (r"cnc|frez", "Brýle, chrániče sluchu, upnutý materiál, ruce pryč od frézy, nouzové zastavení na dosah, odsávání prachu (MDF!)."),
    (r"pila|rezan|cirkular|kotouc", "Brýle, chrániče sluchu, rozpěrný klín, přítlačná hůlka u úzkých kusů, nikdy ruka v ose řezu."),
    (r"sprej|strikan|barv\w* stri|lak", "Respirátor s filtrem A2/P2, větrání, žádný otevřený oheň, brýle."),
    (r"svar|svarov", "Kukla se samozatmívacím filtrem, kožené rukavice, nehořlavý oděv, odsávání, hasicí přístroj."),
    (r"vrt", "Brýle, upnutý materiál, žádné volné rukávy ani rukavice u vrtačky, dlouhé vlasy svázat."),
]


def safety_for(text: str) -> list[str]:
    t = fold(text)
    return [rule for pat, rule in SAFETY if re.search(pat, t)]


# ------------------------------------------------------------------ (340) package for Printables
def printables_package(files: list[Path], out: Path, title: str, description: str = "", settings: dict | None = None,
                       license_: str = "CC BY 4.0") -> dict:
    """A ZIP with the models, a rendered picture of each STL and a description with the print settings – ready to upload
    on printables.com (they have no public upload API, so the last click is yours)."""
    s = settings or {}
    lines = [f"# {title}", "", description or "_Popis: k čemu to je a jak to sestavit._", "", "## Nastavení tisku", "",
             f"- Materiál: {s.get('material', 'PLA')}", f"- Výška vrstvy: {s.get('layer', '0,2 mm')}",
             f"- Výplň: {s.get('infill', '15 %')}", f"- Podpěry: {s.get('supports', 'ne')}", "", f"Licence: {license_}", ""]
    pics = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"modely/{f.name}")
            if f.suffix.lower() == ".stl":
                try:
                    tris = stl_read(f)
                    z.writestr(f"obrazky/{f.stem}.png", thumbnail(tris, 640))
                    d = dims(tris)
                    lines.insert(-2, f"- {f.name}: {d[0]:g} × {d[1]:g} × {d[2]:g} mm, {volume_cm3(tris):.1f} cm³")
                    pics += 1
                except (ValueError, OSError):
                    pass
        z.writestr("POPIS.md", "\n".join(lines))
    return {"path": str(out), "models": len(files), "pictures": pics}


# ------------------------------------------------------------------ daily
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    if not due_today(rt, "sx_daily", "10:00", now):
        return said
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("sx_daily", now.date().isoformat()))
    for r in lent_due(rt, now.date(), cfg(rt).lend_days):
        db(rt).exec("UPDATE sx_lent SET reminded=? WHERE id=?", (now.date().isoformat(), r["id"]))
        said.append(f"{r['person']} má půjčenou věc „{r['item']}“ už {r['days']} dní.")
    due = maint_due(rt, now.date())
    if due:
        said.append("Údržba: " + "; ".join(f"{d['tool']} – {d['task']}" for d in due[:4]) + ".")
    low = reorder_list(rt, cfg(rt).spool_low_g)
    if low and now.weekday() == 0:
        said.append("Dochází filament: " + ", ".join(f"{s['material']} {s['color']} ({s['left_g']:.0f} g)".strip() for s in low[:5]) + ".")
    for t in said:
        rt.notify("Dílna", t)
    return said
