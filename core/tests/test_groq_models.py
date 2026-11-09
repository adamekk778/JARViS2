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
