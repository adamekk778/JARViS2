"""Notetaker (3.0): record a call without a bot joining it, then a transcript person by person, a summary,
the key points and the to-dos.

Two tracks are recorded side by side: your microphone ("Já") and what the PC plays ("Ostatní", WASAPI loopback).
Each is transcribed with timestamps and the two are merged in time order. Without headphones the microphone also
hears the other people, so a microphone line that repeats an overlapping "Ostatní" line is dropped. The audio is
deleted as soon as the transcript is written. The user is told to let the others know they are recorded.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import shutil
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

SR = 16000
MAX_SECONDS = 3 * 3600
SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, created REAL, title TEXT, seconds REAL, status TEXT,
  transcript TEXT, summary TEXT, points TEXT, todos TEXT, error TEXT);
"""
SUMMARY_PROMPT = (
    "Dostaneš přepis hovoru (řádky „Já:“ = uživatel, „Ostatní:“ = ostatní účastníci). Napiš česky "
    "(nebo jazykem hovoru) JSON s klíči: \"title\" (krátký název hovoru, max 6 slov), \"summary\" (shrnutí ve 2–4 "
    "větách), \"points\" (seznam nejdůležitějších bodů, max 8), \"todos\" (seznam úkolů, co z hovoru vyplývá; "
    "u každého kdo, pokud to zaznělo). Vrať jen JSON."
)


class _Track:
    """One recorder thread writing 16 kHz mono int16 to a WAV, padding silence to keep wall-clock time."""

    def __init__(self, path: Path, make_recorder, on_level):
        self.path = path
        self.make_recorder = make_recorder
        self.on_level = on_level
        self.frames = 0
        self.error = ""
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True, name=f"note-{path.stem}")

    def start(self, t0: float):
        self.t0 = t0
        self._t.start()

    def stop(self):
        self._stop.set()
        self._t.join(timeout=5)

    def _run(self):
        import numpy as np

        try:
            with wave.open(str(self.path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                with self.make_recorder() as rec:
                    while not self._stop.is_set():
                        chunk = rec.record(numframes=SR // 10)
                        a = np.asarray(chunk, dtype=np.float32)
                        if a.ndim > 1:
                            a = a.mean(axis=1)
                        # keep both tracks on the same clock: pad what the device did not deliver
                        behind = int((time.monotonic() - self.t0) * SR) - self.frames - len(a)
                        if behind > SR // 2:
                            w.writeframes(b"\0\0" * behind)
                            self.frames += behind
                        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
                        self.frames += len(a)
                        self.on_level(float(np.sqrt(np.mean(a * a))) if a.size else 0.0)
                        if self.frames > MAX_SECONDS * SR:
                            break
        except Exception as e:
            log.warning("notetaker track %s: %s", self.path.stem, e)
            self.error = str(e)


def merge(mine: list[tuple], theirs: list[tuple]) -> list[dict]:
    """Merge the two timed tracks; drop microphone lines that only echo the speakers."""
    lines = [{"who": "Ostatní", "start": s, "end": e, "text": t} for s, e, t in theirs]
    for s, e, t in mine:
        echo = False
        for o in theirs:
            overlap = min(e, o[1]) - max(s, o[0])
            # an echo is simultaneous (the mic hears the speakers) and nearly word for word
            if overlap > 0.2 and difflib.SequenceMatcher(None, t.lower(), o[2].lower()).ratio() > 0.75:
                echo = True
                break
        if not echo:
            lines.append({"who": "Já", "start": s, "end": e, "text": t})
    lines.sort(key=lambda x: x["start"])
    out: list[dict] = []
    for ln in lines:           # glue consecutive lines of the same person
        if out and out[-1]["who"] == ln["who"] and ln["start"] - out[-1]["end"] < 2.5:
            out[-1]["text"] += " " + ln["text"]
            out[-1]["end"] = ln["end"]
        else:
            out.append(dict(ln))
    return out


def parse_summary(text: str) -> dict:
    t = text.strip()
    if "```" in t:
        t = t.split("```")[1].removeprefix("json").strip()
    start, end = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        d = {}
    return {"title": str(d.get("title") or "Hovor")[:80], "summary": str(d.get("summary") or t[:1500]),
            "points": [str(x) for x in d.get("points") or []][:12], "todos": [str(x) for x in d.get("todos") or []][:20]}


class Notetaker:
    def __init__(self, rt: Any):
        self.rt = rt
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
        self.state = "idle"        # idle | recording | processing
        self.current: str | None = None
        self.started = 0.0
        self.tracks: list[_Track] = []
        self._levels = {"mic": 0.0, "sys": 0.0}
        self._last_pub = 0.0
        # stale "recording" rows from a crash become failed
        rt.db.exec("UPDATE notes SET status='failed', error='JARVIS se během nahrávání ukončil.' WHERE status IN ('recording','processing')")

    def folder(self, nid: str) -> Path:
        p = paths.sub("notes") / nid
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------- recording ----------
    def _recorders(self):
        import soundcard as sc

        mic = sc.default_microphone()
        if self.rt.cfg.voice.input_device:
            try:
                mic = sc.get_microphone(self.rt.cfg.voice.input_device)
            except Exception:
                pass
        loop = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
        return (lambda: mic.recorder(samplerate=SR, channels=1)), (lambda: loop.recorder(samplerate=SR, channels=1))

    def start(self) -> dict:
        if self.state != "idle":
            return {"ok": False, "message": "Už se nahrává." if self.state == "recording" else "Ještě zpracovávám minulý hovor."}
        try:
            mic_rec, sys_rec = self._recorders()
        except Exception as e:
            return {"ok": False, "message": f"Nahrávání zvuku není dostupné: {e}"}
        nid = uuid.uuid4().hex[:12]
        folder = self.folder(nid)
        self.current, self.state, self.started = nid, "recording", time.time()
        self.rt.db.exec("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (nid, self.started, "Nahrávám…", 0, "recording", "[]", "", "[]", "[]", ""))
        t0 = time.monotonic()
        self.tracks = [_Track(folder / "mic.wav", mic_rec, lambda v: self._level("mic", v)),
                       _Track(folder / "sys.wav", sys_rec, lambda v: self._level("sys", v))]
        for t in self.tracks:
            t.start(t0)
        self._publish()
        return {"ok": True, "id": nid}

    def _level(self, which: str, v: float) -> None:
        self._levels[which] = round(min(1.0, v * 6), 3)
        now = time.monotonic()
        if now - self._last_pub > 0.25:
            self._last_pub = now
            self._publish()

    def _publish(self, **extra: Any) -> None:
        self.rt.bus.publish_threadsafe("notetaker", state=self.state, id=self.current,
                                       seconds=round(time.time() - self.started) if self.state == "recording" else 0,
                                       mic=self._levels["mic"], sys=self._levels["sys"], **extra)

    def stop(self, cancel: bool = False) -> dict:
        if self.state != "recording" or not self.current:
            return {"ok": False, "message": "Nic se nenahrává."}
        for t in self.tracks:
            t.stop()
        nid, seconds = self.current, time.time() - self.started
        if cancel:
            shutil.rmtree(self.folder(nid), ignore_errors=True)
            self.rt.db.exec("DELETE FROM notes WHERE id=?", (nid,))
            self.state, self.current = "idle", None
            self._publish()
            return {"ok": True}
        self.state = "processing"
        self.rt.db.exec("UPDATE notes SET status='processing', seconds=? WHERE id=?", (round(seconds, 1), nid))
        self._publish(progress=0)
        errors = [t.error for t in self.tracks if t.error]
        self.rt.submit(self.process(nid, errors))
        return {"ok": True, "id": nid}

    # ---------- transcript, summary ----------
    def _stt(self):
        return self.rt.dictation._stt()

    async def process(self, nid: str, errors: list[str] | None = None) -> None:
        folder = self.folder(nid)
        try:
            stt = self._stt()
            tracks = {}
            for i, name in enumerate(("mic", "sys")):
                f = folder / f"{name}.wav"
                if f.exists() and f.stat().st_size > 44 + SR:      # more than ~0.5 s of audio
                    def prog(x, i=i):
                        self.rt.bus.publish_threadsafe("notetaker", state="processing", id=nid, progress=round((i + x) / 2.4, 3))
                    tracks[name] = await asyncio.to_thread(stt.segments, str(f), prog)
                else:
                    tracks[name] = []
            lines = merge(tracks["mic"], tracks["sys"])
            if not lines:
                raise RuntimeError("V nahrávce jsem neslyšel žádnou řeč." + (f" ({'; '.join(errors)})" if errors else ""))
            self.rt.db.exec("UPDATE notes SET transcript=? WHERE id=?", (json.dumps(lines, ensure_ascii=False), nid))
            shutil.rmtree(folder, ignore_errors=True)          # the audio is gone once the words are written
            self.rt.bus.publish("notetaker", state="processing", id=nid, progress=0.85)
            text = "\n".join(f"{ln['who']}: {ln['text']}" for ln in lines)[:60000]
            try:
                out = await asyncio.wait_for(self.rt.router.complete(
                    [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": text}]), 180)
                s = parse_summary(out)
            except Exception as e:
                log.warning("notetaker summary: %s", e)
                s = {"title": "Hovor", "summary": "Shrnutí se nepodařilo (AI není dostupná). Přepis je níže.", "points": [], "todos": []}
            self.rt.db.exec("UPDATE notes SET title=?, summary=?, points=?, todos=?, status='done' WHERE id=?",
                            (s["title"], s["summary"], json.dumps(s["points"], ensure_ascii=False),
                             json.dumps(s["todos"], ensure_ascii=False), nid))
            self.rt.notify("Přepis hovoru je hotový", s["title"], speak=False)
        except Exception as e:
            log.exception("notetaker processing")
            shutil.rmtree(folder, ignore_errors=True)
            self.rt.db.exec("UPDATE notes SET status='failed', error=? WHERE id=?", (str(e)[:500], nid))
        finally:
            self.state, self.current = "idle", None
            self.rt.bus.publish("notetaker", state="idle", id=None, done=nid)

    # ---------- reading ----------
    def list(self) -> list[dict]:
        return self.rt.db.all("SELECT id, created, title, seconds, status, error FROM notes ORDER BY created DESC LIMIT 200")

    def get(self, nid: str) -> dict | None:
        r = self.rt.db.one("SELECT * FROM notes WHERE id=?", (nid,))
        if not r:
            return None
        for k in ("transcript", "points", "todos"):
            r[k] = json.loads(r[k] or "[]")
        return r

    def delete(self, nid: str) -> None:
        if nid == self.current:
            return
        shutil.rmtree(paths.sub("notes") / nid, ignore_errors=True)
        self.rt.db.exec("DELETE FROM notes WHERE id=?", (nid,))
