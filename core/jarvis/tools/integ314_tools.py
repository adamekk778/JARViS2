"""3.14 tools: OBS Studio, highlights, signed skill packages (návrhy 102–105)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from .. import paths
from .base import ToolResult, tool


async def _obs(ctx, fn):
    from .. import obs

    try:
        return await fn(obs.from_config(ctx))
    except obs.ObsError as e:
        return ToolResult(False, str(e))


@tool("obs_scene", "OBS Studio: bez názvu vypíše scény a aktuální; s názvem přepne na scénu (stačí část názvu).", category="média")
async def obs_scene(ctx, name: str = "") -> ToolResult:
    async def go(o):
        if not name:
            s = await o.scenes()
            return ToolResult(True, f"Teď: {s['current']}. Scény: {', '.join(x for x in s['scenes'] if x)}.", data=s)
        return ToolResult(True, f"Scéna: {await o.set_scene(name)}.")
    return await _obs(ctx, go)


@tool("obs_record", "OBS Studio: nahrávání – start, stop, toggle, pause, resume, status.", category="média")
async def obs_record(ctx, action: Literal["start", "stop", "toggle", "pause", "resume", "status"] = "toggle") -> ToolResult:
    async def go(o):
        d = await o.record(action)
        if action == "status":
            return ToolResult(True, "Nahrává se." if d.get("outputActive") else "Nenahrává se.", data=d)
        if action == "stop" and d.get("outputPath"):
            return ToolResult(True, f"Nahrávání uloženo: {d['outputPath']}", data=d)
        return ToolResult(True, {"start": "Nahrávám.", "toggle": "Přepnuto.", "pause": "Pozastaveno.", "resume": "Pokračuju."}.get(action, "Hotovo."))
    return await _obs(ctx, go)


@tool("obs_stream", "OBS Studio: vysílání (stream) – start, stop, toggle, status.", danger_if=lambda a: a.get("action") in ("start", "toggle"),
      category="média", details=lambda a: ["OBS začne vysílat živě (stream) na tvůj nastavený kanál."])
async def obs_stream(ctx, action: Literal["start", "stop", "toggle", "status"] = "status") -> ToolResult:
    async def go(o):
        d = await o.stream(action)
        if action == "status":
            return ToolResult(True, "Vysílá se." if d.get("outputActive") else "Nevysílá se.", data=d)
        return ToolResult(True, {"start": "Vysílám.", "stop": "Vysílání ukončeno.", "toggle": "Přepnuto."}[action])
    return await _obs(ctx, go)


@tool("save_highlight", "Uloží posledních pár desítek vteřin hry nebo obrazovky jako klip („ulož to“, „to bylo dobrý, ulož "
      "to“) – přes záznam posledních chvil v OBS (replay buffer); když neběží, zapne ho.", category="hry")
async def save_highlight(ctx) -> ToolResult:
    async def go(o):
        path = await o.save_replay()
        try:
            from ..notchplus import live

            live(ctx, "clip", "Klip uložen", "film-strip", progress=1.0)
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"Uloženo{': ' + path if path else ''}.", data={"path": path})
    return await _obs(ctx, go)


# ---------- signed skill packages ----------
def _inspect_details(a: dict, ctx=None) -> list[str]:
    from .. import skillpack

    try:
        info = skillpack.inspect(Path(str(a.get("path", ""))).read_bytes(), getattr(getattr(ctx, "cfg", None), "tools", None)
                                 and ctx.cfg.tools.trusted_publishers)
    except (OSError, ValueError) as e:
        return [f"Balíček nejde přečíst: {e}"]
    m = info["manifest"]
    who = "tvoje vlastní" if info["mine"] else ("důvěryhodný autor" if info["trusted"] else "NEZNÁMÝ autor")
    lines = [f"Dovednost: {m.get('name')} {m.get('version')} – {m.get('description', '')}",
             f"Autor: {m.get('author') or '?'} ({who}, otisk {info['fingerprint']})",
             f"Oprávnění: {', '.join(m.get('permissions') or []) or 'žádná'}",
             "Podpis: v pořádku" if info["valid"] else f"PODPIS NESEDÍ: {'; '.join(info['problems'])}", "Kód:"]
    return lines + info["code"].splitlines()[:40]


@tool("skill_pack", "Zabalí naučenou dovednost do souboru .jarvisskill podepsaného klíčem tohoto PC – dá se poslat a "
      "nainstalovat jinde (podpis ověří, že ji nikdo nezměnil).", category="dovednosti", perm="files_write")
async def skill_pack(ctx, name: str, author: str = "") -> ToolResult:
    from .. import skillpack
    from .skills import skills_dir

    src = skills_dir() / f"{name}.py"
    if not src.exists():
        return ToolResult(False, f"Dovednost {name} neznám.")
    data = skillpack.pack(src, author or getattr(ctx.cfg.general, "user_name", ""))
    out = paths.sub("dovednosti") / f"{name}-{time.strftime('%Y%m%d')}.jarvisskill"
    out.write_bytes(data)
    return ToolResult(True, f"Zabaleno: {out} (otisk autora {skillpack.my_fingerprint()}).", data={"path": str(out)})


@tool("skill_install_package", "Nainstaluje dovednost ze souboru .jarvisskill: ověří podpis a otisk kódu, ukáže autora, "
      "oprávnění a celý kód ke schválení.", danger=True, details=_inspect_details, category="dovednosti")
async def skill_install_package(ctx, path: str, trust_author: bool = False) -> ToolResult:
    from .. import skillpack
    from .skills import create_skill

    try:
        info = skillpack.inspect(Path(path).read_bytes(), ctx.cfg.tools.trusted_publishers)
    except (OSError, ValueError) as e:
        return ToolResult(False, str(e))
    if not info["valid"]:
        return ToolResult(False, "Balíček odmítnut: " + "; ".join(info["problems"]))
    name = Path(info["manifest"]["file"]).stem
    res = await create_skill(ctx, name, info["code"])
    if res.ok and trust_author and info["fingerprint"] and not info["trusted"]:
        ctx.update_config({"tools": {"trusted_publishers": sorted(set(ctx.cfg.tools.trusted_publishers) | {info["fingerprint"]})}})
    return res


@tool("skill_catalog", "Katalogy dovedností (JSON seznam na webu, třeba v repozitáři GitHub): bez url projde nastavené "
      "katalogy; vrátí názvy, popisy a odkazy na balíčky .jarvisskill.", category="dovednosti", perm="network")
async def skill_catalog(ctx, url: str = "") -> ToolResult:
    from .. import skillpack

    urls = [url] if url else list(getattr(ctx.cfg.integrations, "skill_catalogs", []) or [])
    if not urls:
        return ToolResult(False, "Žádný katalog není nastavený – přidej adresu katalogu (JSON).")
    found = []
    for u in urls[:5]:
        try:
            async with ctx.http() as c:
                r = await c.get(u, timeout=15, follow_redirects=True)
            found += skillpack.catalog_entries(r.json())
        except Exception as e:  # noqa: BLE001
            found.append({"name": "(nedostupné)", "url": u, "description": str(e)[:100], "author": "", "version": ""})
    return ToolResult(True, "; ".join(f"{f['name']} – {f['description'][:60]}" for f in found[:12]) or "Katalog je prázdný.", data=found)
