"""3.15 Dílna – 3D model v HUD (návrh C1): STL / OBJ / GLB / 3MF / STEP se ukáže jako hologram, jde točit rukou, gesty
i hlasem a „rozložit“ na díly (rozložený pohled).

Soubor se zkopíruje do složky modelů (HUD čte jen odtud, přes /api/workshop/model/<jméno>). STEP neumí prohlížeč
přečíst sám – převede ho FreeCAD (když je nainstalovaný) na OBJ, každé těleso jako samostatný díl, takže i STEP sestava
jde rozložit.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import paths

log = logging.getLogger("jarvis.models3d")

FORMATS = {".stl": "stl", ".obj": "obj", ".glb": "glb", ".3mf": "3mf", ".step": "step", ".stp": "step"}
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\.(stl|obj|glb|3mf|step)$")
MAX_MB = 200

FREECAD_SCRIPT = r'''
import os, Part, MeshPart
src, dst = os.environ["JARVIS_STEP_IN"], os.environ["JARVIS_OBJ_OUT"]
shape = Part.read(src)
solids = shape.Solids or [shape]
with open(dst, "w") as f:
    base = 1
    for i, s in enumerate(solids):
        m = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.1, AngularDeflection=0.35)
        pts, facets = m.Topology
        f.write("o dil_%d\n" % (i + 1))
        for p in pts:
            f.write("v %.4f %.4f %.4f\n" % (p.x, p.y, p.z))
        for a, b, c in facets:
            f.write("f %d %d %d\n" % (a + base, b + base, c + base))
        base += len(pts)
'''


def models_dir() -> Path:
    d = paths.sub("workshop") / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))


def safe_name(stem: str, data_hash: str, ext: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(stem)).strip("-")[:48] or "model"
    return f"{slug}-{data_hash[:8]}.{ext}"


def freecad() -> str | None:
    for name in ("freecadcmd", "FreeCADCmd", "freecad.cmd"):
        found = shutil.which(name)
        if found:
            return found
    for root in (r"C:\Program Files", r"C:\Program Files (x86)"):
        base = Path(root)
        if base.exists():
            for d in sorted(base.glob("FreeCAD*"), reverse=True):
                exe = d / "bin" / "FreeCADCmd.exe"
                if exe.exists():
                    return str(exe)
    return None


def step_to_obj(src: Path, dst: Path, runner=subprocess.run) -> str:
    """'' on success, else why not."""
    exe = freecad()
    if not exe:
        return "STEP umím ukázat jen s nainstalovaným FreeCADem (zdarma, freecad.org) – nebo ho vyexportuj jako STL / 3MF / GLB"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "jarvis_step.py"
        script.write_text(FREECAD_SCRIPT, encoding="utf-8")
        env = dict(os.environ, JARVIS_STEP_IN=str(src), JARVIS_OBJ_OUT=str(dst))
        try:
            r = runner([exe, str(script)], capture_output=True, text=True, timeout=300, env=env)
        except (OSError, subprocess.SubprocessError) as e:
            return f"FreeCAD selhal: {e}"
        if not dst.exists() or dst.stat().st_size < 20:
            return "FreeCAD soubor nepřevedl: " + ((r.stderr or r.stdout or "")[-200:] or "bez chyby, ale bez výsledku")
    return ""


def add(src: Path, title: str = "") -> dict:
    """Copy (or convert) a model into the HUD's folder → {name, url, format, parts_hint} or {error}."""
    src = Path(src).expanduser()
    if not src.exists() or not src.is_file():
        return {"error": f"Soubor {src} neexistuje."}
    fmt = FORMATS.get(src.suffix.lower())
    if not fmt:
        return {"error": "Umím STL, OBJ, GLB, 3MF a STEP."}
    if src.stat().st_size > MAX_MB * 2**20:
        return {"error": f"Model má přes {MAX_MB} MB – to by HUD nezvládl plynule."}
    h = hashlib.sha1(src.read_bytes()).hexdigest()
    stem = title or src.stem
    if fmt == "step" and freecad():                  # FreeCAD on the PC: exact, every body its own part
        name = safe_name(stem, h, "obj")
        dst = models_dir() / name
        err = "" if dst.exists() else step_to_obj(src, dst)
        if not err:
            return {"name": name, "url": f"/api/workshop/model/{name}", "format": "obj", "title": title or src.stem}
        log.info("FreeCAD STEP → OBJ: %s (the HUD reads it itself)", err)
    if fmt == "step":                                # 3.17 no FreeCAD: the HUD reads the STEP itself (occt-import-js)
        name = safe_name(stem, h, "step")
        dst = models_dir() / name
        if not dst.exists():
            shutil.copy2(src, dst)
    else:
        name = safe_name(stem, h, fmt)
        dst = models_dir() / name
        if not dst.exists():
            shutil.copy2(src, dst)
    return {"name": name, "url": f"/api/workshop/model/{name}", "format": fmt, "title": title or src.stem}


def path_of(name: str) -> Path | None:
    """The file for /api/workshop/model/<name> – only names made here, only inside the models folder."""
    if not NAME_OK.match(name or ""):
        return None
    p = (models_dir() / name).resolve()
    if p.parent != models_dir().resolve() or not p.exists():
        return None
    return p


def show(rt, info: dict, explode: bool = False) -> None:
    """Open the HUD with the model."""
    hook = getattr(rt, "ui_hook", None)
    if hook:
        hook("hud")
    rt.bus.publish("hud_model", url=info["url"], format=info["format"], title=info.get("title", ""), explode=explode)
