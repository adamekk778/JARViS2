"""Dictation anywhere (3.0): hold a key in any app, speak, let go — the words are pasted where you type.

Flow: the desktop host watches the key (desktop/dictation_keys.py) and calls start() / finish() / cancel()
from its thread. Audio is captured here, transcribed offline (faster-whisper, or Groq when chosen), then the
dictionary, replacements, snippets and the optional AI clean-up are applied, and the text is pasted through the
clipboard, which gets its previous text back. Every dictation goes to a local history (kept `keep_days`) that
feeds the Statistics page and the weekly recap. Nothing leaves the PC except what the chosen recognizer or the
clean-up AI needs.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

SR = 16000
MIN_SECONDS = 0.35      # shorter = a normal key press (Ctrl+C with the right Ctrl), not a dictation
MAX_SECONDS = 600
TYPING_WPM = 40         # "time saved" compares with typing at this speed
SPEECH_RMS = 0.012      # loudest 30 ms frame below this = nobody spoke (Ctrl + click, a hold by mistake)
# What speech recognizers write for silence or noise: never paste these
HALLUCINATIONS = ("titulky vytvořil", "titulky vytvořila", "děkuji za pozornost", "děkuji za sledování",
                  "thank you for watching", "thanks for watching", "subtitles by", "www.", "amara.org", "♪")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, text TEXT, raw TEXT,
  words INT, seconds REAL, app TEXT, style TEXT);
CREATE INDEX IF NOT EXISTS dictations_ts ON dictations(ts);
"""

CLEANUP_PROMPTS = {
    "natural": ("Uprav přepis diktátu: odstraň vycpávková slova (ehm, jakoby, prostě), opakování a opravy, které "
                "mluvčí udělal během mluvení, a oprav interpunkci a velká písmena. Zachovej tón, slova a jazyk mluvčího. "
                "Nic nepřidávej, neodpovídej na obsah. Vrať jen upravený text."),
    "polished": ("Přepiš diktát do čistého, dobře čitelného textu: odstraň vycpávková slova, opakování a opravy, "
                 "sjednoť věty, oprav gramatiku a interpunkci, rozděl na odstavce, kde to dává smysl. Zachovej význam "
                 "a jazyk mluvčího, nic nepřidávej, neodpovídej na obsah. Vrať jen výsledný text."),
}

_norm_re = re.compile(r"[^\w]+", re.UNICODE)


def _norm(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return _norm_re.sub(" ", s).strip()


def has_speech(pcm16: bytes) -> bool:
    import numpy as np

    a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    n = SR * 30 // 1000
    if a.size < n:
        return False
    frames = a[: a.size // n * n].reshape(-1, n)
    return float(np.sqrt((frames * frames).mean(axis=1)).max()) >= SPEECH_RMS


def is_hallucination(text: str) -> bool:
    t = text.strip().lower()
    return not t or any(h in t for h in HALLUCINATIONS) and count_words(t) <= 8


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text, re.UNICODE))


def apply_words(text: str, cfg) -> str:
    """Snippets (whole dictation = trigger) and replacements (whole words, any case)."""
    said = _norm(text)
    for sn in cfg.snippets:
        if sn.trigger.strip() and said == _norm(sn.trigger):
            return sn.text
    for r in cfg.replacements:
        if r.src.strip():
            text = re.sub(rf"(?<!\w){re.escape(r.src.strip())}(?!\w)", r.dst.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    return text


class Dictation:
    def __init__(self, rt: Any):
        self.rt = rt
        self.db = rt.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
        self.state = "idle"          # idle | listening | transcribing
        self.hands_free = False
        self._buf = bytearray()
        self._stream = None
        self._started = 0.0
        self._lock = threading.Lock()
        self._level_t = 0.0
        self._own_stt = None
        self.last_text = ""

    @property
    def cfg(self):
        return self.rt.cfg.dictation

    # ---------- capture (called from the key thread) ----------
    def start(self, hands_free: bool = False) -> bool:
        with self._lock:
            if self.state != "idle" or not self.cfg.enabled:
                return False
            self._buf = bytearray()
            self._started = time.monotonic()
            self.hands_free = hands_free
            try:
                self._stream = self._open_stream()
            except Exception as e:
                log.warning("dictation mic: %s", e)
                self._state("error", message="Mikrofon se nepodařilo otevřít.")
                return False
            self.state = "listening"
        self._state("listening", hands_free=hands_free)
        return True

    def _open_stream(self):
        import sounddevice as sd

        dev = self.rt.cfg.voice.input_device or None

        def cb(indata, frames, t, status):
            data = bytes(indata)
            if len(self._buf) < SR * 2 * MAX_SECONDS:
                self._buf.extend(data)
            now = time.monotonic()
            if now - self._level_t > 0.08:
                self._level_t = now
                import numpy as np

                a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(a * a)) / 32768.0) if a.size else 0.0
                self.rt.bus.publish_threadsafe("dictation", state="listening", level=round(min(1.0, rms * 6), 3),
                                               hands_free=self.hands_free)

        stream = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=1600, device=dev, callback=cb)
        stream.start()
        return stream

    def _close(self) -> bytes:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        return bytes(self._buf)

    def cancel(self) -> None:
        with self._lock:
            if self.state != "listening":
                return
            self._close()
            self.state = "idle"
        self._state("cancelled")

    def finish(self) -> None:
        """Key released (or the hands-free tap): transcribe and paste in the background."""
        with self._lock:
            if self.state != "listening":
                return
            pcm = self._close()
            seconds = time.monotonic() - self._started
            if seconds < MIN_SECONDS:
                self.state = "idle"
                self._state("cancelled", quiet=True)
                return
            self.state = "transcribing"
        self._state("transcribing")
        app = ""
        try:
            app = self.rt.platform.foreground_app()
        except Exception:
            pass
        self.rt.submit(self.handle_audio(pcm, seconds, app))

    # ---------- processing ----------
    def _stt(self):
        stt = getattr(self.rt.voice, "transcriber", None) if self.rt.voice else None
        if stt is None:
            if self._own_stt is None:
                from .voice.stt import Transcriber

                self._own_stt = Transcriber(self.rt.cfg.voice)
            stt = self._own_stt
        return stt

    async def handle_audio(self, pcm: bytes, seconds: float, app: str = "") -> str:
        try:
            if not has_speech(pcm):
                self.state = "idle"
                self._state("cancelled", quiet=True)
                return ""
            prompt = ", ".join(w.strip() for w in self.cfg.words if w.strip())
            raw = await asyncio.to_thread(self._stt().transcribe, pcm, SR, prompt)
            if is_hallucination(raw):
                raw = ""
            text = await self.process(raw)
            if not text.strip():
                self.state = "idle"
                self._state("cancelled", message="Nic jsem neslyšel.")
                return ""
            await asyncio.to_thread(self.paste, text)
            self.last_text = text
            self.add(text, raw, seconds, app)
            self.state = "idle"
            self._state("done", text=text[:300], words=count_words(text), app=app)
            return text
        except Exception as e:
            log.exception("dictation failed")
            self.state = "idle"
            self._state("error", message=f"Diktování selhalo: {e}")
            return ""

    async def process(self, raw: str) -> str:
        text = apply_words(raw.strip(), self.cfg)
        if text != raw.strip() and any(_norm(raw) == _norm(s.trigger) for s in self.cfg.snippets):
            return text      # a snippet is pasted as written
        style = self.cfg.cleanup
        if style != "off" and count_words(text) >= 4:
            try:
                out = await asyncio.wait_for(self.rt.router.complete(
                    [{"role": "system", "content": CLEANUP_PROMPTS[style]}, {"role": "user", "content": text}], fast=True), 20)
                if out.strip():
                    text = apply_words(out.strip(), self.cfg)
            except Exception as e:
                log.info("dictation clean-up skipped: %s", e)
        return text

    def paste(self, text: str) -> None:
        p = self.rt.platform
        old = None
        try:
            old = p.clipboard_get()
        except Exception:
            pass
        p.clipboard_set(text)
        time.sleep(0.05)
        p.hotkey(["ctrl", "v"])
        time.sleep(0.35)
        if old is not None:
            try:
                p.clipboard_set(old)
            except Exception:
                pass

    def paste_again(self) -> None:
        if self.last_text:
            self.paste(self.last_text)

    def _state(self, state: str, **data: Any) -> None:
        self.rt.bus.publish_threadsafe("dictation", state=state, **data)

    # ---------- history ----------
    def add(self, text: str, raw: str, seconds: float, app: str = "") -> None:
        words = count_words(text or raw)
        if self.cfg.keep_days <= 0:
            text = raw = ""      # still counted for the statistics, without the words themselves
        self.db.exec("INSERT INTO dictations (ts, text, raw, words, seconds, app, style) VALUES (?,?,?,?,?,?,?)",
                     (time.time(), text, raw, words, round(seconds, 2), app[:60], self.cfg.cleanup))
        self.purge()

    def purge(self) -> None:
        if self.cfg.keep_days > 0:
            cutoff = time.time() - self.cfg.keep_days * 86400
            self.db.exec("UPDATE dictations SET text='', raw='' WHERE ts < ? AND text != ''", (cutoff,))

    def history(self, query: str = "", limit: int = 200) -> list[dict]:
        rows = _q(self.db, "SELECT id, ts, text, words, seconds, app FROM dictations WHERE text != '' ORDER BY ts DESC LIMIT ?",
                             (limit * 3 if query else limit,))
        out = [dict(zip(("id", "ts", "text", "words", "seconds", "app"), r)) for r in rows]
        if query:
            q = _norm(query)
            out = [r for r in out if q in _norm(r["text"])][:limit]
        return out

    def delete(self, did: int) -> None:
        self.db.exec("UPDATE dictations SET text='', raw='' WHERE id=?", (int(did),))

    def clear(self) -> None:
        self.db.exec("UPDATE dictations SET text='', raw=''")

    # ---------- statistics ----------
    def stats(self, period: str = "month") -> dict:
        now = time.time()
        since = {"week": now - 7 * 86400, "month": now - 30 * 86400}.get(period, 0)
        rows = _q(self.db, "SELECT ts, words, seconds, app FROM dictations WHERE ts >= ? ORDER BY ts", (since,))
        words = sum(r[1] for r in rows)
        secs = sum(r[2] for r in rows)
        per_day: dict[str, int] = {}
        apps: dict[str, int] = {}
        for ts, w, _s, app in rows:
            d = date.fromtimestamp(ts).isoformat()
            per_day[d] = per_day.get(d, 0) + w
            apps[app or "Jiné"] = apps.get(app or "Jiné", 0) + w
        days = 7 if period == "week" else 30 if period == "month" else max(1, min(365, (date.today() - date.fromtimestamp(rows[0][0])).days + 1)) if rows else 30
        series = [{"day": (date.today() - timedelta(days=i)).isoformat(),
                   "words": per_day.get((date.today() - timedelta(days=i)).isoformat(), 0)} for i in range(days - 1, -1, -1)]
        saved = max(0.0, words / TYPING_WPM * 60 - secs)
        top = sorted(apps.items(), key=lambda kv: -kv[1])[:6]
        return {
            "period": period, "words": words, "dictations": len(rows), "seconds": round(secs, 1),
            "wpm": round(words / (secs / 60)) if secs > 5 else 0, "saved_s": round(saved),
            "streak": self.streak(), "series": series,
            "apps": [{"app": a, "words": w, "share": round(100 * w / words) if words else 0} for a, w in top],
            "total_words": _q(self.db, "SELECT COALESCE(SUM(words),0) FROM dictations")[0][0],
        }

    def streak(self) -> int:
        days = {date.fromtimestamp(r[0]) for r in _q(self.db, "SELECT ts FROM dictations WHERE ts >= ?", (time.time() - 400 * 86400,))}
        n, d = 0, date.today()
        if d not in days:
            d -= timedelta(days=1)      # yesterday still keeps the streak alive this morning
        while d in days:
            n += 1
            d -= timedelta(days=1)
        return n


# ---------- the weekly recap (every Monday, over the past Monday–Sunday) ----------
CZ_DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday


def recap(rt: Any, today: date | None = None) -> dict:
    start, end = week_bounds(today)
    t0 = datetime.combine(start, datetime.min.time()).timestamp()
    t1 = datetime.combine(end, datetime.min.time()).timestamp()
    q = lambda sql, args=(): _q(rt.db, sql, args)  # noqa: E731
    dict_rows = q("SELECT ts, words, seconds, app FROM dictations WHERE ts >= ? AND ts < ?", (t0, t1))
    tasks = q("SELECT status, created, finished FROM tasks WHERE created >= ? AND created < ?", (t0, t1))
    actions = q("SELECT tool FROM task_actions WHERE ts >= ? AND ts < ?", (t0, t1))
    msgs = q("SELECT created FROM messages WHERE role='user' AND created >= ? AND created < ?", (t0, t1))
    per_day = [0] * 7
    for (ts,) in msgs:
        per_day[datetime.fromtimestamp(ts).weekday()] += 1
    for ts, *_ in dict_rows:
        per_day[datetime.fromtimestamp(ts).weekday()] += 1
    tools: dict[str, int] = {}
    for (tool,) in actions:
        tools[tool] = tools.get(tool, 0) + 1
    apps: dict[str, int] = {}
    for _ts, w, _s, app in dict_rows:
        apps[app or "Jiné"] = apps.get(app or "Jiné", 0) + w
    words = sum(r[1] for r in dict_rows)
    secs = sum(r[2] for r in dict_rows)
    busiest = max(range(7), key=lambda i: per_day[i]) if any(per_day) else None
    longest = max((f - c for _s, c, f in tasks if f and c), default=0)
    return {
        "week": start.isoformat(), "until": (end - timedelta(days=1)).isoformat(),
        "messages": len(msgs), "tasks": len(tasks), "tasks_done": sum(1 for s, *_ in tasks if s == "done"),
        "actions": len(actions), "top_tools": sorted(tools.items(), key=lambda kv: -kv[1])[:3],
        "words": words, "saved_s": round(max(0.0, words / TYPING_WPM * 60 - secs)),
        "top_app": max(apps, key=apps.get) if apps else "",
        "busiest_day": CZ_DAYS[busiest] if busiest is not None else "", "per_day": per_day,
        "longest_task_s": round(longest),
        "empty": not (msgs or tasks or dict_rows),
    }


def _q(db: Any, sql: str, args: tuple = ()) -> list[tuple]:
    return [tuple(r.values()) for r in db.all(sql, args)]
