"""3.14 Hlas – kdo mluví a jak (návrhy 37, 38, 39, 41).

- voice print: mean and spread of the MFCCs + the pitch of a few sentences → a vector per person; a new utterance
  is compared with each person (cosine similarity, a threshold learnt from that person's own samples)
- owner only: money, deleting, unlocking and other actions that ask for confirmation are done by voice only when
  the voice is the owner's. This is protection against a TV, a guest or a child – not against a determined
  attacker with a recording; the confirmation itself still asks as before
- household: each person has a name; JARVIS is told who is speaking (and guests get the guest rules)
- own wake word: 8–20 recordings of the word → their MFCC sequences; a short utterance followed by a pause is
  compared with them by dynamic time warping (DTW); it works next to "Hey Jarvis", fully on this PC
- whispering: speech with energy but almost no voiced (pitched) frames → the answer comes quietly
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .dsp import mfcc, pitch

log = logging.getLogger(__name__)
SR = 16000


def _dir() -> Path:
    from .. import paths

    d = paths.sub("models") / "voiceid"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _f32(pcm16: bytes | np.ndarray) -> np.ndarray:
    if isinstance(pcm16, np.ndarray):
        return pcm16.astype(np.float32)
    return np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0


# ---------- 38 / 39: voice print ----------
def embed(x: np.ndarray, rate: int = SR) -> np.ndarray | None:
    """Mean + standard deviation of 12 MFCCs, their mean change, and the pitch – normalised to length 1."""
    m = mfcc(x, rate)
    if len(m) < 30:
        return None
    d = np.diff(m, axis=0)
    f0 = pitch(x, rate)
    v = np.concatenate([m.mean(axis=0), m.std(axis=0), np.abs(d).mean(axis=0),
                        [12 * math.log2(f0 / 100) if f0 else 0.0]]).astype(np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n else None


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


class Profiles:
    """People of the household: name → their voice print, the threshold, whether it is the owner."""

    FILE = "profiles.json"

    def __init__(self, folder: Path | None = None):
        self.folder = folder or _dir()
        self.people: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            self.people = json.loads((self.folder / self.FILE).read_text("utf-8"))
        except (OSError, ValueError):
            self.people = {}

    def save(self) -> None:
        (self.folder / self.FILE).write_text(json.dumps(self.people, ensure_ascii=False), "utf-8")

    def enroll(self, name: str, samples: list[np.ndarray], owner: bool = False) -> dict:
        vecs = [e for e in (embed(s) for s in samples) if e is not None]
        if len(vecs) < 3:
            raise ValueError("na hlasový otisk potřebuju aspoň 3 věty (každá aspoň 1 s řeči)")
        centre = np.mean(vecs, axis=0)
        sims = [cosine(v, centre) for v in vecs]
        # accept what is as close as this person's own weakest sample, with a little room
        thr = max(0.80, min(0.97, min(sims) - 0.03))
        if owner:
            for p in self.people.values():
                p["owner"] = False
        self.people[name] = {"vec": centre.tolist(), "threshold": round(thr, 3), "owner": owner, "samples": len(vecs),
                             "created": time.time()}
        self.save()
        return {"name": name, "threshold": thr, "samples": len(vecs), "owner": owner}

    def remove(self, name: str) -> None:
        self.people.pop(name, None)
        self.save()

    def owner(self) -> str:
        return next((n for n, p in self.people.items() if p.get("owner")), "")

    def identify(self, x: np.ndarray) -> tuple[str, float]:
        """(name, similarity) of the best match above its threshold, or ("", best similarity)."""
        e = embed(x)
        if e is None or not self.people:
            return "", 0.0
        best, score = "", 0.0
        for name, p in self.people.items():
            s = cosine(e, np.asarray(p["vec"]))
            if s >= p["threshold"] and s > score:
                best, score = name, s
            elif not best:
                score = max(score, s)
        return best, round(score, 3)

    def public(self) -> list[dict]:
        return [{"name": n, "owner": p.get("owner", False), "samples": p.get("samples", 0), "threshold": p.get("threshold")}
                for n, p in self.people.items()]


# ---------- 37: own wake word (DTW over MFCC sequences) ----------
def _feat(x: np.ndarray) -> np.ndarray:
    m = mfcc(x, SR)
    if len(m) == 0:
        return m
    return (m - m.mean(axis=0)) / (m.std(axis=0) + 1e-6)            # per-utterance normalisation (mic, loudness)


def dtw(a: np.ndarray, b: np.ndarray) -> float:
    """Length-normalised DTW distance of two MFCC sequences (rows = frames)."""
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    cost = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    n, m = cost.shape
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0.0
    for i in range(1, n + 1):
        row = cost[i - 1]
        prev = acc[i - 1]
        cur = acc[i]
        # vertical / diagonal from the previous row at once, horizontal needs the running minimum
        best = np.minimum(prev[1:], prev[:-1]) + row
        run = np.inf
        for j in range(1, m + 1):
            run = min(best[j - 1], run + row[j - 1])
            cur[j] = run
    return float(acc[n, m] / (n + m))


class WakeWord:
    """The user's own word, from their recordings. `check(utterance)` → (heard, distance)."""

    FILE = "wakeword.npz"

    def __init__(self, folder: Path | None = None):
        self.folder = folder or _dir()
        self.templates: list[np.ndarray] = []
        self.threshold = 0.0
        self.word = ""
        self.load()

    @property
    def ready(self) -> bool:
        return len(self.templates) >= 3 and self.threshold > 0

    def load(self) -> None:
        f = self.folder / self.FILE
        if not f.exists():
            return
        try:
            d = np.load(f, allow_pickle=False)
            n = int(d["n"])
            self.templates = [d[f"t{i}"] for i in range(n)]
            self.threshold = float(d["threshold"])
            self.word = str(d["word"])
        except Exception as e:  # noqa: BLE001
            log.info("wake word load: %s", e)

    def train(self, word: str, samples: list[np.ndarray]) -> dict:
        feats = [f for f in (_feat(s) for s in samples) if len(f) >= 15]
        if len(feats) < 3:
            raise ValueError("potřebuju aspoň 3 nahrávky slova (každá kolem půl až jedné sekundy)")
        dists = [dtw(a, b) for i, a in enumerate(feats) for b in feats[i + 1:]]
        # the word as you say it varies this much; a little more is still the word, much more is something else
        self.threshold = float(np.mean(dists) + 1.5 * np.std(dists)) if dists else 0.0
        self.templates, self.word = feats, word.strip()[:40]
        arrays: dict[str, Any] = {f"t{i}": f for i, f in enumerate(feats)}
        arrays.update(n=len(feats), threshold=self.threshold, word=self.word)
        np.savez(self.folder / self.FILE, **arrays)
        return {"word": self.word, "samples": len(feats), "threshold": round(self.threshold, 3)}

    def check(self, x: np.ndarray) -> tuple[bool, float]:
        if not self.ready:
            return False, float("inf")
        f = _feat(x)
        if len(f) < 10:
            return False, float("inf")
        d = sorted(dtw(f, t) for t in self.templates)[:3]
        dist = float(np.mean(d))
        return dist <= self.threshold, round(dist, 3)

    def clear(self) -> None:
        self.templates, self.threshold, self.word = [], 0.0, ""
        (self.folder / self.FILE).unlink(missing_ok=True)


class ShortUtterance:
    """Collects a short stretch of speech followed by a pause (the way a wake word is said): 0.3–1.6 s of speech,
    then 0.25 s of silence → the audio; longer speech is not a wake word."""

    def __init__(self, frame_s: float = 0.03):
        self.frame_s = frame_s
        self.buf: list[bytes] = []
        self.silence = 0.0

    def feed(self, frame: bytes, is_speech: bool) -> bytes | None:
        if is_speech:
            self.buf.append(frame)
            self.silence = 0.0
            if len(self.buf) * self.frame_s > 1.6:
                self.buf.clear()                       # too long for a wake word
            return None
        if not self.buf:
            return None
        self.silence += self.frame_s
        self.buf.append(frame)
        if self.silence >= 0.25:
            speech_s = (len(self.buf) - round(self.silence / self.frame_s)) * self.frame_s
            out = b"".join(self.buf) if speech_s >= 0.3 else None
            self.buf.clear()
            self.silence = 0.0
            return out
        return None


# ---------- 41: whispering ----------
def voiced_ratio(x: np.ndarray, rate: int = SR) -> tuple[float, float]:
    """(share of the louder frames that have a pitch, RMS) – whispered speech has energy but almost no pitch."""
    x = np.asarray(x, np.float32)
    size, hop = int(rate * 0.04), int(rate * 0.02)
    if len(x) < size * 3:
        return 1.0, 0.0
    fr = np.lib.stride_tricks.sliding_window_view(x, size)[::hop]
    e = (fr ** 2).mean(axis=1)
    loud = fr[e > max(np.percentile(e, 60), 1e-7)]
    if not len(loud):
        return 1.0, 0.0
    lag_lo, lag_hi = int(rate / 400), int(rate / 70)
    voiced = 0
    for f in loud:
        f = f - f.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2 * size)) ** 2)[: lag_hi + 1]
        if ac[0] > 0 and float(np.max(ac[lag_lo:lag_hi + 1]) / ac[0]) > 0.45:
            voiced += 1
    return voiced / len(loud), float(np.sqrt(np.mean(x ** 2)))


def is_whisper(x: np.ndarray, rate: int = SR) -> bool:
    ratio, rms = voiced_ratio(x, rate)
    return rms > 0.002 and ratio < 0.25


# ---------- the shared state the voice loop and the agent use ----------
class VoiceId:
    def __init__(self, rt: Any):
        self.rt = rt
        self.profiles = Profiles()
        self.wake = WakeWord()
        self.last_speaker = ""
        self.last_score = 0.0
        self.last_at = 0.0
        self.whisper_until = 0.0

    def on_utterance(self, pcm16: bytes) -> dict:
        """After every spoken command: who spoke, and whether it was whispered."""
        x = _f32(pcm16)
        out: dict = {"speaker": "", "score": 0.0, "whisper": False}
        if self.profiles.people:
            out["speaker"], out["score"] = self.profiles.identify(x)
        if getattr(self.rt.cfg.voice, "whisper_reply", True) and is_whisper(x):
            out["whisper"] = True
            self.whisper_until = time.monotonic() + 45
        self.last_speaker, self.last_score, self.last_at = out["speaker"], out["score"], time.time()
        return out

    def whispering(self) -> bool:
        return time.monotonic() < self.whisper_until

    def owner_ok(self, max_age: float = 120.0) -> bool:
        """The last spoken command was the owner's (or no owner is set up – then nothing is checked)."""
        owner = self.profiles.owner()
        if not owner:
            return True
        return self.last_speaker == owner and time.time() - self.last_at <= max_age

    def prompt(self) -> str:
        if not self.last_speaker or time.time() - self.last_at > 120:
            return ""
        owner = self.profiles.owner()
        who = self.last_speaker
        if owner and who != owner:
            return f"Teď mluví {who} (člen domácnosti, ne majitel). Oslov ho jménem; nic citlivého o majiteli neprozrazuj."
        return f"Teď mluví {who}."
