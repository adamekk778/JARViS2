"""Blender, Unity, Roblox and Czech public transport by voice (bridges.py)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from pathlib import Path
from typing import Annotated, Literal

from .. import paths, secrets
from .base import ToolResult, tool
from .files import resolve


def _blender(ctx) -> str | ToolResult:
    from ..bridges import find_blender

    exe = find_blender(getattr(ctx.cfg.integrations, "blender_path", "") if hasattr(ctx.cfg, "integrations") else "")
    return exe or ToolResult(False, "Blender jsem nenašel. Nainstaluj ho z blender.org (nebo Steam), pak to zkus znovu.")


def _blend(path: str) -> Path | ToolResult:
    p = resolve(path) if path else None
    if p is None or not p.is_file() or p.suffix.lower() != ".blend":
        return ToolResult(False, f"Soubor {path} není scéna Blenderu (.blend).")
    return p


@tool("blender_scene", "Co je ve scéně Blenderu (.blend): objekty, polygony, materiály, kamera, snímky, rozlišení – přímo "
      "z Blenderu na pozadí, bez otevírání okna.", category="design", perm="apps")
async def blender_scene(ctx, file: str) -> ToolResult:
    from .. import bridges

    exe, blend = _blender(ctx), _blend(file)
    for x in (exe, blend):
        if isinstance(x, ToolResult):
            return x
    try:
        info = await asyncio.to_thread(bridges.blender_info, exe, str(blend))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    meshes = [o for o in info["objects"] if o["type"] == "MESH"]
    return ToolResult(True, f"Scéna {info['scene']}: {len(info['objects'])} objektů ({len(meshes)} sítí, "
                      f"{sum(o['verts'] for o in meshes):,} vrcholů), kamera {info['camera'] or 'žádná'}, snímky "
                      f"{info['frames'][0]}–{info['frames'][1]} při {info['fps']} fps, {info['resolution'][0]}×{info['resolution'][1]}, "
                      f"render {info['engine']}.".replace(",", " "), data=info)


@tool("blender_render", "Vyrenderuje snímek scény Blenderu (.blend) na pozadí a pošle obrázek.", category="design", perm="apps")
async def blender_render(ctx, file: str, frame: int = 1) -> ToolResult:
    from .. import bridges

    exe, blend = _blender(ctx), _blend(file)
    for x in (exe, blend):
        if isinstance(x, ToolResult):
            return x
    out = paths.sub("blender") / f"{blend.stem}-{frame:04d}-{time.strftime('%H%M%S')}.png"
    try:
        await asyncio.to_thread(bridges.blender_render, exe, str(blend), str(out), int(frame))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    return ToolResult(True, f"Snímek {frame} vyrenderovaný.", attachments=[str(out)])


@tool("blender_export", "Vyexportuje scénu Blenderu do glTF/GLB (web, Unity, Godot), FBX, OBJ nebo STL (3D tisk).",
      category="design", perm="apps")
async def blender_export(ctx, file: str, format: Literal["glb", "gltf", "fbx", "obj", "stl"] = "glb") -> ToolResult:  # noqa: A002
    from .. import bridges

    exe, blend = _blender(ctx), _blend(file)
    for x in (exe, blend):
        if isinstance(x, ToolResult):
            return x
    out = paths.sub("blender") / f"{blend.stem}.{format}"
    try:
        await asyncio.to_thread(bridges.blender_export, exe, str(blend), str(out), format)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    return ToolResult(True, f"Exportováno do {format.upper()}.", attachments=[str(out)])


@tool("blender_run", "Spustí v Blenderu (na pozadí) Python skript – vytvoření modelu, úprava scény, hromadné změny. "
      "Skript vždy ukáže a spustí až po potvrzení.", category="design", perm="shell", danger=True,
      details=lambda a, ctx=None: [f"Blender spustí tento skript nad {a.get('file') or 'prázdnou scénou'}:", (a.get("script") or "")[:1500]])
async def blender_run(ctx, script: str, file: str = "") -> ToolResult:
    from .. import bridges

    exe = _blender(ctx)
    if isinstance(exe, ToolResult):
        return exe
    blend = None
    if file:
        blend = _blend(file)
        if isinstance(blend, ToolResult):
            return blend
    out = await asyncio.to_thread(bridges.blender_script, exe, str(blend) if blend else None, script)
    return ToolResult("Traceback" not in out, "Skript doběhl." if "Traceback" not in out else "Skript skončil chybou.",
                      data={"output": out[-2000:]})


@tool("unity_project", "Přehled projektu Unity: verze editoru, scény v sestavení, balíčky, počet skriptů a testů.",
      category="hry", perm="files_read")
async def unity_project(ctx, project: str) -> ToolResult:
    from .. import bridges

    root = resolve(project)
    try:
        info = await asyncio.to_thread(bridges.unity_project, root)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Unity {info['version']}: {len(info['scenes'])} scén v sestavení ({len(info['all_scenes'])} celkem), "
                      f"{len(info['packages'])} balíčků, {info['scripts']} skriptů, {info['test_files']} souborů s testy.", data=info)


@tool("unity_tests", "Spustí testy projektu Unity (editor na pozadí, EditMode nebo PlayMode) a řekne, co neprošlo.",
      category="hry", perm="shell")
async def unity_tests(ctx, project: str, platform: Literal["EditMode", "PlayMode"] = "EditMode") -> ToolResult:
    from .. import bridges

    root = resolve(project)
    try:
        info = bridges.unity_project(root)
    except ValueError as e:
        return ToolResult(False, str(e))
    exe = bridges.find_unity(info["version"])
    if not exe:
        return ToolResult(False, f"Editor Unity {info['version']} jsem nenašel (Unity Hub).")
    try:
        r = await asyncio.to_thread(bridges.unity_tests, exe, root, platform)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:400])
    msg = f"Testy {platform}: {r['passed']}/{r['total']} prošlo"
    if r["failed"]:
        msg += ". Neprošly: " + "; ".join(f"{f['name']} ({f['message'][:80]})" for f in r["failed"][:5])
    return ToolResult(not r["failed"], msg + ".", data=r)


@tool("roblox_publish", "Nahraje soubor místa (.rbxl / .rbxlx) do Robloxu přes Open Cloud (tvůj API klíč) – jako "
      "zveřejněnou nebo jen uloženou verzi.", category="hry", perm="network", danger=True,
      details=lambda a, ctx=None: [f"Do Robloxu (hra {a.get('universe_id')}, místo {a.get('place_id')}) se nahraje {a.get('file')} "
                                   + ("a hned zveřejní – hráči ho uvidí." if a.get("publish", True) else "jako uložená verze.")])
async def roblox_publish(ctx, file: str, universe_id: int, place_id: int, publish: bool = True) -> ToolResult:
    from .. import bridges

    p = resolve(file)
    if not p.is_file() or p.suffix.lower() not in (".rbxl", ".rbxlx"):
        return ToolResult(False, "Potřebuju soubor místa Roblox (.rbxl nebo .rbxlx).")
    try:
        r = await bridges.roblox_publish(secrets.get("roblox"), universe_id, place_id, p, publish)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    return ToolResult(True, f"Nahráno, verze {r.get('versionNumber', '?')}" + (" je zveřejněná." if publish else " je uložená."), data=r)


@tool("roblox_datastore", "Přečte DataStore hry na Robloxu (Open Cloud): seznam klíčů, nebo hodnotu jednoho klíče.",
      category="hry", perm="network")
async def roblox_datastore(ctx, universe_id: int, datastore: str, key: str = "") -> ToolResult:
    from .. import bridges

    try:
        r = await bridges.roblox_datastore(secrets.get("roblox"), universe_id, datastore, key)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    if key:
        return ToolResult(True, f"{key} = {str(r)[:400]}", data=r)
    keys = [k.get("key") for k in (r or {}).get("keys", [])]
    return ToolResult(True, f"{len(keys)} klíčů: {', '.join(keys[:20])}", data=r)


@tool("roblox_rojo", "Založí projekt Rojo: kód hry Roblox (Luau) v souborech, které se propíšou do Roblox Studia.",
      category="hry", perm="files_write")
async def roblox_rojo(ctx, folder: str, name: str = "MojeHra") -> ToolResult:
    from .. import bridges

    root = resolve(folder)
    root.mkdir(parents=True, exist_ok=True)
    made = bridges.rojo_project(root, name)
    return ToolResult(True, f"Projekt Rojo připraven ({len(made)} souborů). Spusť v té složce „rojo serve“ a v Roblox Studiu "
                      "klikni v pluginu Rojo na Connect.", data=[str(p) for p in made])


@tool("transit_connection", "Najde spojení vlakem, autobusem a MHD v ČR (IDOS) – otevře hotové vyhledávání. Na "
      "„jak se dostanu z Brna do Prahy v 8“, „spojení na zítra ráno“.", category="info", perm="network")
async def transit_connection(ctx, src: Annotated[str, "odkud"], dst: Annotated[str, "kam"], when: str = "", via: str = "",
                             open_browser: bool = True) -> ToolResult:
    from .. import bridges
    from .control_tools import _when

    ts = _when(when) if when else None
    url = bridges.idos_link(src, dst, dt.datetime.fromtimestamp(ts) if ts else None, via)
    if open_browser:
        try:
            await asyncio.to_thread(ctx.platform.open_url, url)
        except Exception:  # noqa: BLE001
            pass
    return ToolResult(True, f"Spojení {src} → {dst}" + (f" ({when})" if when else "") + " jsem otevřel v IDOS.", data={"url": url})


@tool("transit_departures", "Odjezdy z pražské zastávky (PID) v reálném čase – linka, směr, čas, zpoždění.",
      category="info", perm="network")
async def transit_departures(ctx, stop: str, limit: int = 8) -> ToolResult:
    from .. import bridges

    try:
        deps = await bridges.pid_departures(secrets.get("golemio"), stop, max(1, min(limit, 20)))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e)[:300])
    if not deps:
        return ToolResult(True, f"Ze zastávky {stop} teď nic nejede (nebo ji neznám).")
    return ToolResult(True, "; ".join(f"{d['line']} → {d['to']} {d['time']}" + (f" (+{d['delay_min']} min)" if d["delay_min"] > 0 else "")
                                      for d in deps), data=deps)
