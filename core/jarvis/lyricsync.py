"""3.14 Texty se samy doladí: the lyrics' timing fitted to the singing, by listening to what the PC plays.

Players report where the song is a little late or early, and a text made for a slightly different version is shifted –
until now you moved it by hand ("Text pozadu / napřed"). Now, once per song, JARVIS listens to ~25 s of the sound the PC
plays (WASAPI loopback of the speaker – never the microphone; processed in memory, nothing is stored or sent) and finds
the shift at which the lines start together with the singing:

- the sound → the energy of the voice band (300–3400 Hz) every 50 ms → how sharply it rises (an onset)
- every shift from −3 s to +3 s is tried: how strongly do the singing onsets fall on the starts of the lines?
- the best one is used only when it clearly stands out and at least 4 lines started in the window; otherwise nothing
  changes (an instrumental part, a quiet song, speech over the music)

Nastavení → Notch → Texty se samy doladí (on by default). You can still nudge it by hand – that wins for the song.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

SR = 16000
FRAME_S = 0.05
LISTEN_S = 25.0
SHIFTS = [round(-3.0 + i * 0.05, 2) for i in range(121)]      # −3 … +3 s
MIN_LINES = 4
MIN_Z = 4.0
LEAD_S = 0.2                                                 # the light a hair before the voice reads best
WEIGHTS = (0.25, 0.5, 1.0, 0.5, 0.25)
MIN_SCORE = 1.5                                              # the singing must rise clearly at the lines, not by chance


def onset_strength(samples: Any, sr: int = SR, frame_s: float = FRAME_S) -> Any:
    """Mono samples → per frame how sharply the voice band rises (0 = no rise), normalised."""
    import numpy as np

    x = np.asarray(samples, dtype="float32")
    n = int(sr * frame_s)
    frames = len(x) // n
    if frames < 4:
        return np.zeros(0, dtype="float32")
    x = x[: frames * n].reshape(frames, n) * np.hanning(n).astype("float32")
    spec = np.abs(np.fft.rfft(x, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / sr)
    band = (freqs >= 300) & (freqs <= 3400)
    energy = np.log1p(spec[:, band].sum(axis=1) * 1e3)
    rise = np.maximum(0.0, np.diff(energy, prepend=energy[0]))
    sd = float(rise.std()) or 1.0
    return ((rise - float(rise.mean())) / sd).astype("float32")


def estimate_shift(onsets: Any, start_pos: float, line_times: list[float], frame_s: float = FRAME_S) -> dict:
    """The song position of frame 0 is `start_pos`. → {"shift": s to add to the position for the lyrics, "z", "lines"}
    or {"shift": None, …} when the singing does not clearly line up with the text."""
    import numpy as np

    o = np.asarray(onsets, dtype="float32")
    weights = np.asarray(WEIGHTS, dtype="float32")
    if not len(o):
        return {"shift": None, "z": 0.0, "lines": 0}
    end_pos = start_pos + len(o) * frame_s
    scores, counts = [], []
    for d in SHIFTS:
        vals = []
        for t in line_times:
            at = t + d                                     # where the singing of this line would start
            if at < start_pos + 0.3 or at > end_pos - 0.3:
                continue
            i = int(round((at - start_pos) / frame_s))
            lo = max(0, i - 2)
            win = o[lo: i + 3]
            w = weights[2 - (i - lo): 2 - (i - lo) + len(win)]
            vals.append(float((win * w).sum()))           # centred: the rise right at the line counts most
        scores.append(float(np.mean(vals)) if vals else -1e9)
        counts.append(len(vals))
    arr = np.array(scores)
    ok = arr > -1e8
    if ok.sum() < 10:
        return {"shift": None, "z": 0.0, "lines": 0}
    best = int(np.argmax(np.where(ok, arr, -1e9)))
    z = float((arr[best] - arr[ok].mean()) / (arr[ok].std() or 1.0))
    if counts[best] < MIN_LINES or z < MIN_Z or arr[best] < MIN_SCORE:
        return {"shift": None, "z": round(z, 2), "lines": counts[best]}
    d = SHIFTS[best]
    return {"shift": round(-d + LEAD_S, 2), "z": round(z, 2), "lines": counts[best], "delay": d}


class AutoSync:
    """Once per song with timed lyrics: listen, estimate, tell the notch."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.done: set[tuple] = set()
        self._busy = False

    def wanted(self) -> bool:
        import sys

        n = getattr(self.rt.cfg, "notch", None)
        return sys.platform == "win32" and bool(getattr(n, "lyrics", True)) and bool(getattr(n, "lyrics_autosync", True))

    def maybe_start(self) -> bool:
        st = getattr(self.rt, "lyrics_state", {}) or {}
        media = getattr(self.rt, "media_state", {}) or {}
        key = (st.get("title"), st.get("artist"))
        if (self._busy or not self.wanted() or not st.get("synced") or not media.get("playing") or key in self.done
                or st.get("title") != media.get("title") or len(st.get("lines") or []) < MIN_LINES):
            return False
        self.done.add(key)
        if len(self.done) > 300:
            self.done.clear()
        self._busy = True
        threading.Thread(target=self._run, args=(key, [float(x["t"]) for x in st["lines"] if x.get("text")]),
                         daemon=True, name="lyrics-autosync").start()
        return True

    def _position(self) -> float | None:
        m = getattr(self.rt, "media_state", {}) or {}
        if not isinstance(m.get("position"), (int, float)):
            return None
        return float(m["position"]) + ((time.time() - float(m.get("at") or time.time())) if m.get("playing") else 0.0)

    def _run(self, key: tuple, line_times: list[float]) -> None:
        try:
            import numpy as np
            import soundcard as sc

            spk = sc.default_speaker()
            mic = sc.get_microphone(str(spk.name), include_loopback=True)
            start = self._position()
            if start is None:
                return
            with mic.recorder(samplerate=SR, channels=1) as r:
                data = r.record(numframes=int(SR * LISTEN_S))
            block = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
            media = getattr(self.rt, "media_state", {}) or {}
            if (media.get("title"), media.get("artist")) != key or not media.get("playing"):
                return                                     # the song changed or paused while listening: no guess
            res = estimate_shift(onset_strength(np.asarray(block)), start, line_times)
            log.info("lyrics autosync %s: %s", key[0], res)
            if res["shift"] is not None:
                self.rt.bus.publish("lyrics_autoshift", title=key[0] or "", artist=key[1] or "", shift=res["shift"], z=res["z"])
        except Exception as e:  # noqa: BLE001 – no loopback (no speaker, Linux): the hand-made shift stays
            log.info("lyrics autosync: %s", e)
        finally:
            self._busy = False


def of(rt: Any) -> AutoSync:
    a = getattr(rt, "lyrics_autosync", None)
    if a is None:
        a = rt.lyrics_autosync = AutoSync(rt)
    return a
