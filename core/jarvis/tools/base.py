"""Tool registry: @tool turns an async function into something the LLM can call."""
from __future__ import annotations

import inspect
import logging
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Annotated, Callable, Literal, get_args, get_origin

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: Any = None
    attachments: list[str] = field(default_factory=list)

    def for_llm(self) -> str:
        import json

        out: dict = {"ok": self.ok, "result": self.summary}
        if self.data is not None:
            out["data"] = self.data
        if self.attachments:
            out["attachments"] = self.attachments
        s = json.dumps(out, ensure_ascii=False, default=str)
        return s if len(s) < 12000 else s[:12000] + "…(zkráceno)"


@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: dict
    danger: bool = False
    danger_if: Callable[[dict], bool] | None = None
    category: str = "obecné"
    source: str = "builtin"

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


REGISTRY: dict[str, ToolSpec] = {}


def _json_type(tp: Any) -> dict:
    origin = get_origin(tp)
    if origin is Annotated:
        base, *meta = get_args(tp)
        d = _json_type(base)
        desc = next((m for m in meta if isinstance(m, str)), None)
        if desc:
            d["description"] = desc
        return d
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return _json_type(args[0]) if args else {"type": "string"}
    if origin is Literal:
        vals = list(get_args(tp))
        return {"type": "string" if isinstance(vals[0], str) else "integer", "enum": vals}
    if origin in (list, tuple):
        args = get_args(tp)
        return {"type": "array", "items": _json_type(args[0]) if args else {"type": "string"}}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is dict or origin is dict:
        return {"type": "object"}
    return {"type": "string"}


def schema_for(func: Callable) -> dict:
    sig = inspect.signature(func)
    hints = typing.get_type_hints(func, include_extras=True)
    props, required = {}, []
    for i, (name, p) in enumerate(sig.parameters.items()):
        if i == 0:  # ctx
            continue
        props[name] = _json_type(hints.get(name, str))
        if p.default is inspect.Parameter.empty:
            required.append(name)
        elif p.default is not None:
            props[name]["default"] = p.default
    out: dict = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def tool(name: str, description: str, *, danger: bool = False,
         danger_if: Callable[[dict], bool] | None = None, category: str = "obecné"):
    def deco(func):
        REGISTRY[name] = ToolSpec(name, description, func, schema_for(func), danger, danger_if, category,
                                  getattr(func, "__module__", "builtin"))
        return func
    return deco


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


def unregister_source(source: str) -> None:
    for k in [k for k, v in REGISTRY.items() if v.source == source]:
        del REGISTRY[k]


def is_dangerous(spec: ToolSpec, args: dict, always_confirm: list[str] = (), trusted: list[str] = ()) -> bool:
    if spec.name in trusted:
        return False
    if spec.name in always_confirm:
        return True
    if spec.danger_if is not None:
        try:
            return bool(spec.danger_if(args))
        except Exception:
            return True
    return spec.danger


def schemas(disabled: list[str] | set[str] = ()) -> list[dict]:
    return [s.schema() for s in REGISTRY.values() if s.name not in disabled]


async def call(name: str, args: dict, ctx: Any) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(False, f"Neznámý nástroj: {name}")
    allowed = set(spec.parameters.get("properties", {}))
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    missing = [r for r in spec.parameters.get("required", []) if r not in clean]
    if missing:
        return ToolResult(False, f"Chybí parametry: {', '.join(missing)}")
    try:
        res = spec.func(ctx, **clean)
        if inspect.isawaitable(res):
            res = await res
        if isinstance(res, ToolResult):
            return res
        return ToolResult(True, str(res) if res is not None else "hotovo")
    except Exception as e:  # tools never crash the agent
        log.exception("tool %s failed", name)
        return ToolResult(False, f"{type(e).__name__}: {e}")
