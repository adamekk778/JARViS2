"""Wave 38 by voice: test scenes, environment concepts, game logs, assets, automated game runs, mods, FPS by settings,
anti-exploit tests, voxel builds and game settings advice."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _out(name: str, ext: str) -> Path:
    return paths.sub("hry") / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}{ext}"


def _dir(path: str) -> Path:
    p = resolve(path)
    if not p.is_dir():
        raise ValueError(f"Složka neexistuje: {p}")
    return p


@tool("godot_test_scene", "Vygeneruje testovací herní scénu pro Godot 4 (.tscn): level z místností a chodeb se stěnami (kolize), "
      "startem, cílem a testovacími nepřáteli. Stejné semínko = stejná scéna.", category="hry")
async def godot_test_scene(ctx, seed: int = 1, rooms: int = 8, enemies: int = 3, tile: int = 32) -> ToolResult:
    from .. import gameplus, gamedev

    lvl = gamedev.dungeon(seed, 48, 32, max(2, min(rooms, 20)), _out("level", ".png"))
    out = _out(f"test_scene_{seed}", ".tscn")
    out.write_text(gameplus.godot_scene(lvl, tile, enemies, seed), encoding="utf-8")
    return ToolResult(True, f"Scéna se {lvl['rooms']} místnostmi, cesta ze startu do cíle {lvl['path_length']} polí, {enemies} testovací nepřátelé. "
                            "Zkopíruj .tscn do projektu Godot a otevři.", data={k: v for k, v in lvl.items() if k != "ascii"},
                      attachments=[str(out), lvl["path"]])


@tool("environment_concept", "Koncept herního prostředí (les, poušť, sci-fi, zima, jeskyně): moodboard s paletou barev, náčrtem "
      "rozvržení, rekvizitami a světlem, plus zadání pro generátor obrázků.", category="hry")
async def environment_concept(ctx, theme: str, seed: int = -1) -> ToolResult:
    from .. import gameplus

    out = _out(f"koncept-{theme}", ".png")
    try:
        r = await asyncio.to_thread(gameplus.concept_board, theme, out, None if seed < 0 else seed)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Koncept „{theme}“: paleta {', '.join(r['palette'])}; rekvizity: {r['props']}; světlo: {r['light']}. "
                            f"Zadání pro obrázek: {r['prompt']}", data=r, attachments=[str(out)])


@tool("game_log_check", "Rozbor herního logu (Unity Player.log, Unreal, Godot): chyby a výjimky seskupené podle druhu, záseky, "
      "problémy s pamětí a chybějící soubory, kde se objevily poprvé.", category="hry", perm="files_read")
async def game_log_check(ctx, file: str) -> ToolResult:
    from .. import gameplus

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    r = gameplus.game_log(p.read_text(encoding="utf-8", errors="replace")[-20_000_000:])
    if not r["top"]:
        return ToolResult(True, f"Log ({r['engine']}, {r['lines']} řádků) je čistý – žádné chyby ani varování.", data=r)
    counts = ", ".join(f"{k} {v}×" for k, v in r["counts"].items())
    first = r["top"][0]
    return ToolResult(True, f"{r['engine']}: {counts}. Nejdůležitější: „{first['message'][:120]}“ ({first['count']}×, poprvé ř. {first['first_line']}).", data=r)


@tool("game_assets", "Úklid herních assetů: nepoužité textury / modely / zvuky, příliš velké textury, rozměry mimo mocninu dvou, "
      "duplicity a špatné názvy (mezery, diakritika, „copy“) s návrhem přejmenování. Nic nemaže ani nepřesouvá.",
      category="hry", perm="files_read")
async def game_assets(ctx, folder: str) -> ToolResult:
    from .. import gameplus

    try:
        r = await asyncio.to_thread(gameplus.assets_report, _dir(folder))
    except ValueError as e:
        return ToolResult(False, str(e))
    kinds = ", ".join(f"{k} {v}" for k, v in r["kinds"].items())
    issues = [f"{len(r['unused'])} možná nepoužitých", f"{len(r['oversized'])} přes 4096 px", f"{len(r['not_power_of_two'])} mimo mocninu dvou",
              f"{len(r['duplicates'])} duplicit", f"{len(r['bad_names'])} špatných názvů"]
    return ToolResult(True, f"{r['files']} souborů ({kinds}). " + ", ".join(i for i in issues if not i.startswith("0 ")) + ".", data=r)


def _auto_details(a: dict, ctx=None) -> list[str]:
    return [f"Spustí tvoji hru (projekt Godot {a.get('project')}) bez okna na {a.get('seconds', 20)} s a zachytí chyby.", "Hra se opravdu spustí."]


@tool("game_autotest", "Automatický test vlastní hry v Godotu: spustí projekt bez okna, zachytí chyby skriptů, pády a chybějící "
      "soubory (res://…).", category="hry", perm="shell", danger=True, details=_auto_details)
async def game_autotest(ctx, project: str, seconds: int = 20) -> ToolResult:
    from .. import gameplus

    try:
        r = await asyncio.to_thread(gameplus.godot_run, _dir(project), max(5, min(seconds, 300)))
    except (ValueError, FileNotFoundError) as e:
        return ToolResult(False, str(e))
    if r["ok"]:
        return ToolResult(True, "Hra běžela bez chyb.", data=r)
    msg = f"{len(r['errors'])} chyb" + (", hra spadla" if r["crashed"] else "") + (f", chybí: {', '.join(r['missing'][:5])}" if r["missing"] else "")
    return ToolResult(True, msg + (f". První: {r['errors'][0][:160]}" if r["errors"] else "."), data=r)


@tool("minecraft_mods", "Kontrola modů pro Minecraft (složka mods, Fabric / Forge / NeoForge / Quilt): verze, chybějící závislosti, "
      "duplicity, míchání zavaděčů, nekompatibility a nesoulad s verzí hry.", category="hry", perm="files_read")
async def minecraft_mods(ctx, folder: str, minecraft_version: str = "") -> ToolResult:
    from .. import gameplus

    try:
        r = await asyncio.to_thread(gameplus.mods_report, _dir(folder), minecraft_version.strip())
    except ValueError as e:
        return ToolResult(False, str(e))
    if not r["count"]:
        return ToolResult(False, "Ve složce nevidím žádné módy (.jar).")
    if not r["problems"]:
        return ToolResult(True, f"{r['count']} módů ({', '.join(f'{k} {v}' for k, v in r['loaders'].items())}), žádný problém.", data=r)
    return ToolResult(True, f"{r['count']} módů, {len(r['problems'])} problémů: " + " ".join(r["problems"][:6]), data=r)


@tool("fps_by_settings", "Porovná výkon hry podle nastavení z měření snímků (PresentMon / CapFrameX / Afterburner CSV): průměr, "
      "1 % nejhorších snímků, záseky – a doporučí nejvyšší nastavení, které drží plynulost.", category="hry", perm="files_read")
async def fps_by_settings(ctx, runs: Annotated[str, "„nízké=cesta.csv; střední=…; vysoké=…“ od nejnižšího po nejvyšší"], target_fps: float = 60) -> ToolResult:
    from .. import gameplus
    from ..pccare import frame_times

    data = {}
    for part in runs.split(";"):
        if "=" not in part:
            continue
        name, path = (x.strip() for x in part.split("=", 1))
        p = resolve(path)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8", errors="replace"))))
        try:
            data[name] = frame_times(rows[0], rows[1:])
        except ValueError as e:
            return ToolResult(False, f"{name}: {e}")
    if len(data) < 2:
        return ToolResult(False, "Zadej aspoň dvě měření: „nízké=a.csv; vysoké=b.csv“.")
    try:
        r = gameplus.compare_settings(data, target_fps)
    except ValueError as e:
        return ToolResult(False, str(e))
    rows = "; ".join(f"{x['settings']}: {x['avg_fps']} FPS, 1 % low {x['low_1pct_fps']}, {x['verdict']}" for x in r["runs"])
    return ToolResult(True, f"{rows}. Doporučuji: {r['recommended']} – {r['reason']}", data=r)


@tool("exploit_test", "Test odolnosti vlastní hry proti podvodům: z uložené hry (JSON) připraví upravené varianty (obří / záporná čísla, "
      "kopírování předmětů) k ověření, že je hra odmítne; z telemetrie (CSV player,t,x,y) najde nemožné rychlosti a teleporty.",
      category="hry", perm="files_read")
async def exploit_test(ctx, save: str = "", telemetry: str = "", max_speed: float = 10) -> ToolResult:
    from .. import gameplus

    msg, data, atts = [], {}, []
    if save:
        p = resolve(save)
        try:
            original = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return ToolResult(False, f"Uloženou hru nejde přečíst jako JSON: {e}")
        variants = gameplus.tampered_saves(original)
        out = paths.sub("hry") / f"podvrzene-{p.stem}-{time.strftime('%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        for i, v in enumerate(variants, 1):
            (out / f"{i:02d}.json").write_text(json.dumps(v["data"], ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "SEZNAM.txt").write_text("\n".join(f"{i:02d}.json: {v['change']}" for i, v in enumerate(variants, 1)), encoding="utf-8")
        data["variants"] = [v["change"] for v in variants]
        data["folder"] = str(out)
        msg.append(f"{len(variants)} upravených uložení ve {out} – každé načti ve hře; měla by ho odmítnout nebo opravit.")
    if telemetry:
        p = resolve(telemetry)
        rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8", errors="replace"))))
        try:
            bad = gameplus.impossible_moves(rows, max_speed)
        except (KeyError, ValueError) as e:
            return ToolResult(False, f"Telemetrie potřebuje sloupce player, t, x, y ({e}).")
        data["impossible"] = bad
        msg.append(f"Nemožné pohyby: {len(bad)}" + (f" (nejhorší {bad[0]['player']}: {bad[0]['speed']} j/s, {bad[0]['times_max']}× víc než max.)" if bad else "."))
    if not msg:
        return ToolResult(False, "Zadej uloženou hru (JSON) nebo telemetrii (CSV).")
    return ToolResult(True, " ".join(msg), data=data, attachments=atts)


@tool("voxel_build", "Postaví voxelovou stavbu (dům, věž, strom, pyramida) jako model MagicaVoxel (.vox) a příkazy pro Minecraft "
      "(.mcfunction).", category="hry")
async def voxel_build(ctx, kind: Annotated[str, "dům / věž / strom / pyramida"] = "dům", size: int = 9, seed: int = 1) -> ToolResult:
    from .. import gameplus

    try:
        m = gameplus.voxel_model(kind.lower(), size, seed)
    except ValueError as e:
        return ToolResult(False, str(e))
    vox, mc = _out(f"voxel-{kind}", ".vox"), _out(f"voxel-{kind}", ".mcfunction")
    vox.write_bytes(gameplus.vox_bytes(m))
    mc.write_text(gameplus.mcfunction(m), encoding="utf-8")
    mats = {}
    for v in m.values():
        mats[v] = mats.get(v, 0) + 1
    return ToolResult(True, f"{kind.capitalize()}: {len(m)} kostek (" + ", ".join(f"{k} {n}" for k, n in mats.items()) + "). "
                            ".vox otevřeš v MagicaVoxelu, .mcfunction dej do datapacku.", data={"blocks": len(m), "materials": mats}, attachments=[str(vox), str(mc)])


@tool("game_settings", "Doporučí nastavení grafiky ve hrách pro tenhle počítač (grafická karta, paměť, monitor): předvolba, "
      "upscaling, omezení FPS a co nejvíc brzdí.", category="hry")
async def game_settings(ctx, game: str = "", refresh_hz: int = 0) -> ToolResult:
    from .. import gameplus
    from ..llm.local import detect_hardware

    hw = await asyncio.to_thread(detect_hardware)
    gpus = [g for g in hw.get("gpus") or [] if not any(x in g["name"].lower() for x in ("microsoft basic", "virtual", "parsec"))]
    gpu = max(gpus, key=lambda g: g.get("vram_gb") or 0) if gpus else {"name": "", "vram_gb": None}
    vram = gpu.get("vram_gb")
    if vram and 4.2 <= vram <= 4.3:          # Windows caps this value at 4 GB – unknown, not small
        vram = None
    try:
        screen = tuple(ctx.platform.screen_size())
    except Exception:  # noqa: BLE001
        screen = (1920, 1080)
    r = gameplus.settings_advice(gpu["name"], vram or 0, hw.get("ram_gb") or 0, screen, refresh_hz or 60, hw.get("cores") or 8)
    head = f"{game}: " if game else ""
    return ToolResult(True, head + f"{gpu['name'] or 'grafika nezjištěna'}, {hw.get('ram_gb')} GB RAM. " + " ".join(r["tips"]), data={**r, "gpu": gpu})
