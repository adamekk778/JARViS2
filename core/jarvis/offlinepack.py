"""3.14 Úplně offline (návrh 31): everything JARVIS needs to work without internet, prepared with one click and checked.

Three parts, each shown with its size before anything downloads (D8 – big models never download silently):
- speech recognition on this PC (Whisper, ~0.5 GB)
- the AI on this PC (Ollama, the model recommended for this graphics card / RAM)
- JARVIS's voice on this PC (Piper, ~60 MB)

The test then makes them talk to each other: the offline voice says a command, the offline recognition writes it
down (word error rate), the command it becomes is checked, and the offline AI answers a small question.
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave
from typing import Any

log = logging.getLogger(__name__)

TEST_SENTENCE = "Hlasitost na třicet procent."
TEST_TOOL = "volume"
WHISPER_GB = {"tiny": 0.08, "base": 0.15, "small": 0.46, "medium": 1.5, "large-v3": 3.1, "large-v3-turbo": 1.6}
PIPER_GB = 0.06


def _piper_ready(rt: Any) -> bool:
    from . import paths

    v = rt.cfg.voice
    return (paths.sub("models") / "piper" / f"{v.piper_voice}.onnx").exists()


def _stt_ready(rt: Any) -> bool:
    from .voice.stt import Transcriber

    return Transcriber(rt.cfg.voice).local_ready()


async def status(rt: Any) -> dict:
    """What is ready and what each missing part would download."""
    from .llm.local import MODELS

    st: dict = {}
    try:
        st = await rt.local.status()
    except Exception as e:  # noqa: BLE001
        log.info("offline pack: ollama status: %s", e)
    rec = (st.get("recommended") or ["qwen3:4b"])[0]
    installed = {m["name"] for m in st.get("installed", [])}
    model_ok = any(n == rec or n.split(":")[0] == rec.split(":")[0] for n in installed) if installed else False
    size = next((m["size_gb"] for m in MODELS if m["name"] == rec), 3.0)
    stt_model = str(rt.cfg.voice.stt_model)
    if stt_model == "auto":
        from .voice.stt import best_model

        stt_model = best_model()
    parts = [
        {"key": "stt", "name": "Rozpoznávání řeči v PC (Whisper)", "ready": await asyncio.to_thread(_stt_ready, rt),
         "size_gb": WHISPER_GB.get(stt_model, 0.5), "note": f"model {stt_model}"},
        {"key": "llm", "name": "AI v tomhle PC (Ollama)", "ready": bool(st.get("running")) and model_ok,
         "size_gb": 0 if model_ok else size, "note": rec if st.get("running") else "nejdřív nainstaluj Ollamu (ollama.com)",
         "model": rec, "ollama": bool(st.get("running"))},
        {"key": "tts", "name": "Hlas JARVISe v PC (Piper)", "ready": await asyncio.to_thread(_piper_ready, rt),
         "size_gb": PIPER_GB, "note": rt.cfg.voice.piper_voice},
    ]
    need = round(sum(p["size_gb"] for p in parts if not p["ready"]), 2)
    return {"parts": parts, "ready": all(p["ready"] for p in parts), "download_gb": need,
            "offline_only": bool(rt.cfg.brain.offline_only)}


async def prepare(rt: Any, switch: bool = False, progress=None) -> dict:
    """Download what is missing – only ever on the user's click. `switch`: afterwards use only the offline parts."""
    say = progress or (lambda *_: None)
    st = await status(rt)
    done: list[str] = []
    errors: list[str] = []
    parts = {p["key"]: p for p in st["parts"]}
    if not parts["stt"]["ready"]:
        say("stt", "Stahuju rozpoznávání řeči…")
        rt.update_config({"voice": {"stt_download_ok": True}})
        try:
            from .voice.stt import Transcriber

            t = Transcriber(rt.cfg.voice)
            await asyncio.to_thread(t._local)
            done.append("stt")
        except Exception as e:  # noqa: BLE001
            errors.append(f"Rozpoznávání řeči: {e}")
    if not parts["llm"]["ready"]:
        if not parts["llm"].get("ollama"):
            errors.append("AI v PC: Ollama neběží – nainstaluj ji z ollama.com a zkus to znovu.")
        else:
            say("llm", f"Stahuju {parts['llm']['model']}…")
            ok = await rt.local.pull(parts["llm"]["model"])
            (done if ok else errors).append("llm" if ok else f"AI v PC: {parts['llm']['model']} se nestáhl")
            if ok:
                provs = [p.model_dump() for p in rt.cfg.brain.providers]
                for p in provs:
                    if p["preset"] == "ollama":
                        p["model"] = parts["llm"]["model"]
                rt.update_config({"brain": {"providers": provs}})
    if not parts["tts"]["ready"]:
        say("tts", "Stahuju hlas…")
        try:
            from .voice.tts import piper_synth

            await asyncio.to_thread(piper_synth, "Ahoj.", rt.cfg.voice.piper_voice)
            done.append("tts")
        except Exception as e:  # noqa: BLE001
            errors.append(f"Hlas v PC: {e}")
    if switch and not errors:
        rt.update_config({"brain": {"offline_only": True}, "voice": {"stt_provider": "local", "tts_engine": "piper"}})
    return {"done": done, "errors": errors, **(await status(rt))}


async def test(rt: Any) -> dict:
    """Offline voice → offline recognition → the command; and one question to the offline AI."""
    from .evals.voice import tool_for, wer

    out: dict = {"items": []}

    def add(key: str, ok: bool | None, detail: str) -> None:
        out["items"].append({"key": key, "ok": ok, "detail": detail})

    wav = b""
    try:
        from .voice.tts import piper_synth

        wav = await asyncio.to_thread(piper_synth, TEST_SENTENCE, rt.cfg.voice.piper_voice)
        add("tts", True, f"Hlas v PC řekl: „{TEST_SENTENCE}“")
    except Exception as e:  # noqa: BLE001
        add("tts", False, f"Hlas v PC nefunguje: {e}")
    if wav:
        try:
            import numpy as np

            from .voice.stt import Transcriber

            with wave.open(io.BytesIO(wav), "rb") as w:
                sr, frames = w.getframerate(), w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if sr != 16000:
                idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr))
                audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
            t = Transcriber(rt.cfg.voice)
            heard = await asyncio.to_thread(t._run, audio)
            w_ = wer(TEST_SENTENCE, heard)
            add("stt", w_ <= 0.34, f"Rozpoznání v PC slyšelo „{heard}“ (chybovost slov {round(w_ * 100)} %)")
            got = tool_for(heard)
            add("command", got == TEST_TOOL, f"Z toho je příkaz: {got or 'žádný'}")
        except Exception as e:  # noqa: BLE001
            add("stt", False, f"Rozpoznávání řeči v PC nefunguje: {e}")
    lid = next((p.id for p in rt.cfg.brain.providers if p.preset in ("ollama", "lmstudio") and p.enabled), "")
    if lid:
        try:
            ans = await asyncio.wait_for(rt.router.complete(
                [{"role": "user", "content": "Kolik je dva plus tři? Odpověz jen číslem."}], only=lid), 120)
            add("llm", "5" in ans or "pět" in ans.lower(), f"AI v PC odpověděla: „{ans.strip()[:60]}“")
        except Exception as e:  # noqa: BLE001
            add("llm", False, f"AI v PC neodpověděla: {e}")
    else:
        add("llm", None, "AI v PC není nastavená.")
    out["ok"] = all(i["ok"] is not False for i in out["items"])
    return out
