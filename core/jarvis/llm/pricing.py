"""3.13 What the AI costs: an estimate in crowns from the providers' public price lists (USD per million tokens) and the
characters JARVIS sent and got back (≈ 4 characters a token). It is the price of a PAID key – with a free key (Gemini,
Groq free tier) or the offline AI in this PC you pay nothing; the control room says so next to the number."""
from __future__ import annotations

USD_CZK = 23.0
CHARS_PER_TOKEN = 4
FREE_PROVIDERS = ("local", "ollama", "offline", "lmstudio")
# (substring of the model name, USD per 1M input tokens, USD per 1M output tokens) – the first match wins
PRICES: list[tuple[str, float, float]] = [
    (":free", 0.0, 0.0),
    ("flash-lite", 0.10, 0.40), ("flash", 0.30, 2.50), ("gemini", 1.25, 10.0),
    ("gpt-oss", 0.15, 0.60), ("llama", 0.15, 0.60), ("qwen", 0.20, 0.60), ("kimi", 1.0, 3.0),
    ("nano", 0.05, 0.40), ("mini", 0.25, 2.0), ("gpt", 1.25, 10.0), ("o3", 2.0, 8.0), ("o4", 1.1, 4.4),
    ("haiku", 1.0, 5.0), ("sonnet", 3.0, 15.0), ("opus", 5.0, 25.0), ("claude", 3.0, 15.0),
    ("deepseek", 0.28, 0.42), ("mistral-small", 0.10, 0.30), ("mistral", 2.0, 6.0), ("grok", 3.0, 15.0),
]
DEFAULT = (0.50, 1.50)


def czk(model: str, tokens_in: int, tokens_out: int) -> float | None:
    """The cost of these tokens in CZK (None = unknown model, nothing used)."""
    if not model and not (tokens_in or tokens_out):
        return None
    m = (model or "").lower()
    provider = m.split(":", 1)[0] if ":" in m else ""
    if provider in FREE_PROVIDERS:
        return 0.0
    pin, pout = next(((i, o) for k, i, o in PRICES if k in m), DEFAULT)
    return round((tokens_in * pin + tokens_out * pout) / 1_000_000 * USD_CZK, 4)


def tokens(chars: int) -> int:
    return int(chars) // CHARS_PER_TOKEN
