"""Voice studio: find a voice (all Microsoft Edge voices, the Piper catalogue), bring your own (a Piper .onnx file
or an ElevenLabs voice you created or cloned from your own recordings) and shape it (speed, pitch, effects).

Nothing imitates a real person: no built-in celebrity voices, and a cloned voice is only ever the user's own one,
made in their own ElevenLabs account where they confirm they have the right to it."""
from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import wave
from pathlib import Path

import httpx

from .. import paths

log = logging.getLogger(__name__)

EFFECTS: dict[str, str] = {
    "none": "Bez efektu",
    "jarvis": "JARVIS – jemný kovový lesk",
    "radio": "Vysílačka / rádio",
    "robot": "Robot",
    "hall": "Velká místnost (dozvuk)",
}
ELEVEN_API = "https://api.elevenlabs.io/v1"
PIPER_CATALOG = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
LANGS = ("cs", "sk", "en")
_cache: dict[str, tuple[float, object]] = {}


# ---------- effects (numpy only) ----------
def _recursive(x, delay: int, g: float, allpass: bool = False):
    """y[n] = x[n] + g·y[n-d] (comb) or the Schroeder all-pass, vectorised in blocks of `delay` samples."""
    import numpy as np

    y = np.zeros_like(x)
    xd = np.concatenate([np.zeros(delay, dtype=x.dtype), x])[: len(x)]          # x[n-d]
    for s in range(0, len(x), delay):
        e = min(s + delay, len(x))
        prev = y[s - delay:e - delay] if s >= delay else np.zeros(e - s, dtype=x.dtype)
        y[s:e] = (-g * x[s:e] + xd[s:e] + g * prev) if allpass else (x[s:e] + g * prev)
    return y


def _reverb(x, sr: int, room: float, mix: float):
    import numpy as np

    wet = np.zeros_like(x)
    for ms, g in ((29.7, .77), (37.1, .75), (41.1, .73), (43.7, .71)):
        wet += _recursive(x, max(1, int(sr * ms / 1000 * (0.6 + room))), g * (0.85 + 0.15 * room))
    for ms, g in ((5.0, .7), (1.7, .7)):
        wet = _recursive(wet, max(1, int(sr * ms / 1000)), g, allpass=True)
    return (1 - mix) * x + mix * wet / 4


def _band(x, sr: int, lo: float, hi: float):
    import numpy as np

    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, len(x)).astype(x.dtype)


def apply_effect(pcm, sr: int, name: str):
    """The chosen character on top of any voice; returns float32 mono in [-1, 1]."""
    import numpy as np

    x = np.asarray(pcm, dtype=np.float32)
    if name == "none" or name not in EFFECTS or not len(x):
        return x
    if name == "jarvis":
        d = int(sr * 0.007)
        shimmer = x + 0.35 * np.concatenate([np.zeros(d, np.float32), x])[: len(x)]
        y = _reverb(shimmer + 0.15 * _band(x, sr, 3000, sr / 2), sr, room=0.3, mix=0.12)
    elif name == "radio":
        y = np.tanh(2.5 * _band(x, sr, 300, 3400)) / np.tanh(2.5)
    elif name == "robot":
        t = np.arange(len(x), dtype=np.float32) / sr
        y = _recursive(0.5 * x + 0.8 * x * np.sin(2 * np.pi * 55 * t).astype(np.float32), int(sr * 0.01), 0.45)
    else:  # hall
        y = _reverb(x, sr, room=0.9, mix=0.35)
    peak = float(np.max(np.abs(y)))
    if peak > 0.98:
        y = y / peak * 0.98
    return y.astype(np.float32)


def encode_wav(pcm, sr: int) -> bytes:
    import numpy as np

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


# ---------- ElevenLabs (your own created / cloned voice) ----------
async def eleven_synth(text: str, key: str, voice_id: str, model: str, transport=None) -> bytes:
    if not key:
        raise RuntimeError("chybí API klíč ElevenLabs (Nastavení → Hlas → Hlasová dílna)")
    if not voice_id:
        raise RuntimeError("v Hlasové dílně vyber hlas z ElevenLabs")
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", voice_id):
        raise RuntimeError("neplatné ID hlasu ElevenLabs")
    async with httpx.AsyncClient(transport=transport, timeout=60) as c:
        r = await c.post(f"{ELEVEN_API}/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                         headers={"xi-api-key": key, "accept": "audio/mpeg"},
                         json={"text": text, "model_id": model or "eleven_multilingual_v2"})
    if r.status_code in (401, 403):
        raise RuntimeError("ElevenLabs odmítl API klíč – zkontroluj ho v Hlasové dílně")
    if r.status_code == 429 or "quota" in r.text.lower():
        raise RuntimeError("v ElevenLabs došel měsíční limit znaků")
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"ElevenLabs: HTTP {r.status_code} {r.text[:160]}")
    return r.content


async def eleven_voices(key: str, transport=None) -> list[dict]:
    """The voices in the user's ElevenLabs account – their own clones / designs first."""
    if not key:
        return []
    async with httpx.AsyncClient(transport=transport, timeout=20) as c:
        r = await c.get(f"{ELEVEN_API}/voices", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise RuntimeError("ElevenLabs odmítl API klíč" if r.status_code in (401, 403) else f"ElevenLabs: HTTP {r.status_code}")
    own = ("cloned", "generated", "professional")
    out = [{"id": v.get("voice_id"), "name": v.get("name") or "?", "own": v.get("category") in own}
           for v in r.json().get("voices", []) if v.get("voice_id")]
    return sorted(out, key=lambda v: (not v["own"], v["name"].lower()))


# ---------- the Edge and Piper catalogues ----------
async def edge_voices() -> list[dict]:
    """Every Microsoft Edge voice that speaks Czech, Slovak or English – including the multilingual ones."""
    hit = _cache.get("edge")
    if hit and time.time() - hit[0] < 24 * 3600:
        return hit[1]  # type: ignore[return-value]
    import edge_tts

    out = []
    for v in await edge_tts.list_voices():
        loc, name = v.get("Locale", ""), v.get("ShortName", "")
        multi = "Multilingual" in name
        if not (loc[:2] in LANGS or multi):
            continue
        out.append({"id": name, "lang": loc, "gender": "žena" if v.get("Gender") == "Female" else "muž", "multi": multi,
                    "name": re.sub(r"^[a-z]{2}-[A-Z]{2}-|Neural$", "", name)})
    out.sort(key=lambda v: (v["lang"][:2] != "cs", v["lang"][:2] != "sk", not v["multi"], v["lang"], v["name"]))
    _cache["edge"] = (time.time(), out)
    return out


def piper_dir() -> Path:
    d = paths.sub("models") / "piper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def custom_dir() -> Path:
    d = piper_dir() / "custom"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def piper_catalog(transport=None) -> list[dict]:
    """Offline Piper voices for cs / sk / en with their download size (they download only when chosen)."""
    hit = _cache.get("piper")
    if hit and time.time() - hit[0] < 24 * 3600:
        return hit[1]  # type: ignore[return-value]
    local = piper_dir() / "voices.json"
    data = None
    try:
        async with httpx.AsyncClient(transport=transport, timeout=20, follow_redirects=True) as c:
            r = await c.get(PIPER_CATALOG)
        if r.status_code == 200:
            data = r.json()
            local.write_text(json.dumps(data), encoding="utf-8")
    except (httpx.HTTPError, ValueError) as e:
        log.info("piper catalogue: %s", e)
    if data is None and local.exists():
        data = json.loads(local.read_text(encoding="utf-8"))
    out = []
    for key, v in (data or {}).items():
        code = ((v.get("language") or {}).get("code") or key.split("-")[0])
        if code[:2] not in LANGS:
            continue
        size = sum(f.get("size_bytes", 0) for name, f in (v.get("files") or {}).items() if name.endswith(".onnx"))
        out.append({"id": key, "lang": code, "quality": v.get("quality", ""), "mb": round(size / 2**20),
                    "downloaded": (piper_dir() / f"{key}.onnx").exists()})
    out.sort(key=lambda v: (v["lang"][:2] != "cs", v["lang"][:2] != "sk", v["lang"], v["id"]))
    if out:
        _cache["piper"] = (time.time(), out)
    return out


def custom_voices() -> list[dict]:
    return [{"id": p.stem, "mb": round(p.stat().st_size / 2**20)} for p in sorted(custom_dir().glob("*.onnx"))
            if p.with_suffix(".onnx.json").exists()]


def import_piper(onnx: Path, cfg: Path, name: str = "") -> str:
    """Add your own Piper voice (a .onnx model + its .onnx.json) – e.g. one trained on your own recordings or
    downloaded from the Piper catalogue / Hugging Face. Returns its name."""
    try:
        meta = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("soubor .onnx.json není platný popis hlasu Piper") from e
    if not isinstance(meta, dict) or not (meta.get("audio") or {}).get("sample_rate"):
        raise ValueError("soubor .onnx.json není popis hlasu Piper (chybí audio.sample_rate)")
    if onnx.stat().st_size < 1_000_000:
        raise ValueError("soubor .onnx je moc malý na hlasový model")
    base = name or re.sub(r"\.onnx(\.json)?$", "", onnx.name, flags=re.I)
    base = re.sub(r"[^\w.-]+", "_", base).strip("._")[:60] or "muj-hlas"
    shutil.copyfile(onnx, custom_dir() / f"{base}.onnx")
    shutil.copyfile(cfg, custom_dir() / f"{base}.onnx.json")
    _cache.pop("piper", None)
    return base


def delete_custom(name: str) -> bool:
    gone = False
    for p in (custom_dir() / f"{name}.onnx", custom_dir() / f"{name}.onnx.json"):
        if p.parent == custom_dir() and p.exists():
            p.unlink()
            gone = True
    return gone
