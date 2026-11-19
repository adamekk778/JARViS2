"""3.13 "Nahraj zvuk, co teď pustím": JARVIS records what the PC plays – a song, a video, a call's other side – into a
WAV file, from the moment you finish the sentence until you say "stop nahrávání" (or at most an hour).

Only the sound the PC plays is taken (WASAPI loopback of the default speaker, like pcaudio.py) – never the
microphone. The notch and the PC say it records the whole time.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)
SR, CH, BLOCK = 48000, 2, 2048
MAX_S = 3600


class SoundRecorder:
    def __init__(self, rt: Any, source: Callable[[], Any] | None = None):
        self.rt = rt
        self._source = source
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.path: Path | None = None
        self.started = 0.0
        self.frames = 0
        self.error = ""

    @property
    def on(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def seconds(self) -> int:
        return int(self.frames / SR)

    def status(self) -> dict:
        return {"on": self.on, "seconds": self.seconds(), "path": str(self.path or ""), "error": self.error}

    def _emit(self) -> None:
        try:
            self.rt.bus.publish_threadsafe("sound_record", **self.status())
        except Exception:  # noqa: BLE001
            pass

    def start(self, name: str = "") -> Path:
        if self.on:
            return self.path  # type: ignore[return-value]
        from . import paths

        folder = paths.data_dir() / "Nahrávky"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in " -_")[:40].strip().replace(" ", "_")
        self.path = folder / f"{safe or 'nahravka'}_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.wav"
        self._stop.clear()
        self.frames, self.error, self.started = 0, "", time.time()
        self._thread = threading.Thread(target=self._run, name="jarvis-soundrec", daemon=True)
        self._thread.start()
        self._emit()
        return self.path

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        st = self.status()
        self._emit()
        return st

    def _run(self) -> None:
        import numpy as np

        from .pcaudio import loopback_source

        try:
            src = (self._source or loopback_source)()
            with src as rec, wave.open(str(self.path), "wb") as w:
                w.setnchannels(CH)
                w.setsampwidth(2)
                w.setframerate(SR)
                last_emit = 0.0
                while not self._stop.is_set() and self.frames < SR * MAX_S:
                    data = rec.record(numframes=BLOCK)
                    if data is None or not len(data):
                        continue
                    a = np.asarray(data, dtype=np.float32)
                    if a.ndim == 1:
                        a = np.repeat(a[:, None], CH, axis=1)
                    a = a[:, :CH] if a.shape[1] >= CH else np.repeat(a, CH, axis=1)[:, :CH]
                    w.writeframes((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
                    self.frames += len(a)
                    if time.time() - last_emit > 1.0:
                        last_emit = time.time()
                        self._emit()
        except Exception as e:  # noqa: BLE001 – no speaker, no driver: said, not crashed
            self.error = str(e)[:200]
            log.warning("sound record: %s", e)


def of(rt: Any) -> SoundRecorder:
    r = getattr(rt, "sound_recorder", None)
    if r is None:
        r = SoundRecorder(rt)
        rt.sound_recorder = r
    return r
