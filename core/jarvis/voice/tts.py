"""Text-to-speech: Microsoft Edge neural voices (free) with Piper as offline fallback; playback with levels."""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
import wave

from .. import paths
from .text import strip_markdown

log = logging.getLogger(__name__)


async def edge_synth(text: str, voice: str, rate: str, pitch: str, volume: str) -> bytes:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
    out = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            out += chunk["data"]
    if not out:
        raise RuntimeError("edge-tts vrátil prázdné audio")
    return bytes(out)


def piper_synth(text: str, voice_name: str) -> bytes:
    from piper import PiperVoice

    d = paths.sub("models") / "piper"
    d.mkdir(parents=True, exist_ok=True)
    model = d / f"{voice_name}.onnx"
    if not model.exists():
        from piper.download_voices import download_voice

        download_voice(voice_name, d)
    voice = PiperVoice.load(str(model))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w)
    return buf.getvalue()


def decode_to_pcm(data: bytes):
    """mp3/wav bytes → (float32 mono numpy, sample_rate)."""
    import numpy as np

    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data)) as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if w.getnchannels() > 1:
                pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
            return pcm, sr
    import av

    with av.open(io.BytesIO(data)) as c:
        stream = c.streams.audio[0]
        res = av.AudioResampler(format="flt", layout="mono", rate=24000)
        chunks = []
        for frame in c.decode(stream):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        return (np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)), 24000


class Speaker:
    def __init__(self, rt):
        self.rt = rt
        self.speaking = False
        self._stop = threading.Event()
        self._lock = asyncio.Lock()
        self.on_finished = None  # callback after speech ends (voice loop uses it)

    def _voice_for(self, lang: str) -> tuple[str, str]:
        v = self.rt.cfg.voice
        return (v.tts_voice_en, v.piper_voice_en) if lang == "en" else (v.tts_voice, v.piper_voice)

    async def synth(self, text: str, lang: str = "cs") -> tuple[bytes, str]:
        v = self.rt.cfg.voice
        edge_voice, piper_voice = self._voice_for(lang)
        spoken = strip_markdown(text)[:3000] or ("Done." if lang == "en" else "Hotovo.")
        try:
            return await edge_synth(spoken, edge_voice, v.tts_rate, v.tts_pitch, v.tts_volume), "audio/mpeg"
        except Exception as e:
            log.info("edge-tts failed (%s), using piper", e)
            return await asyncio.to_thread(piper_synth, spoken, piper_voice), "audio/wav"

    def stop(self) -> None:
        self._stop.set()

    async def say(self, text: str, lang: str = "cs") -> None:
        if not text.strip():
            return
        async with self._lock:
            self._stop.clear()
            try:
                audio, _mime = await self.synth(text, lang)
            except Exception as e:
                log.warning("tts failed: %s", e)
                self.rt.bus.publish("error", message=f"Hlas selhal: {e}")
                return
            self.speaking = True
            self.rt.bus.publish("state", state="speaking")
            ducker = getattr(getattr(self.rt, "voice", None), "ducker", None) if self.rt.cfg.voice.duck_media else None
            if ducker:
                ducker.acquire()
            try:
                await asyncio.to_thread(self._play, audio)
            except Exception as e:
                log.warning("playback failed: %s", e)
            finally:
                if ducker:
                    ducker.release()
                self.speaking = False
                if not self.rt.agent.busy:
                    self.rt.bus.publish("state", state="idle")
                if self.on_finished:
                    try:
                        self.on_finished()
                    except Exception:
                        pass

    def _play(self, audio: bytes) -> None:
        import numpy as np
        import sounddevice as sd

        pcm, sr = decode_to_pcm(audio)
        block = int(sr * 0.05)
        from .devices import output_index

        dev = output_index(self.rt.cfg.voice.output_device)
        echo = getattr(getattr(self.rt, "voice", None), "echo", None)
        with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", device=dev) as out:
            for i in range(0, len(pcm), block):
                if self._stop.is_set():
                    break
                chunk = pcm[i:i + block]
                if echo is not None:            # what goes to the speaker, so the mic can subtract it
                    echo.played(chunk, sr, time.monotonic())
                out.write(chunk.reshape(-1, 1))
                rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
                self.rt.bus.publish_threadsafe("level", rms=round(rms, 3))
