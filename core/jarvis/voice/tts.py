"""Text-to-speech: Microsoft Edge neural voices (free) with Piper as offline fallback; playback with levels."""
from __future__ import annotations

import asyncio
import io
import logging
import re
import sys
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


def windows_synth(text: str, lang: str = "cs") -> bytes:
    """The last resort, offline: the voice built into Windows (System.Speech) – no download, no internet. On a real PC
    the firewall refused JARVIS's internet, Edge and Piper both failed, and JARVIS said nothing at all."""
    import os
    import subprocess
    import tempfile

    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    script = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like $env:JV_LANG } | Select-Object -First 1; "
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; $s.SetOutputToWaveFile($env:JV_OUT); "
              "$s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
    env = {**os.environ, "JV_OUT": out, "JV_LANG": "en*" if lang == "en" else "cs*"}
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], input=text.encode("utf-8"), env=env, timeout=60,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with open(out, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    if len(data) < 1000:
        raise RuntimeError("hlas Windows nic nevytvořil")
    return data


_PIPER: dict = {}


def piper_synth(text: str, voice_name: str, custom: bool = False) -> bytes:
    if not re.fullmatch(r"[\w.-]{1,80}", voice_name) or voice_name.startswith("."):
        raise RuntimeError("neplatný název hlasu")
    from piper import PiperVoice

    d = paths.sub("models") / "piper"
    d.mkdir(parents=True, exist_ok=True)
    model = (d / "custom" if custom else d) / f"{voice_name}.onnx"
    if custom and not model.exists():
        raise RuntimeError(f"vlastní hlas {voice_name} už není ve složce hlasů")
    if not model.exists():
        from piper.download_voices import download_voice

        download_voice(voice_name, d)
    key = str(model)
    voice = _PIPER.get(key)
    if voice is None:                              # 3.16 loaded once, not for every sentence (0.3–1.5 s each time)
        voice = PiperVoice.load(key)
        if len(_PIPER) >= 2:
            _PIPER.pop(next(iter(_PIPER)))
        _PIPER[key] = voice
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

    PHRASE_MAX = 48            # 3.16 short phrases ("Moment, pane.", "Hotovo.") are kept ready – heard at once
    COMMON = ("Moment, {a}.", "Hned to bude, {a}.", "Pracuji na tom, {a}.", "Hotovo.", "Další.", "Předchozí.",
              "Rozumím, {a}.", "Ano, {a}?")

    def _phrase_key(self, text: str, lang: str) -> tuple | None:
        if len(text) > self.PHRASE_MAX:
            return None
        v = self.rt.cfg.voice
        try:
            from .style import prosody

            pros = tuple(prosody(self.rt, v))
        except Exception:  # noqa: BLE001
            pros = ()
        return (text, lang, v.tts_engine, v.tts_voice, v.tts_voice_en, v.piper_voice, v.piper_custom, v.eleven_voice_id,
                v.effect, pros)

    async def prepare_phrases(self) -> int:
        """Make the common short phrases ready in the background (not with ElevenLabs – it would cost credits)."""
        if self.rt.cfg.voice.tts_engine == "elevenlabs":
            return 0
        a = (self.rt.cfg.general.address_as or "pane").strip()
        n = 0
        for t in self.COMMON:
            try:
                await self.synth(t.format(a=a))
                n += 1
            except Exception as e:  # noqa: BLE001
                log.debug("phrase %s: %s", t, e)
                break
        return n

    def has_phrase(self, text: str, lang: str = "cs") -> bool:
        key = self._phrase_key(text.strip(), lang)
        return key is not None and key in (getattr(self, "_phrases", None) or {})

    def can_stream(self) -> bool:
        """3.17 the sentence can play while it is being made (Edge / ElevenLabs, no studio effect, PyAV there)."""
        from .streamplay import STREAM_ENGINES

        v = self.rt.cfg.voice
        if v.tts_engine not in STREAM_ENGINES or v.effect != "none" or not getattr(v, "stream_voice", True):
            return False
        try:
            import av  # noqa: F401

            return True
        except ImportError:
            return False

    async def stream_and_play(self, text: str, lang: str = "cs") -> bool:
        """3.17 make and play one sentence at the same time; False = nothing played (then the usual way)."""
        import queue as _q

        from .streamplay import edge_chunks, eleven_chunks, play_queue
        from .style import gain, pronounce, prosody

        v = self.rt.cfg.voice
        spoken = strip_markdown(text)[:3000]
        if not spoken.strip():
            return False
        if lang != "en":
            spoken = pronounce(self.rt.cfg, spoken)
        q: _q.Queue = _q.Queue()
        g = 1.0
        if v.tts_engine == "elevenlabs":
            from .. import secrets

            model = "eleven_flash_v2_5" if getattr(v, "low_latency", False) else v.eleven_model
            gen = eleven_chunks(spoken, secrets.get("elevenlabs"), v.eleven_voice_id, model)
            g = gain(self.rt)
        else:
            e_rate, e_pitch, e_vol = prosody(self.rt, v)
            gen = edge_chunks(spoken, v.tts_voice_en if lang == "en" else v.tts_voice, e_rate, e_pitch, e_vol)
        player = asyncio.get_running_loop().run_in_executor(None, play_queue, self, q, self.rt, g)
        try:
            async for part in gen:
                q.put(part)
                if self._stop.is_set():
                    break
        except Exception as e:  # noqa: BLE001 – the service failed: the usual way takes over (if nothing played)
            log.info("streamed voice failed: %s", e)
        q.put(None)
        try:
            return bool(await player)
        except Exception as e:  # noqa: BLE001
            log.info("streamed playback failed: %s", e)
            return False

    async def synth(self, text: str, lang: str = "cs", override: dict | None = None) -> tuple[bytes, str]:
        """The chosen engine (Edge, Piper incl. an own voice, ElevenLabs), then the others as a fallback, and the
        studio effect on top. `override` = unsaved studio settings for a preview."""
        key = None if override else self._phrase_key(text.strip(), lang)
        cache = getattr(self, "_phrases", None)
        if cache is None:
            cache = self._phrases = {}
        if key is not None and key in cache:
            return cache[key]
        out = await self._synth(text, lang, override)
        if key is not None:
            if len(cache) > 64:
                cache.pop(next(iter(cache)))
            cache[key] = out
        return out

    async def _synth(self, text: str, lang: str = "cs", override: dict | None = None) -> tuple[bytes, str]:
        v = self.rt.cfg.voice.model_copy(update=override) if override else self.rt.cfg.voice
        edge_voice, piper_voice = (v.tts_voice_en, v.piper_voice_en) if lang == "en" else (v.tts_voice, v.piper_voice)
        spoken = strip_markdown(text)[:3000] or ("Done." if lang == "en" else "Hotovo.")
        from .style import pronounce, prosody

        if lang != "en":
            spoken = pronounce(self.rt.cfg, spoken)          # 3.14 your own "how to say it"
        e_rate, e_pitch, e_vol = prosody(self.rt, v)        # 3.14 tone by the time of day, a whisper
        order = [v.tts_engine] + [e for e in ("edge", "piper") if e != v.tts_engine] + (["windows"] if sys.platform == "win32" else [])
        audio, mime, err = b"", "", None
        for eng in order:
            try:
                if eng == "elevenlabs":
                    from .. import secrets
                    from .studio import eleven_synth

                    model = "eleven_flash_v2_5" if getattr(v, "low_latency", False) else v.eleven_model   # 3.16 ~75 ms model
                    audio, mime = await eleven_synth(spoken, secrets.get("elevenlabs"), v.eleven_voice_id, model), "audio/mpeg"
                elif eng == "windows":
                    audio, mime = await asyncio.to_thread(windows_synth, spoken, lang), "audio/wav"
                elif eng == "piper":
                    own = bool(v.piper_custom) and lang != "en"
                    args = (spoken, v.piper_custom, True) if own else (spoken, piper_voice)
                    audio = await asyncio.to_thread(piper_synth, *args)
                    mime = "audio/wav"
                else:
                    audio, mime = await edge_synth(spoken, edge_voice, e_rate, e_pitch, e_vol), "audio/mpeg"
                break
            except Exception as e:
                err = e
                log.info("tts %s failed (%s)%s", eng, e, ", trying the next engine" if eng != order[-1] else "")
        if not audio:
            raise RuntimeError(str(err) if err else "žádný hlas nefunguje")
        if v.effect != "none":
            from .studio import apply_effect, encode_wav

            pcm, sr = await asyncio.to_thread(decode_to_pcm, audio)
            audio, mime = encode_wav(await asyncio.to_thread(apply_effect, pcm, sr, v.effect), sr), "audio/wav"
        return audio, mime

    async def backchannel(self) -> bool:
        """3.16 a quiet "mhm" while you think aloud (live conversation): played beside the microphone, never waits."""
        try:
            audio, _ = await self.synth("Mhm.")
        except Exception as e:  # noqa: BLE001
            log.debug("backchannel: %s", e)
            return False
        threading.Thread(target=self._play, args=(audio,), daemon=True, name="mhm").start()
        return True

    def stop(self) -> None:
        self._stop.set()

    async def say(self, text: str, lang: str = "cs", reply_to: str = "") -> None:
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
                        self.on_finished(reply_to)
                    except Exception:
                        pass

    def _play(self, audio: bytes) -> None:
        import numpy as np
        import sounddevice as sd

        pcm, sr = decode_to_pcm(audio)
        from .style import gain, mark_sound

        if getattr(self.rt.cfg.voice, "tts_engine", "edge") != "edge":   # Edge got the volume in its request
            g = gain(self.rt)
            if g != 1.0:
                pcm = pcm * g
        block = int(sr * 0.05)
        first = True
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
                if first:                       # 3.14 návrh 1: the delay from the end of your sentence to this
                    first = False
                    mark_sound(self.rt)
                rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
                self.rt.bus.publish_threadsafe("level", rms=round(rms, 3))
