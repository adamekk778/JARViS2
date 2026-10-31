"""Native bridges to creative tools and Czech public transport (catalogue 116 / 117 / 118 / 784).

* Blender – its own command line in the background (`blender -b file.blend --python-expr …`): scene contents as JSON,
  a rendered frame, an export (glTF / FBX / OBJ / STL). A script written by the AI runs only after confirmation.
* Unity – the project read from its files (version, scenes, packages, scripts) and the editor in batch mode to run
  its tests (`-runTests`, NUnit XML results).
* Roblox – Open Cloud with the user's own API key (in the keyring): publish a place file, read DataStore entries; a
  Rojo project to keep the Luau code in files.
* Public transport – a connection search on IDOS opened ready (no public API exists), departures in Prague from the
  PID Golemio API with the user's free key.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
Runner = Callable[..., subprocess.CompletedProcess]


def _run(cmd: list[str], timeout: int, runner: Runner | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    return (runner or subprocess.run)(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=timeout, cwd=cwd, creationflags=NO_WINDOW)


# ---------------------------------------------------------------- Blender
def find_blender(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    if (w := shutil.which("blender")):
        return w
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation"]
    found = sorted((p for r in roots if r.is_dir() for p in r.glob("Blender*/blender.exe")), reverse=True)
    steam = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam/steamapps/common/Blender/blender.exe"
    return str(found[0]) if found else (str(steam) if steam.is_file() else None)


INFO_SCRIPT = r'''
import bpy, json, sys
sc = bpy.context.scene
objs = [{"name": o.name, "type": o.type, "location": [round(v, 3) for v in o.location],
         "dims": [round(v, 3) for v in o.dimensions], "verts": len(o.data.vertices) if o.type == "MESH" else 0,
         "materials": [m.name for m in getattr(o.data, "materials", []) if m]} for o in sc.objects]
print("JARVIS_JSON" + json.dumps({"scene": sc.name, "frames": [sc.frame_start, sc.frame_end], "fps": sc.render.fps,
      "engine": sc.render.engine, "resolution": [sc.render.resolution_x, sc.render.resolution_y],
      "camera": sc.camera.name if sc.camera else None, "objects": objs}))
'''
EXPORTS = {"glb": "bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB')",
           "gltf": "bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLTF_SEPARATE')",
           "fbx": "bpy.ops.export_scene.fbx(filepath=OUT)",
           "obj": "bpy.ops.wm.obj_export(filepath=OUT)",
           "stl": "bpy.ops.wm.stl_export(filepath=OUT)"}


def _json_line(out: str) -> dict:
    for ln in out.splitlines():
        if ln.startswith("JARVIS_JSON"):
            return json.loads(ln[len("JARVIS_JSON"):])
    raise RuntimeError("Blender nevrátil výsledek: " + (out.strip().splitlines() or ["(nic)"])[-1][:200])


def blender_cmd(exe: str, blend: str | None, expr: str | None = None, script: str | None = None, extra: list[str] | None = None) -> list[str]:
    cmd = [exe, "-b"] + ([blend] if blend else []) + ["--factory-startup"]
    if expr:
        cmd += ["--python-expr", expr]
    if script:
        cmd += ["--python", script]
    return cmd + (extra or [])


def blender_info(exe: str, blend: str, runner: Runner | None = None) -> dict:
    r = _run(blender_cmd(exe, blend, expr=INFO_SCRIPT), 180, runner)
    return _json_line(r.stdout + r.stderr)


def blender_render(exe: str, blend: str, out_png: str, frame: int = 1, runner: Runner | None = None) -> str:
    base = str(Path(out_png).with_suffix(""))
    r = _run(blender_cmd(exe, blend, extra=["-o", base + "_####", "-F", "PNG", "-f", str(frame)]), 1800, runner)
    produced = Path(f"{base}_{frame:04d}.png")
    if produced.exists():
        produced.replace(out_png)
        return out_png
    raise RuntimeError("Render se nepovedl: " + (r.stdout + r.stderr).strip()[-300:])


def blender_export(exe: str, blend: str, out: str, fmt: str, runner: Runner | None = None) -> str:
    if fmt not in EXPORTS:
        raise ValueError(f"Formát {fmt} neumím – mám {', '.join(EXPORTS)}.")
    expr = f"import bpy\nOUT = {out!r}\n{EXPORTS[fmt]}\nprint('JARVIS_JSON{{\"ok\": true}}')"
    r = _run(blender_cmd(exe, blend, expr=expr), 600, runner)
    _json_line(r.stdout + r.stderr)
    return out


def blender_script(exe: str, blend: str | None, code: str, runner: Runner | None = None) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
    try:
        r = _run(blender_cmd(exe, blend, script=f.name), 1800, runner)
        return (r.stdout + r.stderr)[-4000:]
    finally:
        os.unlink(f.name)


# ---------------------------------------------------------------- Unity
def unity_project(root: Path) -> dict:
    ver_file = root / "ProjectSettings" / "ProjectVersion.txt"
    if not ver_file.is_file():
        raise ValueError(f"{root} není projekt Unity (chybí ProjectSettings/ProjectVersion.txt).")
    m = re.search(r"m_EditorVersion:\s*(\S+)", ver_file.read_text(encoding="utf-8", errors="replace"))
    scenes = []
    ebs = root / "ProjectSettings" / "EditorBuildSettings.asset"
    if ebs.is_file():
        scenes = re.findall(r"path:\s*(\S+\.unity)", ebs.read_text(encoding="utf-8", errors="replace"))
    packages = {}
    man = root / "Packages" / "manifest.json"
    if man.is_file():
        try:
            packages = json.loads(man.read_text(encoding="utf-8")).get("dependencies", {})
        except ValueError:
            pass
    assets = root / "Assets"
    scripts = [p for p in assets.rglob("*.cs")] if assets.is_dir() else []
    tests = [p for p in scripts if re.search(r"\[(Test|UnityTest)\]", p.read_text(encoding="utf-8", errors="replace"))]
    return {"version": m.group(1) if m else "?", "scenes": scenes, "packages": packages,
            "scripts": len(scripts), "test_files": len(tests),
            "all_scenes": sorted(str(p.relative_to(root)).replace("\\", "/") for p in assets.rglob("*.unity")) if assets.is_dir() else []}


def find_unity(version: str, configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    hub = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Unity" / "Hub" / "Editor"
    exact = hub / version / "Editor" / "Unity.exe"
    if exact.is_file():
        return str(exact)
    others = sorted(hub.glob("*/Editor/Unity.exe"), reverse=True) if hub.is_dir() else []
    return str(others[0]) if others else shutil.which("Unity")


def parse_nunit(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    cases = root.iter("test-case")
    failed = []
    total = passed = 0
    for c in cases:
        total += 1
        if c.get("result") == "Passed":
            passed += 1
        elif c.get("result") == "Failed":
            msg = c.find("./failure/message")
            failed.append({"name": c.get("fullname") or c.get("name"), "message": (msg.text or "").strip()[:300] if msg is not None else ""})
    return {"total": total, "passed": passed, "failed": failed, "skipped": total - passed - len(failed)}


def unity_tests(exe: str, root: Path, platform: str = "EditMode", runner: Runner | None = None) -> dict:
    out = Path(tempfile.gettempdir()) / f"jarvis-unity-{os.getpid()}.xml"
    log = out.with_suffix(".log")
    r = _run([exe, "-batchmode", "-nographics", "-projectPath", str(root), "-runTests", "-testPlatform", platform,
              "-testResults", str(out), "-logFile", str(log)], 3600, runner)
    if not out.is_file():
        tail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.is_file() else (r.stdout + r.stderr)[-600:]
        raise RuntimeError("Unity testy nevytvořily výsledky. Konec logu: " + tail)
    try:
        return parse_nunit(out.read_text(encoding="utf-8", errors="replace"))
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------- Roblox Open Cloud
OPEN_CLOUD = "https://apis.roblox.com"


async def roblox_publish(key: str, universe: int, place: int, file: Path, publish: bool = True, transport=None) -> dict:
    import httpx

    if not key:
        raise RuntimeError("chybí API klíč Roblox Open Cloud (create.roblox.com → Credentials, oprávnění universe-places:write)")
    ctype = "application/xml" if file.suffix.lower() == ".rbxlx" else "application/octet-stream"
    async with httpx.AsyncClient(transport=transport, timeout=120) as c:
        r = await c.post(f"{OPEN_CLOUD}/universes/v1/{int(universe)}/places/{int(place)}/versions",
                         params={"versionType": "Published" if publish else "Saved"},
                         headers={"x-api-key": key, "Content-Type": ctype}, content=file.read_bytes())
    if r.status_code in (401, 403):
        raise RuntimeError("Roblox odmítl klíč – zkontroluj oprávnění universe-places:write a IP adresu klíče")
    if r.status_code != 200:
        raise RuntimeError(f"Roblox: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


async def roblox_datastore(key: str, universe: int, store: str, entry: str = "", scope: str = "global", transport=None) -> Any:
    import httpx

    if not key:
        raise RuntimeError("chybí API klíč Roblox Open Cloud (oprávnění universe-datastores.objects:read)")
    base = f"{OPEN_CLOUD}/datastores/v1/universes/{int(universe)}/standard-datastores/datastore/entries"
    params = {"datastoreName": store, "scope": scope}
    async with httpx.AsyncClient(transport=transport, timeout=30) as c:
        if entry:
            r = await c.get(base + "/entry", params={**params, "entryKey": entry}, headers={"x-api-key": key})
        else:
            r = await c.get(base, params={**params, "limit": 50}, headers={"x-api-key": key})
    if r.status_code != 200:
        raise RuntimeError(f"Roblox DataStore: HTTP {r.status_code} {r.text[:200]}")
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def rojo_project(folder: Path, name: str) -> list[Path]:
    """A Rojo project: Luau code in files (git, your editor), synced into Roblox Studio with the Rojo plugin."""
    files = {
        "default.project.json": json.dumps({"name": name, "tree": {"$className": "DataModel",
            "ReplicatedStorage": {"Shared": {"$path": "src/shared"}},
            "ServerScriptService": {"Server": {"$path": "src/server"}},
            "StarterPlayer": {"StarterPlayerScripts": {"Client": {"$path": "src/client"}}}}}, indent=2),
        "src/shared/Hello.luau": "return function()\n\treturn \"Ahoj z Rojo\"\nend\n",
        "src/server/init.server.luau": "local hello = require(game.ReplicatedStorage.Shared.Hello)\nprint(hello())\n",
        "src/client/init.client.luau": "print(\"Klient běží\")\n",
        "README.md": f"# {name}\n\n1. Nainstaluj Rojo (rojo.space) a plugin Rojo v Roblox Studiu.\n2. Tady spusť `rojo serve`.\n"
                     "3. V Studiu klikni v pluginu Rojo na Connect – kód ze složky src se propíše do hry.\n",
    }
    out = []
    for rel, text in files.items():
        p = folder / rel
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out


# ---------------------------------------------------------------- Czech public transport
def idos_link(src: str, dst: str, when: dt.datetime | None = None, via: str = "", by: str = "vlakyautobusymhdvse") -> str:
    """IDOS has no public API, so JARVIS opens the search already filled in."""
    q = {"f": src, "t": dst}
    if via:
        q["v"] = via
    if when:
        q["date"] = when.strftime("%d.%m.%Y")
        q["time"] = when.strftime("%H:%M")
    return f"https://idos.cz/{by}/spojeni/vysledky/?" + urllib.parse.urlencode(q)


async def pid_departures(key: str, stop: str, limit: int = 8, transport=None) -> list[dict]:
    """Departures from a Prague stop (PID, Golemio API – free key at api.golemio.cz)."""
    import httpx

    if not key:
        raise RuntimeError("na odjezdy MHD v Praze je potřeba bezplatný klíč z api.golemio.cz")
    async with httpx.AsyncClient(transport=transport, timeout=20) as c:
        r = await c.get("https://api.golemio.cz/v2/pid/departureboards", headers={"X-Access-Token": key},
                        params={"names": stop, "limit": limit, "minutesAfter": 90})
    if r.status_code != 200:
        raise RuntimeError(f"Golemio: HTTP {r.status_code} {r.text[:200]}")
    out = []
    for d in r.json().get("departures", []):
        ts = (d.get("departure_timestamp") or {})
        out.append({"line": (d.get("route") or {}).get("short_name", "?"), "to": (d.get("trip") or {}).get("headsign", ""),
                    "time": (ts.get("predicted") or ts.get("scheduled") or "")[11:16],
                    "delay_min": round(((d.get("delay") or {}).get("seconds") or 0) / 60),
                    "platform": (d.get("stop") or {}).get("platform_code") or ""})
    return out
