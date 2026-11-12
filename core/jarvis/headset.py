"""3.12 Hlas z telefonu se sluchátky: a short recording from the phone → text → JARVIS → the answer as audio.

The phone records only in its visible JARVIS window (after a beep), never in the background. Here the recording is
turned into text and deleted right away; the answer comes back as text + audio and is played in the headphones.
The PC itself stays silent – you are talking through the phone, maybe in another room.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

log = logging.getLogger("jarvis.headset")

MAX_AUDIO = 4 * 2**20          # ~2 min of 16 kHz speech; the phone stops at 15 s
SOURCE = "headset"


async def ask(rt: Any, audio: bytes, mime: str = "audio/wav") -> dict:
    if not audio:
        raise ValueError("Prázdná nahrávka")
    if len(audio) > MAX_AUDIO:
        raise ValueError("Nahrávka je moc dlouhá")
    att = await rt.store.save("telefon-hlas.wav", audio, mime or "audio/wav")
    try:
        att = await rt.store.ensure(att.id) or att
        heard = (att.text or "").strip()
        err = att.error or ""
    finally:
        rt.store.delete(att.id)              # the recording is not kept – only the text goes on, like any message
    if not heard:
        reply = ("Převod řeči na text na PC nefunguje – zkontroluj Nastavení → Hlas." if err
                 else "Nerozuměl jsem. Zkus to prosím znovu.")
        return {"heard": "", "reply": reply, **await _voice(rt, reply)}
    rt.bus.publish("transcript", text=heard, final=True)
    reply = (await rt.agent.handle(heard, [], SOURCE) or "").strip() or "Hotovo."
    return {"heard": heard, "reply": reply, **await _voice(rt, reply)}


async def _voice(rt: Any, text: str) -> dict:
    """The answer in JARVIS's own voice; without it the phone reads the text with its own Czech voice."""
    if not getattr(rt, "speaker", None):
        return {}
    try:
        audio, mime = await rt.speaker.synth(text[:1500])
    except Exception as e:  # noqa: BLE001 – the text is enough
        log.debug("headset tts: %s", e)
        return {}
    if not audio:
        return {}
    return {"audio": base64.b64encode(audio).decode("ascii"), "mime": mime}
