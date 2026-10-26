"""Speech-to-text: faster-whisper locally (offline) or Groq Whisper API."""
from __future__ import annotations

import io
import logging
import threading
import wave

from .. import paths, secrets

log = logging.getLogger(__name__)


def pcm_to_wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


class Transcriber:
    def __init__(self, cfg_voice, groq_base: str = "https://api.groq.com/openai/v1"):
        self.cfg = cfg_voice
        self.groq_base = groq_base
        self._model = None
        self._model_name = None
        self._lock = threading.Lock()
        self.error: str | None = None
        self.last_language = "cs"

    def update(self, cfg_voice) -> None:
        self.cfg = cfg_voice

    def _language(self):
        lang = self.cfg.stt_language
        return None if lang in ("", "auto") else lang

    def warmup(self) -> None:
        if self.cfg.stt_provider == "local":
            try:
                self._local()
            except Exception as e:
                self.error = str(e)
                log.warning("whisper load failed: %s", e)

    def _local(self):
        with self._lock:
            name = self.cfg.stt_model
            if self._model is None or self._model_name != name:
                from faster_whisper import WhisperModel

                device = "cpu"
                try:
                    import ctranslate2

                    if ctranslate2.get_cuda_device_count() > 0:
                        device = "cuda"
                except Exception:
                    pass
                log.info("loading whisper %s on %s", name, device)
                root = str(paths.sub("models") / "whisper")
                model = None
                if device == "cuda":
                    try:  # needs cuBLAS/cuDNN DLLs, which most PCs don't have → test, else CPU
                        import numpy as np

                        model = WhisperModel(name, device="cuda", compute_type="float16", download_root=root)
                        list(model.transcribe(np.zeros(16000, dtype=np.float32))[0])
                    except Exception as e:
                        log.info("CUDA whisper unavailable (%s), using CPU", e)
                        model = None
                self._model = model or WhisperModel(name, device="cpu", compute_type="int8", download_root=root)
                self._model_name = name
            return self._model

    def _groq(self, wav: bytes, filename: str = "audio.wav", prompt: str = "") -> str:
        import httpx

        key = secrets.get("groq")
        if not key:
            raise RuntimeError("Groq API klíč není nastavený (poskytovatel 'groq' v Nastavení → Mozek)")
        data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
        if self._language():
            data["language"] = self._language()
        if prompt:
            data["prompt"] = prompt[:800]
        r = httpx.post(f"{self.groq_base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       files={"file": (filename, wav)}, data=data, timeout=60)
        r.raise_for_status()
        text = r.json().get("text", "").strip()
        from ..lang import detect

        self.last_language = detect(text)
        return text

    def transcribe(self, pcm16: bytes, sr: int = 16000, prompt: str = "") -> str:
        """prompt: words the recognizer should expect (names from the dictation dictionary)."""
        if self.cfg.stt_provider == "groq":
            try:
                return self._groq(pcm_to_wav(pcm16, sr), prompt=prompt)
            except Exception as e:
                log.warning("groq stt failed, falling back to local: %s", e)
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if sr != 16000:
            idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
            audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
        return self._run(audio, prompt)

    def transcribe_file(self, path: str) -> str:
        if self.cfg.stt_provider == "groq":
            try:
                with open(path, "rb") as f:
                    return self._groq(f.read(), filename=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
            except Exception as e:
                log.warning("groq stt failed, falling back to local: %s", e)
        return self._run(path)

    def segments(self, path: str, progress=None) -> list[tuple[float, float, str]]:
        """(start, end, text) for a whole recording (Notetaker). progress(fraction) is called as it goes."""
        if self.cfg.stt_provider == "groq":
            try:
                return self._groq_segments(path)
            except Exception as e:
                log.warning("groq segments failed, falling back to local: %s", e)
        model = self._local()
        segs, info = model.transcribe(path, language=self._language(), beam_size=1, vad_filter=True,
                                      condition_on_previous_text=False)
        total = float(getattr(info, "duration", 0) or 0)
        out = []
        for s in segs:
            if s.text.strip():
                out.append((float(s.start), float(s.end), s.text.strip()))
            if progress and total:
                progress(min(1.0, float(s.end) / total))
        return out

    def _groq_segments(self, path: str) -> list[tuple[float, float, str]]:
        import httpx

        key = secrets.get("groq")
        if not key:
            raise RuntimeError("Groq API klíč není nastavený")
        data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json"}
        if self._language():
            data["language"] = self._language()
        with open(path, "rb") as f:
            r = httpx.post(f"{self.groq_base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                           files={"file": ("audio.wav", f.read())}, data=data, timeout=600)
        r.raise_for_status()
        return [(float(s["start"]), float(s["end"]), s["text"].strip()) for s in r.json().get("segments", []) if s.get("text", "").strip()]

    def _run(self, audio, prompt: str = "") -> str:
        model = self._local()
        segments, info = model.transcribe(audio, language=self._language(), beam_size=1, vad_filter=True,
                                          condition_on_previous_text=False, initial_prompt=prompt or None)
        text = " ".join(s.text.strip() for s in segments).strip()
        from ..lang import detect

        self.last_language = "en" if getattr(info, "language", "") == "en" or detect(text) == "en" else "cs"
        return text
