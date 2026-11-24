"""3.18 Kontrola před tiskem (návrh 8): before a model goes to the printer JARVIS looks at it – does it fit the bed,
how much hangs in the air (supports?), how big is the part that touches the bed (will it come off? brim?), and roughly
how much filament and time it takes. The lines appear right in the print confirmation; a part that does not fit is
never sent. Estimates only – the slicer knows the exact numbers.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

BEDS = {"x1": (256, 256, 256), "p1": (256, 256, 256), "a1": (256, 256, 256), "a1mini": (180, 180, 180)}
DEFAULT_BED = (220, 220, 250)
OVERHANG_DEG = 45.0
PLA_G_CM3 = 1.24
MAX_TRIANGLES = 3_000_000


def bed(rt: Any) -> tuple[float, float, float]:
    c = rt.cfg.workshop
    own = list(getattr(c, "bed_mm", []) or [])
    if len(own) == 3 and all(float(x) > 0 for x in own):
        return float(own[0]), float(own[1]), float(own[2])
    if c.printer in ("bambu_lan", "bambu_ha"):
        return BEDS.get(getattr(c, "bambu_model", "auto"), BEDS["p1"])
    return DEFAULT_BED


def read_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Binary or ASCII STL → (vertices (N, 3), faces (M, 3)); every triangle keeps its own three vertices."""
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 0 < n <= MAX_TRIANGLES and 84 + 50 * n == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            verts = rec["v"].reshape(-1, 3).astype(np.float64)
            return verts, np.arange(len(verts)).reshape(-1, 3)
    text = data.decode("latin-1", "replace")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums or len(nums) % 3 or len(nums) // 3 > MAX_TRIANGLES:
        raise ValueError("soubor není čitelné STL")
    verts = np.array(nums, dtype=np.float64)
    return verts, np.arange(len(verts)).reshape(-1, 3)


def read_3mf(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """An unsliced 3MF (the model, not G-code) → its meshes together (build transforms are ignored)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".model")]
        if not names:
            raise ValueError("3MF nemá model")
        allv, allf, off = [], [], 0
        for n in names:
            xml = z.read(n).decode("utf-8", "replace")
            v = np.array(re.findall(r'<vertex[^>]*\bx="([^"]+)"[^>]*\by="([^"]+)"[^>]*\bz="([^"]+)"', xml), dtype=np.float64)
            f = np.array(re.findall(r'<triangle[^>]*\bv1="(\d+)"[^>]*\bv2="(\d+)"[^>]*\bv3="(\d+)"', xml), dtype=np.int64)
            if len(v) and len(f):
                allv.append(v)
                allf.append(f + off)
                off += len(v)
        if not allv:
            raise ValueError("3MF nemá žádné těleso")
        return np.vstack(allv), np.vstack(allf)


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = Path(path).read_bytes()
    if path.suffix.lower() == ".3mf":
        return read_3mf(data)
    return read_stl(data)


def analyze(verts: np.ndarray, faces: np.ndarray, bed_mm: tuple[float, float, float] = DEFAULT_BED, fast: bool = False) -> dict:
    """fast = a Bambu-class printer (about twice the volume per second)."""
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    size = hi - lo
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 1e-12
    area = area2 / 2
    nz = np.where(ok, n[:, 2] / np.where(ok, area2, 1), 0)
    zmin = tri[:, :, 2].min(axis=1)
    on_bed = (tri[:, :, 2].max(axis=1) <= lo[2] + 0.2) & (nz < -0.99)
    down = nz < -np.cos(np.radians(OVERHANG_DEG))
    overhang = down & ~on_bed & (zmin > lo[2] + 0.2)
    total = float(area.sum()) or 1.0
    overhang_pct = round(100 * float(area[overhang].sum()) / total, 1)
    contact = float(area[on_bed].sum())
    vol = abs(float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6) / 1000   # cm³
    shell = min(vol, total / 100 * 0.12)                     # 1.2 mm walls
    printed = shell + max(0.0, vol - shell) * 0.15           # 15 % infill
    grams = round(printed * PLA_G_CM3, 1)
    mm3_s = 15.0 if fast else 8.0
    layers = size[2] / 0.2
    minutes = int(round((printed * 1000 / mm3_s + layers * 3) / 60))
    fits = bool(np.all(size <= np.array(bed_mm) + 1e-6))
    turn = not fits and bool(np.all(np.sort(size) <= np.sort(np.array(bed_mm)) + 1e-6))
    warnings: list[str] = []
    if not fits:
        warnings.append("nevejde se na podložku" + (" – otočením by se vešel" if turn else ""))
    if overhang_pct >= 8:
        warnings.append(f"převisy {overhang_pct:.0f} % plochy → zapni podpory")
    elif overhang_pct >= 2:
        warnings.append(f"malé převisy ({overhang_pct:.0f} %) – obvykle bez podpor")
    footprint = float(size[0] * size[1]) or 1.0
    if contact < 25 or contact / footprint < 0.05:
        warnings.append("na podložce leží jen malá plocha – přidej brim, ať se neodlepí")
    if size[2] > 4 * max(1.0, min(size[0], size[1])):
        warnings.append("vysoký a tenký – může se při tisku kývat")
    return {"size_mm": [round(float(x), 1) for x in size], "fits": fits, "turn_fits": turn, "overhang_pct": overhang_pct,
            "contact_mm2": round(contact, 1), "volume_cm3": round(vol, 1), "grams": grams, "minutes": minutes,
            "triangles": int(len(faces)), "warnings": warnings}


def lines(res: dict) -> list[str]:
    s = res["size_mm"]
    m = res["minutes"]
    t = f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"
    out = [f"Rozměr {s[0]:g} × {s[1]:g} × {s[2]:g} mm – {'vejde se' if res['fits'] else 'NEVEJDE SE'} na podložku",
           f"Odhad: asi {res['grams']:g} g filamentu, {t} (přesně řekne slicer)"]
    out += [f"⚠ {w}" for w in res["warnings"] if not w.startswith("nevejde")]
    return out


def check_file(rt: Any, path: Path) -> dict | None:
    """None for a file that is already G-code / a sliced 3MF (nothing to look at)."""
    p = Path(path)
    if p.suffix.lower() not in (".stl", ".3mf") or p.name.lower().endswith(".gcode.3mf"):
        return None
    if p.suffix.lower() == ".3mf":
        try:
            with zipfile.ZipFile(p) as z:
                if any(n.startswith("Metadata/plate_") and n.endswith(".gcode") for n in z.namelist()):
                    return None                       # already sliced (Bambu Studio / Orca)
        except zipfile.BadZipFile:
            return None
    v, f = load(p)
    return analyze(v, f, bed(rt), fast=rt.cfg.workshop.printer in ("bambu_lan", "bambu_ha"))
