"""The always-on voice loop: wake word → listen → transcribe → agent → speak."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections import deque

from .stt import Transcriber
from .text import Endpointer, parse_yes_no
from .tts import Speaker

log = logging.getLogger(__name__)
SR = 16000
FRAME = 1280  # 80 ms, what openWakeWord expects
FOLLOWUP_S = 6.0
LIVE_S = 12.0           # 3.14 živý rozhovor: this long to start the next sentence before the conversation rests
LOOK_SPEECH_S = 0.24    # 3.14 mluv bez Hey Jarvis: this much speech while you look at the screen = talking to JARVIS
END_PHRASES = ("to je vse", "to je vsechno", "diky to je vse", "dekuji to je vse", "stop", "konec", "that's all",
               "thats all", "that is all", "thank you that's all")


def is_end_phrase(text: str) -> bool:
    from ..tools.platform.base import norm
    import re

    t = re.sub(r"[^\w' ]+", " ", norm(text)).split()
    s = " ".join(t)
    return any(s == p or s.endswith(" " + p) or s.startswith(p + " ") and len(t) <= 6 for p in END_PHRASES)


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
        self.followup_active = False
        from .dsp import Ducker, EchoPath

        self.echo = EchoPath(SR)                 # the player tells it what JARVIS says → removed from the mic
        self.ducker = Ducker(rt.platform, lambda: rt.cfg.voice.duck_level)
        self._recent: deque = deque(maxlen=12)  # ~1 s of microphone before the wake word = the room's noise
        self._score_sink: list | None = None    # wake-word calibration collects the scores here
        self._rec: dict | None = None           # 3.14 recording one sample (own wake word / voice print)
        from .voiceid import ShortUtterance

        self._short = ShortUtterance(FRAME / SR)  # 3.14 own wake word: a short word followed by a pause

    # ---------- public ----------
    def start(self) -> None:
        # saving memory: the speech model is not loaded at start-up any more – it loads the moment somebody starts
        # talking (while they speak) and goes again after 10 minutes unused (stt.Transcriber.prefetch/release_if_idle)
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
    def _after_speech(self, reply_to: str = "") -> None:
        # JARVIS just asked "Ano, nebo ne?" → listen right away without the wake word
        if self._confirm_id and self.rt.agent.pending_confirm() == self._confirm_id:
            self._ptt.set()
            return
        # follow-up: keep the conversation going for 6 s without the wake word (visible "listening" state) – 3.13 only
        # after an answer to something you SAID ("Hey Jarvis, …"). An announcement (an automation, notifications from
        # the phone, the greeting after start-up, a reminder) is just said; the microphone does not open after it.
        if reply_to not in ("voice",):
            return
        if (self.rt.cfg.voice.followup or getattr(self.rt, "voice_mode", False) or getattr(self.rt, "live_talk", False)) \
                and not self.paused:
            self.followup_active = True
            self._ptt.set()

    def _open_stream(self):
        import sounddevice as sd

        dev = self.rt.cfg.voice.input_device or None

        def cb(indata, frames, t, status):
            raw = getattr(self, "_raw", None)
            if raw is not None and len(raw) < SR * 2 * 60 * 20:     # 3.20 (17) nácvik prezentace: up to 20 minutes
                raw.extend(bytes(indata))
            try:   # the frame started being recorded one frame ago (the echo canceller lines it up with the player)
                self._q.put_nowait((bytes(indata), time.monotonic() - frames / SR))
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

    # ---------- saving power: the wake-word model only runs while the room is not quiet ----------
    HOT_TAIL_S = 2.0            # keep listening this long after the last sound (the model then has the whole phrase)

    def _wake_gate(self, frame: bytes, ww, vad, np, now: float | None = None) -> bool:
        """Should this frame go through the wake-word model? A quiet room = no (the model is the costly part, ~12×
        a second). A sound (speech by the VAD, or clearly louder than the room's own noise) wakes it, and the frames
        just before are fed first so the start of "Hey" is not lost; it keeps running a while after the sound ends."""
        now = time.monotonic() if now is None else now
        if self._score_sink is not None:
            return True                                  # calibrating: every frame is measured
        a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
        floor = getattr(self, "_floor", None)
        loud = floor is None or rms > floor * 1.8 + 60
        if not loud and vad is not None:
            sub = 320 * 2
            try:
                loud = any(vad.is_speech(frame[i:i + sub], SR) for i in range(0, len(frame) - sub + 1, sub))
            except Exception:  # noqa: BLE001
                loud = True
        if not loud:                                     # learn the room's noise from the quiet frames only
            self._floor = rms if floor is None else floor * 0.97 + rms * 0.03
        else:                                            # a louder room (a fan came on) is learnt slowly too
            self._floor = rms if floor is None else floor * 0.999 + rms * 0.001
        hot = now < getattr(self, "_hot_until", 0.0)
        if loud:
            if not hot:                                  # waking up: the frames just before go in first
                for prev in list(self._recent)[-3:-1]:
                    try:
                        ww.predict(np.frombuffer(prev, dtype=np.int16))
                    except Exception:  # noqa: BLE001
                        break
            self._hot_until = now + self.HOT_TAIL_S
            return True
        return hot

    TALK_OVER_S = 0.64          # this long of clear speech while JARVIS talks = you want to say something
    TALK_OVER_GRACE_S = 0.8     # …not in the first moment of its speech (the echo canceller is still settling)

    def _talk_over(self, frame: bytes, vad, np, now: float | None = None) -> bool:
        """3.13 Skočit do řeči: JARVIS speaks, its own voice is taken out of the microphone, and what is left is clear,
        loud speech for ~0.6 s → it stops talking and listens. Only with echo cancellation (otherwise it would hear itself)."""
        v = self.rt.cfg.voice
        now = time.monotonic() if now is None else now
        if not (getattr(v, "barge_in", True) and v.echo_cancel and self.speaker.speaking):
            self._over_n, self._spk_since = 0, 0.0
            return False
        if not getattr(self, "_spk_since", 0.0):
            self._spk_since = now
        if now - self._spk_since < self.TALK_OVER_GRACE_S:
            return False
        a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
        floor = getattr(self, "_floor", None) or 300.0
        clear = rms > max(900.0, floor * 3.0) and self._is_speech(frame, vad, np)
        self._over_n = (getattr(self, "_over_n", 0) + 1) if clear else 0
        if self._over_n * FRAME / SR >= self.TALK_OVER_S:
            self._over_n, self._spk_since = 0, 0.0
            return True
        return False

    def _look_talk(self, frame: bytes, vad, np) -> bool:
        """3.14 Mluv bez „Hey Jarvis“: one person looks at the screen (the camera says so) and starts talking."""
        lw = getattr(self.rt, "look_watcher", None)
        if lw is None or not getattr(self.rt.cfg.voice, "look_to_talk", False) or self.speaker.speaking or not lw.ok():
            self._look_n = 0
            return False
        self._look_n = (getattr(self, "_look_n", 0) + 1) if self._is_speech(frame, vad, np) else 0
        if self._look_n * FRAME / SR >= LOOK_SPEECH_S:
            self._look_n = 0
            return True
        return False

    def _listen_forever(self, ww, vad, np) -> None:
        cooldown = 0.0
        while not self._restart.is_set():
            try:
                frame = self._frame(self._q.get(timeout=0.5), np)
            except queue.Empty:
                frame = None
            if self.paused:
                continue
            if frame is not None:
                self._recent.append(frame)
            if frame is not None and self._rec is not None:       # 3.14 recording a sample: nothing triggers meanwhile
                self._record_frame(frame, vad, np)
                continue
            triggered = self._ptt.is_set()
            vid = getattr(self.rt, "voiceid", None)
            if (frame is not None and not triggered and vid is not None and vid.wake.ready
                    and getattr(self.rt.cfg.voice, "custom_wake", False) and time.time() > cooldown):
                utt = self._short.feed(frame, self._is_speech(frame, vad, np))
                if utt is not None:
                    heard, _dist = vid.wake.check(np.frombuffer(utt, dtype=np.int16).astype(np.float32) / 32768.0)
                    if heard:
                        triggered = True
            if frame is not None and not triggered and time.time() > cooldown and self._look_talk(frame, vad, np):
                triggered = True                          # 3.14 you looked at the screen and spoke
                self._preroll = list(self._recent)[-8:]   # the start of the sentence is already said: keep it
            if frame is not None and not triggered and self._talk_over(frame, vad, np):
                triggered = True                          # 3.13 you started talking over JARVIS
                self.rt.bus.publish_threadsafe("barge_in")
            if frame is not None and ww is not None and self.rt.cfg.voice.wake_word and time.time() > cooldown \
                    and self._wake_gate(frame, ww, vad, np):
                scores = ww.predict(np.frombuffer(frame, dtype=np.int16))
                score = max(scores.values(), default=0)
                if self._score_sink is not None:            # calibrating: measure only, never trigger
                    self._score_sink.append(float(score))
                    continue
                if score >= self.rt.cfg.voice.wake_threshold:
                    triggered = True
                    ww.reset() if hasattr(ww, "reset") else None
            if triggered:
                self._ptt.clear()
                self.transcriber.prefetch()              # the model loads while the command is being spoken
                self.prewarm()                           # 3.16 the AI's connection opens while you speak
                if self.speaker.speaking:
                    self.speaker.stop()  # barge-in
                cooldown = time.time() + 2.0
                self._capture(vad, np)

    # ---------- 3.14 recording samples for the own wake word / the voice print ----------
    def record_utterance(self, short: bool, timeout: float = 8.0) -> bytes | None:
        """The next thing said into the microphone (a short word, or a sentence up to ~6 s). Blocks; call in a thread."""
        ev = threading.Event()
        self._rec = {"short": short, "buf": bytearray(), "speech": 0.0, "silence": 0.0, "event": ev, "out": None}
        try:
            ev.wait(timeout)
            return self._rec["out"] if self._rec else None
        finally:
            self._rec = None

    def _record_frame(self, frame: bytes, vad, np) -> None:
        r = self._rec
        if r is None or r["event"].is_set():
            return
        step = FRAME / SR
        speech = self._is_speech(frame, vad, np)
        if speech:
            r["buf"] += frame
            r["speech"] += step
            r["silence"] = 0.0
        elif r["speech"] > 0:
            r["buf"] += frame
            r["silence"] += step
        limit = 1.6 if r["short"] else 6.0
        if (r["speech"] >= 0.3 and r["silence"] >= (0.25 if r["short"] else 0.6)) or r["speech"] >= limit:
            r["out"] = bytes(r["buf"])
            r["event"].set()

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
        if self.rt.cfg.voice.duck_media:
            self.ducker.acquire()
        try:
            self._capture_inner(vad, np)
        finally:
            if self.rt.cfg.voice.duck_media:
                self.ducker.release()

    def _frame(self, item, np) -> bytes:
        """A queued microphone frame, with JARVIS's own voice removed while it speaks."""
        frame, t = item if isinstance(item, tuple) else (item, 0.0)
        if self.rt.cfg.voice.echo_cancel and t and t <= self.echo.active_until:
            a = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            frame = (np.clip(self.echo.clean(a, t), -1, 1) * 32767).astype(np.int16).tobytes()
        return frame

    def clean_utterance(self, audio: bytes, np) -> bytes:
        """Noise suppression (noise from the second before the wake word) and gain for a distant voice."""
        from .dsp import agc, denoise

        v = self.rt.cfg.voice
        boost = v.auto_gain and getattr(v, "whisper_boost", True)     # 3.20 (2) part of the automatic gain
        if not (v.noise_suppression or v.auto_gain or boost) or len(audio) < SR // 2:
            return audio
        x = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        if boost:                                       # 3.20 (2) a whispered command, levelled up for the recognizer
            from ..voicex import whisper_boost

            x = whisper_boost(x, SR)
        if v.noise_suppression:
            noise = np.frombuffer(b"".join(self._recent), dtype=np.int16).astype(np.float32) / 32768.0 if self._recent else None
            x, _ = denoise(x, SR, noise if noise is not None and len(noise) >= SR // 4 else None)
        if v.auto_gain:
            x, _ = agc(x, SR)
        return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()

    def collect_wake_scores(self, seconds: float) -> list[float]:
        """Wake-word scores frame by frame for a while (nothing gets triggered meanwhile)."""
        self._score_sink = []
        try:
            time.sleep(seconds)
            return list(self._score_sink)
        finally:
            self._score_sink = None

    def _capture_inner(self, vad, np) -> None:
        bus = self.rt.bus
        self._beep(np)
        while not self._q.empty():  # drop audio from before the trigger
            self._q.get_nowait()
        live = bool(getattr(self.rt, "live_talk", False))
        from .fastear import pace

        ep = Endpointer(FRAME / SR, pace(self.rt).silence(self.rt.cfg.voice.silence_seconds),     # 3.17 your tempo
                        no_speech_s=(LIVE_S if live else FOLLOWUP_S) if self.followup_active else 6.0)
        bus.publish_threadsafe("state", state="listening", followup=self.followup_active, live=live)
        audio = bytearray()
        result = None
        pre, self._preroll = getattr(self, "_preroll", None), None
        for f in pre or []:                       # 3.14 the words said before JARVIS knew you meant it
            audio += f
            result = ep.feed(self._is_speech(f, vad, np))
        result = None if result == "done" else result
        n = 0
        self._cancel_capture = False
        spec = self._speculator(ep, np)                   # 3.16 written down at each pause, finished sentences end early
        while result is None:
            if self._cancel_capture:
                break
            try:
                frame = self._frame(self._q.get(timeout=1.0), np)
            except queue.Empty:
                break
            audio += frame
            speaking = self._is_speech(frame, vad, np)
            result = ep.feed(speaking)
            if result is None and spec is not None:
                result = spec.step(ep, audio, speaking)
                if result is None and live:
                    self._maybe_backchannel(ep, spec, speaking)
            n += 1
            if n % 2 == 0:
                a = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                bus.publish_threadsafe("level", rms=round(float(np.sqrt(np.mean(a ** 2))), 3))
        self.listening = False
        if result != "done" and spec is not None:
            spec.close()
        if result != "done":
            if self.followup_active and getattr(self.rt, "live_talk", False):   # 3.14 a long silence ends the conversation
                self.rt.live_talk = False
                bus.publish_threadsafe("live_talk", on=False)
            self.followup_active = False
            bus.publish_threadsafe("state", state="idle")
            return
        self._beep(np, 660.0)
        from .style import mark_end

        mark_end(self.rt)                                  # 3.14 návrh 1: from here to JARVIS's first sound
        from .. import latency

        latency.get(self.rt).begin("voice")                # 3.16 the steps of this answer are measured from here
        bus.publish_threadsafe("state", state="thinking")
        vid = getattr(self.rt, "voiceid", None)
        if vid is not None:                                # 3.14 who spoke (household, owner) and whether whispered
            try:
                vid.on_utterance(bytes(audio))
            except Exception as e:  # noqa: BLE001
                log.debug("voice id: %s", e)
        try:
            early = spec.result_for(len(audio)) if spec is not None else None
            if spec is not None:
                spec.close()
            text = early if early is not None else self._stt(bytes(audio), np)
        except Exception as e:
            log.warning("stt failed: %s", e)
            bus.publish_threadsafe("error", message=f"Rozpoznávání řeči selhalo: {e}")
            if str(e) == self.transcriber.NO_MODEL:           # say it, so a voice-only user knows what to do
                try:
                    self.rt.speak("Rozpoznávání řeči ještě není nastavené. Vlož v Nastavení, Mozek, klíč od Groq – je zdarma.")
                except Exception:  # noqa: BLE001
                    pass
            bus.publish_threadsafe("state", state="idle")
            return
        bus.publish_threadsafe("transcript", text=text, final=True)
        latency.get(self.rt).mark("stt")
        if getattr(self.rt.cfg.voice, "emotion", False) and text.strip():
            try:                                       # OMEGA P3.12: tone of voice vs the user's own usual voice
                from ..sysplus import update_voice_mood

                update_voice_mood(self.rt, np.frombuffer(bytes(audio), dtype=np.int16), SR)
            except Exception as e:
                log.debug("voice mood: %s", e)
        if not text.strip():
            self.followup_active = False
            bus.publish_threadsafe("state", state="idle")
            return
        self.rt.voicex_last_pcm, self.rt.voicex_last_pcm_text = bytes(audio), text   # 3.20 (7) a note keeps the recording
        self.handle_transcript(text, getattr(self.transcriber, "last_language", "cs"))

    # ---------- 3.20 (17) nácvik prezentace: everything the microphone hears, raw ----------
    def start_raw_recording(self) -> None:
        self._raw = bytearray()

    def stop_raw_recording(self) -> bytes:
        raw, self._raw = getattr(self, "_raw", None), None
        return bytes(raw or b"")

    def _stt(self, pcm: bytes, np) -> str:
        """The words, with the names the recognizer should expect (3.16 tvoje slova); the time it took is remembered."""
        from .fastear import vocabulary

        try:
            vocab = vocabulary(self.rt) if getattr(self.rt.cfg.voice, "vocabulary", True) else ""
        except Exception:  # noqa: BLE001
            vocab = ""
        t0 = time.monotonic()
        text = self.transcriber.transcribe(self.clean_utterance(pcm, np), SR, prompt=vocab)
        from ..voicex import codeswitch

        text = codeswitch(self.rt, text)                # 3.20 (12) "čil vajbs" → "chill vibes"
        took = time.monotonic() - t0
        self._stt_s = took if not getattr(self, "_stt_s", 0) else 0.7 * self._stt_s + 0.3 * took
        return text

    def _partial_stt(self, pcm: bytes, np) -> str:
        """3.17 the live text while you speak: Whisper "tiny" (~75 MB, quick on any PC); the final words still come
        from your own model."""
        tr = getattr(self, "_partial", None)
        if tr is None:
            tr = self._partial = Transcriber(self.rt.cfg.voice.model_copy(update={"stt_model": "tiny", "stt_provider": "local"}))
        return tr.transcribe(self.clean_utterance(pcm, np), SR)

    def _live_words(self, small: bool):
        """3.18 the words with their times for the live window: the tiny model, or your own one on a fast PC."""
        def words(audio) -> list[dict]:
            if small:
                tr = getattr(self, "_partial", None)
                if tr is None:
                    tr = self._partial = Transcriber(self.rt.cfg.voice.model_copy(update={"stt_model": "tiny",
                                                                                        "stt_provider": "local"}))
                return tr.words(audio)
            return self.transcriber.words(audio)
        return words

    def _speculator(self, ep, np):
        """3.16 the early transcription at pauses (+ the live text in the notch when speech recognition is fast)."""
        if not getattr(self.rt.cfg.voice, "smart_endpoint", True):
            return None
        from .fastear import Speculator

        bus = self.rt.bus
        from .fastear import pace

        local = self.transcriber.provider() == "local"
        fast = 0 < getattr(self, "_stt_s", 9.0) < 0.45
        small = local and not fast and getattr(self.rt.cfg.voice, "live_partial", True) \
            and getattr(self.rt.cfg.voice, "stt_download_ok", False)       # 3.17 the live text by a tiny model
        window = None
        if local and (fast or small) and getattr(self.rt.cfg.voice, "live_window", True):
            from .fastear import LiveWindow                  # 3.18 only the new audio is read each time

            window = LiveWindow(self._live_words(small))
        sp = Speculator(lambda b: self._stt(b, np), FRAME * 2, ep.silence_s,
                        live=lambda t: bus.publish_threadsafe("transcript", text=t, final=False),
                        live_ok=lambda: local and (fast or small),
                        max_spec=3 if local else 2,
                        live_transcribe=window.update if window is not None else
                        ((lambda b: self._partial_stt(b, np)) if small else None))
        if window is not None:
            sp.live_every = 0.5 if fast else 0.8
        sp.on_pause = pace(self.rt).record
        loop = getattr(self.rt, "loop", None)
        agent = getattr(self.rt, "agent", None)
        if loop is not None and agent is not None and getattr(self.rt.cfg.voice, "speculate", True):
            sp.on_unsure = lambda t: asyncio.run_coroutine_threadsafe(agent.speculate(t), loop)
            sp.on_stale = lambda: loop.call_soon_threadsafe(agent.cancel_spec)
        return sp

    BACKCHANNEL_AFTER_S = 6.0                             # this much talking since the last "mhm"

    def _maybe_backchannel(self, ep, spec, speaking: bool) -> bool:
        """3.16 (návrh 23) a long live conversation, you pause mid-thought (the words so far are unfinished): "mhm"."""
        v = self.rt.cfg.voice
        if not (getattr(v, "backchannel", False) and getattr(v, "echo_cancel", True)):
            return False
        now = time.monotonic()
        if speaking:
            if not getattr(self, "_bc_talk_from", 0):
                self._bc_talk_from = now
            return False
        talked = now - (getattr(self, "_bc_talk_from", 0) or now)
        if spec.decided is not False or not (0.35 <= ep.quiet < 0.6) or talked < self.BACKCHANNEL_AFTER_S:
            return False
        self._bc_talk_from = 0
        loop = getattr(self.rt, "loop", None)
        if loop is None:
            return False
        asyncio.run_coroutine_threadsafe(self.speaker.backchannel(), loop)
        return True

    def prewarm(self) -> None:
        """3.16 "Hey Jarvis" heard: open the connection to the AI (and the local model) in the background."""
        last = getattr(self, "_prewarmed", 0.0)
        if time.monotonic() - last < 45:                   # a connection stays open ~2 minutes
            return
        self._prewarmed = time.monotonic()
        loop = getattr(self.rt, "loop", None)
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.rt.router.prewarm(), loop)
            agent = getattr(self.rt, "agent", None)
            if agent is not None and hasattr(agent, "warm_cache"):        # 3.18 Claude's cache too, while you speak
                asyncio.run_coroutine_threadsafe(agent.warm_cache(), loop)
            if not getattr(self, "_phrases_ready", False):     # 3.16 "Moment, pane." etc. ready to be heard at once
                self._phrases_ready = True
                asyncio.run_coroutine_threadsafe(self.speaker.prepare_phrases(), loop)
        except Exception as e:  # noqa: BLE001
            log.debug("prewarm: %s", e)

    def handle_transcript(self, text: str, lang: str = "cs") -> None:
        """What to do with a finished utterance: answer a pending confirmation, end a follow-up, or ask the agent."""
        cid = self.rt.agent.pending_confirm()
        if cid:
            yn = parse_yes_no(text)
            if yn is not None:
                self._confirm_id = None
                self.rt.call_soon(self.rt.agent.confirm, cid, yn)
                return
        from .. import voicex

        if voicex.poll_active(self.rt):                  # 3.20 (14) a vote while the family poll runs
            vid = getattr(self.rt, "voiceid", None)
            said = voicex.poll_answer(self.rt, text, getattr(vid, "last_speaker", "") if vid is not None else "")
            if said:
                self.rt.speak(said)
                return
        if (self.followup_active or getattr(self.rt, "live_talk", False)) and voicex.aside(self.rt, text):
            self.followup_active = True                  # 3.20 (4) not meant for JARVIS: keep listening, say nothing
            self._ptt.set()
            return
        if is_end_phrase(text):
            self.followup_active = False
            if getattr(self.rt, "live_talk", False):     # 3.14 the end of a live conversation
                self.rt.live_talk = False
                self.rt.bus.publish_threadsafe("live_talk", on=False)
            self.rt.bus.publish_threadsafe("state", state="idle")
            return
        self.rt.submit(self.rt.agent.handle(text, [], "voice", lang=lang))
