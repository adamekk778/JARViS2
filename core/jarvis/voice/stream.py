"""3.12 Rychlejší hlas: JARVIS starts speaking as soon as the first sentence of the answer is written, instead of
waiting for the whole answer. Each finished sentence is turned into speech right away (the next ones are prepared
while the current one plays, so there are no gaps); code blocks are never read out; "Stop" or talking over JARVIS
ends it at once.
"""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

FIRST_MIN = 12          # the first piece may be short – it is what makes the answer feel instant
NEXT_MIN = 60           # later pieces: a sentence or two together (fewer, smoother joins)
_END = re.compile(r"[.!?…:](?=\s)|\n\s*\n|\n(?=[-*•\d])")
_CLAUSE = re.compile(r"[,;–—](?=\s)")
CLAUSE_MIN = 28         # 3.14 a first clause this long may be spoken before its sentence ends


def cut(buf: str, first: bool) -> tuple[str, str]:
    """(a piece ready to speak, the rest) – cut after a sentence end, never inside a ``` code block."""
    need = FIRST_MIN if first else NEXT_MIN
    best = -1
    for m in _END.finditer(buf):
        end = m.end()
        if buf[:end].count("```") % 2:            # inside a code block: not here
            continue
        if end >= need:
            best = end
            break
    if best < 0 and first and buf.count("```") % 2 == 0:
        # 3.14 the first sound sooner: no sentence end yet, but a long clause is written → say it already
        m = next((m for m in _CLAUSE.finditer(buf) if CLAUSE_MIN <= m.end() <= 110), None)
        if m:
            best = m.end()
    if best < 0:
        return "", buf
    return buf[:best], buf[best:]


def speakable(text: str) -> str:
    """Without code blocks (they are not read out) – the rest is cleaned by the speaker as usual."""
    return re.sub(r"```.*?```", " ", text, flags=re.S).strip()


class SpeechStream:
    def __init__(self, rt, lang: str = "cs", reply_to: str = ""):
        self.rt = rt
        self.lang = lang
        self.reply_to = reply_to        # the source of the request this answers ("voice" → JARVIS may listen on after it)
        self.buf = ""
        self.fed = ""                   # everything given so far (the agent adds only what is new at the end)
        self.first = True
        self.spoke = False
        self._jobs: asyncio.Queue = asyncio.Queue()
        self.turn: dict | None = None    # 3.16 latency: the answer whose first sound this is
        self._player = asyncio.get_running_loop().create_task(self._play_all())

    def feed(self, delta: str) -> None:
        self.fed += delta
        if self.rt.speaker is None or (self.rt.speaker._stop.is_set() and self.spoke):
            return
        self.buf += delta
        while True:
            piece, rest = cut(self.buf, self.first)
            if not piece:
                break
            self.buf = rest
            self._queue(piece)

    def preface(self, line: str) -> None:
        """3.14 one short sentence said before the answer is written (not part of the answer text)."""
        if self.spoke or self.rt.speaker is None or not line.strip():
            return
        self._queue(line)

    def _queue(self, piece: str) -> None:
        text = speakable(piece)
        if not re.search(r"\w", text):
            return
        self.first = False
        self.spoke = True
        # synthesis starts now, in parallel with whatever is playing (no gap between sentences)
        self._jobs.put_nowait((text, asyncio.get_running_loop().create_task(self.rt.speaker.synth(text, self.lang))))

    async def finish(self) -> None:
        """The answer is complete: say what is left, then wait until everything has been said."""
        if self.buf.strip():
            self._queue(self.buf)
            self.buf = ""
        self._jobs.put_nowait(None)
        try:
            await self._player
        except asyncio.CancelledError:
            pass

    def cancel(self) -> None:
        self._player.cancel()

    async def _play_all(self) -> None:
        sp = self.rt.speaker
        async with sp._lock:                       # one voice at a time: other announcements wait for this answer
            sp._stop.clear()
            ducker = getattr(getattr(self.rt, "voice", None), "ducker", None) if self.rt.cfg.voice.duck_media else None
            started = False
            try:
                while True:
                    job = await self._jobs.get()
                    if job is None:
                        break
                    text, synth = job
                    if sp._stop.is_set():            # "Stop" / talked over: drop the rest
                        synth.cancel()
                        continue
                    try:
                        audio, _mime = await synth
                    except Exception as e:  # noqa: BLE001
                        log.warning("tts (stream) failed: %s", e)
                        continue
                    if not started:
                        started = True
                        if self.turn is not None and "first_audio" not in self.turn["marks"]:
                            import time as _t

                            self.turn["marks"]["first_audio"] = round((_t.monotonic() - self.turn["t0"]) * 1000)
                        sp.speaking = True
                        self.rt.bus.publish("state", state="speaking")
                        if ducker:
                            ducker.acquire()
                    if getattr(self.rt.cfg.appearance, "captions", False):
                        from ..uixplus import caption_chunks, caption_timing

                        self.rt.bus.publish("caption", who="jarvis", lines=caption_timing(caption_chunks(text)))
                    try:
                        await asyncio.to_thread(sp._play, audio)
                    except Exception as e:  # noqa: BLE001
                        log.warning("playback failed: %s", e)
            finally:
                if started:
                    if ducker:
                        ducker.release()
                    sp.speaking = False
                    if not self.rt.agent.busy:
                        self.rt.bus.publish("state", state="idle")
                    if sp.on_finished:
                        try:
                            sp.on_finished(self.reply_to)
                        except Exception:  # noqa: BLE001
                            pass
