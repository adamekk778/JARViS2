"""OMEGA wave 28 by voice: microphone check, wake-word calibration, bookmarks, speaker labels in a recording and
pronunciation practice. Every recording here shows JARVIS as listening (notch) and lands in the microphone history."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


async def _record(ctx, seconds: float):
    """Visible recording from the configured microphone (state "listening" → notch + microphone history)."""
    from ..voice import dsp

    ctx.bus.publish("state", state="listening")
    try:
        return await asyncio.to_thread(dsp.record, seconds, 16000, ctx.cfg.voice.input_device or None)
    finally:
        ctx.bus.publish("state", state="idle")


@tool("mic_check", "Zkontroluje mikrofon: pár vteřin nahraje (mluv normálně), změří šum v pozadí, hlasitost řeči, odstup řeči "
      "od šumu a přebuzení a poradí, co zlepšit (blíž, citlivost, filtr hluku, automatické zesílení).", category="systém", perm="system")
async def mic_check(ctx, seconds: float = 4) -> ToolResult:
    from ..voice import dsp

    try:
        x = await _record(ctx, max(1.0, min(seconds, 15)))
        r = dsp.mic_report(x)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – no microphone / blocked by Windows privacy settings
        return ToolResult(False, f"Mikrofon nejde použít: {str(e)[:150]}. Zkontroluj Nastavení Windows → Soukromí → Mikrofon.")
    return ToolResult(True, f"Mikrofon {r['verdict']}: řeč {r['speech_dbfs']} dBFS, šum {r['noise_dbfs']} dBFS, odstup {r['snr_db']} dB" +
                      (". " + "; ".join(r["advice"]) if r["advice"] else "") + ".", data=r)


@tool("wake_word_calibrate", "Nastaví citlivost „Hey Jarvis“ podle tvé místnosti: krok „ticho“ změří okolní zvuk (televize, "
      "hovor), krok „fraze“ změří, jak silně zní tvoje vyslovení (řekni ji 3–5×). Pak doporučí práh a na požádání ho uloží.",
      category="systém", perm="system")
async def wake_word_calibrate(ctx, step: Annotated[str, "ticho / fraze / vysledek"] = "vysledek", seconds: float = 10, apply: bool = False) -> ToolResult:
    from ..voice import dsp
    from .. import voiceplus

    v = getattr(ctx, "voice", None)
    if v is None or not getattr(v, "available", False) or not ctx.cfg.voice.wake_word:
        return ToolResult(False, "Naslouchání „Hey Jarvis“ teď neběží – zapni ho v Nastavení → Hlas.")
    calib = v.__dict__.setdefault("calibration", {"quiet": [], "words": []})
    if step in ("ticho", "quiet"):
        scores = await asyncio.to_thread(v.collect_wake_scores, max(3.0, min(seconds, 60)))
        calib["quiet"] = scores
        return ToolResult(True, f"Okolní zvuk změřen ({len(scores)} vzorků, nejvyšší skóre {max(scores, default=0):.2f}). Teď krok „fraze“.",
                          data={"max": max(scores, default=0)})
    if step in ("fraze", "fráze", "word"):
        scores = await asyncio.to_thread(v.collect_wake_scores, max(3.0, min(seconds, 60)))
        calib["words"] = voiceplus.peaks(scores)
        if not calib["words"]:
            return ToolResult(False, "Frázi jsem vůbec neslyšel – řekni „Hey Jarvis“ zřetelně několikrát během měření.")
    try:
        r = dsp.recommend_threshold(calib["quiet"], calib["words"])
    except ValueError as e:
        return ToolResult(False, str(e))
    if apply and r["ok"]:
        ctx.update_config({"voice": {"wake_threshold": r["threshold"]}})
        r["applied"] = True
    return ToolResult(True, r["advice"] + (" Uloženo." if r.get("applied") else " Řekni „ulož“, a nastavím ho." if r["ok"] else ""), data=r)


@tool("voice_bookmark", "Záložka: „tohle si označ“ – při nahrávání hovoru na právě této vteřině, jinak u poslední výměny v "
      "konverzaci. Volitelně s názvem.", category="paměť")
async def voice_bookmark(ctx, label: str = "") -> ToolResult:
    from .. import voiceplus

    try:
        r = voiceplus.add_bookmark(ctx, label)
    except ValueError as e:
        return ToolResult(False, str(e))
    if r["kind"] == "note":
        return ToolResult(True, f"Označeno v nahrávce na {voiceplus._fmt(r['at'])}" + (f" („{label}“)" if label else "") + ".", data=r)
    return ToolResult(True, "Označeno v konverzaci" + (f" („{label}“)" if label else "") + ".", data=r)


@tool("voice_bookmarks", "Moje záložky z hovorů a konverzací (volitelně podle slova), s tím, co tam zaznělo.", category="paměť")
async def voice_bookmarks(ctx, query: str = "") -> ToolResult:
    from .. import voiceplus

    r = voiceplus.bookmarks(ctx, query)
    if not r:
        return ToolResult(True, "Žádné záložky." if not query else f"Žádná záložka s „{query}“.", data=[])
    return ToolResult(True, " | ".join(f"{b['when']}{' ' + b['at'] if b.get('at') else ''} {b['label'] or ''}: {b['context'][:120]}".strip()
                                       for b in r[:8]), data=r)


@tool("label_speakers", "Přepis nahrávky (porada, rozhovor, podcast) s rozlišením mluvčích podle hlasu: kdo mluvil kdy "
      "(Mluvčí 1, 2…), volitelně se známým počtem lidí.", category="média", perm="files_read")
async def label_speakers(ctx, file: str, speakers: int = 0) -> ToolResult:
    from .. import media
    from ..voice import dsp

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Nahrávka neexistuje: {p}")
    try:
        segs = await asyncio.to_thread(ctx.dictation._stt().segments, str(p))
        x, rate = await asyncio.to_thread(media.read_audio, p)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Nahrávku nejde zpracovat: {str(e)[:150]}")
    if not segs:
        return ToolResult(True, "V nahrávce jsem neslyšel řeč.", data={"lines": []})
    r = await asyncio.to_thread(dsp.diarize, media._mono(x), rate, [(s, e) for s, e, _ in segs], max(0, speakers))
    lines = []
    for (s, e, t), lab in zip(segs, r["labels"]):
        who = f"Mluvčí {lab + 1}"
        if lines and lines[-1]["who"] == who and s - lines[-1]["end"] < 2.5:
            lines[-1]["text"] += " " + t
            lines[-1]["end"] = e
        else:
            lines.append({"who": who, "start": s, "end": e, "text": t})
    talk = {}
    for ln in lines:
        talk[ln["who"]] = talk.get(ln["who"], 0) + ln["end"] - ln["start"]
    share = ", ".join(f"{k} {round(100 * v / sum(talk.values()))} %" for k, v in sorted(talk.items()))
    return ToolResult(True, f"{r['speakers']} mluvčí ({share}). " + " | ".join(f"{ln['who']}: {ln['text'][:80]}" for ln in lines[:6]),
                      data={"lines": lines, "speakers": r["speakers"], "confidence": r["confidence"], "talk_seconds": talk})


@tool("pronunciation_practice", "Nácvik výslovnosti: přečti nahlas zadanou větu (nahraje se, nebo dej nahrávku) a JARVIS řekne, "
      "která slova vyslovuješ špatně nebo nezřetelně, co vynecháváš a jak rychle mluvíš.", category="učení", perm="system")
async def pronunciation_practice(ctx, sentence: str, audio: str = "", seconds: float = 0, language: Annotated[str, "cs / en / de …"] = "") -> ToolResult:
    from .. import voiceplus

    stt = ctx.dictation._stt()
    try:
        if audio:
            p = resolve(audio)
            if not p.is_file():
                return ToolResult(False, f"Nahrávka neexistuje: {p}")
            words = await asyncio.to_thread(stt.words, str(p), language or None)
        else:
            dur = seconds or min(20.0, 2.5 + len(sentence.split()) * 0.6)
            x = await _record(ctx, dur)
            words = await asyncio.to_thread(stt.words, x, language or None)
        r = voiceplus.pronunciation(sentence, words)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – no mic / recogniser not available
        return ToolResult(False, f"Nahrávání nebo rozpoznání selhalo: {str(e)[:150]}")
    msg = f"Výslovnost {r['score']} % ({r['good']} z {r['total']} slov jasně)."
    if r["tips"]:
        msg += " " + ". ".join(r["tips"]) + "."
    return ToolResult(True, msg, data=r)
