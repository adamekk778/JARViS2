"""3.17 Hlas po kouscích (návrh 4): the first sentence of an answer starts playing while the voice service is still
sending it – the first ~50 ms of sound play as soon as they arrive, instead of waiting for the whole sentence.

Edge (the free Microsoft voice) and ElevenLabs send MP3 in pieces; each piece is decoded at once (PyAV) and written to
the speaker. The echo path still gets every block (so you can talk over JARVIS), "Stop" still ends it at once. With a
studio effect, Piper or the Windows voice, the sentence is made whole first as before.
"""
from __future__ import annotations

import logging
import queue
import time
from typing import Any, AsyncIterator

import numpy as np

log = logging.getLogger(__name__)

STREAM_ENGINES = ("edge", "elevenlabs")


class Mp3Decoder:
    """MP3 bytes as they come → float32 mono blocks (and the sample rate once known)."""

    def __init__(self) -> None:
        import av

        self.codec = av.CodecContext.create("mp3", "r")
        self.rate = 0
        self._res: Any = None

    def feed(self, data: bytes | None) -> list[np.ndarray]:
        import av

        out: list[np.ndarray] = []
        try:
            packets = self.codec.parse(data) if data is not None else self.codec.parse(b"") + [None]
        except av.error.FFmpegError as e:            # a broken piece: skip it, keep going
            log.debug("mp3 parse: %s", e)
            return out
        for pkt in packets:
            try:
                frames = self.codec.decode(pkt)
            except av.error.FFmpegError as e:
                log.debug("mp3 decode: %s", e)
                continue
            for fr in frames:
                if not self.rate:
                    self.rate = fr.sample_rate
                    self._res = av.AudioResampler(format="flt", layout="mono", rate=self.rate)
                for r in self._res.resample(fr):
                    out.append(r.to_ndarray().reshape(-1).astype(np.float32))
        return out


def play_queue(speaker: Any, chunks: "queue.Queue[bytes | None]", rt: Any, gain_db: float = 1.0) -> bool:
    """In a thread: decode what arrives in `chunks` (None = the end) and play it; True when something was played."""
    import sounddevice as sd

    from .devices import output_index
    from .style import mark_sound

    dec = Mp3Decoder()
    dev = output_index(rt.cfg.voice.output_device)
    echo = getattr(getattr(rt, "voice", None), "echo", None)
    out = None
    played = False
    try:
        while True:
            data = chunks.get(timeout=20)
            blocks = dec.feed(data)
            for b in blocks:
                if speaker._stop.is_set():
                    return played
                if gain_db != 1.0:
                    b = b * gain_db
                if out is None:
                    out = sd.OutputStream(samplerate=dec.rate, channels=1, dtype="float32", device=dev)
                    out.start()
                if echo is not None:
                    echo.played(b, dec.rate, time.monotonic())
                out.write(b.reshape(-1, 1))
                if not played:
                    played = True
                    mark_sound(rt)
                    cb = getattr(speaker, "on_first_sound", None)
                    if cb is not None:
                        try:
                            cb()
                        except Exception:  # noqa: BLE001
                            pass
                rms = float(np.sqrt(np.mean(b ** 2))) if len(b) else 0.0
                rt.bus.publish_threadsafe("level", rms=round(rms, 3))
            if data is None:
                return played
    except queue.Empty:
        return played
    finally:
        if out is not None:
            try:
                out.stop()
                out.close()
            except Exception:  # noqa: BLE001
                pass


async def edge_chunks(text: str, voice: str, rate: str, pitch: str, volume: str) -> AsyncIterator[bytes]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
    async for chunk in comm.stream():
        if chunk["type"] == "audio" and chunk.get("data"):
            yield chunk["data"]


async def eleven_chunks(text: str, key: str, voice_id: str, model: str, transport: Any = None) -> AsyncIterator[bytes]:
    import re

    from .. import tlsctx
    from ..llm import pool
    from .studio import ELEVEN_API

    if not key or not re.fullmatch(r"[A-Za-z0-9]{8,64}", voice_id or ""):
        raise RuntimeError("ElevenLabs: chybí klíč nebo hlas")
    async with pool.client(transport, 60, tlsctx.context()) as c:
        async with c.stream("POST", f"{ELEVEN_API}/text-to-speech/{voice_id}/stream", params={"output_format": "mp3_44100_128"},
                            headers={"xi-api-key": key, "accept": "audio/mpeg"},
                            json={"text": text, "model_id": model or "eleven_multilingual_v2"}, timeout=60) as r:
            if r.status_code != 200:
                raise RuntimeError(f"ElevenLabs: HTTP {r.status_code}")
            async for part in r.aiter_bytes():
                if part:
                    yield part
