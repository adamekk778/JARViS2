"""3.14 Hlas (návrhy 1, 37, 38, 39): voice prints of the household, the owner, the own wake word, the voice delay."""
from __future__ import annotations

import asyncio

import numpy as np

from ... import quality
from . import handles


def _state(c) -> dict:
    vid = c.rt.voiceid
    pend = getattr(vid, "pending", {}) or {}
    return {"people": vid.profiles.public(), "owner": vid.profiles.owner(), "wake_word": vid.wake.word,
            "wake_ready": vid.wake.ready, "pending": {k: len(v) for k, v in pend.items()},
            "custom_wake": bool(getattr(c.rt.cfg.voice, "custom_wake", False)),
            "owner_only": bool(getattr(c.rt.cfg.voice, "owner_only", True)), "latency": quality.voice_latency(c.rt),
            "mic": bool(getattr(c.rt, "voice", None) and getattr(c.rt.voice, "available", False))}


@handles("voiceid_get")
async def voiceid_get(c, m: dict) -> None:
    await c.send("voiceid", **_state(c))


@handles("voiceid_sample", local_only=True, slow=True)
async def voiceid_sample(c, m: dict) -> None:
    """One recording: kind "wake" = the word alone; "person" = a sentence of about 3 s."""
    loop = getattr(c.rt, "voice", None)
    if loop is None or not getattr(loop, "available", False):
        await c.send("error", message="Mikrofon teď JARVIS nemá (Nastavení → Hlas).")
        return
    kind = "wake" if m.get("kind") == "wake" else "person"
    pcm = await asyncio.to_thread(loop.record_utterance, kind == "wake", 8.0)
    if not pcm:
        await c.send("error", message="Nic jsem neslyšel – řekni to znovu, kousek blíž k mikrofonu.")
    else:
        vid = c.rt.voiceid
        vid.pending = getattr(vid, "pending", {}) or {}
        vid.pending.setdefault(kind, []).append(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0)
    await c.send("voiceid", **_state(c))


@handles("voiceid_save", local_only=True, slow=True)
async def voiceid_save(c, m: dict) -> None:
    vid = c.rt.voiceid
    pend = getattr(vid, "pending", {}) or {}
    kind = "wake" if m.get("kind") == "wake" else "person"
    samples = pend.get(kind, [])
    try:
        if kind == "wake":
            await asyncio.to_thread(vid.wake.train, str(m.get("word", "") or "vlastní slovo"), samples)
            c.rt.update_config({"voice": {"custom_wake": True}})
        else:
            name = str(m.get("name", "")).strip()[:40] or "Já"
            await asyncio.to_thread(vid.profiles.enroll, name, samples, bool(m.get("owner")))
    except ValueError as e:
        await c.send("error", message=str(e))
        await c.send("voiceid", **_state(c))
        return
    pend[kind] = []
    await c.send("voiceid", **_state(c))


@handles("voiceid_delete", local_only=True)
async def voiceid_delete(c, m: dict) -> None:
    vid = c.rt.voiceid
    if m.get("kind") == "wake":
        vid.wake.clear()
        c.rt.update_config({"voice": {"custom_wake": False}})
    else:
        vid.profiles.remove(str(m.get("name", "")))
    await c.send("voiceid", **_state(c))


@handles("voiceid_reset", local_only=True)
async def voiceid_reset(c, m: dict) -> None:
    """Throw away the recordings not saved yet."""
    c.rt.voiceid.pending = {}
    await c.send("voiceid", **_state(c))
