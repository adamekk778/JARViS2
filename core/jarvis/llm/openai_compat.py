"""Any OpenAI-compatible endpoint: OmniRoute, OpenRouter, Groq, Gemini, LM Studio, ..."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Chunk, ProviderError, ToolCallAssembler


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

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            h["HTTP-Referer"] = "https://github.com/adamekk778/JARViS2"
            h["X-Title"] = "JARVIS 2"
        return h

    async def stream(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> AsyncIterator[Chunk]:
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
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=body) as r:
                    if r.status_code >= 400:
                        text = (await r.aread()).decode("utf-8", "replace")[:500]
                        raise ProviderError(f"HTTP {r.status_code}: {text}", status=r.status_code)
                    ctype = r.headers.get("content-type", "")
                    if "text/event-stream" not in ctype:
                        # Some gateways ignore stream=true; accept a plain JSON body.
                        data = json.loads(await r.aread())
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
            async with httpx.AsyncClient(transport=self._transport, timeout=15) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("data") if isinstance(data, dict) else data
            return [str(m.get("id")) for m in items or [] if isinstance(m, dict) and m.get("id")]
        except (httpx.HTTPError, ValueError):
            return []


def pick_model(models: list[str]) -> str:
    """The best general model from a gateway's list: its automatic route if it has one, else the first."""
    if not models:
        return ""
    for want in ("auto", "auto/smart", "auto/best", "auto/best-free", "auto/free", "auto/fast"):
        if want in models:
            return want
    autos = [m for m in models if m.lower().startswith("auto")]
    return (autos or models)[0]


def friendly_error(preset: str, base_url: str, e: Exception) -> str:
    """A message a person can act on instead of 'HTTP 401: {...}'."""
    status = getattr(e, "status", None)
    name = "OmniRoute" if preset == "omniroute" else "Poskytovatel"
    if status in (401, 403):
        return (f"{name} odmítl přístup – chybí nebo nesedí API klíč. Vlož ho v Nastavení → AI mozek → API klíč"
                + (" (klíč vytvoříš v OmniRoute v části API Keys)." if preset == "omniroute" else "."))
    text = str(e)
    if status is None and any(w in text for w in ("ConnectError", "ConnectTimeout", "refused")):
        return (f"{name} na adrese {base_url} neodpovídá"
                + (" – běží OmniRoute? (spusť ho, nebo v Nastavení oprav adresu)." if preset == "omniroute" else "."))
    return text[:200]
