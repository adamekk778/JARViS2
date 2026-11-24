"""3.16 Rychlý poslech (návrhy 1, 2, 3, 20): the answer starts right after you stop talking.

- Přepis s předstihem: when you pause (a quarter of a second of silence), the words so far are written down at once in
  the background. If you do not go on, that text is used – the transcription is already done when the pause turns out
  to be the end.
- Chytrý konec věty: a finished sentence ("pusť hudbu", "kolik je hodin?") ends at that quarter second instead of the
  usual 0.6 s; an unfinished one ("zapni světlo a…", "napiš mámě, že") waits longer (1.2 s), so it does not cut you off.
- Živý přepis: with a fast speech model (a graphics card, or a quick enough PC) what you say appears in the notch while
  you speak.
- Tvoje slova: the names the recognizer should spell right go with every command – your name, your own dictionary
  (Diktování → Slovník), your projects and 3D parts, your Home Assistant rooms and devices, your apps.
The AI itself starts only on the finished words, so half a sentence never does anything.
"""
from __future__ import annotations

import concurrent.futures
import logging
import re
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

EARLY_S = 0.25            # this much silence: write down what was said (and maybe end, when it is a finished sentence)
LONGER_S = 1.2            # an unfinished sentence waits this long
LIVE_EVERY_S = 1.0        # the live transcript while speaking (only with a fast model)
MAX_SPEC = 3              # at most this many early transcriptions for one command (an API counts each)
_VOCAB: dict[str, Any] = {"at": 0.0, "text": "", "key": ""}

_OPEN_END = re.compile(
    r"(?:\b(?:a|i|nebo|ani|ale|že|aby|protože|kdyby|když|jestli|takže|pak|potom|do|na|v|ve|s|se|z|ze|k|ke|o|u|od|po|pro|"
    r"přes|za|před|pod|nad|mezi|bez|kolem|jako|než|který|která|které|kde|kdy|co|jak|tak|ten|ta|to|ty|tu|mi|ti|mu|jí|si|"
    r"and|or|but|that|to|the|a|of|with|for|in|on|at)|[,;:–-])\s*$", re.I)
_DONE_END = re.compile(r"[.!?…]\s*$")


def looks_complete(text: str) -> bool | None:
    """True = a finished sentence, False = clearly unfinished, None = cannot tell (keep the normal pause)."""
    t = (text or "").strip()
    if not t or len(t) < 2:
        return None
    if _OPEN_END.search(t):
        return False
    words = re.findall(r"\w+", t)
    if _DONE_END.search(t) and len(words) >= 1:
        return True
    try:                                       # an everyday command JARVIS knows by heart is finished
        from .. import instant

        if instant.plan(t) is not None:
            return True
    except Exception:  # noqa: BLE001
        pass
    return True if len(words) >= 3 else None


def vocabulary(rt: Any, max_chars: int = 600) -> str:
    """The words the recognizer should expect (refreshed every 10 minutes)."""
    if time.time() - _VOCAB["at"] < 600 and _VOCAB["text"]:
        return _VOCAB["text"]
    words: list[str] = ["JARVIS"]
    g = rt.cfg.general
    words += [w for w in (g.user_name, g.address_as, g.city) if w]
    words += list(getattr(rt.cfg.dictation, "words", []) or [])
    try:
        from .. import workbench

        words += [p["name"] for p in workbench.projects(rt)[:8]]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .. import cad

        words += [p["name"] for p in cad.parts(rt)[:8]]
    except Exception:  # noqa: BLE001
        pass
    try:
        home = getattr(rt, "home", None)
        items = home._cache[1] if home is not None else []
        for e in items[:400]:
            n = (e.get("attributes") or {}).get("friendly_name") or ""
            if n and len(n) < 30:
                words.append(n)
    except Exception:  # noqa: BLE001
        pass
    try:
        words += [a for a in rt.platform.list_apps()[:60] if 2 < len(a) < 25]
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    out: list[str] = []
    size = 0
    for w in words:
        w = str(w).strip()
        k = w.lower()
        if not w or k in seen:
            continue
        if size + len(w) + 2 > max_chars:
            break
        seen.add(k)
        out.append(w)
        size += len(w) + 2
    _VOCAB.update(at=time.time(), text=", ".join(out))
    return _VOCAB["text"]


class Pace:
    """3.17 Tvoje tempo (návrh 8): how long YOU pause in the middle of a sentence. Someone who thinks between words
    gets a longer wait before JARVIS takes the sentence as finished; someone who speaks in one go a shorter one.
    From 20 pauses on: the wait = your longer pauses (90th percentile) + 0.15 s, between 0.45 and 1.1 s."""
    KEY = "voice_pace"

    def __init__(self, rt: Any):
        self.rt = rt
        self.pauses: list[float] = []
        try:
            row = rt.db.one("SELECT v FROM kv WHERE k=?", (self.KEY,))
            if row:
                import json

                self.pauses = [float(x) for x in json.loads(row["v"])][-200:]
        except Exception:  # noqa: BLE001
            self.pauses = []

    def record(self, pause_s: float) -> None:
        if 0.12 <= pause_s <= 2.5:
            self.pauses = (self.pauses + [round(pause_s, 2)])[-200:]
            if len(self.pauses) % 5 == 0:
                self.save()

    def save(self) -> None:
        import json

        try:
            self.rt.db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
            self.rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (self.KEY, json.dumps(self.pauses)))
        except Exception as e:  # noqa: BLE001
            log.debug("pace: %s", e)

    def silence(self, default: float) -> float:
        if len(self.pauses) < 20 or not getattr(self.rt.cfg.voice, "adaptive_pace", True):
            return default
        p = sorted(self.pauses)
        p90 = p[min(len(p) - 1, int(len(p) * 0.9))]
        return round(max(0.45, min(1.1, p90 + 0.15)), 2)


def pace(rt: Any) -> Pace:
    p = getattr(rt, "voice_pace", None)
    if p is None:
        p = rt.voice_pace = Pace(rt)
    return p


class Speculator:
    """Writes down the words at each pause, in the background; ends early on a finished sentence; waits on an open one."""

    def __init__(self, transcribe: Callable[[bytes], str], frame_bytes: int, base_silence: float, *,
                 early_s: float = EARLY_S, longer_s: float = LONGER_S, live: Callable[[str], None] | None = None,
                 live_ok: Callable[[], bool] | None = None, max_spec: int = MAX_SPEC,
                 live_transcribe: Callable[[bytes], str] | None = None):
        self.transcribe = transcribe
        self.live_transcribe = live_transcribe or transcribe     # 3.17 a small fast model just for the live text
        self.frame_bytes = frame_bytes
        self.base = base_silence
        self.early_s, self.longer_s = early_s, max(longer_s, base_silence)
        self.live, self.live_ok = live, live_ok
        self.max_spec = max_spec
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-early")
        self.fut: concurrent.futures.Future | None = None
        self.fut_len = 0                   # bytes of audio the running / finished early transcription covers
        self.text: str | None = None       # its result
        self.speech_end = 0                # bytes of audio up to the last speech frame
        self.n_spec = 0
        self.live_fut: concurrent.futures.Future | None = None
        self.last_live = 0.0
        self.decided: bool | None = None
        self.judged = False                # the early words were looked at (once per pause)
        self.on_pause: Callable[[float], None] | None = None    # 3.17 a pause you went on after (your tempo)
        self.on_unsure: Callable[[str], None] | None = None     # 3.17 the words so far at an unsure pause (ask ahead)
        self.on_stale: Callable[[], None] | None = None         # …and you went on speaking (drop that)
        self._quiet_before = 0.0

    def step(self, ep: Any, audio: bytearray, is_speech: bool) -> str | None:
        """After each frame: 'done' to end now, else None (may make the endpointer wait longer)."""
        if is_speech:
            if self._quiet_before > 0 and self.speech_end > 0 and self.on_pause is not None:
                self.on_pause(self._quiet_before)            # you paused this long and went on
            self._quiet_before = 0.0
            self.speech_end = len(audio)
            if self.fut is not None and self.fut_len < self.speech_end:     # you went on: that guess is old
                if self.decided is None and self.text and self.on_stale is not None:
                    self.on_stale()
                self.fut, self.text, self.decided, self.judged = None, None, None, False
                ep.silence_s = self.base
            self._live(audio)
            return None
        self._quiet_before = ep.quiet
        if not ep.heard or ep.quiet + 1e-6 < self.early_s:
            return None
        if self.fut is None and self.n_spec < self.max_spec and self.speech_end > 0:
            self.n_spec += 1
            self.fut_len = self.speech_end
            snap = bytes(audio[: self.speech_end])
            self.fut = self.pool.submit(self.transcribe, snap)
        if self.fut is not None and self.fut.done() and not self.judged:
            self.judged = True
            try:
                self.text = self.fut.result()
            except Exception as e:  # noqa: BLE001
                log.debug("early stt: %s", e)
                self.text = None
            self.decided = looks_complete(self.text or "")
            if self.decided is False:
                ep.silence_s = self.longer_s                    # an open sentence: give the speaker time
            elif self.decided is True:
                return "done"
            elif self.text and self.on_unsure is not None:     # unsure: the AI may start while we still wait
                self.on_unsure(self.text)
        return None

    def _live(self, audio: bytearray) -> None:
        if self.live is None or (self.live_ok is not None and not self.live_ok()):
            return
        now = time.monotonic()
        if now - self.last_live < LIVE_EVERY_S or (self.live_fut is not None and not self.live_fut.done()):
            return
        self.last_live = now
        snap = bytes(audio)

        def go() -> None:
            try:
                t = self.live_transcribe(snap)
                if t and self.live:
                    self.live(t)
            except Exception as e:  # noqa: BLE001
                log.debug("live stt: %s", e)
        self.live_fut = self.pool.submit(go)

    def result_for(self, audio_len: int, wait_s: float = 8.0) -> str | None:
        """The early text when it covers all the speech of the final recording (else None → transcribe as usual)."""
        if self.fut is None or self.fut_len < self.speech_end:
            return None
        if self.text is not None:
            return self.text
        try:
            self.text = self.fut.result(timeout=wait_s)
        except Exception as e:  # noqa: BLE001
            log.debug("early stt: %s", e)
            return None
        return self.text

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
