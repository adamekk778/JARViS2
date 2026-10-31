"""OMEGA wave 26 by voice: creative production – brand colours, social formats, caption variants, asset licences and
provenance, camera moves and lights for Blender, lip-sync, mix advice, render cost, colour profiles, storyboard →
timeline, click-through product demo."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve

IMG = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def _out_dir(sub: str) -> Path:
    return paths.data_dir() / "kreativa" / sub


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


@tool("brand_check", "Zkontroluje, jestli obrázky (soubor nebo složka) drží barvy značky: hlavní barvy každého obrázku proti "
      "paletě, kolik % plochy je mimo značku a v jakých poměrech stran sada je.", category="design", perm="files_read")
async def brand_check(ctx, path: str, palette: Annotated[list[str], "barvy značky #rrggbb"], tolerance: float = 15) -> ToolResult:
    from .. import creative

    p = resolve(path)
    files = sorted(x for x in p.rglob("*") if x.suffix.lower() in IMG)[:300] if p.is_dir() else [p]
    files = [f for f in files if f.is_file()]
    if not files:
        return ToolResult(False, f"Žádné obrázky v {p}.")
    try:
        r = await asyncio.to_thread(creative.brand_check, files, palette, tolerance)
    except ValueError:
        return ToolResult(False, "Barvy palety zadej jako #rrggbb.")
    bad = [x for x in r["images"] if not x.get("ok", True)]
    msg = (f"Všech {len(files)} obrázků drží barvy značky." if not bad else
           f"{len(bad)} z {len(files)} mimo značku: " + "; ".join(f"{x['file']} {x['off_brand_pct']} % ({', '.join(o['color'] for o in x['off'][:3])})" for x in bad[:5]))
    if len(r["aspect_ratios"]) > 1:
        msg += f". Poměry stran: {', '.join(str(a) for a in r['aspect_ratios'][:6])}"
    return ToolResult(True, msg + ".", data=r)


@tool("social_formats", "Z jedné fotky udělá verze pro sítě (Instagram, příběh, Facebook, LinkedIn, X, náhled YouTube, Pinterest) – "
      "ořízne tam, kde je nejvíc detailu, ne naslepo na střed.", category="design", perm="files_read")
async def social_formats(ctx, image: str, formats: list[str] | None = None) -> ToolResult:
    from .. import creative

    p = resolve(image)
    if not p.is_file():
        return ToolResult(False, f"Obrázek neexistuje: {p}")
    try:
        r = await asyncio.to_thread(creative.batch_formats, p, _out_dir(f"formaty-{_stamp()}"), formats)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    up = [x["format"] for x in r if x["upscaled"]]
    return ToolResult(True, f"Hotovo {len(r)} formátů: {', '.join(x['format'] for x in r)}." + (f" Zvětšeno (méně ostré): {', '.join(up)}." if up else ""),
                      data=r, attachments=[x["path"] for x in r])


@tool("caption_variants", "Napíše několik variant popisku k příspěvku pro danou síť a každou ohodnotí: délka vůči limitu, co je "
      "vidět před „více“, hashtagy, háček na začátku. Nic nepublikuje.", category="komunikace")
async def caption_variants(ctx, about: str, platform: Annotated[str, "instagram / facebook / linkedin / x / tiktok / youtube"] = "instagram",
                           count: int = 3, tone: str = "") -> ToolResult:
    from .. import creative

    try:
        r = await creative.caption_variants(ctx, about, platform.lower(), max(2, min(count, 6)), tone)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not r:
        return ToolResult(False, "AI nevrátila žádnou variantu.")
    return ToolResult(True, " | ".join(f"{x['variant']} ({x['score']} b.): {x['text'][:90]}" + (f" – {'; '.join(x['issues'])}" if x["issues"] else "") for x in r), data=r)


@tool("asset_register", "Zaeviduje soubor (obrázek, hudbu, font…) s licencí: odkud je, autor, licence, nutné uvedení autora, do "
      "kdy platí, z čeho vznikl. Uloží otisk SHA-256, takže pozná pozdější změnu.", category="design", perm="files_read")
async def asset_register(ctx, file: str, source: str = "", author: str = "", license: str = "", attribution: str = "",
                         expires: Annotated[str, "RRRR-MM-DD"] = "", derived_from: str = "", note: str = "") -> ToolResult:
    from .. import creative

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        r = await asyncio.to_thread(creative.register_asset, ctx, p, source, author, license, attribution, expires,
                                    str(resolve(derived_from)) if derived_from else "", note)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Zaevidováno {p.name} ({r['license'] or 'bez licence'}), otisk {r['sha256'][:12]}…", data=r)


@tool("assets_report", "Přehled evidovaných souborů: které se od evidence změnily nebo zmizely, kterým licence vypršela či brzy "
      "vyprší, komu musíš uvést autora (hotový text), a ve složce co v evidenci chybí.", category="design", perm="files_read")
async def assets_report(ctx, days: int = 30, folder: str = "") -> ToolResult:
    from .. import creative

    r = await asyncio.to_thread(creative.assets_report, ctx, max(1, days))
    if folder:
        f = resolve(folder)
        if f.is_dir():
            r["unregistered"] = await asyncio.to_thread(creative.unregistered, ctx, f)
    parts = [f"{r['assets']} souborů v evidenci"]
    if r["expired"]:
        parts.append("licence vypršela: " + ", ".join(x["file"] for x in r["expired"][:5]))
    if r["expiring"]:
        parts.append("brzy vyprší: " + ", ".join(f"{x['file']} ({x['days']} d)" for x in r["expiring"][:5]))
    if r["changed"]:
        parts.append("změněné: " + ", ".join(r["changed"][:5]))
    if r["missing"]:
        parts.append("chybí: " + ", ".join(r["missing"][:5]))
    if r.get("unregistered"):
        parts.append(f"{len(r['unregistered'])} souborů ve složce bez evidence")
    if r["credits"]:
        parts.append(f"uvést autora u {len(r['credits'])}")
    return ToolResult(True, "; ".join(parts) + ".", data=r)


@tool("asset_lineage", "Původ souboru: z čeho vznikl, odkud byl ten původní, autor a licence po celém řetězci.", category="design", perm="files_read")
async def asset_lineage(ctx, file: str) -> ToolResult:
    from .. import creative

    chain = await asyncio.to_thread(creative.lineage, ctx, resolve(file))
    if not chain:
        return ToolResult(True, "Tenhle soubor v evidenci není.", data=[])
    return ToolResult(True, " ← ".join(f"{c['file']} ({c['license'] or '?'}{', ' + c['author'] if c['author'] else ''}{', ' + c['source'] if c['source'] else ''})" for c in chain) + ".",
                      data=chain)


@tool("camera_move", "Pohyb kamery pro 3D scénu: oblet (orbit), najetí / odjetí (dolly), jeřáb nahoru, přiblížení se zoomem – "
      "klíčové snímky s plynulým rozjezdem a dojezdem a skript pro Blender (spustíš sám).", category="design")
async def camera_move(ctx, kind: Annotated[str, "orbit / dolly / crane / push-in"], target: list[float] | None = None, distance: float = 5,
                      height: float = 1.6, seconds: float = 5, fps: int = 24, degrees: float = 360, end_distance: float | None = None,
                      end_height: float | None = None, ease: Annotated[str, "in-out / in / out / linear"] = "in-out") -> ToolResult:
    from .. import creative

    try:
        r = creative.camera_path(kind, target or [0, 0, 1], distance, height, max(2, int(seconds * fps)), fps, degrees, end_distance, end_height, ease)
    except ValueError as e:
        return ToolResult(False, str(e))
    script = _out_dir("blender") / f"kamera-{kind}-{_stamp()}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(creative.blender_camera_script(r), encoding="utf-8")
    r["script"] = str(script)
    return ToolResult(True, f"{kind}: {len(r['keys'])} snímků ({r['seconds']} s), rychlost na začátku {r['speed_start']}, uprostřed {r['speed_mid']} m/s. "
                            f"Skript pro Blender: {script.name}.", data={k: v for k, v in r.items() if k != "keys"} | {"keys": r["keys"][:: max(1, len(r["keys"]) // 24)]},
                      attachments=[str(script)])


@tool("lighting_plan", "Rozestavění světel (tříbodové, Rembrandt, butterfly, split, high key, low key): kam dát klíčové, výplňové "
      "a kontra světlo vůči kameře, jaký výkon podle poměru, a skript pro Blender.", category="design")
async def lighting_plan(ctx, style: str = "three_point", subject: list[float] | None = None, camera: list[float] | None = None,
                        distance: float = 2.5, key_watts: float = 1000) -> ToolResult:
    from .. import creative

    subj = subject or [0, 0, 1.5]
    try:
        r = creative.lighting(style, subj, camera or [0, -5, 1.6], distance, key_watts)
    except ValueError as e:
        return ToolResult(False, str(e))
    script = _out_dir("blender") / f"svetla-{style}-{_stamp()}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(creative.blender_lights_script(r, subj), encoding="utf-8")
    r["script"] = str(script)
    return ToolResult(True, f"{style}: poměr {r['ratio']} ({r['stops']} EV); " + "; ".join(f"{x['name']} {x['watts']:g} W na {x['position']}" for x in r["lights"]) + ".",
                      data=r, attachments=[str(script)])


@tool("lip_sync", "Pohyb úst podle zvuku (WAV/MP3): tvar úst na každý snímek jako klíčové snímky a soubor pro Moho / Papagayo. "
      "S textem repliky (text) podle skutečných hlásek (MBP zavře rty, O/U zakulatí…), bez textu podle hlasitosti "
      "(zavřená, pootevřená, otevřená, dokořán).", category="média", perm="files_read")
async def lip_sync(ctx, audio: str, fps: int = 24, text: Annotated[str, "co se v nahrávce říká (volitelné, přesnější)"] = "") -> ToolResult:
    from .. import creative, media

    p = resolve(audio)
    if not p.is_file():
        return ToolResult(False, f"Zvuk neexistuje: {p}")
    try:
        x, rate = await asyncio.to_thread(media.read_audio, p, 1800)
    except (ValueError, OSError) as e:
        return ToolResult(False, f"Zvuk nejde přečíst: {e}")
    fps = max(6, min(fps, 60))
    r = await asyncio.to_thread(creative.lipsync_text, x, rate, text, fps) if text.strip() else await asyncio.to_thread(creative.lipsync, x, rate, fps)
    out = _out_dir("lipsync") / f"{p.stem}-{_stamp()}.dat"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r["moho"], encoding="utf-8")
    how = f" podle {r['sounds']} hlásek z {r['words']} slov" if r.get("mode") == "hlásky" else " podle hlasitosti"
    return ToolResult(True, f"{r['frames']} snímků, {len(r['keys'])} změn úst{how}, pusa otevřená {r['open_pct']} % času. Soubor {out.name}.",
                      data={k: v for k, v in r.items() if k != "moho"} | {"path": str(out)}, attachments=[str(out)])


@tool("mix_advice", "Rada k mixu ze stop (dialog, hudba, efekty, atmosféra): hlasitost každé, o kolik dB ji ztlumit / zesílit, jestli "
      "hudba nepřekrývá řeč a jestli součet nepřebudí.", category="média", perm="files_read")
async def mix_advice(ctx, stems: Annotated[dict[str, str], "role → soubor, např. {dialog: hlas.wav, hudba: music.wav}"], master_lufs: float = -16) -> ToolResult:
    from .. import creative, media

    loaded = {}
    for role, f in stems.items():
        p = resolve(f)
        if not p.is_file():
            return ToolResult(False, f"Stopa {role} neexistuje: {p}")
        try:
            loaded[role] = await asyncio.to_thread(media.read_audio, p, 1800)
        except (ValueError, OSError) as e:
            return ToolResult(False, f"Stopu {role} nejde přečíst: {e}")
    r = await asyncio.to_thread(creative.mix_advice, loaded, master_lufs)
    return ToolResult(True, ("; ".join(r["advice"]) if r["advice"] else "Poměry stop sedí.") + ".", data=r)


@tool("render_cost", "Kolik potrvá a bude stát render: z času testovacího snímku (přepočet na finální rozlišení a vzorky) celkový "
      "čas, čas na N strojích, cena v cloudu a místo na disku.", category="design")
async def render_cost(ctx, frames: int, seconds_per_frame: float, machines: int = 1, price_per_hour: float = 0, mb_per_frame: float = 0,
                      test_resolution: list[int] | None = None, final_resolution: list[int] | None = None, samples_ratio: float = 1.0) -> ToolResult:
    from .. import creative

    if frames < 1 or seconds_per_frame <= 0:
        return ToolResult(False, "Počet snímků a čas snímku musí být kladné.")
    r = creative.render_cost(frames, seconds_per_frame, machines, price_per_hour, mb_per_frame, test_resolution, final_resolution, samples_ratio)
    return ToolResult(True, f"{r['seconds_per_frame']:g} s/snímek, celkem {r['machine_hours']:g} strojových hodin, na {machines} strojích {r['wall']}"
                            + (f", cena {r['cost']:g}" if price_per_hour else "") + (f", {r['disk_gb']:g} GB" if mb_per_frame else "") + ".", data=r)


@tool("color_profile", "Barevný profil obrázku (sRGB, Display P3, Adobe RGB, CMYK…) a jestli bude na webu vypadat stejně; "
      "volitelně uloží kopii převedenou do sRGB.", category="design", perm="files_read")
async def color_profile(ctx, image: str, convert: bool = False) -> ToolResult:
    from .. import creative

    p = resolve(image)
    if not p.is_file():
        return ToolResult(False, f"Obrázek neexistuje: {p}")
    try:
        r = await asyncio.to_thread(creative.color_profile, p, _out_dir("srgb") / f"{p.stem}-srgb.png" if convert else None)
    except ValueError as e:
        return ToolResult(False, str(e))
    except OSError as e:
        return ToolResult(False, f"Obrázek nejde otevřít: {e}")
    msg = f"{r['mode']}, profil {r['profile'] or 'žádný'}" + (f"; {'; '.join(r['advice'])}" if r["advice"] else "; v pořádku pro web")
    if r.get("converted"):
        msg += f". Převedeno: {Path(r['converted']).name}"
    return ToolResult(True, msg + ".", data=r, attachments=[r["converted"]] if r.get("converted") else [])


@tool("storyboard_timeline", "Ze storyboardu (záběry s dialogem / akcí) udělá časovou osu: délky podle dialogu, timecody, EDL pro "
      "střihový program a titulky SRT.", category="média")
async def storyboard_timeline(ctx, shots: Annotated[list[dict], "[{name, duration?, dialogue?, action?}]"], fps: int = 25, title: str = "JARVIS") -> ToolResult:
    from .. import creative

    if not shots:
        return ToolResult(False, "Zadej záběry.")
    r = creative.storyboard(shots, fps, 2.5, 2.0, title)
    d = _out_dir("storyboard")
    d.mkdir(parents=True, exist_ok=True)
    edl, files = d / f"{_stamp()}.edl", []
    edl.write_text(r["edl"], encoding="utf-8")
    files.append(str(edl))
    if r["srt"]:
        srt = edl.with_suffix(".srt")
        srt.write_text(r["srt"], encoding="utf-8")
        files.append(str(srt))
    msg = f"{len(r['shots'])} záběrů, celkem {r['total_tc']}." + (f" Pozor: {'; '.join(r['warnings'][:3])}." if r["warnings"] else "")
    return ToolResult(True, msg, data={k: v for k, v in r.items() if k not in ("edl", "srt")} | {"files": files}, attachments=files)


@tool("product_demo", "Klikací ukázka produktu ze snímků obrazovky: každý krok má popis a zvýrazněné místo, kam kliknout; vznikne "
      "jeden soubor HTML, který jde poslat.", category="design", perm="files_read")
async def product_demo(ctx, steps: Annotated[list[dict], "[{image, title, text, hotspot: [x, y, šířka, výška] v pixelech}]"], title: str = "Ukázka") -> ToolResult:
    from .. import creative

    if not steps:
        return ToolResult(False, "Zadej kroky.")
    fixed = [dict(s, image=str(resolve(s.get("image", "")))) for s in steps]
    try:
        r = await asyncio.to_thread(creative.product_demo, fixed, _out_dir("ukazky") / f"ukazka-{_stamp()}.html", title)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Ukázka: {r['steps']} kroků, {r['hotspots']} klikacích míst, {r['kb']} kB – {Path(r['path']).name}.", data=r, attachments=[r["path"]])
