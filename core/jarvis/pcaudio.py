"""3.12 Zvuk z PC do telefonu: what the PC plays (music, a film, a game) goes to the paired phone – into its speaker or
headphones, in another room or away from home through JARVIS Link.

Only the sound the PC itself plays is taken (WASAPI loopback of the default speaker, like the live subtitles) – never
a microphone. It runs only while the phone listens (it starts it in the app; a notification there shows it the whole
time) and the PC shows a notice when it starts. AAC 128 kbit/s in an ADTS stream – any Android player can play it.
"""
from __future__ import annotations

import asyncio
import io
import logging
import queue
import threading
import time
from typing import Any, AsyncIterator, Callable

log = logging.getLogger("jarvis.pcaudio")

SR = 48000
CH = 2
BLOCK = 1024                      # ~21 ms
BITRATE = 128_000
GRACE_S = 5.0                     # the last listener left: keep running this long (a reconnect after a hiccup)


def loopback_source():
    """The default speaker's loopback as a context manager whose .record(numframes) gives float32 (n, 2)."""
    import soundcard as sc

    spk = sc.default_speaker()
    return sc.get_microphone(str(spk.name), include_loopback=True).recorder(samplerate=SR, channels=CH, blocksize=BLOCK)


class _Sink(io.RawIOBase):
    """What the AAC muxer writes goes straight to the listeners."""

    def __init__(self, out: Callable[[bytes], None]):
        self.out = out

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def write(self, b) -> int:
        data = bytes(b)
        if data:
            self.out(data)
        return len(data)


class PcAudio:
    def __init__(self, rt: Any, source: Callable[[], Any] | None = None):
        self.rt = rt
        self.source = source or loopback_source
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stopper: asyncio.TimerHandle | None = None
        self.error = ""

    @property
    def on(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        return {"on": self.on, "listeners": len(self._subs), "error": self.error}

    # ---------- the phone listens ----------
    async def listen(self) -> AsyncIterator[bytes]:
        q: asyncio.Queue = asyncio.Queue(maxsize=400)
        self._loop = asyncio.get_running_loop()
        self._subs.add(q)
        if self._stopper:
            self._stopper.cancel()
            self._stopper = None
        if not self.on:
            self._begin()
        try:
            while True:
                chunk = await q.get()
                if chunk is None:                       # the capture ended (error): end this stream too
                    break
                yield chunk
        finally:
            self._subs.discard(q)
            if not self._subs and self._loop is not None:
                self._stopper = self._loop.call_later(GRACE_S, self._end_if_alone)

    def _begin(self) -> None:
        self.error = ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-pcaudio", daemon=True)
        self._thread.start()
        try:
            self.rt.bus.publish("notify", title="Zvuk z PC jde do telefonu",
                                body="Telefon přehrává zvuk tohoto PC. Zastavíš ho v telefonu.", url="", target="all")
        except Exception:  # noqa: BLE001
            pass

    def _end_if_alone(self) -> None:
        self._stopper = None
        if not self._subs:
            self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    def _push(self, data: bytes | None) -> None:
        for q in list(self._subs):
            if q.full():                                 # a slow phone: drop the oldest (better a skip than a delay)
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(data)

    def _emit(self, data: bytes | None) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._push, data)

    # ---------- capture + AAC (a thread) ----------
    def _run(self) -> None:
        import av
        import numpy as np

        blocks: queue.Queue = queue.Queue(maxsize=50)
        reader_stop = threading.Event()

        def reader() -> None:                            # the loopback blocks while nothing plays: read it apart
            try:
                with self.source() as rec:
                    while not reader_stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        try:
                            blocks.put(data, timeout=1)
                        except queue.Full:
                            pass
            except Exception as e:  # noqa: BLE001
                self.error = f"Zvuk z PC nejde zachytit: {e}"[:200]
                log.info("pc audio capture: %s", e)

        rt_ = threading.Thread(target=reader, name="jarvis-pcaudio-read", daemon=True)
        rt_.start()
        silence = np.zeros((BLOCK, CH), dtype=np.float32)
        out = None
        try:
            out = av.open(_Sink(self._emit), mode="w", format="adts", buffer_size=4096)
            st = out.add_stream("aac", rate=SR)
            st.codec_context.layout = "stereo"
            st.codec_context.bit_rate = BITRATE
            pts = 0
            t0 = time.monotonic()

            def encode(data) -> None:
                nonlocal pts
                arr = np.ascontiguousarray(np.asarray(data, dtype=np.float32).reshape(-1, CH).T)
                frame = av.AudioFrame.from_ndarray(arr, format="fltp", layout="stereo")
                frame.sample_rate = SR
                frame.pts = pts
                pts += arr.shape[1]
                for pkt in st.encode(frame):
                    out.mux(pkt)

            while not self._stop.is_set():
                try:
                    encode(blocks.get(timeout=BLOCK / SR * 2))
                except queue.Empty:
                    if not rt_.is_alive():
                        break                            # the capture failed
                    # nothing plays (the loopback is silent): fill with silence at the real pace, so the phone's
                    # player never runs dry and stutters
                    due = int((time.monotonic() - t0) * SR)
                    while pts + BLOCK <= due and not self._stop.is_set():
                        encode(silence)
            for pkt in st.encode(None):
                out.mux(pkt)
        except Exception as e:  # noqa: BLE001
            self.error = f"Zvuk z PC nejde odeslat: {e}"[:200]
            log.info("pc audio: %s", e)
        finally:
            reader_stop.set()
            try:
                if out is not None:
                    out.close()
            except Exception:  # noqa: BLE001
                pass
            self._emit(None)
