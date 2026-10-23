"""Fallback chain over providers: OmniRoute → … → Ollama."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

import httpx

from ..config import Brain, ProviderCfg
from .base import AllProvidersFailed, Chunk, ProviderError
from .ollama import Ollama
from .openai_compat import OpenAICompat
from .presets import PRESETS

log = logging.getLogger(__name__)


def build_provider(p: ProviderCfg, api_key: str, brain: Brain, transport: httpx.AsyncBaseTransport | None = None):
    base = p.base_url or PRESETS.get(p.preset, {}).get("base_url", "")
    model = p.model or PRESETS.get(p.preset, {}).get("model", "")
    if p.preset == "ollama":
        return Ollama(p.id, base, model, temperature=brain.temperature, transport=transport)
    return OpenAICompat(p.id, base, model, api_key, temperature=brain.temperature,
                        max_tokens=brain.max_tokens, transport=transport)


def _strip_images(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            texts = [p["text"] for p in c if p.get("type") == "text"]
            n_img = sum(1 for p in c if p.get("type") == "image_url")
            if n_img:
                texts.append(f"[{n_img}× obrázek – tento model obrázky nevidí]")
            m = {**m, "content": "\n".join(texts)}
        out.append(m)
    return out


class Router:
    def __init__(self, brain: Brain, key_lookup: Callable[[str], str],
                 transport: httpx.AsyncBaseTransport | None = None):
        self.brain = brain
        self.key_lookup = key_lookup
        self.transport = transport
        self.no_tools: set[str] = set()
        self.no_vision: set[str] = set()
        self.last_used: tuple[str, str] | None = None
        self.last_errors: dict[str, str] = {}

    def update(self, brain: Brain) -> None:
        self.brain = brain

    def providers(self) -> list[ProviderCfg]:
        by_id = {p.id: p for p in self.brain.providers if p.enabled}
        order = [by_id[i] for i in self.brain.chain if i in by_id]
        order += [p for p in by_id.values() if p not in order]
        if self.brain.offline_only:
            order = [p for p in order if PRESETS.get(p.preset, {}).get("local")]
        return order

    async def stream(self, messages: list[dict], tools: list[dict] | None,
                     need_vision: bool = False, fast: bool = False) -> AsyncIterator[Chunk]:
        errors: dict[str, str] = {}
        cands = self.providers()
        if need_vision:
            # Providers with an explicit vision model go first.
            cands = sorted(cands, key=lambda p: (p.id in self.no_vision, not p.vision_model))
        for pcfg in cands:
            prov = build_provider(pcfg, self.key_lookup(pcfg.id), self.brain, self.transport)
            model = (pcfg.vision_model if need_vision and pcfg.vision_model else
                     pcfg.fast_model if fast and pcfg.fast_model else None)
            msgs = messages
            if need_vision and pcfg.id in self.no_vision:
                msgs = _strip_images(messages)
            use_tools = tools if pcfg.id not in self.no_tools else None
            for attempt in range(3):
                started = False
                try:
                    agen = prov.stream(msgs, use_tools, model=model)
                    first = await asyncio.wait_for(agen.__anext__(), timeout=self.brain.first_token_timeout)
                    started = True
                    self.last_used = (pcfg.id, model or prov.model)
                    yield first
                    async for ch in agen:
                        yield ch
                    self.last_errors = errors
                    return
                except StopAsyncIteration:
                    self.last_used = (pcfg.id, model or prov.model)
                    yield Chunk(done=True)
                    return
                except asyncio.TimeoutError:
                    errors[pcfg.id] = "neodpověděl včas"
                    break
                except ProviderError as e:
                    if started:
                        raise
                    if use_tools and e.is_tools_unsupported:
                        log.info("%s: tools unsupported, retrying without", pcfg.id)
                        self.no_tools.add(pcfg.id)
                        use_tools = None
                        continue
                    if need_vision and e.is_vision_unsupported and pcfg.id not in self.no_vision:
                        self.no_vision.add(pcfg.id)
                        msgs = _strip_images(messages)
                        continue
                    errors[pcfg.id] = str(e)[:200]
                    break
        self.last_errors = errors
        raise AllProvidersFailed(errors)

    async def complete(self, messages: list[dict], need_vision: bool = False, fast: bool = False) -> str:
        out = []
        async for ch in self.stream(messages, None, need_vision=need_vision, fast=fast):
            out.append(ch.text)
        return "".join(out)
