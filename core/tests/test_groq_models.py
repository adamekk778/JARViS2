"""3.12: Groq switched off Llama 3.3 70B & co. in 2026 – saved ones move to GPT-OSS, the preset uses the strongest."""
from jarvis.config import GROQ_BEST, GROQ_FAST, Config
from jarvis.llm.presets import PRESETS


def test_preset_uses_the_strongest_groq_model():
    assert PRESETS["groq"]["model"] == GROQ_BEST == "openai/gpt-oss-120b"


def test_saved_retired_groq_models_move_to_gpt_oss():
    cfg = Config.model_validate({"brain": {"providers": [
        {"id": "groq", "preset": "groq", "model": "llama-3.3-70b-versatile", "fast_model": "llama-3.1-8b-instant"},
        {"id": "groq2", "preset": "groq", "model": "my-own-model"},
        {"id": "or", "preset": "openrouter", "model": "llama-3.3-70b-versatile"}]}})
    by = {p.id: p for p in cfg.brain.providers}
    assert by["groq"].model == GROQ_BEST and by["groq"].fast_model == GROQ_FAST
    assert by["groq2"].model == "my-own-model"                  # not a retired one: left alone
    assert by["or"].model == "llama-3.3-70b-versatile"          # other providers are not touched


def test_pick_model_prefers_gpt_oss_and_skips_speech_models():
    from jarvis.llm.openai_compat import pick_model

    groq = ["whisper-large-v3", "llama-guard-4-12b", "llama-3.1-8b-instant", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    assert pick_model(groq) == "openai/gpt-oss-120b"
    assert pick_model(["whisper-large-v3", "qwen/qwen3-32b"]) == "qwen/qwen3-32b"
    assert pick_model(["auto", "openai/gpt-oss-120b"]) == "auto"          # a gateway's own route still wins


def test_retired_model_error_counts_as_unknown_model():
    from jarvis.llm.base import ProviderError

    e = ProviderError("HTTP 400: The model `llama-3.3-70b-versatile` has been decommissioned and is no longer supported.", 400)
    assert e.is_unknown_model


def test_groq_wrong_key_gets_a_clear_czech_message():
    from jarvis.llm.base import ProviderError
    from jarvis.llm.openai_compat import friendly_error

    msg = friendly_error("groq", "https://api.groq.com/openai/v1", ProviderError("HTTP 401: Invalid API Key", 401, False))
    assert "gsk_" in msg and "console.groq.com" in msg
    assert "429" not in friendly_error("groq", "", ProviderError("HTTP 429: rate limit", 429))
