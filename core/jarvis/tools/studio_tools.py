"""OMEGA wave 18 by voice: design and media – contrast, colour theme and design system, visual regression, typography and
UI consistency of a page, similar images, removing silences, ducking music under speech, cleaning up speech, loudness
and export quality, scenes and highlights in a video, subtitle checks / fixes / styled ASS."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _src(path: str) -> Path:
    p = resolve(path)
    if not p.is_file():
        raise ValueError(f"Soubor neexistuje: {p}")
    return p


def _dest(src: Path, suffix: str, target: str, ext: str = "") -> Path:
    d = resolve(target) if target else src.with_name(src.stem + suffix + (ext or src.suffix))
    if d.exists():
        raise ValueError(f"{d.name} už existuje.")
    return d


def _out_dir(kind: str) -> Path:
    d = paths.data_dir() / "studio" / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


async def _run(fn, *a):
    try:
        return await asyncio.to_thread(fn, *a), None
    except (ValueError, OSError, EOFError) as e:
        return None, ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – a broken media file
        return None, ToolResult(False, f"Soubor nejde zpracovat: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------------------------- design
@tool("contrast_check", "Kontrast textu a pozadí podle WCAG (AA / AAA), a když nestačí, nejbližší barva stejného odstínu, "
      "která projde.", category="design")
async def contrast_check(ctx, text_color: str, background: str) -> ToolResult:
    from .. import design

    try:
        r = design.contrast_report(text_color, background)
    except ValueError as e:
        return ToolResult(False, str(e))
    lv = "AAA" if r["aaa"] else "AA" if r["aa"] else "jen pro velký text (AA large)" if r["aa_large"] else "NEPROJDE"
    msg = f"Kontrast {r['ratio']}:1 → {lv}."
    if not r["aa"] and r.get("suggestion"):
        msg += f" Nejbližší barva, která projde AA: {r['suggestion']} ({r['suggestion_ratio']}:1)."
    return ToolResult(True, msg, data=r)


@tool("color_theme", "Barevné téma z jedné barvy značky: škály odstínů, světlý i tmavý režim, a každá dvojice text/pozadí "
      "ověřená na čitelnost (WCAG AA).", category="design")
async def color_theme(ctx, primary: str, accent: str = "") -> ToolResult:
    from .. import design

    try:
        t = design.theme(primary, accent)
    except ValueError as e:
        return ToolResult(False, str(e))
    lt, dk = t["light"], t["dark"]
    return ToolResult(True, f"Světlé: pozadí {lt['bg']}, text {lt['text']}, hlavní {lt['primary']}, akcent {lt['accent']}. Tmavé: pozadí {dk['bg']}, "
                      f"text {dk['text']}, hlavní {dk['primary']}. Čitelnost: {'všech ' + str(len(t['checks'])) + ' dvojic projde AA' if t['all_aa'] else 'některé dvojice neprojdou'}.",
                      data=t)


@tool("design_system", "Design systém do složky: barvy (světlé i tmavé), typografická škála, mezery, zaoblení, stíny – jako "
      "CSS proměnné (tokens.css) a JSON (tokens.json).", category="design", perm="files_write")
async def design_system(ctx, primary: str, folder: str, base_font: float = 16, type_ratio: float = 1.25, spacing_unit: int = 4,
                        radius: int = 8, font: str = "Inter, system-ui, sans-serif") -> ToolResult:
    from .. import design

    try:
        tok = design.design_tokens(primary, base_font, type_ratio, spacing_unit, radius, font)
        files = await asyncio.to_thread(design.save_design_system, tok, resolve(folder))
    except ValueError as e:
        return ToolResult(False, str(e))
    sizes = ", ".join(f"{k} {v:g}px" for k, v in tok["font"]["size"].items())
    return ToolResult(True, f"Design systém uložen ({', '.join(Path(f).name for f in files)} ve {Path(files[0]).parent}). Písmo: {sizes}.",
                      data={"files": files, "tokens": tok})


@tool("visual_diff", "Porovná dva snímky (před / po, dvě verze webu nebo aplikace): kolik pixelů se změnilo, kde (oblasti) "
      "a uloží obrázek se změnami zakroužkovanými červeně.", category="design", perm="files_read")
async def visual_diff(ctx, before: str, after: str, tolerance: int = 24) -> ToolResult:
    from .. import design

    try:
        a, b = _src(before), _src(after)
    except ValueError as e:
        return ToolResult(False, str(e))
    out = _out_dir("porovnani") / "zmeny.png"
    r, err = await _run(design.visual_diff, a, b, out, max(0, min(tolerance, 200)))
    if err:
        return err
    if r["same"]:
        return ToolResult(True, "Obrázky jsou stejné.", data=r)
    msg = f"Změněno {r['changed_pct']} % pixelů v {len(r['regions'])} oblastech" + (f"; velikost {r['before_size']} → {r['after_size']}" if r["size_changed"] else "")
    return ToolResult(True, msg + f". Vyznačeno: {r['diff_image']}", data=r)


@tool("typography_check", "Typografie stránky (adresa nebo .html): použitá písma a velikosti, příliš dlouhé řádky, těsné "
      "řádkování, drobné písmo, příliš mnoho velikostí.", category="design", perm="network")
async def typography_check(ctx, url: str) -> ToolResult:
    from .. import design

    try:
        els = await design.page_styles(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {str(e).splitlines()[0][:200]}")
    r = design.typography(els)
    return ToolResult(True, f"Písma: {', '.join(list(r['fonts'])[:4])}; velikosti: {', '.join(f'{k}px' for k in r['sizes'])}. " +
                      ("Problémy: " + "; ".join(r["issues"]) + "." if r["issues"] else "Typografie je v pořádku."), data=r)


@tool("ui_consistency", "Jednotnost vzhledu stránky: kolik různých barev, odsazení a zaoblení se doopravdy používá, skoro "
      "stejné barvy a odsazení mimo mřížku – co sjednotit.", category="design", perm="network")
async def ui_consistency(ctx, url: str) -> ToolResult:
    from .. import design

    try:
        els = await design.page_styles(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {str(e).splitlines()[0][:200]}")
    r = design.consistency(els)
    return ToolResult(True, f"{len(r['text_colors'])} barev textu, {len(r['spacing'])} odsazení, {len(r['radii'])} zaoblení. " +
                      ("Sjednotit: " + "; ".join(r["issues"]) + "." if r["issues"] else "Vzhled je jednotný."), data=r)


@tool("find_similar_image", "Najde ve složce obrázky podobné zadanému (i zmenšené, překódované nebo trochu upravené).",
      category="soubory", perm="files_read")
async def find_similar_image(ctx, image: str, folder: str, max_distance: int = 10) -> ToolResult:
    from .. import fileuniverse as fu

    try:
        q = _src(image)
    except ValueError as e:
        return ToolResult(False, str(e))
    root = resolve(folder)
    if not root.is_dir():
        return ToolResult(False, f"Složka neexistuje: {root}")

    def run():
        h0 = fu.dhash(q)
        if h0 is None:
            raise ValueError("Zadaný soubor není obrázek, který umím přečíst.")
        hits = []
        for p in fu.walk([root]):
            if p.suffix.lower() in fu.IMAGE_EXT and p.resolve() != q.resolve():
                h = fu.dhash(p)
                if h is not None:
                    d = bin(h ^ h0).count("1")
                    if d <= max_distance:
                        hits.append({"path": str(p), "distance": d})
        return sorted(hits, key=lambda x: x["distance"])
    hits, err = await _run(run)
    if err:
        return err
    if not hits:
        return ToolResult(True, "Žádný podobný obrázek jsem nenašel.", data=[])
    return ToolResult(True, f"{len(hits)} podobných: " + "; ".join(f"{Path(h['path']).name} (rozdíl {h['distance']})" for h in hits[:8]) + ".", data=hits)


# ---------------------------------------------------------------------------------------------- audio
@tool("remove_silence", "Vystřihne ze záznamu dlouhá ticha (přednáška, podcast, hlasovka) a uloží NOVÝ soubor WAV. "
      "Krátké pauzy nechá, aby řeč zněla přirozeně.", category="média", perm="files_write")
async def remove_silence(ctx, file: str, threshold_db: float = -40, min_silence_ms: int = 600, target: str = "") -> ToolResult:
    from .. import media

    try:
        src = _src(file)
        dest = _dest(src, "_bez-ticha", target, ".wav")
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        x, rate = media.read_audio(src)
        y, info = media.remove_silence(x, rate, threshold_db, min_silence_ms)
        media.write_wav(dest, y, rate)
        return info
    r, err = await _run(run)
    if err:
        return err
    return ToolResult(True, f"Vystřiženo {r['removed_s']} s ticha ({len(r['cuts'])} míst): {_mmss(r['before_s'])} → {_mmss(r['after_s'])}. Uloženo: {dest}",
                      data={**r, "path": str(dest)})


@tool("duck_music", "Smíchá řeč s hudbou a hudbu automaticky ztiší, když se mluví (ducking). Výsledek je NOVÝ soubor WAV.",
      category="média", perm="files_write")
async def duck_music(ctx, voice: str, music: str, duck_db: float = -15, music_db: float = -6, target: str = "") -> ToolResult:
    from .. import media

    try:
        v, m = _src(voice), _src(music)
        dest = _dest(v, "_s-hudbou", target, ".wav")
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        xv, rv = media.read_audio(v)
        xm, rm = media.read_audio(m)
        y, info = media.duck(xv, rv, xm, rm, duck_db, music_db)
        media.write_wav(dest, y, rv)
        return info
    r, err = await _run(run)
    if err:
        return err
    return ToolResult(True, f"Smícháno ({_mmss(r['seconds'])}), řeč {r['speech_pct']} % času, hudba pod řečí o {abs(duck_db):g} dB tišší. Uloženo: {dest}",
                      data={**r, "path": str(dest)})


@tool("clean_speech", "Vyčistí nahranou řeč: odstraní hučení a dunění, potlačí stálý šum v pozadí (větrák, šum mikrofonu) a "
      "srovná hlasitost. Výsledek je NOVÝ soubor WAV.", category="média", perm="files_write")
async def clean_speech(ctx, file: str, strength: Annotated[float, "síla potlačení šumu 1–3"] = 1.5, target: str = "") -> ToolResult:
    from .. import media

    try:
        src = _src(file)
        dest = _dest(src, "_cisty", target, ".wav")
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        x, rate = media.read_audio(src)
        y, info = media.enhance_speech(x, rate, reduction=max(0.5, min(strength, 3)))
        media.write_wav(dest, y, rate)
        return info
    r, err = await _run(run)
    if err:
        return err
    return ToolResult(True, f"Šum v tichých místech snížen o {r['noise_reduction_db']} dB, dunění pod {r['highpass_hz']:g} Hz pryč. Uloženo: {dest}",
                      data={**r, "path": str(dest)})


@tool("media_quality", "Kontrola kvality zvuku nebo videa před zveřejněním: hlasitost v LUFS a kolik upravit pro YouTube / "
      "Spotify / podcast / TV, špičky, přebuzení, ticho na začátku a konci; u videa rozlišení, snímky, datový tok a kodeky.",
      category="média", perm="files_read")
async def media_quality(ctx, file: str) -> ToolResult:
    from .. import media

    try:
        src = _src(file)
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        info = {}
        if src.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"):
            info = media.video_info(src)
        try:
            x, rate = media.read_audio(src)
            info["audio"] = media.audio_quality(x, rate)
        except ValueError as e:
            info["audio_error"] = str(e)
        return info
    r, err = await _run(run)
    if err:
        return err
    parts = []
    if r.get("width"):
        parts.append(f"video {r['width']}×{r['height']} {r.get('fps')} fps, {r.get('video_codec')}, {r.get('bitrate_kbps')} kb/s")
    a = r.get("audio")
    if a:
        parts.append(f"zvuk {a['lufs']} LUFS, špička {a['peak_dbfs']} dBFS")
        adj = a["adjust_db"]
        if adj:
            parts.append("úprava hlasitosti: " + ", ".join(f"{k} {v:+g} dB" for k, v in adj.items() if k in ("YouTube", "podcast", "TV (EBU R128)")))
        if a["issues"]:
            parts.append("problémy: " + "; ".join(a["issues"]))
    elif r.get("audio_error"):
        parts.append(r["audio_error"])
    return ToolResult(True, ". ".join(parts) + ".", data=r)


# ---------------------------------------------------------------------------------------------- video
@tool("video_scenes", "Najde ve videu střihy a scény (časy), volitelně i nejzajímavější momenty podle zvuku – pro kapitoly, "
      "náhledy nebo krátká videa.", category="média", perm="files_read")
async def video_scenes(ctx, file: str, threshold: float = 0.35, highlights: int = 5) -> ToolResult:
    from .. import media

    try:
        src = _src(file)
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        sc = media.scenes(src, threshold)
        hl = []
        if highlights:
            try:
                x, rate = media.read_audio(src)
                hl = media.highlights(x, rate, highlights, scene_cuts=[c["t"] for c in sc["cuts"]])
            except ValueError:
                hl = []
        return {**sc, "highlights": hl}
    r, err = await _run(run)
    if err:
        return err
    msg = f"{r['scenes']} scén; střihy v " + (", ".join(_mmss(c["t"]) for c in r["cuts"][:15]) or "—")
    if r["highlights"]:
        msg += ". Zajímavé momenty: " + ", ".join(_mmss(h["t"]) for h in r["highlights"])
    return ToolResult(True, msg + ".", data=r)


@tool("audio_highlights", "Nejzajímavější (nejhlasitější, nejživější) momenty ve zvukovém záznamu – časy pro střih nebo upoutávku.",
      category="média", perm="files_read")
async def audio_highlights(ctx, file: str, top: int = 5, min_gap_s: float = 10) -> ToolResult:
    from .. import media

    try:
        src = _src(file)
    except ValueError as e:
        return ToolResult(False, str(e))

    def run():
        x, rate = media.read_audio(src)
        return media.highlights(x, rate, max(1, min(top, 20)), min_gap_s)
    r, err = await _run(run)
    if err:
        return err
    if not r:
        return ToolResult(True, "Záznam je vyrovnaný – žádný moment výrazně nevyčnívá.", data=[])
    return ToolResult(True, "Momenty: " + ", ".join(f"{_mmss(h['t'])} (+{h['score']}σ)" for h in r) + ".", data=r)


# ---------------------------------------------------------------------------------------------- subtitles
@tool("check_subtitles", "Zkontroluje titulky SRT: rychlost čtení (znaky za sekundu), délku řádků, počet řádků, příliš krátké "
      "nebo dlouhé zobrazení a překryvy.", category="média", perm="files_read")
async def check_subtitles(ctx, file: str, max_cps: float = 17, max_line: int = 42) -> ToolResult:
    from .. import media

    try:
        subs = media.parse_srt(_src(file).read_text(encoding="utf-8-sig", errors="replace"))
    except ValueError as e:
        return ToolResult(False, str(e))
    iss = media.check_subtitles(subs, max_cps, max_line)
    if not iss:
        return ToolResult(True, f"{len(subs)} titulků – vše v pořádku.", data=[])
    return ToolResult(True, f"{len(iss)} problémů v {len(subs)} titulcích: " + "; ".join(f"č. {x['n']}: {x['problem']}" for x in iss[:10]) + ".", data=iss)


@tool("restyle_subtitles", "Opraví titulky (zalomí řádky, prodlouží příliš krátké zobrazení) a uloží NOVÝ soubor: SRT, nebo "
      "ASS se stylem (písmo, velikost, barva, obrys, pozice, podklad) pro vypálení do videa.", category="média", perm="files_write")
async def restyle_subtitles(ctx, file: str, format: Annotated[str, "srt nebo ass"] = "ass", font: str = "Arial", size: int = 54,
                            color: str = "#FFFFFF", outline_color: str = "#000000", position: Annotated[str, "dole / nahoře / uprostřed"] = "dole",
                            box: bool = False, target: str = "") -> ToolResult:
    from .. import media

    fmt = format.lower().strip(". ")
    if fmt not in ("srt", "ass"):
        return ToolResult(False, "Formát: srt nebo ass.")
    try:
        src = _src(file)
        subs = media.parse_srt(src.read_text(encoding="utf-8-sig", errors="replace"))
        dest = _dest(src, "_upravene", target, "." + fmt)
    except ValueError as e:
        return ToolResult(False, str(e))
    before = len(media.check_subtitles(subs))
    fixed = media.fix_subtitles(subs)
    after = len(media.check_subtitles(fixed))
    text = media.to_srt(fixed) if fmt == "srt" else media.to_ass(fixed, font, size, color, outline_color, position=position, box=box)
    dest.write_text(text, encoding="utf-8")
    return ToolResult(True, f"{len(fixed)} titulků, problémů {before} → {after}. Uloženo: {dest}", data={"path": str(dest), "before": before, "after": after})
