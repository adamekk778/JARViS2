"""The always-on voice loop: wake word → listen → transcribe → agent → speak."""
from __future__ import annotations

import logging
import queue
import threading
import time

from .stt import Transcriber
from .text import Endpointer, parse_yes_no
from .tts import Speaker

log = logging.getLogger(__name__)
SR = 16000
FRAME = 1280  # 80 ms, what openWakeWord expects


def load_wakeword(name: str):
    import openwakeword
    from openwakeword.model import Model

    try:  # openwakeword >= 0.5
        try:
            openwakeword.utils.download_models([name])
        except Exception:
            pass
        return Model(wakeword_models=[name], inference_framework="onnx")
    except TypeError:  # 0.4.x
        return Model(wakeword_model_paths=[openwakeword.models[name]["model_path"]])


class VoiceLoop:
    def __init__(self, rt):
        self.rt = rt
        self.speaker = Speaker(rt)
        self.speaker.on_finished = self._after_speech
        self.transcriber = Transcriber(rt.cfg.voice)
        self.available = False
        self.paused = False
        self.listening = False
        self.error: str | None = None
        self._ptt = threading.Event()
        self._confirm_id: str | None = None
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self._stream = None
        self._thread: threading.Thread | None = None
        self._restart = threading.Event()

    # ---------- public ----------
    def start(self) -> None:
        threading.Thread(target=self.transcriber.warmup, daemon=True, name="whisper-warmup").start()
        self._thread = threading.Thread(target=self._run, daemon=True, name="voice")
        self._thread.start()

    def status(self) -> dict:
        devices = []
        try:
            import sounddevice as sd

            devices = sorted({d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0})
        except Exception:
            pass
        return {"available": self.available, "listening": self.available and not self.paused, "paused": self.paused,
                "error": self.error or self.transcriber.error, "devices": devices}

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.rt.bus.publish_threadsafe("voice_status", **self.status())

    def cancel_capture(self) -> None:
        """STOP: drop the recording in progress (nothing gets transcribed)."""
        self._cancel_capture = True

    def push_to_talk(self) -> None:
        if self.speaker.speaking:
            self.speaker.stop()
        self._ptt.set()

    def expect_confirmation(self, cid: str) -> None:
        self._confirm_id = cid

    def on_config(self, cfg) -> None:
        self.transcriber.update(cfg.voice)
        self._restart.set()

    # ---------- internals ----------
    def _after_speech(self) -> None:
        # JARVIS just asked "Ano, nebo ne?" → listen right away without the wake word
        if self._confirm_id and self.rt.agent.pending_confirm() == self._confirm_id:
            self._ptt.set()

    def _open_stream(self):
        import sounddevice as sd

        dev = self.rt.cfg.voice.input_device or None

        def cb(indata, frames, t, status):
            try:
                self._q.put_nowait(bytes(indata))
            except queue.Full:
                pass

        stream = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME, device=dev, callback=cb)
        stream.start()
        return stream

    def _run(self) -> None:
        import numpy as np

        try:
            import webrtcvad

            vad = webrtcvad.Vad(2)
        except Exception as e:
            vad = None
            log.info("webrtcvad unavailable (%s), using energy VAD", e)
        ww = None
        while True:
            try:
                if self.rt.cfg.voice.wake_word and ww is None:
                    try:
                        ww = load_wakeword(self.rt.cfg.voice.wake_word_model)
                    except Exception as e:
                        log.warning("wake word unavailable: %s", e)
                        self.error = f"Wake word nedostupné: {e}"
                self._stream = self._open_stream()
                self.available = True
                self.error = None if ww or not self.rt.cfg.voice.wake_word else self.error
                self.rt.bus.publish_threadsafe("voice_status", **self.status())
                self._restart.clear()
                self._listen_forever(ww, vad, np)
            except Exception as e:
                self.available = False
                self.error = f"Mikrofon nedostupný: {e}"
                log.warning("voice loop error: %s", e)
                self.rt.bus.publish_threadsafe("voice_status", **self.status())
                time.sleep(10)
            finally:
                try:
                    if self._stream:
                        self._stream.stop()
                        self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def _is_speech(self, frame: bytes, vad, np) -> bool:
        if vad is not None:
            sub = 320 * 2  # 20 ms
            return sum(vad.is_speech(frame[i:i + sub], SR) for i in range(0, len(frame) - sub + 1, sub)) >= 2
        a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(a ** 2))) > 700

    def _listen_forever(self, ww, vad, np) -> None:
        cooldown = 0.0
        while not self._restart.is_set():
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                frame = None
            if self.paused:
                continue
            triggered = self._ptt.is_set()
            if frame is not None and ww is not None and self.rt.cfg.voice.wake_word and time.time() > cooldown:
                scores = ww.predict(np.frombuffer(frame, dtype=np.int16))
                if max(scores.values(), default=0) >= self.rt.cfg.voice.wake_threshold:
                    triggered = True
                    ww.reset() if hasattr(ww, "reset") else None
            if triggered:
                self._ptt.clear()
                if self.speaker.speaking:
                    self.speaker.stop()  # barge-in
                cooldown = time.time() + 2.0
                self._capture(vad, np)

    def _beep(self, np, freq: float = 880.0) -> None:
        try:
            import sounddevice as sd

            t = np.linspace(0, 0.09, int(24000 * 0.09), False)
            tone = (0.18 * np.sin(2 * np.pi * freq * t) * np.hanning(len(t))).astype(np.float32)
            sd.play(tone, 24000, blocking=False)
        except Exception:
            pass

    def _capture(self, vad, np) -> None:
        bus = self.rt.bus
        self.listening = True
        bus.publish_threadsafe("state", state="listening")
        self._beep(np)
        while not self._q.empty():  # drop audio from before the trigger
            self._q.get_nowait()
        ep = Endpointer(FRAME / SR, self.rt.cfg.voice.silence_seconds)
        audio = bytearray()
        result = None
        n = 0
        self._cancel_capture = False
        while result is None:
            if self._cancel_capture:
                break
            try:
                frame = self._q.get(timeout=1.0)
            except queue.Empty:
                break
            audio += frame
            result = ep.feed(self._is_speech(frame, vad, np))
            n += 1
            if n % 2 == 0:
                a = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                bus.publish_threadsafe("level", rms=round(float(np.sqrt(np.mean(a ** 2))), 3))
        self.listening = False
        if result != "done":
            bus.publish_threadsafe("state", state="idle")
            return
        self._beep(np, 660.0)
        bus.publish_threadsafe("state", state="thinking")
        try:
            text = self.transcriber.transcribe(bytes(audio), SR)
        except Exception as e:
            log.warning("stt failed: %s", e)
            bus.publish_threadsafe("error", message=f"Rozpoznávání řeči selhalo: {e}")
            bus.publish_threadsafe("state", state="idle")
            return
        bus.publish_threadsafe("transcript", text=text, final=True)
        if not text.strip():
            bus.publish_threadsafe("state", state="idle")
            return
        cid = self.rt.agent.pending_confirm()
        if cid:
            yn = parse_yes_no(text)
            if yn is not None:
                self._confirm_id = None
                self.rt.call_soon(self.rt.agent.confirm, cid, yn)
                return
        self.rt.submit(self.rt.agent.handle(text, [], "voice"))
