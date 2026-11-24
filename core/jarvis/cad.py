"""3.15 Dílna – text → CAD (návrh C2): a part described in words becomes a parametric model you can keep changing by voice.

"Udělej L-držák 40 mm široký s dírami na šrouby M4" → the template and its parameters; "o 5 mm širší", "stěna 3 mm",
"díry 5 mm", "o 10 % větší", "vrať to" → a new version. Every part is a list of primitives (boxes and cylinders, each
added or cut away). From that come:
- the exact OpenSCAD source (and, when OpenSCAD is installed, the exact STL rendered by it),
- a preview mesh made here without anything installed: the signed distance of the shape sampled on a grid and turned
  into triangles (surface nets) – edges come out slightly rounded (about half the grid step), fine for a look and for
  most prints; the exact file is the .scad.
Versions are kept in the database, so any earlier one can come back.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import paths

Prim = dict[str, Any]    # {"kind": "box", "min": [x,y,z], "max": [x,y,z], "cut": bool} | {"kind": "cyl", "c": [x,y,z], "r", "h", "axis", "cut"}

# ------------------------------------------------------------------------------------------ templates
TEMPLATES: dict[str, dict[str, Any]] = {
    "box": {"label": "krabička", "words": ("krabic", "krabick", "box", "pouzdr", "skrin"),
            "params": {"w": 60.0, "d": 40.0, "h": 30.0, "t": 2.0, "lid": 1.0}},
    "bracket": {"label": "L-držák", "words": ("drzak", "uhelnik", "bracket", "konzol"),
                "params": {"w": 40.0, "d": 30.0, "h": 30.0, "t": 4.0, "hole": 4.3, "holes": 2.0}},
    "plate": {"label": "deska s dírami", "words": ("desk", "plech", "podlozk", "plate", "panel", "montazni"),
              "params": {"w": 80.0, "d": 50.0, "t": 3.0, "hole": 3.2, "holes": 4.0, "margin": 5.0}},
    "spacer": {"label": "distanční sloupek", "words": ("sloupek", "distancn", "spacer", "rozpern", "trubk", "trubic", "pouzdro na"),
               "params": {"od": 8.0, "id": 3.2, "h": 10.0}},
    "hook": {"label": "háček", "words": ("hacek", "hak", "vesak", "hook"),
             "params": {"w": 15.0, "h": 50.0, "t": 4.0, "d": 20.0, "hole": 4.0}},
    "knob": {"label": "knoflík / kolečko", "words": ("knofl", "kolecko", "knob", "otocn"),
             "params": {"od": 30.0, "h": 15.0, "id": 6.2, "grip": 12.0}},
}
PARAM_LABEL = {"w": "šířka", "d": "hloubka", "h": "výška", "t": "tloušťka stěny", "hole": "průměr děr", "holes": "počet děr",
               "margin": "okraj děr", "od": "vnější průměr", "id": "vnitřní průměr", "lid": "víko", "grip": "počet žlábků"}
SCREW = {"m2": 2.4, "m2.5": 2.9, "m3": 3.4, "m4": 4.5, "m5": 5.5, "m6": 6.6, "m8": 8.8}   # clearance holes


def fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def guess_template(text: str) -> str:
    t = fold(text)
    for key, tpl in TEMPLATES.items():
        if any(w in t for w in tpl["words"]):
            return key
    return "box"


def _box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float, cut: bool = False) -> Prim:
    return {"kind": "box", "min": [min(x0, x1), min(y0, y1), min(z0, z1)], "max": [max(x0, x1), max(y0, y1), max(z0, z1)], "cut": cut}


def _cyl(x: float, y: float, z: float, r: float, h: float, axis: str = "z", cut: bool = False) -> Prim:
    """A cylinder starting at (x, y, z) going h along the axis."""
    return {"kind": "cyl", "c": [x, y, z], "r": r, "h": h, "axis": axis, "cut": cut}


def build(template: str, p: dict[str, float]) -> list[Prim]:
    """Template + parameters → primitives (mm, the part stands on z = 0)."""
    g = lambda k: float(p.get(k, TEMPLATES[template]["params"].get(k, 0)))   # noqa: E731
    if template == "box":
        w, d, h, t = g("w"), g("d"), g("h"), g("t")
        out = [_box(0, 0, 0, w, d, h), _box(t, t, t, w - t, d - t, h + 1, cut=True)]
        if g("lid") >= 0.5:                                         # the lid next to it: a plate and a lip that fits inside
            ox, gap = w + 8, 0.3
            out += [_box(ox, 0, 0, ox + w, d, t), _box(ox + t + gap, t + gap, t, ox + w - t - gap, d - t - gap, t + 3),
                    _box(ox + 2 * t + gap, 2 * t + gap, t, ox + w - 2 * t - gap, d - 2 * t - gap, t + 4, cut=True)]
        return out
    if template == "bracket":
        w, d, h, t, r, n = g("w"), g("d"), g("h"), g("t"), g("hole") / 2, max(0, int(round(g("holes"))))
        out = [_box(0, 0, 0, w, d, t), _box(0, 0, 0, w, t, h)]
        for i in range(n):                                          # holes along the width, in both legs
            x = w * (i + 1) / (n + 1)
            out += [_cyl(x, t + (d - t) / 2, -1, r, t + 2, cut=True), _cyl(x, -1, t + (h - t) / 2, r, t + 2, axis="y", cut=True)]
        return out
    if template == "plate":
        w, d, t, r, m, n = g("w"), g("d"), g("t"), g("hole") / 2, g("margin"), max(0, int(round(g("holes"))))
        out = [_box(0, 0, 0, w, d, t)]
        pts = [(m, m), (w - m, d - m), (w - m, m), (m, d - m)]
        if n > 4:                                                    # more holes: along both long edges
            k = (n + 1) // 2
            pts = [(m + (w - 2 * m) * i / max(1, k - 1), y) for y in (m, d - m) for i in range(k)][:n]
        for x, y in pts[:n]:
            out.append(_cyl(x, y, -1, r, t + 2, cut=True))
        return out
    if template == "spacer":
        od, idd, h = g("od"), g("id"), g("h")
        out = [_cyl(od / 2, od / 2, 0, od / 2, h)]
        if idd > 0:
            out.append(_cyl(od / 2, od / 2, -1, idd / 2, h + 2, cut=True))
        return out
    if template == "hook":
        w, h, t, d, r = g("w"), g("h"), g("t"), g("d"), g("hole") / 2
        out = [_box(0, 0, 0, w, t, h), _box(0, 0, 0, w, d, t), _box(0, d - t, 0, w, d, t + max(6.0, d * 0.4))]
        if r > 0:
            out.append(_cyl(w / 2, -1, h - max(8.0, r * 3), r, t + 2, axis="y", cut=True))
        return out
    if template == "knob":
        od, h, idd, n = g("od"), g("h"), g("id"), max(0, int(round(g("grip"))))
        R = od / 2
        out = [_cyl(R, R, 0, R, h)]
        for i in range(n):                                          # grip grooves around the edge
            a = 2 * math.pi * i / max(1, n)
            out.append(_cyl(R + R * math.cos(a), R + R * math.sin(a), -1, max(1.0, od * 0.06), h + 2, cut=True))
        if idd > 0:
            out.append(_cyl(R, R, -1, idd / 2, h * 0.8 + 1, cut=True))
        return out
    raise ValueError(f"Neznámá šablona {template}")


def check(template: str, p: dict[str, float]) -> str:
    """'' when the parameters make a printable part, else what is wrong (in Czech)."""
    g = lambda k: float(p.get(k, TEMPLATES[template]["params"].get(k, 0)))   # noqa: E731
    for k, v in p.items():
        if k not in ("lid",) and v < 0:
            return f"{PARAM_LABEL.get(k, k)} nemůže být záporná"
    if "t" in TEMPLATES[template]["params"] and g("t") < 0.8:
        return "stěna pod 0,8 mm se nevytiskne"
    if template == "box" and (g("w") <= 2 * g("t") + 1 or g("d") <= 2 * g("t") + 1 or g("h") <= g("t") + 1):
        return "krabička je na tak silnou stěnu moc malá"
    if template in ("spacer", "knob") and g("id") >= g("od") - 1:
        return "vnitřní průměr musí být menší než vnější"
    if template == "plate" and g("hole") >= min(g("w"), g("d")) / 2:
        return "díry jsou na desku moc velké"
    if max(g(k) for k in TEMPLATES[template]["params"] if k in ("w", "d", "h", "od")) > 1000:
        return "díl přes metr – opravdu? Napiš rozměry v mm"
    return ""


# ------------------------------------------------------------------------------------------ voice edits
_NUM = r"(\d+(?:[.,]\d+)?)"
_WORDS = [  # (regex on folded text, param key, sign for "o X mm …")
    (r"sirs|sirok|sirk", "w", 1), (r"uzs|uzk", "w", -1),
    (r"delsi|hloubk|hlubs|hlubok|delk", "d", 1), (r"kratsi", "d", -1),
    (r"vyss|vysok|vysk", "h", 1), (r"nizs|nizk", "h", -1),
    (r"tencs|tenci|slabs", "t", -1), (r"tluss|silnej|silnejs|tloust|sten", "t", 1),
    (r"vnitrn\w* prumer|otvor\w* uprostred|osk|hridel", "id", 1),
    (r"prumer|tlustsi sloup", "od", 1),
    (r"pocet der|der\b.*\bkus|(\d+) der\b|(\d+) dir", "holes", 1),
    (r"dir|der|otvor|sroub", "hole", 1),
    (r"okraj", "margin", 1), (r"zlab|ryh", "grip", 1),
]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_edit(text: str, template: str, params: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Czech words → the new parameters and what changed ("šířka 40 → 45 mm"). Nothing understood → ([], unchanged)."""
    t = fold(text).replace("milimetr", "mm").replace("centimetr", "cm")
    p = dict(params)
    keys = TEMPLATES[template]["params"]
    changes: list[str] = []

    def setp(k: str, v: float) -> None:
        if k not in keys:
            return
        old = p.get(k, keys[k])
        v = round(max(0.0, v), 2)
        if k in ("holes", "grip"):
            v = float(int(round(v)))
        if v != old:
            p[k] = v
            unit = "" if k in ("holes", "grip", "lid") else " mm"
            changes.append(f"{PARAM_LABEL.get(k, k)} {old:g} → {v:g}{unit}")

    # "o 10 % větší / menší" scales every length
    m = re.search(_NUM + r"\s*(%|procent)\w*\s*(vets|mens)", t)
    if m:
        f = 1 + _num(m.group(1)) / 100 * (1 if m.group(3) == "vets" else -1)
        for k in keys:
            if k not in ("holes", "grip", "lid", "t", "hole", "id"):
                setp(k, p.get(k, keys[k]) * f)
        return p, changes
    m = re.search(r"(dvakrat|2x|dvojnasob)\w*\s*(vets|mens)", t)
    if m:
        f = 2.0 if m.group(2) == "vets" else 0.5
        for k in keys:
            if k not in ("holes", "grip", "lid", "t", "hole", "id"):
                setp(k, p.get(k, keys[k]) * f)
        return p, changes
    # screws: "na šrouby M4" → the clearance hole
    m = re.search(r"\bm\s?(2[.,]5|\d)\b", t)
    if m and "hole" in keys:
        setp("hole", SCREW.get("m" + m.group(1).replace(",", "."), _num(m.group(1)) * 1.1))
    if "id" in keys and m and "hole" not in keys:
        setp("id", SCREW.get("m" + m.group(1).replace(",", "."), _num(m.group(1)) * 1.1))
    if m:
        t = t.replace(m.group(0), " ")
    # lid on / off
    if "lid" in keys and re.search(r"bez vik", t):
        setp("lid", 0)
    elif "lid" in keys and re.search(r"(s |pridej |udelej )vik", t):
        setp("lid", 1)
    # "N děr / dírami"
    m = re.search(r"(\d+)\s*(der|dir|otvor)", t)
    if m and "holes" in keys:
        setp("holes", _num(m.group(1)))
        t = t.replace(m.group(0), " ")
    for part in re.split(r"(?<!\d),|,(?!\d)|;|\ba\b|\bpak\b", t):
        part = part.strip()
        if not part:
            continue
        rel = re.search(r"\bo\s*" + _NUM + r"\s*(mm|cm)?", part)          # "o 5 mm širší"
        ab = re.search(_NUM + r"\s*(mm|cm)?", part)                      # "šířka 50", "stěna 3 mm"
        for rx, k, sign in _WORDS:
            if k not in keys or not re.search(rx, part):
                continue
            if k == "holes" and not re.search(r"pocet|kus", part):
                continue
            if rel:
                v = _num(rel.group(1)) * (10 if rel.group(2) == "cm" else 1)
                s = sign if sign else 1
                setp(k, p.get(k, keys[k]) + s * v)
            elif ab:
                v = _num(ab.group(1)) * (10 if ab.group(2) == "cm" else 1)
                setp(k, v)
            break
    return p, changes


# ------------------------------------------------------------------------------------------ geometry: signed distance
def _sd_box(P: np.ndarray, pr: Prim) -> np.ndarray:
    lo, hi = np.array(pr["min"], dtype=np.float32), np.array(pr["max"], dtype=np.float32)
    c, half = (lo + hi) / 2, (hi - lo) / 2
    q = np.abs(P - c) - half
    out = np.linalg.norm(np.maximum(q, 0), axis=-1)
    return out + np.minimum(q.max(axis=-1), 0)


def _sd_cyl(P: np.ndarray, pr: Prim) -> np.ndarray:
    ax = "xyz".index(pr["axis"])
    others = [i for i in range(3) if i != ax]
    c = np.array(pr["c"], dtype=np.float32)
    radial = np.sqrt((P[..., others[0]] - c[others[0]]) ** 2 + (P[..., others[1]] - c[others[1]]) ** 2) - pr["r"]
    along = np.abs(P[..., ax] - (c[ax] + pr["h"] / 2)) - pr["h"] / 2
    q = np.stack([radial, along], axis=-1)
    return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(axis=-1), 0)


def sdf(prims: list[Prim], P: np.ndarray) -> np.ndarray:
    """Negative inside the part: the union of what is added, minus the union of what is cut."""
    add = [(_sd_box if pr["kind"] == "box" else _sd_cyl)(P, pr) for pr in prims if not pr.get("cut")]
    cut = [(_sd_box if pr["kind"] == "box" else _sd_cyl)(P, pr) for pr in prims if pr.get("cut")]
    d = np.minimum.reduce(add) if add else np.full(P.shape[:-1], 1e3, dtype=np.float32)
    if cut:
        d = np.maximum(d, -np.minimum.reduce(cut))
    return d


def bounds(prims: list[Prim]) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for pr in prims:
        if pr.get("cut"):
            continue
        if pr["kind"] == "box":
            a, b = np.array(pr["min"]), np.array(pr["max"])
        else:
            ax = "xyz".index(pr["axis"])
            a = np.array(pr["c"], dtype=float) - pr["r"]
            b = np.array(pr["c"], dtype=float) + pr["r"]
            a[ax], b[ax] = pr["c"][ax], pr["c"][ax] + pr["h"]
        lo, hi = np.minimum(lo, a), np.maximum(hi, b)
    return lo, hi


def mesh(prims: list[Prim], max_cells: int = 2_500_000, min_step: float = 0.25, feature: float = 0) -> tuple[np.ndarray, np.ndarray, float]:
    """Surface nets: vertices (N×3) and triangles (M×3 indices) of the part, and the grid step in mm (feature = the
    thinnest wall, which a hollow shape does not show in its primitives)."""
    lo, hi = bounds(prims)
    size = hi - lo
    feats = [pr["r"] * 2 for pr in prims if pr["kind"] == "cyl"] + \
            [float(min(np.array(pr["max"]) - np.array(pr["min"]))) for pr in prims if pr["kind"] == "box"]
    thin = max(0.5, min(feats + ([feature] if feature > 0 else []))) if feats else 1.0
    budget = float(np.cbrt(np.prod(size + 4) / max_cells))           # the finest step the cell budget allows
    step = max(min_step, budget, min(thin / 3, float(size.max()) / 90))
    lo, hi = lo - 2 * step, hi + 2 * step
    axes = [np.arange(lo[i], hi[i] + step, step, dtype=np.float32) for i in range(3)]
    X, Y, Z = np.meshgrid(*axes, indexing="ij")
    F = sdf(prims, np.stack([X, Y, Z], axis=-1)).astype(np.float32)
    inside = F < 0
    nx, ny, nz = F.shape
    corners = [(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if sum(abs(corners[a][q] - corners[b][q]) for q in range(3)) == 1]
    cell = (slice(0, nx - 1), slice(0, ny - 1), slice(0, nz - 1))

    def at(off: tuple[int, int, int]) -> tuple[slice, slice, slice]:
        return tuple(slice(o, n - 1 + o) for o, n in zip(off, (nx, ny, nz)))   # type: ignore[return-value]

    acc = np.zeros((nx - 1, ny - 1, nz - 1, 3), dtype=np.float32)
    cnt = np.zeros((nx - 1, ny - 1, nz - 1), dtype=np.float32)
    base = np.stack(np.meshgrid(*[a[:-1] for a in axes], indexing="ij"), axis=-1)
    for a, b in edges:
        fa, fb = F[at(corners[a])], F[at(corners[b])]
        cross = (fa < 0) != (fb < 0)
        tt = np.where(cross, fa / np.where(fa - fb == 0, 1, fa - fb), 0)
        ca, cb = np.array(corners[a], dtype=np.float32), np.array(corners[b], dtype=np.float32)
        pos = base + (ca + (cb - ca) * tt[..., None]) * step
        acc += np.where(cross[..., None], pos, 0)
        cnt += cross
    active = cnt > 0
    vidx = -np.ones(cnt.shape, dtype=np.int64)
    vidx[active] = np.arange(int(active.sum()))
    verts = acc[active] / cnt[active][:, None]
    _ = cell
    tris: list[np.ndarray] = []
    for ax in range(3):
        o1, o2 = [q for q in range(3) if q != ax]
        sl = [slice(None)] * 3
        sl_next = [slice(None)] * 3
        sl[ax], sl_next[ax] = slice(0, -1), slice(1, None)
        s0, s1 = inside[tuple(sl)], inside[tuple(sl_next)]
        flip = s0 & ~s1                    # inside → outside along +axis
        same = s0 == s1
        # interior edges only (need cells on both sides in o1 and o2)
        idx = np.argwhere(~same)
        idx = idx[(idx[:, o1] >= 1) & (idx[:, o2] >= 1) & (idx[:, o1] < inside.shape[o1] - 1) & (idx[:, o2] < inside.shape[o2] - 1)]
        if not len(idx):
            continue
        fl = flip[tuple(idx.T)]

        def cv(d1: int, d2: int) -> np.ndarray:
            c = idx.copy()
            c[:, o1] -= d1
            c[:, o2] -= d2
            return vidx[tuple(c.T)]

        q = np.stack([cv(1, 1), cv(0, 1), cv(0, 0), cv(1, 0)], axis=1)
        # orientation: (o1, o2, ax) right-handed → this order faces +ax; swap where the outside is at −ax
        right = (o1, o2, ax) in ((0, 1, 2), (1, 2, 0), (2, 0, 1))
        want_pos = fl if right else ~fl
        q = np.where(want_pos[:, None], q, q[:, ::-1])
        tris.append(np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]]))
    faces = np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)
    faces = faces[(faces >= 0).all(axis=1)]
    return verts.astype(np.float32), faces, float(step)


def volume(verts: np.ndarray, faces: np.ndarray) -> float:
    v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6)


def stl_bytes(verts: np.ndarray, faces: np.ndarray, name: str = "jarvis") -> bytes:
    v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 0, n / np.where(ln == 0, 1, ln), 0)
    rec = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, np.stack([v0, v1, v2], axis=1)
    head = name.encode("ascii", "replace")[:80].ljust(80, b" ")
    return head + struct.pack("<I", len(faces)) + rec.tobytes()


# ------------------------------------------------------------------------------------------ OpenSCAD
def scad(prims: list[Prim], title: str = "", params: dict[str, float] | None = None) -> str:
    def one(pr: Prim) -> str:
        if pr["kind"] == "box":
            a, b = pr["min"], pr["max"]
            return f"translate([{a[0]:g},{a[1]:g},{a[2]:g}]) cube([{b[0] - a[0]:g},{b[1] - a[1]:g},{b[2] - a[2]:g}]);"
        c, rot = pr["c"], {"z": "", "x": "rotate([0,90,0]) ", "y": "rotate([-90,0,0]) "}[pr["axis"]]
        return f"translate([{c[0]:g},{c[1]:g},{c[2]:g}]) {rot}cylinder(h={pr['h']:g}, r={pr['r']:g}, $fn=96);"

    head = [f"// {title} – vytvořil JARVIS {time.strftime('%Y-%m-%d %H:%M')}"]
    if params:
        head.append("// parametry: " + ", ".join(f"{PARAM_LABEL.get(k, k)} {v:g}" for k, v in params.items()))
    add = "\n    ".join(one(p) for p in prims if not p.get("cut"))
    cut = "\n    ".join(one(p) for p in prims if p.get("cut"))
    body = f"difference() {{\n  union() {{\n    {add}\n  }}\n  union() {{\n    {cut}\n  }}\n}}" if cut else f"union() {{\n    {add}\n}}"
    return "\n".join(head) + "\n" + body + "\n"


def openscad() -> str | None:
    found = shutil.which("openscad") or shutil.which("openscad.com")
    if found:
        return found
    for p in (r"C:\Program Files\OpenSCAD\openscad.com", r"C:\Program Files\OpenSCAD\openscad.exe"):
        if Path(p).exists():
            return p
    return None


def render_exact(scad_path: Path, stl_path: Path, runner=subprocess.run) -> bool:
    exe = openscad()
    if not exe:
        return False
    try:
        r = runner([exe, "-o", str(stl_path), str(scad_path)], capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and stl_path.exists() and stl_path.stat().st_size > 84
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------------------------------ the parts (versions in the DB)
SQL = """CREATE TABLE IF NOT EXISTS cad_parts (name TEXT PRIMARY KEY, template TEXT, params TEXT, version INTEGER, project TEXT,
           updated REAL);
         CREATE TABLE IF NOT EXISTS cad_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, version INTEGER, params TEXT,
           change TEXT, ts REAL);"""


def _db(rt):
    rt.db.conn.executescript(SQL)
    return rt.db


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")[:40] or "dil"


def get(rt, name: str) -> dict | None:
    r = _db(rt).one("SELECT * FROM cad_parts WHERE name=?", (name.strip(),))
    if not r:
        r = _db(rt).one("SELECT * FROM cad_parts WHERE name LIKE ? ORDER BY updated DESC", (f"%{name.strip()}%",))
    if not r:
        return None
    d = dict(r)
    d["params"] = json.loads(d["params"] or "{}")
    return d


def latest(rt) -> dict | None:
    r = _db(rt).one("SELECT name FROM cad_parts ORDER BY updated DESC LIMIT 1")
    return get(rt, r["name"]) if r else None


def parts(rt) -> list[dict]:
    return [dict(r) | {"params": json.loads(r["params"] or "{}")} for r in _db(rt).all("SELECT * FROM cad_parts ORDER BY updated DESC")]


def save(rt, name: str, template: str, params: dict[str, float], change: str, project: str = "") -> dict:
    db = _db(rt)
    old = get(rt, name)
    version = (old["version"] + 1) if old and old["name"] == name else 1
    db.exec("INSERT OR REPLACE INTO cad_parts (name, template, params, version, project, updated) VALUES (?,?,?,?,?,?)",
            (name, template, json.dumps(params), version, project or (old or {}).get("project", ""), time.time()))
    db.exec("INSERT INTO cad_versions (name, version, params, change, ts) VALUES (?,?,?,?,?)",
            (name, version, json.dumps(params), change[:300], time.time()))
    return get(rt, name) or {}


def history(rt, name: str) -> list[dict]:
    return [dict(r) | {"params": json.loads(r["params"])} for r in
            _db(rt).all("SELECT * FROM cad_versions WHERE name=? ORDER BY version", (name,))]


def undo(rt, name: str) -> dict | None:
    """Back to the previous version (as a new version, so nothing is lost)."""
    h = history(rt, name)
    part = get(rt, name)
    if not part or len(h) < 2:
        return None
    prev = h[-2]
    return save(rt, part["name"], part["template"], prev["params"], f"zpět na verzi {prev['version']}")


def export(rt, part: dict) -> dict:
    """The part's files: .scad (exact), .stl (exact via OpenSCAD when installed, else the preview mesh) and the numbers."""
    tpl, params = part["template"], part["params"]
    prims = build(tpl, params)
    out = paths.sub("workshop") / "cad"
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"{slug(part['name'])}-v{part['version']}"
    scad_p, stl_p = base.with_suffix(".scad"), base.with_suffix(".stl")
    scad_p.write_text(scad(prims, f"{part['name']} ({TEMPLATES[tpl]['label']}), verze {part['version']}", params), encoding="utf-8")
    verts, faces, step = mesh(prims, feature=min([v for k, v in params.items() if k in ('t', 'hole')] or [0]))
    exact = render_exact(scad_p, stl_p)
    if not exact:
        stl_p.write_bytes(stl_bytes(verts, faces, part["name"]))
    lo, hi = bounds(prims)
    vol = abs(volume(verts, faces)) / 1000                                     # cm³
    return {"scad": str(scad_p), "stl": str(stl_p), "exact": exact, "step_mm": round(step, 2),
            "size_mm": [round(float(x), 1) for x in (hi - lo)], "volume_cm3": round(vol, 1),
            "grams_pla": round(vol * 1.24, 1), "triangles": int(len(faces))}


def describe(part: dict) -> str:
    tpl = TEMPLATES[part["template"]]
    ps = ", ".join(f"{PARAM_LABEL.get(k, k)} {v:g}{'' if k in ('holes', 'grip', 'lid') else ' mm'}"
                   for k, v in part["params"].items() if not (k == "lid" and v >= 0.5))
    return f"{part['name']} – {tpl['label']}, verze {part['version']}: {ps}"
