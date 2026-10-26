"""OMEGA §23 voice and audio: clean speech before it is recognised – noise suppression (Wiener filter with a
decision-directed SNR estimate), automatic gain for a distant microphone, an acoustic echo canceller (partitioned
block frequency-domain NLMS with delay estimation) so JARVIS does not hear itself, a microphone check, speaker
labels by clustering voice features (MFCC), and a wake-word threshold from measured scores. Pure numpy."""
from __future__ import annotations

import math
import threading
from collections import deque

import numpy as np


def _db(v: float) -> float:
    return 20 * math.log10(max(v, 1e-9))


def _frames(x: np.ndarray, n: int, hop: int) -> np.ndarray:
    pad = np.concatenate([np.zeros(n, np.float32), x.astype(np.float32), np.zeros(n, np.float32)])
    return np.lib.stride_tricks.sliding_window_view(pad, n)[::hop]


# ============================================================================================== 257 noise suppression
def denoise(x: np.ndarray, rate: int = 16000, noise: np.ndarray | None = None, floor_db: float = -22, alpha: float = 0.98) -> tuple[np.ndarray, dict]:
    """Wiener-style noise suppression. The noise spectrum comes from `noise` (e.g. the second before the wake word)
    or from the quietest 10 % of the frames. Returns the cleaned signal and how much the noise dropped."""
    x = np.asarray(x, np.float32)
    if len(x) < 256:
        return x.copy(), {"noise_reduction_db": 0.0}
    n = 512 if rate <= 16000 else 1024
    hop = n // 2
    win = np.sqrt(np.hanning(n + 1)[:n]).astype(np.float32)          # sqrt-Hann at 50 %: analysis × synthesis sums to 1
    spec = np.fft.rfft(_frames(x, n, hop) * win, axis=1)
    p = np.abs(spec) ** 2
    if noise is not None and len(noise) >= n:
        npsd = (np.abs(np.fft.rfft(_frames(np.asarray(noise, np.float32), n, hop)[1:-1] * win, axis=1)) ** 2).mean(axis=0)
    else:
        e = p.sum(axis=1)
        npsd = p[e <= np.percentile(e, 10)].mean(axis=0)
    npsd = np.maximum(npsd, 1e-12)
    floor = 10 ** (floor_db / 20)
    gains = np.empty_like(p)
    prev = np.zeros(p.shape[1])
    for t in range(len(p)):
        gamma = p[t] / npsd
        xi = alpha * prev / npsd + (1 - alpha) * np.maximum(gamma - 1, 0)
        g = np.maximum(xi / (1 + xi), floor)
        gains[t] = g
        prev = (g ** 2) * p[t]
    y_fr = np.fft.irfft(spec * gains, n=n, axis=1) * win
    out = np.zeros(len(x) + 3 * n, np.float32)
    for i, fr in enumerate(y_fr):
        out[i * hop:i * hop + n] += fr
    y = out[n:n + len(x)]
    e = p.sum(axis=1)
    quiet = e <= np.percentile(e, 10)
    before = float(p[quiet].sum())
    after = float((p * gains ** 2)[quiet].sum())
    return y.astype(np.float32), {"noise_reduction_db": round(10 * math.log10(max(before, 1e-20) / max(after, 1e-20)), 1)}


# ============================================================================================== 256 distant microphone
def agc(x: np.ndarray, rate: int = 16000, target_dbfs: float = -20, max_gain_db: float = 24) -> tuple[np.ndarray, dict]:
    """Automatic gain for speech from across the room: the level of the speech frames (not the pauses) brought to
    the target, the gain limited, the peaks kept under −1 dBFS."""
    x = np.asarray(x, np.float32)
    f = max(1, int(rate * 0.03))
    n = len(x) // f
    if n < 3:
        return x.copy(), {"gain_db": 0.0, "speech_dbfs": None}
    rms = np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(axis=1) + 1e-12)
    floor = np.percentile(rms, 20)
    active = rms[rms > floor * 2] if (rms > floor * 2).any() else rms
    level = _db(float(np.sqrt((active ** 2).mean())))
    gain_db = max(-12.0, min(max_gain_db, target_dbfs - level))
    y = x * 10 ** (gain_db / 20)
    peak = float(np.max(np.abs(y))) if len(y) else 0
    lim = 10 ** (-1 / 20)
    if peak > lim:
        y = y * (lim / peak)
        gain_db += _db(lim / peak)
    return y.astype(np.float32), {"gain_db": round(gain_db, 1), "speech_dbfs": round(level, 1)}


# ============================================================================================== 258 echo cancellation
def gcc_phat(mic: np.ndarray, ref: np.ndarray, max_delay: int) -> tuple[int, float]:
    """Delay (in samples) by which `mic` lags `ref`, by generalised cross-correlation with phase transform, and the
    peak's prominence (how sure it is)."""
    n = 1 << int(math.ceil(math.log2(len(mic) + len(ref))))
    cross = np.fft.rfft(mic, n) * np.conj(np.fft.rfft(ref, n))
    cc = np.fft.irfft(cross / np.maximum(np.abs(cross), 1e-12), n)
    window = cc[: max_delay + 1]
    k = int(np.argmax(window))
    return k, float(window[k] / (np.mean(np.abs(window)) + 1e-12))


class EchoCanceller:
    """Partitioned-block frequency-domain NLMS: learns how the speaker sound reaches the microphone and subtracts it.
    Blocks of `block` samples, `partitions` blocks of echo tail (256 × 8 = 128 ms at 16 kHz). Adaptation is frozen
    while the near end clearly talks over the echo (Geigel double-talk detector)."""

    def __init__(self, block: int = 256, partitions: int = 8, mu: float = 0.5):
        self.B, self.P, self.mu = block, partitions, mu
        self.W = np.zeros((partitions, block + 1), np.complex128)
        self.X = deque([np.zeros(block + 1, np.complex128)] * partitions, maxlen=partitions)
        self.prev_far = np.zeros(block)
        self.pow: np.ndarray | None = None
        self.long = 0.0                                      # long-term far-end power: regularises the quiet moments
        self.far_peak = deque(maxlen=partitions * 2)

    def process(self, mic: np.ndarray, far: np.ndarray) -> np.ndarray:
        B = self.B
        mic, far = np.asarray(mic, np.float64), np.asarray(far, np.float64)
        Xk = np.fft.rfft(np.concatenate([self.prev_far, far]))
        self.prev_far = far
        self.X.appendleft(Xk)
        Y = sum(w * x for w, x in zip(self.W, self.X))
        y = np.fft.irfft(Y)[B:]
        e = mic - y
        self.far_peak.append(float(np.max(np.abs(far))) if len(far) else 0.0)
        double_talk = float(np.max(np.abs(mic))) > 0.9 * max(self.far_peak) and float(np.max(np.abs(e))) > 0.5 * float(np.max(np.abs(mic)))
        px = np.abs(Xk) ** 2
        self.long = float(px.mean()) if not self.long else 0.995 * self.long + 0.005 * float(px.mean())
        # adapt only while JARVIS really sounds (a near-silent far end would blow the step up) and nobody talks over it
        if float(px.mean()) > 0.05 * self.long > 0 and not double_talk:
            # power over the whole filter length (all partitions), smoothed; starts from the real level, not from 0
            tot = sum(np.abs(x) ** 2 for x in self.X)
            self.pow = tot if self.pow is None else 0.7 * self.pow + 0.3 * tot
            E = np.fft.rfft(np.concatenate([np.zeros(B), e]))
            norm = self.pow + 0.1 * self.long * self.P + 1e-12
            for p, x in enumerate(self.X):
                g = np.fft.irfft(self.mu * np.conj(x) * E / norm)
                g[B:] = 0                                              # gradient constraint (linear, not circular)
                self.W[p] += np.fft.rfft(g)
        return e.astype(np.float32)


class EchoPath:
    """Puts the far end (what JARVIS plays) next to the microphone in time. The player writes what it plays with a
    timestamp; each microphone frame asks for the far-end samples played at the same moment, shifted by the
    measured device delay (estimated once by GCC-PHAT while JARVIS speaks)."""

    def __init__(self, rate: int = 16000, seconds: float = 6.0, block: int = 256):
        self.rate, self.block = rate, block
        self.buf = np.zeros(int(rate * seconds), np.float32)
        self.end = 0                                          # absolute sample index of the newest far-end sample
        self.t_end = 0.0
        self.delay: int | None = None
        self.aec = EchoCanceller(block)
        self.lock = threading.Lock()
        self._mic_hist: list[np.ndarray] = []
        self.active_until = 0.0

    def _pos(self, t: float) -> int:
        return self.end - int(round((self.t_end - t) * self.rate))

    def played(self, samples: np.ndarray, rate: int, t: float) -> None:
        """The player wrote `samples` (float, any rate) at monotonic time t."""
        s = np.asarray(samples, np.float32)
        if rate != self.rate and len(s):
            s = np.interp(np.linspace(0, len(s) - 1, int(len(s) * self.rate / rate)), np.arange(len(s)), s).astype(np.float32)
        with self.lock:
            n = len(s)
            if n >= len(self.buf):
                s, n = s[-len(self.buf):], len(self.buf)
            self.buf = np.roll(self.buf, -n)
            self.buf[-n:] = s
            self.end += n
            self.t_end = t + n / self.rate
            self.active_until = self.t_end + 0.6

    def far_for(self, t_start: float, n: int) -> np.ndarray:
        with self.lock:
            start = self._pos(t_start) - (self.delay or 0)
            off = start - (self.end - len(self.buf))
            if off + n <= 0 or off >= len(self.buf):
                return np.zeros(n, np.float32)
            out = np.zeros(n, np.float32)
            a, b = max(0, off), min(len(self.buf), off + n)
            out[a - off:b - off] = self.buf[a:b]
            return out

    def clean(self, mic: np.ndarray, t_start: float) -> np.ndarray:
        """Remove JARVIS's own voice from a microphone frame recorded starting at monotonic time t_start."""
        if t_start > self.active_until:
            return np.asarray(mic, np.float32)
        mic = np.asarray(mic, np.float32)
        if self.delay is None:
            self._mic_hist.append(mic)
            got = sum(len(m) for m in self._mic_hist)
            if got >= self.rate:                               # one second of mic while speaking → measure the delay
                m = np.concatenate(self._mic_hist)
                with self.lock:
                    ref_start = self._pos(t_start + len(mic) / self.rate - len(m) / self.rate)
                ref = self._slice(ref_start - int(0.3 * self.rate), len(m) + int(0.3 * self.rate))
                d, conf = gcc_phat(m, ref, int(0.5 * self.rate))
                self.delay = max(0, d - int(0.3 * self.rate)) if conf > 5 else 0
                self._mic_hist = []
        out = np.empty_like(mic)
        B = self.block
        for i in range(0, len(mic) - B + 1, B):
            far = self.far_for(t_start + i / self.rate, B)
            out[i:i + B] = self.aec.process(mic[i:i + B], far)
        rest = len(mic) % B
        if rest:
            out[-rest:] = mic[-rest:]
        return out

    def _slice(self, start: int, n: int) -> np.ndarray:
        with self.lock:
            off = start - (self.end - len(self.buf))
            out = np.zeros(n, np.float32)
            a, b = max(0, off), min(len(self.buf), off + n)
            if b > a:
                out[a - off:b - off] = self.buf[a:b]
            return out


# ============================================================================================== mic check
def mic_report(x: np.ndarray, rate: int = 16000) -> dict:
    """Noise floor, speech level, signal-to-noise ratio, clipping and DC of a short recording, with advice."""
    x = np.asarray(x, np.float32)
    f = int(rate * 0.03)
    n = len(x) // f
    if n < 10:
        raise ValueError("Nahrávka je moc krátká (aspoň půl vteřiny).")
    rms = np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(axis=1) + 1e-12)
    noise, speech = _db(float(np.percentile(rms, 10))), _db(float(np.percentile(rms, 95)))
    clip = float(np.mean(np.abs(x) >= 0.99))
    snr = speech - noise
    advice = []
    if clip > 0.001:
        advice.append("mikrofon se přebuzuje – sniž jeho citlivost ve Windows nebo mluv dál")
    if speech < -35:
        advice.append("řeč je slabá – mluv blíž nebo zvyš citlivost mikrofonu; pro vzdálený mikrofon zapni automatické zesílení")
    if noise > -45:
        advice.append("hodně šumu v pozadí – nech zapnutý filtr hluku, vypni ventilátor / klimatizaci poblíž")
    if snr < 15 and speech >= -35:
        advice.append("řeč je jen málo nad šumem – rozpoznávání bude chybovat")
    if abs(float(np.mean(x))) > 0.01:
        advice.append("posunutá nula signálu (DC) – vadný nebo špatně nastavený mikrofon")
    return {"noise_dbfs": round(noise, 1), "speech_dbfs": round(speech, 1), "snr_db": round(snr, 1), "clipping_pct": round(100 * clip, 3),
            "verdict": "výborné" if snr >= 30 and not clip and speech > -35 else "dobré" if snr >= 20 else "slabé", "advice": advice}


def record(seconds: float, rate: int = 16000, device: str | None = None) -> np.ndarray:
    import sounddevice as sd

    a = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="float32", device=device or None)
    sd.wait()
    return a.reshape(-1)


# ============================================================================================== 267 speaker labels
def _mel(n_fft: int, rate: int, n_mels: int = 26) -> np.ndarray:
    def hz2mel(h):
        return 2595 * np.log10(1 + h / 700)
    pts = 700 * (10 ** (np.linspace(hz2mel(60), hz2mel(rate / 2 * 0.95), n_mels + 2) / 2595) - 1)
    bins = np.floor((n_fft + 1) * pts / rate).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        for k in range(a, b):
            fb[m - 1, k] = (k - a) / max(1, b - a)
        for k in range(b, c):
            fb[m - 1, k] = (c - k) / max(1, c - b)
    return fb


def mfcc(x: np.ndarray, rate: int = 16000, n: int = 13) -> np.ndarray:
    x = np.asarray(x, np.float32)
    x = np.append(x[0], x[1:] - 0.97 * x[:-1]) if len(x) > 1 else x
    size, hop = int(rate * 0.025), int(rate * 0.01)
    n_fft = 1 << int(math.ceil(math.log2(size)))
    if len(x) < size:
        return np.zeros((0, n - 1))
    fr = np.lib.stride_tricks.sliding_window_view(x, size)[::hop] * np.hamming(size)
    pw = np.abs(np.fft.rfft(fr, n_fft, axis=1)) ** 2 / n_fft
    energy = pw.sum(axis=1)
    keep = energy > np.percentile(energy, 30)                          # voiced / loud frames carry the voice
    mel = np.log(pw[keep] @ _mel(n_fft, rate).T + 1e-10)
    k = np.arange(mel.shape[1])
    dct = np.cos(np.pi / mel.shape[1] * (k[None, :] + 0.5) * np.arange(n)[:, None]) * math.sqrt(2 / mel.shape[1])   # orthonormal DCT-II
    return (mel @ dct.T)[:, 1:]


def pitch(x: np.ndarray, rate: int = 16000, lo: float = 70, hi: float = 400) -> float | None:
    """Median fundamental frequency of the voiced frames (normalised autocorrelation), Hz."""
    x = np.asarray(x, np.float32)
    size, hop = int(rate * 0.04), int(rate * 0.02)
    if len(x) < size:
        return None
    fr = np.lib.stride_tricks.sliding_window_view(x, size)[::hop]
    e = (fr ** 2).sum(axis=1)
    lag_lo, lag_hi = int(rate / hi), int(rate / lo)
    f0 = []
    for f in fr[e > np.percentile(e, 50)]:
        f = f - f.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2 * size)) ** 2)[: lag_hi + 1]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        k = lag_lo + int(np.argmax(ac[lag_lo:lag_hi + 1]))
        if ac[k] > 0.4:
            f0.append(rate / k)
    return float(np.median(f0)) if len(f0) >= 3 else None


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    k = len(set(labels.tolist()))
    if k < 2 or k >= len(X):
        return -1.0
    D = np.linalg.norm(X[:, None] - X[None], axis=2)
    s = []
    for i in range(len(X)):
        same = labels == labels[i]
        a = D[i, same & (np.arange(len(X)) != i)].mean() if same.sum() > 1 else 0.0
        b = min(D[i, labels == c].mean() for c in set(labels.tolist()) if c != labels[i])
        s.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(s))


def _agglomerate(X: np.ndarray, k: int) -> np.ndarray:
    """Average-linkage agglomerative clustering into k groups."""
    D = np.linalg.norm(X[:, None] - X[None], axis=2)
    clusters = [[i] for i in range(len(X))]
    while len(clusters) > k:
        best, pair = None, None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = D[np.ix_(clusters[i], clusters[j])].mean()
                if best is None or d < best:
                    best, pair = d, (i, j)
        i, j = pair
        clusters[i] += clusters.pop(j)
    lab = np.zeros(len(X), int)
    for c, members in enumerate(sorted(clusters, key=min)):
        lab[members] = c
    return lab


def voice_features(x: np.ndarray, rate: int) -> np.ndarray | None:
    """Mean MFCC (timbre, vocal tract) and pitch in semitones (voice height) of one stretch of speech."""
    m = mfcc(x, rate)
    if len(m) < 20:
        return None
    f0 = pitch(x, rate)
    return np.concatenate([m.mean(axis=0), [12 * math.log2(f0 / 100) if f0 else np.nan]])


MIN_VOICE_GAP = 3.0   # centroid distance (≈ semitones of pitch / units of timbre) below which two groups are one voice


def diarize(x: np.ndarray, rate: int, segments: list[tuple[float, float]], speakers: int = 0, max_speakers: int = 6) -> dict:
    """Which segments were said by the same voice: per segment the timbre (mean MFCC, mean-normalised over the
    recording) and the pitch, clustered by average linkage; the number of speakers given, or chosen by the
    silhouette score with at least two segments per speaker."""
    feats, idx = [], []
    for i, (s, e) in enumerate(segments):
        f = voice_features(x[int(s * rate):int(e * rate)], rate)
        if f is not None:
            feats.append(f)
            idx.append(i)
    if len(feats) < 2:
        return {"labels": [0] * len(segments), "speakers": 1 if segments else 0, "confidence": None}
    X = np.array(feats)
    pitch_col = X[:, -1]
    pitch_col[np.isnan(pitch_col)] = np.nanmedian(pitch_col) if not np.isnan(pitch_col).all() else 0
    X[:, :-1] -= X[:, :-1].mean(axis=0)                                 # cepstral mean normalisation over the recording
    X[:, -1] = pitch_col - pitch_col.mean()                            # 1 semitone weighs like 1 unit of timbre
    if speakers:
        k = min(speakers, len(X))
        lab = _agglomerate(X, k)
        score = _silhouette(X, lab) if k > 1 else None
    else:
        k, lab, score = 1, np.zeros(len(X), int), None
        best = -1.0
        for kk in range(2, min(max_speakers, len(X) // 2) + 1):
            cand = _agglomerate(X, kk)
            if np.bincount(cand).min() < 2:                            # a "speaker" with a single segment is noise
                continue
            cents = np.array([X[cand == c].mean(axis=0) for c in range(kk)])
            if min(np.linalg.norm(cents[i] - cents[j]) for i in range(kk) for j in range(i + 1, kk)) < MIN_VOICE_GAP:
                continue                                               # groups this close are one voice saying different things
            sc = _silhouette(X, cand)
            if sc > best + 0.02:
                best, k, lab, score = sc, kk, cand, sc
        if best < 0.3:
            k, lab = 1, np.zeros(len(X), int)
    labels = [0] * len(segments)
    for j, i in enumerate(idx):
        labels[i] = int(lab[j])
    for i in range(len(segments)):                                   # too-short segments take the neighbour's voice
        if i not in idx:
            labels[i] = labels[i - 1] if i else (labels[idx[0]] if idx else 0)
    return {"labels": labels, "speakers": int(k), "confidence": round(float(score), 2) if score is not None else None}


# ============================================================================================== 260 wake word sensitivity
def recommend_threshold(quiet: list[float], words: list[float]) -> dict:
    """quiet: wake-word scores while nobody says it (TV, talking); words: the peak score each time it was said."""
    if not words:
        raise ValueError("Nejdřív několikrát řekni probouzecí frázi.")
    noise = max(quiet) if quiet else 0.0
    weakest = min(words)
    if weakest <= noise:
        return {"threshold": None, "ok": False, "noise_max": round(noise, 3), "weakest_word": round(weakest, 3),
                "advice": "Fráze se od okolního zvuku neliší – mluv blíž, zapni filtr hluku nebo zvol jiné probouzecí slovo."}
    thr = round(min(0.9, max(0.2, noise + (weakest - noise) * 0.4)), 2)
    caught = sum(1 for w in words if w >= thr)
    return {"threshold": thr, "ok": True, "noise_max": round(noise, 3), "weakest_word": round(weakest, 3), "caught": f"{caught}/{len(words)}",
            "advice": f"Práh {thr}: zachytí {caught} z {len(words)} vyslovení a okolní zvuk nejvýš {noise:.2f} ho nespustí."}


# ============================================================================================== 99 ducking
class Ducker:
    """Turns the other programs down while JARVIS listens or speaks and back up afterwards (reference-counted, so
    listening and speaking can overlap)."""

    def __init__(self, platform, level_fn):
        self.platform, self.level_fn = platform, level_fn
        self.n = 0
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            self.n += 1
            if self.n == 1:
                try:
                    self.platform.duck_audio(self.level_fn())
                except Exception:  # noqa: BLE001 – audio sessions unavailable: just do not duck
                    pass

    def release(self) -> None:
        with self.lock:
            if self.n == 0:
                return
            self.n -= 1
            if self.n == 0:
                try:
                    self.platform.duck_audio(None)
                except Exception:  # noqa: BLE001
                    pass
