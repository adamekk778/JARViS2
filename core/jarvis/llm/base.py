"""LLM provider interface (OpenAI chat format everywhere)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Chunk:
    text: str = ""
    tool_calls: list[ToolCall] | None = None
    done: bool = False


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable

    @property
    def is_tools_unsupported(self) -> bool:
        m = str(self).lower()
        return self.status == 400 and any(w in m for w in ("tool", "function"))

    @property
    def is_unknown_model(self) -> bool:
        """The gateway does not know this model name (e.g. OmniRoute without an "auto" route)."""
        m = str(self).lower()
        return self.status in (400, 404, 422) and "model" in m and any(
            w in m for w in ("not found", "unknown", "invalid", "does not exist", "not exist", "unsupported", "no such",
                             "not available", "not allowed"))

    @property
    def is_vision_unsupported(self) -> bool:
        m = str(self).lower()
        return self.status in (400, 422) and any(w in m for w in ("image", "vision", "multimodal"))


class AllProvidersFailed(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()) or "žádný poskytovatel není nastaven")
        self.errors = errors

    @property
    def is_limit(self) -> bool:
        """Every provider refused because of rate limits / quota."""
        import re

        return bool(self.errors) and all(re.search(r"429|rate.?limit|quota|limit|too many", v, re.I) for v in self.errors.values())


class LLMProvider(Protocol):
    id: str
    model: str

    def stream(self, messages: list[dict], tools: list[dict] | None, model: str | None = None) -> AsyncIterator[Chunk]: ...


@dataclass
class _PartialCall:
    id: str = ""
    name: str = ""
    args: str = ""


@dataclass
class ToolCallAssembler:
    """Merges OpenAI streamed tool_call deltas (by index) into whole calls."""
    parts: dict[int, _PartialCall] = field(default_factory=dict)

    def add(self, deltas: list[dict]) -> None:
        for d in deltas:
            p = self.parts.setdefault(d.get("index", len(self.parts)), _PartialCall())
            if d.get("id"):
                p.id = d["id"]
            fn = d.get("function") or {}
            if fn.get("name"):
                p.name += fn["name"]
            if fn.get("arguments"):
                a = fn["arguments"]
                p.args += a if isinstance(a, str) else __import__("json").dumps(a)

    def result(self) -> list[ToolCall]:
        import json

        out = []
        for i, p in sorted(self.parts.items()):
            try:
                args = json.loads(p.args) if p.args.strip() else {}
            except ValueError:
                args = {"_raw": p.args}
            out.append(ToolCall(id=p.id or f"call_{i}", name=p.name, arguments=args if isinstance(args, dict) else {"value": args}))
        return out
