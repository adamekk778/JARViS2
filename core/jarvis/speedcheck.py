"""3.17 Změřit rychlost (návrh 2): one button in Diagnostika goes through typical requests that only read and never change anything, and measures every step on YOUR PC with
YOUR AI, voice and network:

- for each request: the way it went (bez AI / reflex / AI s katalogem / AI), the first word, the whole answer,
- the voice both ways without a microphone: each sentence is spoken by JARVIS's voice (the time to the first sound)
  and that sound is written down again by the speech recognizer (its time, and whether the words came back right).
The requests run in their own conversation, which is removed afterwards. Nothing is sent anywhere except the usual
questions to your AI and voice; the result stays in the data folder (speedcheck-*.json) and in Diagnostika.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import statistics
import time
from typing import Any

log = logging.getLogger(__name__)

REQUESTS = [  # only reading: nothing is opened, played, changed or sent
    "kolik je hodin", "jaké je dnes datum", "jaké je počasí", "jaké bude zítra počasí", "co mám dnes v kalendáři",
    "kolik stojí bitcoin", "kolik je 100 eur", "jak je na tom počítač", "kolik mám volného místa na disku",
    "co je nového ve světě", "kdo napsal Babičku", "kolik je 17 krát 23", "vysvětli jednou větou, co je fotosyntéza",
    "přelož do angličtiny dobré ráno", "jaké je hlavní město Austrálie", "co mám na nákupním seznamu",
    "kolik je stupňů venku", "jak dlouho jsem dnes u počítače", "co teď hraje", "dej mi jeden tip na produktivitu",
]
VOICE_LINES = ["Kolik je hodin?", "Jaké bude zítra počasí v Praze?", "Přidej mléko na nákupní seznam.",
               "Pusť lo-fi hudbu na YouTube.", "Rozsviť v kuchyni."]


def _how(info: dict) -> str:
    if info.get("instant"):
        return "bez AI"
    if info.get("reflex") or info.get("reflex_model"):
        return "reflex"
    return "AI s katalogem" if info.get("catalog") else "AI"


async def run_requests(rt: Any, requests: list[str] | None = None, progress=None) -> list[dict]:
    from . import latency

    lat = latency.get(rt)
    mem = rt.memory
    before = getattr(mem, "current_conversation", "")
    cid = mem.new_conversation("Měření rychlosti")
    out: list[dict] = []
    rt.speedcheck_running = True                   # the tool memory does not learn from these requests
    try:
        for i, text in enumerate(requests or REQUESTS):
            t0 = time.monotonic()
            try:
                answer = await asyncio.wait_for(rt.agent.handle(text, [], "chat"), timeout=90)
            except asyncio.TimeoutError:
                answer = "(přes 90 s)"
            total = round((time.monotonic() - t0) * 1000)
            turn = lat.turns[-1] if lat.turns else {"marks": {}, "info": {}}
            out.append({"text": text, "how": _how(turn["info"]), "first_word_ms": turn["marks"].get("first_token"),
                        "total_ms": total, "tools": turn["info"].get("tools", 0),
                        "found_tool_first_try": not turn["info"].get("find_tools") and not turn["info"].get("use_tool_errors"),
                        "answer": str(answer or "")[:120]})
            if progress:
                progress(i + 1, len(requests or REQUESTS), out[-1])
    finally:
        rt.speedcheck_running = False
        try:
            mem.delete_conversation(cid)
            if before:
                mem.switch(before)
        except Exception as e:  # noqa: BLE001
            log.debug("speedcheck cleanup: %s", e)
    return out


async def run_voice(rt: Any, lines: list[str] | None = None) -> list[dict]:
    """The voice there and back: synthesis time (to the first sound) and the recognizer's time and accuracy."""
    speaker = getattr(rt, "speaker", None)
    voice = getattr(rt, "voice", None)
    if speaker is None:
        return []
    out = []
    for line in lines or VOICE_LINES:
        row: dict[str, Any] = {"text": line}
        t0 = time.monotonic()
        try:
            audio, _ = await speaker._synth(line) if hasattr(speaker, "_synth") else await speaker.synth(line)
            row["tts_ms"] = round((time.monotonic() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            row["error"] = f"hlas: {e}"
            out.append(row)
            continue
        if voice is not None and getattr(voice, "transcriber", None) is not None:
            try:
                import numpy as np

                from .voice.tts import decode_to_pcm

                pcm, sr = await asyncio.to_thread(decode_to_pcm, audio)
                if sr != 16000:
                    idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * 16000 / sr))
                    pcm = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.float32)
                pcm16 = (np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes()
                t1 = time.monotonic()
                heard = await asyncio.to_thread(voice.transcriber.transcribe, pcm16, 16000)
                row["stt_ms"] = round((time.monotonic() - t1) * 1000)
                row["heard"] = heard
                row["match"] = round(difflib.SequenceMatcher(None, _plain(line), _plain(heard)).ratio(), 2)
            except Exception as e:  # noqa: BLE001
                row["error"] = f"rozpoznávání: {e}"
        out.append(row)
    return out


def _plain(s: str) -> str:
    import re
    import unicodedata

    t = "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))
    return re.sub(r"[^\w ]", "", t).strip()


def summary(reqs: list[dict], voice: list[dict]) -> dict:
    def med(vals: list) -> int | None:
        vals = [v for v in vals if isinstance(v, (int, float))]
        return int(statistics.median(vals)) if vals else None
    hows: dict[str, int] = {}
    for r in reqs:
        hows[r["how"]] = hows.get(r["how"], 0) + 1
    with_tools = [r for r in reqs if r["tools"]]
    return {"requests": len(reqs), "first_word_ms": med([r["first_word_ms"] for r in reqs]),
            "total_ms": med([r["total_ms"] for r in reqs]), "ways": hows,
            "first_try_pct": round(100 * sum(r["found_tool_first_try"] for r in with_tools) / len(with_tools)) if with_tools else None,
            "tts_ms": med([v.get("tts_ms") for v in voice]), "stt_ms": med([v.get("stt_ms") for v in voice]),
            "stt_match": round(statistics.mean([v["match"] for v in voice if "match" in v]), 2) if any("match" in v for v in voice) else None}


async def run(rt: Any, voice: bool = True, progress=None) -> dict:
    reqs = await run_requests(rt, progress=progress)
    vo = await run_voice(rt) if voice else []
    rep = {"ts": time.time(), "summary": summary(reqs, vo), "requests": reqs, "voice": vo}
    try:
        from . import paths

        p = paths.data_dir() / f"speedcheck-{time.strftime('%Y%m%d-%H%M%S')}.json"
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        rep["file"] = str(p)
    except OSError:
        pass
    rt.last_speedcheck = rep
    return rep


def say(rep: dict) -> str:
    s = rep["summary"]
    parts = [f"{s['requests']} dotazů: první slovo za {_ms(s['first_word_ms'])}, celá odpověď za {_ms(s['total_ms'])}"]
    if s["ways"]:
        parts.append("cesty: " + ", ".join(f"{k} {v}×" for k, v in s["ways"].items()))
    if s["first_try_pct"] is not None:
        parts.append(f"nástroj napoprvé {s['first_try_pct']} %")
    if s["tts_ms"] is not None:
        parts.append(f"hlas {_ms(s['tts_ms'])}")
    if s["stt_ms"] is not None:
        parts.append(f"rozpoznání {_ms(s['stt_ms'])} (přesnost {int((s['stt_match'] or 0) * 100)} %)")
    return "; ".join(parts) + "."


def _ms(v: int | None) -> str:
    if v is None:
        return "–"
    return f"{v / 1000:.1f} s".replace(".", ",") if v >= 1000 else f"{v} ms"
