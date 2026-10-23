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

                device, compute = "cpu", "int8"
                try:
                    import ctranslate2

                    if ctranslate2.get_cuda_device_count() > 0:
                        device, compute = "cuda", "float16"
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

    def _groq(self, wav: bytes, filename: str = "audio.wav") -> str:
        import httpx

        key = secrets.get("groq")
        if not key:
            raise RuntimeError("Groq API klíč není nastavený (poskytovatel 'groq' v Nastavení → Mozek)")
        data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
        if self._language():
            data["language"] = self._language()
        r = httpx.post(f"{self.groq_base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       files={"file": (filename, wav)}, data=data, timeout=60)
        r.raise_for_status()
        return r.json().get("text", "").strip()

    def transcribe(self, pcm16: bytes, sr: int = 16000) -> str:
        if self.cfg.stt_provider == "groq":
            try:
                return self._groq(pcm_to_wav(pcm16, sr))
            except Exception as e:
                log.warning("groq stt failed, falling back to local: %s", e)
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if sr != 16000:
            idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
            audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
        return self._run(audio)

    def transcribe_file(self, path: str) -> str:
        if self.cfg.stt_provider == "groq":
            try:
                with open(path, "rb") as f:
                    return self._groq(f.read(), filename=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
            except Exception as e:
                log.warning("groq stt failed, falling back to local: %s", e)
        return self._run(path)

    def _run(self, audio) -> str:
        model = self._local()
        segments, _info = model.transcribe(audio, language=self._language(), beam_size=1, vad_filter=True,
                                           condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()
