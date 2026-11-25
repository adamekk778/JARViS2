"""3.14 Jak JARVIS mluví (návrhy 1, 41, 43, 44).

- pronunciation dictionary: your own "how to say it" for names, abbreviations and English words (Nastavení → Hlas)
- tone by the time of day: a little slower and quieter late in the evening and at night, a little livelier in the
  morning (Edge voices: rate / pitch; every engine: loudness)
- whispered to → answers quietly for a while
- the delay from the end of your sentence to JARVIS's first sound is measured on every spoken answer
"""
from __future__ import annotations

import re
import time
from collections import deque
from typing import Any

NIGHT = (22, 6)          # 22:00–5:59
MORNING = (6, 9)


def _pct(s: str) -> int:
    m = re.match(r"\s*([+-]?\d+)", str(s or "0"))
    return int(m.group(1)) if m else 0


def _hz(s: str) -> int:
    m = re.match(r"\s*([+-]?\d+)", str(s or "0"))
    return int(m.group(1)) if m else 0


def pronounce(cfg: Any, text: str) -> str:
    """Replace whole words by how they should be said (case-insensitive, longest first)."""
    rules = [r for r in (getattr(cfg.voice, "pronounce", None) or []) if getattr(r, "src", "") and getattr(r, "dst", "")]
    for r in sorted(rules, key=lambda r: -len(r.src)):
        text = re.sub(rf"(?<!\w){re.escape(r.src)}(?!\w)", r.dst, text, flags=re.I)
    return text


def part_of_day(hour: int) -> str:
    if hour >= NIGHT[0] or hour < NIGHT[1]:
        return "night"
    if MORNING[0] <= hour < MORNING[1]:
        return "morning"
    if hour >= 20:
        return "evening"
    return "day"


def room_db(rt: Any) -> float | None:
    """The room's noise from the microphone's noise floor (int16 RMS), roughly in dB."""
    import math

    floor = getattr(getattr(rt, "voice", None), "_floor", None)
    if not floor:
        return None
    return 20 * math.log10(max(float(floor), 1.0) / 32768) + 94


def noise_boost(rt: Any, v: Any) -> int:
    """3.20 (475): percent more (or less) volume for the room – louder in noise, softer in a quiet room."""
    if not getattr(v, "auto_volume", False):
        return 0
    from ..accessx import volume_for_noise

    return volume_for_noise(room_db(rt), 50) - 50


def prosody(rt: Any, v: Any, hour: int | None = None) -> tuple[str, str, str]:
    """Edge (rate, pitch, volume) strings with the time of day and a whisper applied to your own settings."""
    rate, pitch, vol = _pct(v.tts_rate), _hz(v.tts_pitch), _pct(v.tts_volume)
    if getattr(v, "adaptive_tone", True):
        pod = part_of_day(time.localtime().tm_hour if hour is None else hour)
        if pod == "night":
            rate, vol = rate - 8, vol - 20
        elif pod == "evening":
            rate -= 4
        elif pod == "morning":
            rate, pitch = rate + 5, pitch + 2
    vid = getattr(rt, "voiceid", None)
    if vid is not None and vid.whispering():
        rate, vol = rate - 5, vol - 45
    vol += noise_boost(rt, v)
    rate, vol = max(-50, min(100, rate)), max(-90, min(50, vol))
    return f"{rate:+d}%", f"{pitch:+d}Hz", f"{vol:+d}%"


def gain(rt: Any) -> float:
    """Loudness for engines without a volume setting (Piper, ElevenLabs, Windows): night 0.75, whisper 0.45."""
    g = 1.0
    if getattr(rt.cfg.voice, "adaptive_tone", True) and part_of_day(time.localtime().tm_hour) == "night":
        g *= 0.75
    g *= 1 + noise_boost(rt, rt.cfg.voice) / 100
    vid = getattr(rt, "voiceid", None)
    if vid is not None and vid.whispering():
        g *= 0.45
    return g


# ---------- návrh 1: end of your sentence → JARVIS's first sound ----------
def mark_end(rt: Any) -> None:
    rt.voice_t_end = time.monotonic()


def mark_sound(rt: Any) -> None:
    t = getattr(rt, "voice_t_end", None)
    if not t:
        return
    rt.voice_t_end = None
    ms = (time.monotonic() - t) * 1000
    if 0 < ms < 30000:
        lat = getattr(rt, "voice_lat", None)
        if lat is None:
            lat = rt.voice_lat = deque(maxlen=50)
        lat.append(ms)
