"""Known providers. Everything with /v1/chat/completions works via openai_compat."""

PRESETS: dict[str, dict] = {
    "omniroute": {"label": "OmniRoute (zdarma, lokální brána)", "base_url": "http://localhost:20128/v1", "needs_key": False, "local": False, "model": "auto"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "needs_key": True, "local": False, "model": "meta-llama/llama-3.3-70b-instruct:free"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "needs_key": True, "local": False, "model": "llama-3.3-70b-versatile"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "needs_key": True, "local": False, "model": "gemini-2.0-flash"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "needs_key": True, "local": False, "model": "gpt-4o-mini"},
    "anthropic": {"label": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "needs_key": True, "local": False, "model": "claude-haiku-4-5"},
    "lmstudio": {"label": "LM Studio (offline)", "base_url": "http://localhost:1234/v1", "needs_key": False, "local": True, "model": "local-model"},
    "ollama": {"label": "Ollama (offline)", "base_url": "http://localhost:11434", "needs_key": False, "local": True, "model": "qwen2.5:3b"},
    "custom": {"label": "Vlastní (OpenAI-kompatibilní)", "base_url": "", "needs_key": False, "local": False, "model": ""},
}
