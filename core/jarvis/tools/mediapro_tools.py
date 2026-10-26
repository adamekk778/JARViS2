"""OMEGA wave 31 by voice: media production – reframe a video, short clips, background removal, organise media,
podcast chapters, shot colour matching (LUT), voice-over timing, sound effects, subtitle sync, animated graphics and the
render queue."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve

ASPECTS = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "16:9": 16 / 9, "4:3": 4 / 3, "21:9": 21 / 9}


def _out(sub: str, name: str) -> Path:
    d = paths.data_dir() / "media" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _video(file: str) -> Path:
    p = resolve(file)
    if not p.is_file():
        raise ValueError(f"Soubor neexistuje: {p}")
    return p


@tool("reframe_video", "Převede video na jiný poměr stran (9:16 na TikTok / Reels / Shorts, 1:1, 4:5) a výřez při tom sleduje, kde "
      "se něco děje – ne naslepo na střed. Běží ve frontě renderů na pozadí.", category="média", perm="files_read")
async def reframe_video(ctx, file: str, aspect: Annotated[str, "9:16 / 1:1 / 4:5 / 16:9"] = "9:16", height: int = 1920) -> ToolResult:
    from .. import mediapro

    try:
        src = _video(file)
        ar = ASPECTS.get(aspect.replace(" ", ""))
        if ar is None:
            raise ValueError(f"Poměr stran: {', '.join(ASPECTS)}.")
        dst = _out("reframe", f"{src.stem}-{aspect.replace(':', 'x')}-{time.strftime('%H%M%S')}.mp4")
        jid = mediapro.queue(ctx).add("reframe", {"src": str(src), "dst": str(dst), "aspect": ar, "height": max(240, min(height, 3840))})
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Zařazeno do fronty jako úloha č. {jid} → {dst.name}. Dám vědět, až bude hotovo.", data={"job": jid, "path": str(dst)})


@tool("extract_clips", "Vybere z videa nejživější momenty (hlasitost, střihy) a vystřihne je jako krátká videa – na sociální sítě "
      "nebo náhledy. Běží ve frontě renderů.", category="média", perm="files_read")
async def extract_clips(ctx, file: str, count: int = 3, seconds: float = 30) -> ToolResult:
    from .. import mediapro

    try:
        src = _video(file)
        clips = await asyncio.to_thread(mediapro.pick_clips, src, max(1, min(count, 10)), max(1.0, min(seconds, 180)))
    except ValueError as e:
        return ToolResult(False, str(e))
    jobs = []
    for i, c in enumerate(clips, 1):
        dst = _out("klipy", f"{src.stem}-klip{i}-{int(c['start'])}s.mp4")
        jobs.append(mediapro.queue(ctx).add("clip", {"src": str(src), "dst": str(dst), "start": c["start"], "end": c["end"]}))
        c["path"] = str(dst)
    return ToolResult(True, f"{len(clips)} klipů ve frontě (úlohy {', '.join(map(str, jobs))}): " +
                      ", ".join(f"{c['start']:g}–{c['end']:g} s" for c in clips) + ".", data={"clips": clips, "jobs": jobs})


@tool("remove_background", "Odstraní jednobarevné pozadí obrázku (produktová fotka, logo, podpis na bílém) – vznikne PNG s průhledností. "
      "Na rušné pozadí neplatí, to řekne.", category="design", perm="files_read")
async def remove_background(ctx, image: str, tolerance: float = 25) -> ToolResult:
    from .. import mediapro

    try:
        src = _video(image)
        r = await asyncio.to_thread(mediapro.remove_background, src, _out("bez-pozadi", f"{src.stem}-bez-pozadi.png"), max(3.0, min(tolerance, 80)))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Pozadí {r['background']} odstraněno ({r['removed_pct']:g} % plochy)." + (" " + "; ".join(r["warnings"]) + "." if r["warnings"] else ""),
                      data=r, attachments=[r["path"]])


def _org_details(args: dict, ctx=None) -> list[str]:
    return [f"Přesunout fotky, videa a zvuky ve „{args.get('folder')}“ do složek Rok / Datum (vratné)"]


@tool("organize_media", "Uspořádá fotky, videa a zvukové nahrávky ve složce podle data pořízení do Rok / Datum (vícedenní akce dohromady), "
      "duplicity stranou. Nejdřív ukáže plán; přesouvá až na „proveď“, a jde to vrátit.", category="soubory", perm="files_write",
      danger_if=lambda a: bool(a.get("apply")), details=_org_details)
async def organize_media(ctx, folder: str, apply: bool = False, gap_hours: float = 6) -> ToolResult:
    from .. import fileuniverse, mediapro

    f = resolve(folder)
    if not f.is_dir():
        return ToolResult(False, f"Složka neexistuje: {f}")
    r = await asyncio.to_thread(mediapro.organize_plan, f, max(1.0, gap_hours))
    if not r["plan"]:
        return ToolResult(True, f"{r['files']} souborů – už je vše uspořádané.", data=r)
    if not apply:
        return ToolResult(True, f"Plán: {len(r['plan'])} přesunů do {len(r['events'])} akcí" + (f", {len(r['duplicates'])} duplicit stranou" if r["duplicates"] else "") +
                          ". Řekni „proveď“.", data=r)
    done = await asyncio.to_thread(fileuniverse.apply_rename, r["plan"])
    return ToolResult(True, f"Přesunuto {done['renamed']} souborů do {len(r['events'])} složek. Vrátit jde příkazem „vrať přejmenování“.", data={**r, **done})


@tool("podcast_chapters", "Kapitoly podcastu / dlouhé nahrávky podle změn tématu (z přepisu), s časy ve formátu pro YouTube „00:00 Název“.",
      category="média", perm="files_read")
async def podcast_chapters(ctx, file: str, min_minutes: float = 2) -> ToolResult:
    from .. import mediapro

    try:
        src = _video(file)
        segs = await asyncio.to_thread(ctx.dictation._stt().segments, str(src))
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Přepis selhal: {str(e)[:150]}")
    ch = mediapro.chapters(segs, 45, max(30.0, min_minutes * 60))
    if not ch:
        return ToolResult(True, "V nahrávce jsem neslyšel řeč.", data=[])
    text = "\n".join(f"{c['stamp']} {c['title']}" for c in ch)
    return ToolResult(True, f"{len(ch)} kapitol:\n{text}", data={"chapters": ch, "text": text})


@tool("match_shot", "Barevně sjednotí záběr podle referenčního (obrázek nebo video): náhled a 3D LUT (.cube) pro DaVinci Resolve, "
      "Premiere, Final Cut; na přání přebarví i celé video (ve frontě).", category="média", perm="files_read")
async def match_shot(ctx, file: str, reference: str, strength: float = 1.0, apply_video: bool = False) -> ToolResult:
    from PIL import Image

    from .. import mediapro

    try:
        src, ref = _video(file), _video(reference)
        a = await asyncio.to_thread(mediapro.frame_at, src)
        b = await asyncio.to_thread(mediapro.frame_at, ref)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    fn = mediapro.color_transfer_fn(a, b, max(0.0, min(strength, 1.0)))
    lut = await asyncio.to_thread(mediapro.write_cube, fn, _out("lut", f"{src.stem}-podle-{ref.stem}.cube"))
    prev = _out("lut", f"{src.stem}-nahled.png")
    await asyncio.to_thread(lambda: Image.fromarray(fn(a)).save(prev))
    data = {"lut": str(lut), "preview": str(prev)}
    msg = f"LUT {lut.name} a náhled hotové."
    if apply_video and src.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        dst = _out("lut", f"{src.stem}-sjednoceno.mp4")
        data["job"] = mediapro.queue(ctx).add("color", {"src": str(src), "dst": str(dst), "lut": str(lut)})
        msg += f" Přebarvení videa je ve frontě (úloha č. {data['job']})."
    return ToolResult(True, msg, data=data, attachments=[str(prev), str(lut)])


@tool("voiceover_fit", "Rozloží text dabingu / komentáře do scén videa podle času, řekne, kde je textu moc (kolik slov ubrat), a "
      "vytvoří titulky pro čtecí zařízení / kontrolu.", category="média", perm="files_read")
async def voiceover_fit(ctx, script: str, video: str = "", scene_seconds: list[float] | None = None, words_per_second: float = 2.5) -> ToolResult:
    from .. import media, mediapro

    try:
        if video:
            src = _video(video)
            meta = await asyncio.to_thread(mediapro.video_meta, src)
            cuts = [c["t"] for c in (await asyncio.to_thread(media.scenes, src))["cuts"]]
            marks = [0.0] + cuts + [meta["seconds"]]
            scenes = [(a, b) for a, b in zip(marks, marks[1:]) if b - a > 0.5]
        elif scene_seconds:
            t, scenes = 0.0, []
            for d in scene_seconds:
                scenes.append((t, t + float(d)))
                t += float(d)
        else:
            return ToolResult(False, "Zadej video nebo délky scén.")
        r = mediapro.fit_script(script, scenes, max(1.0, words_per_second))
    except ValueError as e:
        return ToolResult(False, str(e))
    srt = _out("dabing", f"komentar-{time.strftime('%H%M%S')}.srt")
    srt.write_text(r.pop("srt"), encoding="utf-8")
    r["srt_path"] = str(srt)
    msg = f"Text potřebuje {r['seconds_needed']:g} s, video má {r['seconds_available']:g} s."
    if r["too_long"]:
        msg += " Moc textu ve scénách: " + ", ".join(f"{x['scene']} (ubrat {x['over']} slov)" for x in r["scenes"] if x["over"])
    return ToolResult(True, msg + ".", data=r, attachments=[str(srt)])


@tool("sfx_library", "Knihovna zvukových efektů: zaindexuje složku se zvuky a hledá podle popisu (česky i anglicky: dveře, kroky, "
      "švih, potlesk…), délky, nebo „podobné jako tenhle zvuk“.", category="média", perm="files_read")
async def sfx_library(ctx, query: str = "", folder: str = "", like: str = "", max_seconds: float = 0) -> ToolResult:
    from .. import mediapro

    if folder:
        f = resolve(folder)
        if not f.is_dir():
            return ToolResult(False, f"Složka neexistuje: {f}")
        r = await asyncio.to_thread(mediapro.index_sfx, ctx, f)
        if not query and not like:
            return ToolResult(True, f"Zaindexováno {r['indexed']} zvuků (celkem v knihovně {r['total']}).", data=r)
    try:
        hits = await asyncio.to_thread(mediapro.search_sfx, ctx, query, resolve(like) if like else None, max_seconds)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    if not hits:
        return ToolResult(True, "Nic takového v knihovně nemám" + ("" if folder else " – zaindexuj nejdřív složku se zvuky") + ".", data=[])
    return ToolResult(True, "; ".join(f"{h['name']} ({h['seconds']:g} s, {h['character']})" for h in hits[:6]) + ".", data=hits)


@tool("sync_subtitles", "Srovná titulky SRT s řečí v nahrávce / videu: najde zpoždění nebo předběhnutí (i postupný posun při jiném "
      "počtu snímků) a uloží opravené titulky.", category="média", perm="files_read")
async def sync_subtitles(ctx, subtitles: str, media_file: str) -> ToolResult:
    from .. import media, mediapro

    try:
        sp, mp = _video(subtitles), _video(media_file)
        subs = media.parse_srt(sp.read_text(encoding="utf-8-sig", errors="replace"))
        if not subs:
            raise ValueError("V souboru nejsou titulky SRT.")
        x, rate = await asyncio.to_thread(media.read_audio, mp)
        r = await asyncio.to_thread(mediapro.sync_subtitles, subs, x, rate)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    dst = _out("titulky", f"{sp.stem}-srovnane.srt")
    dst.write_text(media.to_srt(r.pop("fixed")), encoding="utf-8")
    r["path"] = str(dst)
    drift = f", natažení ×{r['stretch']:g}" if r["stretch"] != 1 else ""
    return ToolResult(True, f"Posun {r['offset_s']:+g} s{drift}; shoda s řečí {r['match_before']:.0%} → {r['match_after']:.0%}. Uloženo {dst.name}.",
                      data=r, attachments=[str(dst)])


@tool("animate_elements", "Krátká animace z grafických prvků (logo, obrázky, texty): příjezd zboku / zdola, zvětšení, vyblednutí, "
      "v zadaných časech → video MP4 (intro, outro, příspěvek).", category="design", perm="files_read")
async def animate_elements(ctx, elements: Annotated[list[dict], "[{image | text, x, y (0–1), scale, start, end, effect: fade/slide-left/slide-up/zoom/pop, color, font_size}]"],
                           width: int = 1080, height: int = 1080, seconds: float = 5, background: str = "#101828") -> ToolResult:
    from .. import mediapro

    if not elements:
        return ToolResult(False, "Zadej aspoň jeden prvek.")
    els = [dict(e, image=str(resolve(e["image"]))) if e.get("image") else e for e in elements]
    missing = [e["image"] for e in els if e.get("image") and not Path(e["image"]).is_file()]
    if missing:
        return ToolResult(False, f"Obrázek neexistuje: {missing[0]}")
    try:
        r = await asyncio.to_thread(mediapro.animate, els, _out("animace", f"animace-{time.strftime('%H%M%S')}.mp4"),
                                    (max(64, min(width, 3840)), max(64, min(height, 3840))), max(0.5, min(seconds, 60)), 30, background)
    except (ValueError, OSError, KeyError) as e:
        return ToolResult(False, f"Animace selhala: {e}")
    return ToolResult(True, f"Animace {r['seconds']:g} s, {r['size'][0]}×{r['size'][1]}: {Path(r['path']).name}.", data=r, attachments=[r["path"]])


@tool("render_queue", "Fronta renderů: co čeká, co běží (kolik %), co je hotové nebo selhalo; zrušení úlohy podle čísla.", category="média")
async def render_queue(ctx, cancel: int = 0) -> ToolResult:
    from .. import mediapro

    q = mediapro.queue(ctx)
    if cancel:
        ok = q.cancel(cancel)
        return ToolResult(ok, f"Úloha č. {cancel} zrušena." if ok else f"Úlohu č. {cancel} nejde zrušit (neexistuje nebo už doběhla).")
    jobs = q.jobs()
    if not jobs:
        return ToolResult(True, "Fronta je prázdná.", data=[])
    return ToolResult(True, "; ".join(f"č. {j['id']} {j['kind']}: {j['status']}" + (f" {round(100 * j['progress'])} %" if j["status"] == "běží" else "") +
                                      (f" ({j['error'][:60]})" if j["error"] else "") for j in jobs[:8]) + ".", data=jobs)
