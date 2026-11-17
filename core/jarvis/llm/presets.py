"""Known providers. Everything with /v1/chat/completions works via openai_compat."""

PRESETS: dict[str, dict] = {
    "omniroute": {"label": "OmniRoute (zdarma, lokální brána)", "base_url": "http://localhost:20128/v1", "needs_key": False, "local": False, "model": "auto"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "needs_key": True, "local": False, "model": "openrouter/free"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "needs_key": True, "local": False, "model": "openai/gpt-oss-120b", "fast_model": "llama-3.1-8b-instant", "vision_model": "meta-llama/llama-4-scout-17b-16e-instruct"},   # the strongest on Groq (2026)
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "needs_key": True, "local": False, "model": "gpt-oss-120b", "fast_model": "llama3.1-8b"},   # 3.12 the fastest free one
    "mistral": {"label": "Mistral (zdarma s ověřeným telefonem)", "base_url": "https://api.mistral.ai/v1", "needs_key": True, "local": False, "model": "mistral-medium-latest", "fast_model": "mistral-small-latest"},
    "nvidia": {"label": "NVIDIA NIM (build.nvidia.com)", "base_url": "https://integrate.api.nvidia.com/v1", "needs_key": True, "local": False, "model": "openai/gpt-oss-20b"},
    "github": {"label": "GitHub Models", "base_url": "https://models.github.ai/inference", "needs_key": True, "local": False, "model": "openai/gpt-4.1-mini"},
    "sambanova": {"label": "SambaNova Cloud", "base_url": "https://api.sambanova.ai/v1", "needs_key": True, "local": False, "model": "Meta-Llama-3.3-70B-Instruct"},
    "cohere": {"label": "Cohere (zkušební klíč zdarma)", "base_url": "https://api.cohere.ai/compatibility/v1", "needs_key": True, "local": False, "model": "command-a-03-2025"},
    "huggingface": {"label": "Hugging Face", "base_url": "https://router.huggingface.co/v1", "needs_key": True, "local": False, "model": "openai/gpt-oss-120b"},
    "deepseek": {"label": "DeepSeek (levné, platí se kreditem)", "base_url": "https://api.deepseek.com/v1", "needs_key": True, "local": False, "model": "deepseek-chat", "fast_model": "deepseek-chat"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "needs_key": True, "local": False, "model": "gemini-3.8-flash", "fast_model": "gemini-3.5-flash-lite"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "needs_key": True, "local": False, "model": "gpt-4o-mini"},
    "anthropic": {"label": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "needs_key": True, "local": False, "model": "claude-haiku-4-5"},
    "lmstudio": {"label": "LM Studio (offline)", "base_url": "http://localhost:1234/v1", "needs_key": False, "local": True, "model": "local-model"},
    "ollama": {"label": "Ollama (offline)", "base_url": "http://localhost:11434", "needs_key": False, "local": True, "model": "qwen2.5:3b"},
    "custom": {"label": "Vlastní (OpenAI-kompatibilní)", "base_url": "", "needs_key": False, "local": False, "model": ""},
}
