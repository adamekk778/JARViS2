"""Claude through Anthropic's own Messages API (návrhy 2, 3, 28) – not the OpenAI-compatible layer.

What this adds over the compatible layer:
- prompt caching: the everyday tools (always first, always in the same order), the system prompt and the
  conversation are marked for the cache, so a follow-up in the same task re-reads them at a fraction of the price
  and time
- effort: quick questions think briefly ("low"), missions and hard questions deeper ("high") – set per request by
  the difficulty router (jarvis.llm.difficulty)
- thinking blocks of a task go back with the next step unchanged (the API requires them for tool use); JARVIS's
  system prompt and offered tools change between messages, so the request asks the API to drop a block whose
  conversation changed instead of refusing the request (`prefix_mismatch_behavior: "drop_block"`)
- a refused request goes on with Anthropic's fallback model in the same call (server-side fallbacks)

The OpenAI chat format stays everywhere else in JARVIS; this module converts it both ways.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, AsyncIterator

from .base import Chunk, ProviderError, ToolCall

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FAST_MODEL = "claude-haiku-5-5"
BETAS_THINKING = "thinking-binding-controls-2026-08-01"
BETAS_FALLBACK = "server-side-fallback-2026-07-01"
# models that take the server-side refusal fallback (Haiku has none)
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")
MIN_MAX_TOKENS = 16000          # thinking counts towards max_tokens: a small limit cut answers off mid-sentence
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _tls():
    from .. import tlsctx

    return tlsctx.context()


# ---------- OpenAI chat format → Messages API ----------
def _image_block(part: dict) -> dict | None:
    url = ((part.get("image_url") or {}).get("url") or "") if isinstance(part.get("image_url"), dict) else str(part.get("image_url") or "")
    m = re.match(r"data:(image/[a-z0-9.+-]+);base64,(.+)", url, re.S)
    if m:
        return {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2).replace("\n", "")}}
    if url.startswith("http"):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _content(c: Any) -> list[dict]:
    if c is None:
        return []
    if isinstance(c, str):
        return [{"type": "text", "text": c}] if c else []
    out = []
    for part in c:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            out.append({"type": "text", "text": part["text"]})
        elif part.get("type") in ("image_url", "input_image"):
            b = _image_block(part)
            if b:
                out.append(b)
        elif part.get("type") in ("image", "document"):       # already in this API's shape
            out.append(part)
    return out


def _args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except (TypeError, ValueError):
        return {}


def convert(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """OpenAI chat messages → (system blocks, messages). Tool results in a row become ONE user message (the API
    reads separate ones as the model not calling tools in parallel); thinking blocks kept on the first tool call
    go back in front of it."""
    system: list[dict] = []
    out: list[dict] = []

    def push(role: str, blocks: list[dict]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        if role == "system":
            if not out:
                system += _content(m.get("content"))
            else:                                   # a mid-conversation instruction: appended, never edited back
                push("user", [{"type": "text", "text": f"[Pokyn systému] {t['text']}"} for t in _content(m.get("content"))
                              if t.get("type") == "text"])
        elif role == "user":
            push("user", _content(m.get("content")))
        elif role == "assistant":
            blocks: list[dict] = []
            calls = m.get("tool_calls") or []
            if calls:
                extra = (calls[0].get("extra_content") or {}).get("anthropic") or {}
                blocks += [b for b in extra.get("thinking", []) if isinstance(b, dict)]
            blocks += _content(m.get("content"))
            for c in calls:
                fn = c.get("function") or {}
                blocks.append({"type": "tool_use", "id": c.get("id") or "call", "name": fn.get("name", ""),
                               "input": _args(fn.get("arguments"))})
            push("assistant", blocks)
        elif role == "tool":
            content = m.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
            push("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "call", "content": text or "(prázdné)"}])
    if out and out[0]["role"] != "user":            # the API wants the user first
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(pokračování)"}]})
    return split_static(system), out


def split_static(system: list[dict]) -> list[dict]:
    """3.16 the instructions in two blocks: what never changes (rules + the tool catalog – cached) and what changes
    with every message (time, memory, mood, the hint for this message) after it."""
    from ..toolcatalog import DYN

    out: list[dict] = []
    for b in system:
        t = b.get("text") if b.get("type") == "text" else None
        if t and DYN in t and not out:
            static, dyn = t.split(DYN, 1)
            out.append({"type": "text", "text": static})
            out.append({"type": "text", "text": DYN.lstrip("\n") + dyn})
        else:
            out.append(b)
    return out


def convert_tools(tools: list[dict] | None) -> list[dict]:
    out = []
    for t in tools or []:
        fn = t.get("function") or t
        if not fn.get("name"):
            continue
        out.append({"name": fn["name"], "description": (fn.get("description") or "")[:4000],
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                    "eager_input_streaming": True})
    return out


def mark_cache(tools: list[dict], system: list[dict], messages: list[dict], ttl: str = "5m") -> None:
    """Up to three cache breakpoints (the API takes four): after the run of everyday tools JARVIS always sends first
    and in the same order (the part of the tools that does not change between messages), after the system prompt,
    and on the newest message block (the conversation so far).
    3.17 ttl "1h": the unchanging instructions + catalog stay cached for an hour (you ask again after 20 minutes and it
    is still there). Longer entries must come before shorter ones, so with the split instructions the tools need no
    mark of their own (the instructions' mark covers them) and the conversation's mark keeps 5 minutes."""
    from ..tools.select import CORE

    if ttl == "1h" and len(system) > 1:
        system[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        for msg in reversed(messages):
            blocks = [b for b in msg["content"] if b.get("type") in ("text", "tool_result", "image", "tool_use")]
            if blocks:
                blocks[-1]["cache_control"] = {"type": "ephemeral"}
                break
        return
    core = set(CORE)
    last_core = -1
    for i, t in enumerate(tools):
        if t["name"] in core:
            last_core = i
        else:
            break
    if last_core >= 0:
        tools[last_core]["cache_control"] = {"type": "ephemeral"}
    elif tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    if system:                                      # the unchanging part (+ the catalog) when the instructions are split
        system[0 if len(system) > 1 else -1]["cache_control"] = {"type": "ephemeral"}
    for msg in reversed(messages):
        blocks = [b for b in msg["content"] if b.get("type") in ("text", "tool_result", "image", "tool_use")]
        if blocks:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
            break


def _dump(block: Any) -> dict:
    for attr in ("to_dict", "model_dump"):
        f = getattr(block, attr, None)
        if callable(f):
            try:
                return f(exclude_none=True) if attr == "model_dump" else f()
            except TypeError:
                return f()
    return dict(block) if isinstance(block, dict) else {}


_KEPT: dict[tuple, Any] = {}


class Claude:
    """A provider with the same surface as OpenAICompat (stream, list_models, model, max_tokens, on_headers)."""

    def __init__(self, id: str, base_url: str, model: str, api_key: str = "", *,  # noqa: A002
                 max_tokens: int = 2048, transport: Any = None, timeout: float = 120.0, client: Any = None):
        self.id = id
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.api_key = api_key
        self.max_tokens = max(int(max_tokens or 0), MIN_MAX_TOKENS)
        self.timeout = timeout
        self.on_headers = None
        self.effort: str | None = None        # set per request by the router (difficulty)
        self.cache_ttl = "5m"                 # 3.17 "1h" keeps the instructions + catalog for an hour
        self.last_usage: dict = {}
        self.last_stop: str = ""
        self._client = client

    # the SDK speaks to the API root, our presets keep ".../v1" (as the compatible layer needed)
    def _root(self) -> str:
        return re.sub(r"/v1/?$", "", self.base_url)

    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:            # pragma: no cover – shipped with JARVIS; a dev setup without it
                raise ProviderError("chybí knihovna anthropic (pip install anthropic)", status=None, retryable=False) from e
            import asyncio

            try:                                   # 3.16 one kept client (and connection) per event loop and key
                loop_id = id(asyncio.get_running_loop())
            except RuntimeError:
                loop_id = 0
            key = (loop_id, self.api_key, self._root(), self.timeout)
            kept = _KEPT.get(key)
            if kept is None:
                http = anthropic.DefaultAsyncHttpxClient(verify=_tls())
                kept = anthropic.AsyncAnthropic(api_key=self.api_key or None, base_url=self._root(), http_client=http,
                                                timeout=self.timeout, max_retries=1)
                if loop_id:
                    _KEPT[key] = kept
            self._client = kept
        return self._client

    async def warm(self) -> bool:
        """Open the connection now (Hey Jarvis): a small HEAD on the API root, the answer does not matter."""
        try:
            await self.client()._client.head(self._root() + "/v1/models", timeout=4)
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("claude prewarm: %s", e)
            return False

    async def warm_cache(self, messages: list[dict], tools: list[dict] | None) -> dict:
        """3.18 the cached part (tools + the fixed instructions + the catalog) written again with a 1-token request,
        so the real question after a long pause does not pay for (or wait on) writing it. Returns the cache usage."""
        p = self.params(messages, tools)
        p["max_tokens"] = 1
        p.pop("thinking", None)                 # tools + system stay cached whatever the thinking setting is
        p.pop("output_config", None)
        p.pop("fallbacks", None)
        p["betas"] = [b for b in p.get("betas", []) if b != BETAS_FALLBACK]
        msg = await self.client().beta.messages.create(**p)
        u = getattr(msg, "usage", None)
        return {"read": int(getattr(u, "cache_read_input_tokens", 0) or 0),
                "written": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}

    def params(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> dict:
        system, msgs = convert(messages)
        tl = convert_tools(tools)
        mark_cache(tl, system, msgs, self.cache_ttl)
        use = model or self.model
        p: dict = {"model": use, "max_tokens": self.max_tokens, "messages": msgs,
                   "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}}
        betas = [BETAS_THINKING]
        if system:
            p["system"] = system
        if tl:
            p["tools"] = tl
        if self.effort in EFFORTS:
            p["output_config"] = {"effort": self.effort}
        if use.startswith(FALLBACK_MODELS):     # a refusal goes on with Anthropic's fallback model in the same call
            betas.append(BETAS_FALLBACK)
            p["fallbacks"] = "default"
        p["betas"] = betas
        return p

    async def stream(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> AsyncIterator[Chunk]:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise ProviderError("chybí knihovna anthropic", retryable=False) from e
        params = self.params(messages, tools, model)
        try:
            async with self.client().beta.messages.stream(**params) as s:
                async for ev in s:
                    if ev.type == "text" and getattr(ev, "text", ""):
                        yield Chunk(text=ev.text)
                final = await s.get_final_message()
        except anthropic.RateLimitError as e:
            raise ProviderError(f"HTTP 429: {e.message}", status=429) from e
        except anthropic.AuthenticationError as e:
            raise ProviderError(f"HTTP 401: {e.message}", status=401, retryable=False) from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderError(f"HTTP 403: {e.message}", status=403, retryable=False) from e
        except anthropic.NotFoundError as e:
            raise ProviderError(f"HTTP 404: model not found: {e.message}", status=404, retryable=False) from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"HTTP 400: {e.message}", status=400, retryable=False) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"HTTP {e.status_code}: {e.message}", status=e.status_code) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e
        except ValueError as e:                  # a tool input the SDK could not parse at all
            raise ProviderError(f"HTTP 400: tool_use_failed: {e}", status=400) from e
        u = getattr(final, "usage", None)
        self.last_usage = {"in": getattr(u, "input_tokens", 0) or 0, "out": getattr(u, "output_tokens", 0) or 0,
                           "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                           "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
        stop = getattr(final, "stop_reason", "") or ""
        self.last_stop = stop
        if stop == "refusal":
            cat = getattr(getattr(final, "stop_details", None), "category", None)
            yield Chunk(text=f"\n(Claude tuhle žádost odmítl{f' – oblast: {cat}' if cat else ''}. Zkus ji říct jinak, nebo se zeptej jiné AI.)",
                        done=True)
            return
        blocks = list(getattr(final, "content", []) or [])
        uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
        if uses and stop == "max_tokens":        # a cut-off tool input parses as a valid partial object – never run it
            raise ProviderError("HTTP 400: tool_use_failed: odpověď se uřízla uprostřed volání nástroje", status=400)
        calls = []
        thinking = [_dump(b) for b in blocks if getattr(b, "type", "") in ("thinking", "redacted_thinking")]
        for i, b in enumerate(uses):
            args = b.input if isinstance(b.input, dict) else _args(b.input)
            calls.append(ToolCall(id=b.id, name=b.name, arguments=args,
                                  extra={"anthropic": {"thinking": thinking}} if i == 0 and thinking else None))
        yield Chunk(tool_calls=calls or None, done=True)

    async def list_models(self) -> list[str]:
        try:
            page = await self.client().models.list()
            return [m.id for m in getattr(page, "data", [])]
        except Exception as e:  # noqa: BLE001
            log.info("claude models: %s", e)
            return []


def to_effort(tier: str) -> str | None:
    """Difficulty tier → effort (návrh 4): a quick answer thinks briefly, a mission or a hard question deeper."""
    return {"instant": "low", "fast": "low", "normal": "low", "strong": "high"}.get(tier)


def b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()
