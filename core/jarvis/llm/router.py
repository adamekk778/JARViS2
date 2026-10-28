"""Fallback chain over providers: OmniRoute → … → Ollama."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import defaultdict, deque
from typing import AsyncIterator, Callable

import httpx

from ..config import Brain, ProviderCfg
from .base import AllProvidersFailed, Chunk, ProviderError
from .ollama import Ollama
from .openai_compat import OpenAICompat, friendly_error, pick_model
from .presets import PRESETS

log = logging.getLogger(__name__)


def build_provider(p: ProviderCfg, api_key: str, brain: Brain, transport: httpx.AsyncBaseTransport | None = None):
    base = p.base_url or PRESETS.get(p.preset, {}).get("base_url", "")
    model = p.model or PRESETS.get(p.preset, {}).get("model", "")
    if p.preset == "ollama":
        import os

        from .local import mode_options

        options, keep_alive = mode_options(brain.local_mode, os.cpu_count() or 4)
        if brain.local_gpu_layers >= 0:                       # OMEGA 574: how much of the model goes to the graphics card
            options["num_gpu"] = brain.local_gpu_layers
        return Ollama(p.id, base, model, temperature=brain.temperature, transport=transport, options=options,
                      keep_alive=keep_alive)
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
        self.ttft: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))  # ms to first token, per provider
        self.on_usage: Callable[[str, str, list[dict], int], None] | None = None   # OMEGA 178: usage ledger
        self.gate: Callable[[ProviderCfg], str] | None = None                       # → reason to skip a provider
        self.local_queue = None                                                     # OMEGA 577: aiplus.InferenceQueue
        self.cache = None                                                           # OMEGA 584: aiplus.AICache
        self.resolved_models: dict[str, str] = {}   # provider id → model found via /models when the set one is unknown

    def update(self, brain: Brain) -> None:
        self.brain = brain

    def providers(self) -> list[ProviderCfg]:
        by_id = {p.id: p for p in self.brain.providers if p.enabled}
        order = [by_id[i] for i in self.brain.chain if i in by_id]
        order += [p for p in by_id.values() if p not in order]
        if self.brain.offline_only:
            order = [p for p in order if PRESETS.get(p.preset, {}).get("local")]
        if not self.brain.local_enabled:
            order = [p for p in order if not PRESETS.get(p.preset, {}).get("local")]
        return order

    async def stream(self, messages: list[dict], tools: list[dict] | None,
                     need_vision: bool = False, fast: bool = False, only: str | None = None) -> AsyncIterator[Chunk]:
        errors: dict[str, str] = {}
        cands = self.providers()
        if only:   # OMEGA 204 / 006: ask one particular provider (to compare models)
            cands = [p for p in cands if p.id == only]
        if need_vision:
            # Providers with an explicit vision model go first.
            cands = sorted(cands, key=lambda p: (p.id in self.no_vision, not p.vision_model))
        for pcfg in cands:
            why = self.gate(pcfg) if self.gate else ""
            if why:
                errors[pcfg.id] = why
                continue
            prov = build_provider(pcfg, self.key_lookup(pcfg.id), self.brain, self.transport)
            if pcfg.id in self.resolved_models:
                prov.model = self.resolved_models[pcfg.id]
            model = (pcfg.vision_model if need_vision and pcfg.vision_model else
                     pcfg.fast_model if fast and pcfg.fast_model else None)
            resolved = False
            msgs = messages
            if need_vision and pcfg.id in self.no_vision:
                msgs = _strip_images(messages)
            use_tools = tools if pcfg.id not in self.no_tools else None
            local = self.local_queue is not None and PRESETS.get(pcfg.preset, {}).get("local")
            async with self.local_queue.slot() if local else contextlib.nullcontext():   # OMEGA 577: one local inference at a time
                for attempt in range(4):   # retries: without tools, without images, another model
                    started = False
                    try:
                        agen = prov.stream(msgs, use_tools, model=model)
                        t_req = time.monotonic()
                        first = await asyncio.wait_for(agen.__anext__(), timeout=self.brain.first_token_timeout)
                        self.ttft[pcfg.id].append((time.monotonic() - t_req) * 1000)
                        started = True
                        self.last_used = (pcfg.id, model or prov.model)
                        out = len(first.text or "")
                        yield first
                        async for ch in agen:
                            out += len(ch.text or "") + sum(len(str(c.arguments)) for c in ch.tool_calls or [])
                            yield ch
                        self.last_errors = errors
                        if self.on_usage:
                            try:
                                self.on_usage(pcfg.id, model or prov.model, msgs, out)
                            except Exception as e:  # accounting must never break an answer
                                log.debug("usage: %s", e)
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
                        if e.is_unknown_model and not resolved and hasattr(prov, "list_models"):
                            # the configured model (e.g. "auto") does not exist there: ask the gateway what it has
                            resolved = True
                            found = pick_model(await prov.list_models())
                            if found and found != (model or prov.model):
                                log.info("%s: model %s unknown, using %s", pcfg.id, model or prov.model, found)
                                self.resolved_models[pcfg.id] = prov.model = found
                                model = None
                                continue
                        errors[pcfg.id] = friendly_error(pcfg.preset, prov.base_url if hasattr(prov, "base_url") else "", e)
                        break
        self.last_errors = errors
        raise AllProvidersFailed(errors)

    async def complete(self, messages: list[dict], need_vision: bool = False, fast: bool = False, only: str | None = None,
                       cache: bool = False) -> str:
        key = self.cache.key(messages, vision=need_vision, fast=fast, only=only) if cache and self.cache else ""
        if key and (hit := self.cache.get(key)) is not None:      # OMEGA 584: the same question again → no model call
            return hit
        out = []
        async for ch in self.stream(messages, None, need_vision=need_vision, fast=fast, only=only):
            out.append(ch.text)
        text = "".join(out)
        if key:
            self.cache.put(key, text)
        return text
