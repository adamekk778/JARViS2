"""Ollama native /api/chat — the offline fallback."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Chunk, ProviderError, ToolCall


def to_ollama_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        nm: dict = {"role": m["role"]}
        content = m.get("content")
        if isinstance(content, list):
            texts, images = [], []
            for part in content:
                if part.get("type") == "text":
                    texts.append(part["text"])
                elif part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    if url.startswith("data:"):
                        images.append(url.split(",", 1)[1])
            nm["content"] = "\n".join(texts)
            if images:
                nm["images"] = images
        else:
            nm["content"] = content or ""
        if m.get("tool_calls"):
            nm["tool_calls"] = [
                {"function": {"name": tc["function"]["name"],
                              "arguments": json.loads(tc["function"]["arguments"] or "{}")}}
                for tc in m["tool_calls"]
            ]
        out.append(nm)
    return out


class Ollama:
    def __init__(self, id: str, base_url: str, model: str, *, temperature: float = 0.6,  # noqa: A002
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 300.0, **_):
        self.id = id
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.model = model
        self.temperature = temperature
        self._transport = transport
        self._timeout = timeout

    async def stream(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> AsyncIterator[Chunk]:
        body: dict = {"model": model or self.model, "messages": to_ollama_messages(messages), "stream": True,
                      "options": {"temperature": self.temperature}}
        if tools:
            body["tools"] = tools
        calls: list[ToolCall] = []
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                    if r.status_code >= 400:
                        text = (await r.aread()).decode("utf-8", "replace")[:500]
                        raise ProviderError(f"HTTP {r.status_code}: {text}", status=r.status_code)
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise ProviderError(data["error"], status=500)
                        msg = data.get("message") or {}
                        for i, tc in enumerate(msg.get("tool_calls") or []):
                            fn = tc.get("function") or {}
                            args = fn.get("arguments") or {}
                            if isinstance(args, str):
                                args = json.loads(args or "{}")
                            calls.append(ToolCall(id=f"call_{len(calls)}_{i}", name=fn.get("name", ""), arguments=args))
                        if msg.get("content"):
                            yield Chunk(text=msg["content"])
                        if data.get("done"):
                            break
        except httpx.HTTPError as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e
        yield Chunk(tool_calls=calls or None, done=True)
