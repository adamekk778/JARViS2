"""3.17 Průvodce rychlostí (návrh 9): looks at this PC and recommends the fastest settings – each with a reason and
one button: speech recognition on the graphics card, the reflex model in Ollama (downloaded on the click), the voice
that starts fastest, the hour-long cache for Claude, the tool catalog, the smart end of a sentence.
Nothing changes without the click; every step can be undone in Settings.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

REFLEX_MODEL = "qwen3:1.7b"


def _cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


async def _ollama_models(rt: Any) -> list[str] | None:
    """Installed Ollama models, None when Ollama does not run."""
    try:
        local = getattr(rt, "local", None)
        if local is None:
            return None
        st = await local.status()
        if not st.get("running"):
            return None
        return [m["name"] if isinstance(m, dict) else str(m) for m in st.get("installed", [])]
    except Exception as e:  # noqa: BLE001
        log.debug("wizard ollama: %s", e)
        return None


async def recommendations(rt: Any) -> list[dict]:
    from . import secrets

    cfg = rt.cfg
    v, b = cfg.voice, cfg.brain
    out: list[dict] = []
    gpu = _cuda()
    groq = bool(secrets.get("groq"))
    if gpu:
        done = v.stt_provider == "local" and v.stt_download_ok
        out.append({"id": "stt_gpu", "title": "Rozpoznávání řeči na grafické kartě",
                    "why": "Máš grafiku NVIDIA: Whisper na ní přepíše větu za zlomek sekundy a bez internetu.",
                    "done": done, "patch": {"voice": {"stt_provider": "local", "stt_download_ok": True, "stt_model": "small"}}})
    elif groq:
        out.append({"id": "stt_groq", "title": "Rozpoznávání řeči přes Groq",
                    "why": "Bez grafiky NVIDIA je nejrychlejší Groq (zdarma, klíč už máš).",
                    "done": v.stt_provider in ("auto", "groq"), "patch": {"voice": {"stt_provider": "groq"}}})
    models = await _ollama_models(rt)
    if models is not None:
        have = any(m.startswith(REFLEX_MODEL.split(":")[0]) and "1.7b" in m for m in models)
        out.append({"id": "reflex", "title": f"Reflexní model {REFLEX_MODEL}",
                    "why": "Malý model v Ollamě rozhodne jasné povely za zlomek sekundy, ještě než se zeptá velká AI."
                           + ("" if gpu else " Bez grafiky bude pomalejší – zkus a podívej se do Změřit rychlost."),
                    "done": b.reflex_model == REFLEX_MODEL, "pull": None if have else REFLEX_MODEL,
                    "patch": {"brain": {"reflex_model": REFLEX_MODEL}}})
    if v.tts_engine == "elevenlabs":
        out.append({"id": "voice_flash", "title": "Nejrychlejší hlas ElevenLabs (Flash)",
                    "why": "První slovo zazní dřív; hlas je o kousek méně barevný.",
                    "done": bool(v.low_latency), "patch": {"voice": {"low_latency": True}}})
    out.append({"id": "voice_stream", "title": "Hlas po kouscích",
                "why": "První věta hraje, ještě než je celá vyrobená (Edge a ElevenLabs).",
                "done": bool(getattr(v, "stream_voice", True)) and v.effect == "none",
                "patch": {"voice": {"stream_voice": True}}})
    if any(p.preset == "anthropic" and p.enabled for p in b.providers):
        out.append({"id": "cache_1h", "title": "Hodinová paměť Clauda",
                    "why": "Pokyny a seznam nástrojů zůstanou v cache hodinu – odpověď po delší pauze začne dřív a vyjde levněji.",
                    "done": getattr(b, "claude_cache_ttl", "1h") == "1h", "patch": {"brain": {"claude_cache_ttl": "1h"}}})
    out.append({"id": "catalog", "title": "Všechny nástroje v hlavě",
                "why": "Velká AI zná všechny nástroje najednou a nic nehledá.",
                "done": getattr(b, "tool_catalog", "auto") != "off", "patch": {"brain": {"tool_catalog": "auto"}}})
    out.append({"id": "endpoint", "title": "Chytrý konec věty a tvoje tempo",
                "why": "Hotová věta končí po čtvrt sekundě, čekání se přizpůsobí tvým pauzám.",
                "done": bool(v.smart_endpoint) and bool(getattr(v, "adaptive_pace", True)),
                "patch": {"voice": {"smart_endpoint": True, "adaptive_pace": True}}})
    out.append({"id": "reflexes", "title": "Reflexy a připravené odpovědi",
                "why": "Opakované povely bez AI, počasí a kalendář připravené dopředu.",
                "done": bool(cfg.agent.reflexes) and bool(getattr(cfg.agent, "prefetch", True)),
                "patch": {"agent": {"reflexes": True, "prefetch": True}}})
    return out


async def apply(rt: Any, rec_id: str) -> tuple[bool, str]:
    recs = {r["id"]: r for r in await recommendations(rt)}
    r = recs.get(rec_id)
    if r is None:
        return False, "Tohle doporučení už neplatí."
    if r.get("pull"):
        local = getattr(rt, "local", None)
        if local is None or not hasattr(local, "pull") or not await local.pull(r["pull"]):
            return False, f"Model {r['pull']} se nepodařilo stáhnout – běží Ollama?"
    rt.update_config(r["patch"])
    return True, f"Hotovo: {r['title']}."
