"""OMEGA §30 multimedia: remove silences, duck music under speech, clean up a voice recording (rumble + steady noise),
loudness (EBU R128 / LUFS) and export quality for the big platforms, scenes and highlights in a video, and subtitle
checks / reflow / styled ASS export. Inputs are only read; every result is a NEW file."""
from __future__ import annotations

import math
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np


# ============================================================================================== audio I/O
def read_audio(path: Path, max_seconds: float = 3 * 3600) -> tuple[np.ndarray, int]:
    """→ (samples float32 in −1…1, shape (n, channels), sample rate). WAV natively, anything else through PyAV."""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
                raw = w.readframes(min(n, int(rate * max_seconds)))
            if sw == 1:
                x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
            elif sw == 2:
                x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
            elif sw == 3:
                b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
                v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                x = np.where(v & 0x800000, v - 0x1000000, v).astype(np.float32) / 8388608
            else:
                x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
            return x.reshape(-1, ch), rate
        except wave.Error:
            pass                                                     # e.g. float WAV → PyAV below
    try:
        import av
    except ImportError as e:
        raise ValueError("Tenhle formát umím jen s nainstalovanými hlasovými funkcemi (PyAV). WAV jde vždy.") from e
    chunks, rate = [], 0
    with av.open(str(path)) as c:
        st = next((s for s in c.streams if s.type == "audio"), None)
        if st is None:
            raise ValueError("Soubor nemá zvukovou stopu.")
        rs = av.AudioResampler(format="flt", layout="stereo" if (st.channels or 1) > 1 else "mono")
        total = 0
        for fr in c.decode(st):
            for f2 in rs.resample(fr):
                arr = f2.to_ndarray()
                rate = f2.sample_rate
                arr = arr.reshape(-1, 2) if arr.shape[0] == 1 and (st.channels or 1) > 1 else arr.T
                chunks.append(arr.astype(np.float32))
                total += len(arr)
            if rate and total > rate * max_seconds:
                break
    if not chunks:
        raise ValueError("Ve zvukové stopě nejsou žádná data.")
    return np.concatenate(chunks), rate


def write_wav(path: Path, x: np.ndarray, rate: int) -> Path:
    if path.exists():
        raise ValueError(f"{path.name} už existuje.")
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    data = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return path


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _frames_rms(m: np.ndarray, rate: int, ms: float = 20) -> tuple[np.ndarray, int]:
    hop = max(1, int(rate * ms / 1000))
    n = len(m) // hop
    if n == 0:
        return np.array([float(np.sqrt(np.mean(m ** 2))) if len(m) else 0.0]), hop
    f = m[: n * hop].reshape(n, hop)
    return np.sqrt(np.mean(f ** 2, axis=1)), hop


def db(v: float | np.ndarray) -> Any:
    return 20 * np.log10(np.maximum(v, 1e-9))


# ============================================================================================== 362 silences
def remove_silence(x: np.ndarray, rate: int, threshold_db: float = -40, min_silence_ms: float = 600, keep_ms: float = 150) -> tuple[np.ndarray, dict]:
    m = _mono(x)
    rms, hop = _frames_rms(m, rate, 20)
    peak = float(np.max(np.abs(m))) or 1.0
    silent = db(rms) < (db(peak) + threshold_db)
    need = max(1, int(min_silence_ms / 20))
    keep = max(0, int(keep_ms / 20))
    cuts, i = [], 0
    while i < len(silent):
        if silent[i]:
            j = i
            while j < len(silent) and silent[j]:
                j += 1
            if j - i >= need:
                a, b = i + keep if i > 0 else i, j - keep if j < len(silent) else j
                if b > a:
                    cuts.append((a * hop, b * hop))
            i = j
        else:
            i += 1
    if not cuts:
        return x.copy(), {"removed_s": 0.0, "cuts": [], "before_s": round(len(m) / rate, 2), "after_s": round(len(m) / rate, 2)}
    fade = int(rate * 0.005)
    parts, last = [], 0
    for a, b in cuts:
        seg = x[last:a].copy()
        if len(seg) > 2 * fade and fade:
            ramp = np.linspace(1, 0, fade, dtype=np.float32)[:, None]
            seg[-fade:] *= ramp
            if parts:
                seg[:fade] *= ramp[::-1]
        parts.append(seg)
        last = b
    tail = x[last:].copy()
    if len(tail) > fade and fade and parts:
        tail[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    parts.append(tail)
    out = np.concatenate(parts)
    return out, {"removed_s": round((len(x) - len(out)) / rate, 2), "before_s": round(len(x) / rate, 2), "after_s": round(len(out) / rate, 2),
                 "cuts": [[round(a / rate, 2), round(b / rate, 2)] for a, b in cuts]}


# ============================================================================================== 363 ducking
def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    t_old, t_new = np.arange(len(x)) / src, np.arange(n) / dst
    return np.stack([np.interp(t_new, t_old, x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def duck(voice: np.ndarray, vrate: int, music: np.ndarray, mrate: int, duck_db: float = -15, music_db: float = -6,
         attack_ms: float = 60, release_ms: float = 500) -> tuple[np.ndarray, dict]:
    """Music under speech: lowered by `duck_db` while someone talks, smoothly back up in pauses."""
    music = _resample(music, mrate, vrate)
    ch = max(voice.shape[1], music.shape[1])
    voice = np.repeat(voice, ch // voice.shape[1], axis=1) if voice.shape[1] < ch else voice
    music = np.repeat(music, ch // music.shape[1], axis=1) if music.shape[1] < ch else music
    n = len(voice)
    if len(music) < n:
        music = np.concatenate([music] * (n // max(1, len(music)) + 1))
    music = music[:n] * (10 ** (music_db / 20))
    rms, hop = _frames_rms(_mono(voice), vrate, 20)
    thr = max(float(np.percentile(rms, 30)) * 3, float(np.max(rms)) * 0.05)
    active = rms > thr
    target = np.where(active, 10 ** (duck_db / 20), 1.0)
    g = np.empty_like(target)
    cur = 1.0
    a = math.exp(-20 / attack_ms)
    r = math.exp(-20 / release_ms)
    for i, t in enumerate(target):
        k = a if t < cur else r
        cur = t + (cur - t) * k
        g[i] = cur
    gain = np.repeat(g, hop)[:n]
    if len(gain) < n:
        gain = np.concatenate([gain, np.full(n - len(gain), gain[-1] if len(gain) else 1.0)])
    mix = voice + music * gain[:, None]
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.99:
        mix = mix * (0.98 / peak)
    return mix.astype(np.float32), {"speech_pct": round(100 * float(active.mean()), 1), "duck_db": duck_db, "seconds": round(n / vrate, 2)}


# ============================================================================================== 366 speech clean-up
def enhance_speech(x: np.ndarray, rate: int, highpass_hz: float = 80, reduction: float = 1.5, target_peak_db: float = -1) -> tuple[np.ndarray, dict]:
    """High-pass against rumble, spectral gating with a noise profile from the quietest moments, peak normalisation."""
    n_fft = 1024 if rate <= 24000 else 2048
    hop = n_fft // 4
    win = np.hanning(n_fft).astype(np.float32)
    out = np.zeros_like(x)
    noise_before = noise_after = 0.0
    for c in range(x.shape[1]):
        s = np.concatenate([np.zeros(n_fft, np.float32), x[:, c], np.zeros(n_fft, np.float32)])
        frames = np.lib.stride_tricks.sliding_window_view(s, n_fft)[::hop] * win
        spec = np.fft.rfft(frames, axis=1)
        mag = np.abs(spec)
        freqs = np.fft.rfftfreq(n_fft, 1 / rate)
        energy = mag.sum(axis=1)
        quiet = mag[energy <= np.percentile(energy, 10)]
        noise = quiet.mean(axis=0) if len(quiet) else np.zeros(mag.shape[1])
        gain = np.clip(1 - reduction * noise / np.maximum(mag, 1e-9), 0.05, 1.0)
        gain = (gain + np.roll(gain, 1, axis=0) + np.roll(gain, -1, axis=0)) / 3       # smooth over time → fewer artefacts
        gain[:, freqs < highpass_hz] = 0
        y = np.fft.irfft(spec * gain, n=n_fft, axis=1) * win
        acc = np.zeros(len(s), np.float32)
        norm = np.zeros(len(s), np.float32)
        for i, fr in enumerate(y):
            acc[i * hop:i * hop + n_fft] += fr
            norm[i * hop:i * hop + n_fft] += win ** 2
        rec = acc / np.maximum(norm, 1e-6)
        out[:, c] = rec[n_fft:n_fft + len(x)]
        noise_before += float(np.mean(noise))
        noise_after += float(np.mean((np.abs(np.fft.rfft(frames, axis=1)) * gain)[energy <= np.percentile(energy, 10)])) if len(quiet) else 0
    peak = float(np.max(np.abs(out))) or 1.0
    out = out * (10 ** (target_peak_db / 20) / peak)
    return out.astype(np.float32), {"noise_reduction_db": round(float(db(noise_before) - db(max(noise_after, 1e-9))), 1),
                                    "highpass_hz": highpass_hz, "seconds": round(len(x) / rate, 2)}


# ============================================================================================== 375 loudness / quality
def _k_weight_power(f: np.ndarray, rate: int) -> np.ndarray:
    """|H(f)|² of the ITU-R BS.1770 K-weighting (high shelf + high pass), for any sample rate."""
    def biquad(b, a):
        z = np.exp(-1j * 2 * np.pi * f / rate)
        return np.abs((b[0] + b[1] * z + b[2] * z ** 2) / (a[0] + a[1] * z + a[2] * z ** 2)) ** 2
    # the libebur128 derivation: reproduces the BS.1770 48 kHz coefficients exactly and works for any sample rate
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / rate)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b1 = ((Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0)
    a1 = (1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0)
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / rate)
    d = 1 + K / Q + K * K
    b2 = (1.0, -2.0, 1.0)
    a2 = (1.0, 2 * (K * K - 1) / d, (1 - K / Q + K * K) / d)
    return biquad(b1, a1) * biquad(b2, a2)


def loudness(x: np.ndarray, rate: int) -> dict:
    """Integrated loudness (LUFS, gated as in EBU R128), sample peak, clipping and DC offset."""
    blk, step = int(0.4 * rate), int(0.1 * rate)
    if len(x) < blk:
        x = np.concatenate([x, np.zeros((blk - len(x), x.shape[1]), np.float32)])
    f = np.fft.rfftfreq(blk, 1 / rate)
    kw = _k_weight_power(f, rate)
    zs = []
    for start in range(0, len(x) - blk + 1, step):
        seg = x[start:start + blk]
        spec = np.fft.rfft(seg, axis=0)
        pw = (np.abs(spec) ** 2) * kw[:, None]
        pw[1:-1] *= 2                                              # one-sided spectrum
        ms = pw.sum(axis=0) / (blk ** 2)
        zs.append(ms.sum())
    zs = np.array(zs)
    lj = -0.691 + 10 * np.log10(np.maximum(zs, 1e-12))
    g1 = zs[lj > -70]
    if not len(g1):
        integ = -math.inf
    else:
        rel = -0.691 + 10 * math.log10(g1.mean()) - 10
        g2 = zs[(lj > -70) & (lj > rel)]
        integ = -0.691 + 10 * math.log10(g2.mean()) if len(g2) else -math.inf
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    clip = int(np.sum(np.abs(x) >= 0.999))
    return {"lufs": round(integ, 1), "peak_dbfs": round(float(db(peak)), 1), "clipped_samples": clip,
            "dc_offset": round(float(np.mean(x)), 5), "max_momentary": round(float(lj.max()), 1) if len(lj) else None}


TARGETS = {"YouTube": -14, "Spotify": -14, "Apple Music": -16, "podcast": -16, "TV (EBU R128)": -23}


def audio_quality(x: np.ndarray, rate: int) -> dict:
    lo = loudness(x, rate)
    m = _mono(x)
    rms, hop = _frames_rms(m, rate, 50)
    silent = db(rms) < -50
    lead = int(np.argmax(~silent)) * hop / rate if (~silent).any() else len(m) / rate
    trail = int(np.argmax(~silent[::-1])) * hop / rate if (~silent).any() else 0
    issues = []
    if lo["clipped_samples"] > 10:
        issues.append(f"přebuzení: {lo['clipped_samples']} vzorků na maximu – zvuk praská")
    if lo["peak_dbfs"] > -1:
        issues.append(f"špička {lo['peak_dbfs']} dBFS – nech rezervu aspoň −1 dB")
    if abs(lo["dc_offset"]) > 0.01:
        issues.append(f"stejnosměrná složka {lo['dc_offset']}")
    if lead > 2:
        issues.append(f"na začátku {lead:.1f} s ticha")
    if trail > 3:
        issues.append(f"na konci {trail:.1f} s ticha")
    if rate < 44100:
        issues.append(f"vzorkování {rate} Hz – pro hudbu a video je standard 44,1 nebo 48 kHz")
    adj = {k: round(v - lo["lufs"], 1) for k, v in TARGETS.items()} if math.isfinite(lo["lufs"]) else {}
    return {**lo, "rate": rate, "channels": x.shape[1], "seconds": round(len(x) / rate, 2), "lead_silence_s": round(lead, 2),
            "trail_silence_s": round(trail, 2), "adjust_db": adj, "issues": issues}


def video_info(path: Path) -> dict:
    try:
        import av
    except ImportError as e:
        raise ValueError("Video umím rozebrat jen s nainstalovanými hlasovými funkcemi (PyAV).") from e
    with av.open(str(path)) as c:
        v = next((s for s in c.streams if s.type == "video"), None)
        a = next((s for s in c.streams if s.type == "audio"), None)
        dur = float(c.duration / 1_000_000) if c.duration else None
        out = {"duration_s": round(dur, 2) if dur else None, "bitrate_kbps": round(c.bit_rate / 1000) if c.bit_rate else None, "container": c.format.name}
        if v:
            fps = float(v.average_rate) if v.average_rate else None
            out.update({"video_codec": v.codec_context.name, "width": v.codec_context.width, "height": v.codec_context.height,
                        "fps": round(fps, 3) if fps else None})
        if a:
            out.update({"audio_codec": a.codec_context.name, "audio_rate": a.codec_context.sample_rate, "audio_channels": a.codec_context.channels})
    return out


# ============================================================================================== 361 / 364 video
def scenes(path: Path, threshold: float = 0.35, sample_fps: float = 5, max_seconds: float = 3 * 3600) -> dict:
    """Cuts in a video: grey-level histogram distance between sampled frames."""
    try:
        import av
    except ImportError as e:
        raise ValueError("Video umím rozebrat jen s nainstalovanými hlasovými funkcemi (PyAV).") from e
    cuts, prev, last_t, frames = [], None, -1e9, 0
    with av.open(str(path)) as c:
        st = next((s for s in c.streams if s.type == "video"), None)
        if st is None:
            raise ValueError("Soubor nemá obrazovou stopu.")
        st.thread_type = "AUTO"
        for fr in c.decode(st):
            t = float(fr.time or 0)
            if t > max_seconds:
                break
            if t - last_t < 1 / sample_fps:
                continue
            last_t = t
            frames += 1
            g = fr.to_ndarray(format="gray", width=160, height=90)
            h = np.histogram(g, bins=32, range=(0, 256))[0].astype(np.float32)
            h /= h.sum() or 1
            if prev is not None:
                d = 0.5 * float(np.abs(h - prev).sum())
                if d > threshold and (not cuts or t - cuts[-1]["t"] > 0.5):
                    cuts.append({"t": round(t, 2), "score": round(d, 3)})
            prev = h
    return {"cuts": cuts, "scenes": len(cuts) + 1, "frames_checked": frames}


def highlights(x: np.ndarray, rate: int, top: int = 5, min_gap_s: float = 10, scene_cuts: list[float] | None = None) -> list[dict]:
    """The loudest / most energetic moments (momentary loudness well above the median), spaced apart; scene cuts nearby
    raise the score."""
    rms, hop = _frames_rms(_mono(x), rate, 400)
    if len(rms) < 3:
        return []
    lv = db(rms)
    med, sd = float(np.median(lv)), float(np.std(lv)) or 1.0
    score = (lv - med) / sd
    if scene_cuts:
        for t in scene_cuts:
            i = int(t * rate / hop)
            if 0 <= i < len(score):
                score[max(0, i - 2):i + 3] += 0.5
    order = np.argsort(score)[::-1]
    out = []
    for i in order:
        t = i * hop / rate
        if score[i] < 1.0 or len(out) >= top:
            break
        if all(abs(t - o["t"]) >= min_gap_s for o in out):
            out.append({"t": round(t, 1), "score": round(float(score[i]), 2), "level_db": round(float(lv[i]), 1)})
    return sorted(out, key=lambda o: o["t"])


# ============================================================================================== 369 subtitles
def _ts(s: str) -> float:
    h, m, rest = s.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def parse_srt(text: str) -> list[dict]:
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [x for x in block.splitlines() if x.strip()]
        ti = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if ti is None:
            continue
        a, b = lines[ti].split("-->")
        out.append({"start": _ts(a), "end": _ts(b.split()[0]), "text": "\n".join(lines[ti + 1:])})
    if not out:
        raise ValueError("V souboru nejsou titulky SRT.")
    return out


def wrap(text: str, width: int = 42) -> str:
    words = re.sub(r"\s+", " ", text.replace("\n", " ")).strip().split(" ")
    if len(" ".join(words)) <= width:
        return " ".join(words)
    best, best_score = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(a), len(b)) + (0 if len(a) <= len(b) + 8 else 3)
        if best_score is None or score < best_score:
            best, best_score = f"{a}\n{b}", score
    return best or " ".join(words)


def check_subtitles(subs: list[dict], max_cps: float = 17, max_line: int = 42) -> list[dict]:
    issues = []
    for i, s in enumerate(subs, 1):
        dur = s["end"] - s["start"]
        chars = len(s["text"].replace("\n", ""))
        lines = s["text"].split("\n")
        if dur <= 0:
            issues.append({"n": i, "problem": "konec před začátkem"})
            continue
        if chars / dur > max_cps:
            issues.append({"n": i, "problem": f"rychlé čtení {chars / dur:.0f} znaků/s (max {max_cps:g})"})
        if any(len(x) > max_line for x in lines):
            issues.append({"n": i, "problem": f"řádek delší než {max_line} znaků"})
        if len(lines) > 2:
            issues.append({"n": i, "problem": f"{len(lines)} řádky (max 2)"})
        if dur < 0.8:
            issues.append({"n": i, "problem": f"zobrazení jen {dur:.2f} s"})
        if dur > 7:
            issues.append({"n": i, "problem": f"zobrazení {dur:.1f} s (max 7)"})
        if i < len(subs) and subs[i]["start"] < s["end"]:
            issues.append({"n": i, "problem": "překrývá se s dalším titulkem"})
    return issues


def fix_subtitles(subs: list[dict], max_cps: float = 17, max_line: int = 42, min_gap: float = 0.08) -> list[dict]:
    out = []
    for i, s in enumerate(subs):
        t = wrap(s["text"], max_line)
        end = s["end"]
        need = len(t.replace("\n", "")) / max_cps
        nxt = subs[i + 1]["start"] - min_gap if i + 1 < len(subs) else end + 10
        if end - s["start"] < max(need, 0.8):
            end = min(max(s["start"] + need, s["start"] + 0.8), max(nxt, end))
        end = min(end, nxt) if nxt > s["start"] else end
        out.append({"start": s["start"], "end": round(end, 3), "text": t})
    return out


def to_srt(subs: list[dict]) -> str:
    return "\n".join(f"{i}\n{_fmt_srt(s['start'])} --> {_fmt_srt(s['end'])}\n{s['text']}\n" for i, s in enumerate(subs, 1))


def _ass_color(hex_: str, alpha: int = 0) -> str:
    h = hex_.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def to_ass(subs: list[dict], font: str = "Arial", size: int = 54, color: str = "#FFFFFF", outline_color: str = "#000000",
           outline: float = 3, shadow: float = 1, position: str = "dole", margin_v: int = 60, box: bool = False, width: int = 1920,
           height: int = 1080, bold: bool = True) -> str:
    align = {"dole": 2, "nahoře": 8, "uprostřed": 5}.get(position, 2)
    style = (f"Style: Default,{font},{size},{_ass_color(color)},{_ass_color(color)},{_ass_color(outline_color)},{_ass_color('#000000', 0x80)},"
             f"{-1 if bold else 0},0,0,0,100,100,0,0,{3 if box else 1},{outline:g},{shadow:g},{align},60,60,{margin_v},1")

    def t(x: float) -> str:
        cs = int(round(x * 100))
        return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"
    ev = [f"Dialogue: 0,{t(s['start'])},{t(s['end'])},Default,,0,0,0,,{s['text'].replace(chr(10), chr(92) + 'N')}" for s in subs]
    return "\n".join(["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
                      "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                      "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                      style, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *ev]) + "\n"
