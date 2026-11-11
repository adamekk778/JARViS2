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
from . import budget as bud
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


# Groq's free models each have their own limits: when one is used up for the day, another one still answers
GROQ_ALT = ("openai/gpt-oss-120b", "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile",
            "moonshotai/kimi-k2-instruct-0905", "openai/gpt-oss-20b", "qwen/qwen3-32b", "llama-3.1-8b-instant")
SHORT_WAIT_S = 60           # "try again in 40 s" (a minute's limit) → JARVIS waits it out and carries on


def retry_after(e: Exception) -> float | None:
    """Seconds a rate-limited provider asks to wait ("Please try again in 1m12.5s" / "in 7.66s" / "in 450ms")."""
    import re

    m = re.search(r"try again in\s+(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?", str(e), re.I)
    if not m or not any(m.groups()):
        return None
    h, mi, sec, ms = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + sec + ms / 1000


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
        self.limited: dict[tuple[str, str], float] = {}   # (provider, model) → used up until (monotonic): skip it till then
        self.tpm: dict[tuple[str, str], int] = {}          # (provider, model) → tokens a minute, learnt from its errors
        self.on_wait: Callable[[str, float], None] | None = None   # tells the user "waiting N s for the limit"
        self.on_switch: Callable[[dict, str], None] | None = None  # "Groq ran out → carrying on with Gemini"
        from .quota import Quota

        self.quota = Quota()

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
                     need_vision: bool = False, fast: bool = False, only: str | None = None,
                     model: str | None = None) -> AsyncIterator[Chunk]:
        """`model` asks one particular model of the provider (to compare several models of one gateway)."""
        want_model = model
        errors: dict[str, str] = {}
        cands = self.providers()
        if only:   # OMEGA 204 / 006: ask one particular provider (to compare models)
            cands = [p for p in cands if p.id == only]
        if need_vision:
            # Providers with an explicit vision model go first.
            cands = sorted(cands, key=lambda p: (p.id in self.no_vision,
                                                 not (p.vision_model or PRESETS.get(p.preset, {}).get("vision_model"))))
        for pcfg in cands:
            why = self.gate(pcfg) if self.gate else ""
            if why:
                errors[pcfg.id] = why
                continue
            prov = build_provider(pcfg, self.key_lookup(pcfg.id), self.brain, self.transport)
            if hasattr(prov, "on_headers"):
                prov.on_headers = lambda h, _p=pcfg.id, _prov=prov: self.quota.from_headers(_p, _prov.model, h)
            if pcfg.id in self.resolved_models:
                prov.model = self.resolved_models[pcfg.id]
            if not want_model and self._is_limited(pcfg.id, prov.model):     # used up a moment ago: straight to another
                alt = await self._alt_model(pcfg, prov)
                if alt:
                    prov.model = alt
            quick = pcfg.fast_model or PRESETS.get(pcfg.preset, {}).get("fast_model", "")   # Groq/Gemini: own allowance
            eyes = pcfg.vision_model or PRESETS.get(pcfg.preset, {}).get("vision_model", "")  # Groq: Llama 4 Scout sees
            model = want_model or (eyes if need_vision and eyes else quick if fast and quick else None)
            resolved = False
            bad_call_retried = False
            fitted_again = False
            last_err: Exception | None = None
            msgs = messages
            if need_vision and pcfg.id in self.no_vision:
                msgs = _strip_images(messages)
            use_tools = tools if pcfg.id not in self.no_tools else None
            local = self.local_queue is not None and PRESETS.get(pcfg.preset, {}).get("local")
            async with self.local_queue.slot() if local else contextlib.nullcontext():   # OMEGA 577: one local inference at a time
                for attempt in range(6):   # retries: without tools, without images, another model, after a short wait
                    started = False
                    send_msgs, send_tools = msgs, use_tools
                    limit = self._limit_of(pcfg, model or prov.model)
                    if limit:                    # a small per-minute limit (Groq): make the request fit it
                        send_msgs, send_tools, prov.max_tokens = bud.fit(msgs, use_tools, limit, self.brain.max_tokens)
                        need = bud.estimate(send_msgs, send_tools) + prov.max_tokens
                        if need > limit and not want_model:          # still too big → a model with a bigger limit
                            big = await self._alt_model(pcfg, prov, need=need)
                            if big:
                                log.info("%s: request ~%d tokens > %d of %s, using %s", pcfg.id, need, limit, prov.model, big)
                                prov.model, model = big, None
                                limit = self._limit_of(pcfg, big)
                                send_msgs, send_tools, prov.max_tokens = bud.fit(msgs, use_tools, limit, self.brain.max_tokens)
                    try:
                        agen = prov.stream(send_msgs, send_tools, model=model)
                        t_req = time.monotonic()
                        first = await asyncio.wait_for(agen.__anext__(), timeout=self.brain.first_token_timeout)
                        self.ttft[pcfg.id].append((time.monotonic() - t_req) * 1000)
                        started = True
                        self.last_used = (pcfg.id, model or prov.model)
                        if errors and self.on_switch:          # an earlier provider failed: say who carries on
                            try:
                                self.on_switch(dict(errors), pcfg.id)
                            except Exception:  # noqa: BLE001
                                pass
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
                        last_err = e
                        if started:
                            raise
                        if use_tools and e.is_bad_tool_call and not bad_call_retried:
                            bad_call_retried = True          # a malformed tool call: once more, tools stay on
                            log.info("%s: malformed tool call, asking again", pcfg.id)
                            continue
                        if use_tools and e.is_tools_unsupported:
                            log.info("%s: tools unsupported, retrying without", pcfg.id)
                            self.no_tools.add(pcfg.id)
                            use_tools = None
                            continue
                        if need_vision and e.is_vision_unsupported and pcfg.id not in self.no_vision:
                            self.no_vision.add(pcfg.id)
                            msgs = _strip_images(messages)
                            continue
                        if e.status in (413, 429):
                            learnt = bud.limit_from_error(str(e))
                            if learnt:
                                self.tpm[(pcfg.id, model or prov.model)] = learnt
                            asked = bud.requested_from_error(str(e))
                            if learnt and asked and asked > learnt and not fitted_again:
                                fitted_again = True      # one request bigger than the whole minute: fit it, ask again
                                continue
                            wait = retry_after(e)
                            if e.status == 429 and wait is not None and wait <= SHORT_WAIT_S:
                                log.info("%s: rate limited, waiting %.1f s", pcfg.id, wait)   # a minute's limit: wait it out
                                if self.on_wait and wait >= 4:
                                    try:
                                        self.on_wait(pcfg.id, wait)
                                    except Exception:  # noqa: BLE001
                                        pass
                                await asyncio.sleep(wait + 0.3)
                                continue
                            cur = model or prov.model
                            self.limited[(pcfg.id, cur)] = time.monotonic() + (wait if wait else 600)
                            alt = None if want_model else await self._alt_model(pcfg, prov)
                            if alt:
                                log.info("%s: %s used up, switching to %s", pcfg.id, cur, alt)
                                prov.model, model = alt, None
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
                else:   # every retry used up (waits, other models): say why – it used to end as "no AI brain at all"
                    if last_err is not None and pcfg.id not in errors:
                        errors[pcfg.id] = friendly_error(pcfg.preset, prov.base_url if hasattr(prov, "base_url") else "", last_err)
        self.last_errors = errors
        raise AllProvidersFailed(errors)

    def _is_limited(self, pid: str, model: str) -> bool:
        until = self.limited.get((pid, model))
        return bool(until and until > time.monotonic())

    def _limit_of(self, pcfg: ProviderCfg, model: str) -> int | None:
        """Tokens a minute this model allows, when known (learnt from an error, or Groq's free tier)."""
        if (pcfg.id, model) in self.tpm:
            return self.tpm[(pcfg.id, model)]
        if pcfg.preset == "groq":
            return bud.GROQ_TPM.get(model, 8000)
        return None

    async def _alt_model(self, pcfg: ProviderCfg, prov, need: int = 0) -> str | None:
        """Another model of the same provider whose own limit is not used up (Groq: each model counts separately);
        with `need`, one whose per-minute limit is big enough for the request."""
        if pcfg.preset != "groq":
            return None
        have: list[str] = []
        if hasattr(prov, "list_models"):
            try:
                have = await prov.list_models()
            except Exception:  # noqa: BLE001
                have = []
        for m in GROQ_ALT:
            if (not have or m in have) and m != prov.model and not self._is_limited(pcfg.id, m) \
                    and (not need or (self._limit_of(pcfg, m) or 0) >= need):
                return m
        return None

    async def complete(self, messages: list[dict], need_vision: bool = False, fast: bool = False, only: str | None = None,
                       cache: bool = False, model: str | None = None) -> str:
        key = self.cache.key(messages, vision=need_vision, fast=fast, only=only) if cache and self.cache else ""
        if key and (hit := self.cache.get(key)) is not None:      # OMEGA 584: the same question again → no model call
            return hit
        out = []
        async for ch in self.stream(messages, None, need_vision=need_vision, fast=fast, only=only, model=model):
            out.append(ch.text)
        text = "".join(out)
        if key:
            self.cache.put(key, text)
        return text
