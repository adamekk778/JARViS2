"""Services switch models off: saved dead ones move on, a "gone" answer finds a working one, odd answers stay readable."""
import asyncio

import httpx

from jarvis.config import Config
from jarvis.llm.base import ProviderError
from jarvis.llm.openai_compat import OpenAICompat, pick_model
from jarvis.llm.presets import PRESETS


def test_dead_saved_models_move_to_living_ones():
    cfg = Config.model_validate({"brain": {"providers": [
        {"id": "gemini", "preset": "gemini", "model": "gemini-2.5-flash", "fast_model": "gemini-2.5-flash-lite"},
        {"id": "openrouter", "preset": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
        {"id": "nvidia", "preset": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
        {"id": "mine", "preset": "custom", "model": "meta/llama-3.3-70b-instruct"}], "chain": ["gemini"]}})
    m = {p.id: p for p in cfg.brain.providers}
    assert (m["gemini"].model, m["gemini"].fast_model) == ("gemini-flash-latest", "gemini-flash-lite-latest")
    assert m["openrouter"].model == "openrouter/free"
    assert m["nvidia"].model == "openai/gpt-oss-20b"
    assert m["mine"].model == "meta/llama-3.3-70b-instruct"          # your own endpoint: untouched


def test_presets_no_longer_name_dead_models():
    assert PRESETS["nvidia"]["model"] == "openai/gpt-oss-20b"
    assert PRESETS["openrouter"]["model"] == "openrouter/free"
    assert PRESETS["gemini"]["model"] == "gemini-flash-latest"


def test_end_of_life_answer_counts_as_unknown_model():
    e = ProviderError('HTTP 410: {"title":"Gone","detail":"The model \'meta/llama-3.3-70b-instruct\' has reached its end of life"}', status=410)
    assert e.is_unknown_model


def test_free_stays_free():
    models = ["openrouter/auto", "anthropic/claude-x", "google/gemma-4-31b-it:free", "openrouter/free"]
    assert pick_model(models, prefer_free=True) == "openrouter/free"
    assert pick_model(["x/paid", "y/model:free"], prefer_free=True) == "y/model:free"
    assert pick_model(["bigcode/starcoder2-15b", "openai/gpt-oss-20b"]) == "openai/gpt-oss-20b"


def test_a_plain_text_answer_is_a_readable_error():
    def handler(req):
        return httpx.Response(200, text="OK", headers={"content-type": "text/plain"})

    p = OpenAICompat("github", "https://models.example/inference", "m", "k", transport=httpx.MockTransport(handler))

    async def run():
        async for _ in p.stream([{"role": "user", "content": "hi"}], None):
            pass

    try:
        asyncio.run(run())
        raise AssertionError("no error")
    except ProviderError as e:
        assert "nečekaná odpověď" in str(e)
