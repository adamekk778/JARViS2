"""Any OpenAI-compatible endpoint: OmniRoute, OpenRouter, Groq, Gemini, LM Studio, ..."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from . import pool

from .base import Chunk, ProviderError, ToolCallAssembler



def _tls():
    """The certificates Windows trusts (as the browser) – the same connection the lyrics and covers use, so an
    antivirus that checks HTTPS (Bitdefender) does not stop the AI."""
    from .. import tlsctx

    return tlsctx.context()

GEMINI_SKIP = "skip_thought_signature_validator"      # Google's documented value for calls without a signature


def with_signatures(messages: list[dict]) -> list[dict]:
    """Gemini 3 thinks before it calls a tool and signs that thought; the next request must carry the signature back on
    the first tool call of every assistant step, or Gemini answers 400. Calls that came from another AI (a fallback
    earlier in the chat) or an older JARVIS get Google's documented "skip" value instead."""
    out = []
    for m in messages:
        calls = m.get("tool_calls") if m.get("role") == "assistant" else None
        if calls:
            calls = [dict(c) for c in calls]
            first = calls[0]
            google = ((first.get("extra_content") or {}).get("google") or {})
            if not google.get("thought_signature"):
                first["extra_content"] = {**(first.get("extra_content") or {}),
                                          "google": {**google, "thought_signature": GEMINI_SKIP}}
            m = {**m, "tool_calls": calls}
        out.append(m)
    return out


def without_foreign(messages: list[dict]) -> list[dict]:
    """3.14: what Claude attached to its tool calls (thinking blocks) stays with Claude – another service would refuse
    an unknown field or read a large block it cannot use."""
    out = []
    for m in messages:
        calls = m.get("tool_calls") if m.get("role") == "assistant" else None
        if calls and any("anthropic" in (c.get("extra_content") or {}) for c in calls):
            calls = [dict(c) for c in calls]
            for c in calls:
                ex = {k: v for k, v in (c.get("extra_content") or {}).items() if k != "anthropic"}
                if ex:
                    c["extra_content"] = ex
                else:
                    c.pop("extra_content", None)
            m = {**m, "tool_calls": calls}
        out.append(m)
    return out


def is_gemini(base_url: str) -> bool:
    return "generativelanguage.googleapis.com" in base_url


def best_gemini(models: list[str]) -> str:
    """The newest general Flash model Google offers (not an image/TTS/live/preview variant)."""
    def ver(m: str) -> tuple:
        import re

        v = re.search(r"gemini-(\d+(?:\.\d+)?)-flash", m)
        return (float(v.group(1)) if v else 0.0, "lite" not in m)
    names = [m.removeprefix("models/") for m in models]
    good = [m for m in names if "flash" in m and not any(w in m for w in ("image", "tts", "live", "preview", "exp", "audio", "embed", "thinking"))]
    return max(good, key=ver) if good else ""


class OpenAICompat:
    def __init__(self, id: str, base_url: str, model: str, api_key: str = "", *,  # noqa: A002
                 temperature: float = 0.6, max_tokens: int = 2048,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 120.0):
        self.id = id
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._transport = transport
        self._timeout = timeout
        self.on_headers = None          # 3.12 the router reads the daily allowance left from the answer headers

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            h["HTTP-Referer"] = "https://github.com/adamekk778/JARViS2"
            h["X-Title"] = "JARVIS 2"
        return h

    async def stream(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> AsyncIterator[Chunk]:
        messages = without_foreign(messages)
        if is_gemini(self.base_url):
            messages = with_signatures(messages)
        body: dict = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
        asm = ToolCallAssembler()
        try:
            async with pool.client(self._transport, self._timeout, _tls()) as client:     # 3.16 a kept connection
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=body,
                                         timeout=self._timeout) as r:
                    if self.on_headers is not None:
                        try:
                            self.on_headers(r.headers)
                        except Exception:  # noqa: BLE001
                            pass
                    if r.status_code >= 400:
                        text = (await r.aread()).decode("utf-8", "replace")[:500]
                        raise ProviderError(f"HTTP {r.status_code}: {text}", status=r.status_code)
                    ctype = r.headers.get("content-type", "")
                    if "text/event-stream" not in ctype:
                        # Some gateways ignore stream=true; accept a plain JSON body.
                        raw = await r.aread()
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            raise ProviderError(f"HTTP {r.status_code}: nečekaná odpověď služby: "
                                                f"{raw[:160].decode('utf-8', 'replace')}", status=502) from None
                        if not isinstance(data, dict):
                            raise ProviderError(f"HTTP {r.status_code}: nečekaná odpověď služby", status=502)
                        msg = (data.get("choices") or [{}])[0].get("message") or {}
                        if msg.get("tool_calls"):
                            asm.add([{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])])
                        if msg.get("content"):
                            yield Chunk(text=msg["content"])
                    else:
                        async for line in r.aiter_lines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                data = json.loads(payload)
                            except ValueError:
                                continue
                            if data.get("error"):
                                raise ProviderError(str(data["error"]), status=500)
                            for ch in data.get("choices") or []:
                                delta = ch.get("delta") or {}
                                if delta.get("tool_calls"):
                                    asm.add(delta["tool_calls"])
                                if delta.get("content"):
                                    yield Chunk(text=delta["content"])
        except httpx.HTTPError as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e
        calls = asm.result()
        yield Chunk(tool_calls=calls or None, done=True)

    async def list_models(self) -> list[str]:
        """GET /models – the model names this endpoint offers (empty when it cannot say)."""
        try:
            async with pool.client(self._transport, 15, _tls()) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers(), timeout=15)
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("data") if isinstance(data, dict) else data
            return [str(m.get("id")) for m in items or [] if isinstance(m, dict) and m.get("id")]
        except (httpx.HTTPError, ValueError):
            return []


# models a chat can not use (speech, safety filters, embeddings) – never picked as the "best" one
_NOT_CHAT = ("whisper", "tts", "guard", "embed", "playai", "distil-whisper", "orpheus", "moderation")
# the strongest known chat models, best first (3.12: Groq's own recommendation after it switched off Llama 3.3)
_PREFERRED = ("openai/gpt-oss-120b", "gpt-oss-120b", "openai/gpt-oss-20b")


def pick_model(models: list[str], prefer_free: bool = False) -> str:
    """The best general model from a gateway's list: its automatic route if it has one, a known strong chat model,
    else the first one that can chat. `prefer_free`: the old model was a free one (OpenRouter) – stay free."""
    if not models:
        return ""
    if any(m.removeprefix("models/").startswith("gemini-") for m in models[:50]):
        g = best_gemini(models)                      # Google: the newest Flash (Google retires old ones every few months)
        if g:
            return g
    if prefer_free:
        if "openrouter/free" in models:
            return "openrouter/free"
        free = [m for m in models if m.endswith(":free") and not any(w in m.lower() for w in _NOT_CHAT)]
        if free:
            return free[0]
    for want in ("auto", "auto/smart", "auto/best", "auto/best-free", "auto/free", "auto/fast"):
        if want in models:
            return want
    autos = [m for m in models if m.lower().startswith("auto")]
    if autos:
        return autos[0]
    for want in _PREFERRED:
        if want in models:
            return want
    chat = [m for m in models if not any(w in m.lower() for w in _NOT_CHAT)]
    return (chat or models)[0]


def friendly_error(preset: str, base_url: str, e: Exception) -> str:
    """A message a person can act on instead of 'HTTP 401: {...}'."""
    status = getattr(e, "status", None)
    name = "OmniRoute" if preset == "omniroute" else "Poskytovatel"
    if preset == "groq":
        low = str(e).lower()
        if status == 401 or "invalid api key" in low:
            return ("Groq klíč odmítl – zkopíruj ho znovu celý (začíná gsk_, bez mezer) z console.groq.com/keys "
                    "a vlož do pole API klíč u Groq.")
        if status == 403:
            return ("Groq odmítl přístup (403) – ověř na console.groq.com, že je účet aktivní; pomáhá i vypnout VPN "
                    "nebo zkusit jinou síť.")
        if status == 429:
            return "Groq: vyčerpaný bezplatný limit – chvíli počkej (limit se obnovuje po minutách / za den)."
    if status in (401, 403):
        return (f"{name} odmítl přístup – chybí nebo nesedí API klíč. Vlož ho v Nastavení → AI mozek → API klíč"
                + (" (klíč vytvoříš v OmniRoute v části API Keys)." if preset == "omniroute" else "."))
    text = str(e)
    if "10013" in text or "access permissions" in text or "zakázan" in text:
        from ..brainkey import BLOCKED

        return BLOCKED                          # the key is fine: Windows / an antivirus keeps JARVIS off the internet
    if status is None and any(w in text for w in ("ConnectError", "ConnectTimeout", "refused")):
        return (f"{name} na adrese {base_url} neodpovídá"
                + (" – běží OmniRoute? (spusť ho, nebo v Nastavení oprav adresu)." if preset == "omniroute" else "."))
    return text[:200]
