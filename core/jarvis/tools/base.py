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
    preview: str = ""   # a page the chat shows live under the answer (make_website)

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
    perm: str | None = None   # permission category (jarvis.permissions); None = derived from category
    details: Callable[[dict], list[str]] | None = None   # preview lines shown in the confirmation dialog

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
         danger_if: Callable[[dict], bool] | None = None, category: str = "obecné", perm: str | None = None,
         details: Callable[[dict], list[str]] | None = None):
    def deco(func):
        REGISTRY[name] = ToolSpec(name, description, func, schema_for(func), danger, danger_if, category,
                                  getattr(func, "__module__", "builtin"), perm, _capped(details) if details else None)
        return func
    return deco


MAX_DETAILS = 50


def cap_details(lines: list[str]) -> list[str]:
    lines = [str(x) for x in lines]
    if len(lines) > MAX_DETAILS:
        return lines[:MAX_DETAILS] + [f"…a dalších {len(lines) - MAX_DETAILS}"]
    return lines


def _hook(fn: Callable, args: dict, ctx: Any = None):
    """danger_if / details hooks take (args) or (args, ctx=...); ctx lets them look things up (e.g. a UI ref's name)."""
    try:
        wants_ctx = "ctx" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        wants_ctx = False
    return fn(args or {}, ctx=ctx) if wants_ctx else fn(args or {})


def _capped(fn: Callable) -> Callable[..., list[str]]:
    def wrapped(args: dict, ctx: Any = None) -> list[str]:
        return cap_details(_hook(fn, args, ctx))
    return wrapped


def details_for(spec: ToolSpec, args: dict, ctx: Any = None) -> list[str]:
    """Preview lines for the confirmation dialog. May touch the disk or git → call it from a worker thread."""
    if not spec.details:
        return []
    try:
        return spec.details(args, ctx)
    except Exception:
        return []


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


def unregister_source(source: str) -> None:
    for k in [k for k, v in REGISTRY.items() if v.source == source]:
        del REGISTRY[k]


NEVER_TRUSTED = {"claude_code", "delete_file"}
# results that carry text written by someone else (e-mails, web pages, files, messages): scanned for hidden orders
UNTRUSTED_OUTPUT = {"email_read", "email_inbox", "email_search", "web_read", "web_search", "google_search", "browser_read",
                    "phone_messages", "read_text_file", "read_attachment", "clipboard_get", "ui_read", "selected_text"}   # always confirmed, even when the user marked them trusted


def is_dangerous(spec: ToolSpec, args: dict, always_confirm: list[str] = (), trusted: list[str] = (),
                 ctx: Any = None) -> bool:
    if spec.name in NEVER_TRUSTED:
        return True
    if spec.name in trusted:
        return False
    if spec.name in always_confirm:
        return True
    if spec.danger_if is not None:
        try:
            return bool(_hook(spec.danger_if, args, ctx))
        except Exception:
            return True
    return spec.danger


def schemas(disabled: list[str] | set[str] = (), cfg: Any = None) -> list[dict]:
    from ..permissions import allowed

    return [s.schema() for s in REGISTRY.values() if s.name not in disabled and (cfg is None or allowed(cfg, s))]


async def call(name: str, args: dict, ctx: Any) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(False, f"Neznámý nástroj: {name}")
    from ..permissions import LABELS, READ_ONLY, blocked_by, perm_of

    cfg = getattr(ctx, "cfg", None)
    off = blocked_by(cfg, spec)
    if off == READ_ONLY:
        return ToolResult(False, "Je zapnutý Režim jen pro čtení – nic neměním (vypne se v Nastavení → Oprávnění).")
    if off:
        return ToolResult(False, f"Oprávnění „{LABELS[off]}“ je vypnuté (Nastavení → Oprávnění).")
    from ..mobileplus import device_blocks
    from ..permissions import required

    dev = device_blocks(required(spec))
    if dev:                                       # OMEGA 419: switched off for requests from the phone
        return ToolResult(False, f"Z telefonu je „{LABELS.get(dev, dev)}“ zakázané (na PC: Nastavení → Telefon). Udělej to přímo na počítači.")
    allow = getattr(getattr(cfg, "limits", None), "app_allowlist", None)
    if allow and perm_of(spec) == "input":         # OMEGA 682: mouse/keyboard only in the allowed apps
        try:
            front = (ctx.platform.foreground_info() or {}).get("app", "")
        except Exception:
            front = ""
        if front and not any(a.lower() in front.lower() for a in allow if a.strip()):
            return ToolResult(False, f"Myš a klávesnici smím použít jen v povolených aplikacích ({', '.join(allow)}); "
                                     f"vpředu je {front}.")
    allowed = set(spec.parameters.get("properties", {}))
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    missing = [r for r in spec.parameters.get("required", []) if r not in clean]
    if missing:
        return ToolResult(False, f"Chybí parametry: {', '.join(missing)}")
    try:
        res = spec.func(ctx, **clean)
        if inspect.isawaitable(res):
            res = await res
        if not isinstance(res, ToolResult):
            res = ToolResult(True, str(res) if res is not None else "hotovo")
        if name in UNTRUSTED_OUTPUT and res.ok:     # OMEGA 183: orders hidden in e-mails, pages and files
            from ..injection import warn

            w = warn(res.summary + " " + (str(res.data)[:20000] if res.data is not None else ""))
            if w:
                res.summary = w + "\n\n" + res.summary
        return res
    except Exception as e:  # tools never crash the agent
        log.exception("tool %s failed", name)
        return ToolResult(False, f"{type(e).__name__}: {e}")
