"""3.16 Nástroje v hlavě (návrhy 9–11): JARVIS knows every one of his ~900 tools at once, without searching.

- The catalog: one line a tool – name, parameters, what it is for – grouped by area (~20 000 tokens). It sits in the
  unchanging part of the instructions, so the AI's prompt cache keeps it (it costs ~a tenth and is read at once).
- use_tool: any tool from the catalog in ONE step ("use_tool printer_control {action: pause}"). JARVIS checks the
  arguments against the tool's real description; when they do not fit, the AI gets the exact description back and
  the tool itself joins the offered ones for the next step. No find_tools round any more.
- A steady set of tools with every message (the everyday ones + use_tool): the tools never change between messages,
  so the cache holds tools + instructions + catalog together. What the words of this message point to goes with the
  changing part (after the cache) as a short hint with the exact parameters.

Only for an AI with a big context and a prompt cache (Claude, OpenAI, Gemini, DeepSeek, Mistral); a small model on
this PC or Groq's free tier (a few thousand tokens a minute) keep the small set + find_tools.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

USE = "use_tool"
DYN = "\n\n## Aktuální situace\n"                 # static instructions above, what changes with each message below
CATALOG_PRESETS = {"anthropic", "openai", "gemini", "deepseek", "mistral"}
_cache: dict[str, str] = {}


def _first_sentence(text: str, n: int = 90) -> str:
    t = re.split(r"(?<=[.!?:;])\s", (text or "").strip(), maxsplit=1)[0]
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def params_of(schema: dict) -> dict:
    fn = schema.get("function") or schema
    return fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}}


def signature(name: str, schema: dict, desc_len: int = 90) -> str:
    """"printer_control(action?, file?) – 3D tiskárna …" (? = may be left out)."""
    p = params_of(schema)
    req = set(p.get("required") or [])
    args = [k + ("" if k in req else "?") for k in (p.get("properties") or {})]
    fn = schema.get("function") or schema
    return f"{name}({', '.join(args)}) – {_first_sentence(fn.get('description') or '', desc_len)}"


def catalog(registry: dict, allowed: set[str]) -> str:
    """Every allowed tool, one line each, grouped by category (the same text for the same tools → the cache holds)."""
    names = sorted(n for n in allowed if n in registry and n not in (USE, "find_tools"))
    key = hashlib.sha1("\n".join(names).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    groups: dict[str, list[str]] = {}
    for n in names:
        spec = registry[n]
        groups.setdefault(spec.category or "obecné", []).append(signature(n, spec.schema()))
    lines = ["## Všechny tvoje nástroje",
             "Každý nástroj z tohoto seznamu můžeš použít hned: ty, které nemáš mezi nástroji, zavolej přes use_tool "
             "(name = jméno, args = parametry jako objekt). Nic nehledej, vyber podle seznamu. ? = nepovinný parametr."]
    for cat in sorted(groups):
        lines.append(f"### {cat}")
        lines += groups[cat]
    text = "\n".join(lines)
    if len(_cache) > 8:
        _cache.clear()
    _cache[key] = text
    return text


def hint(registry: dict, names: list[str]) -> str:
    """The exact parameters of the tools this message most likely needs (in the changing part, after the cache)."""
    out = []
    for n in names:
        spec = registry.get(n)
        if spec is None or n in (USE, "find_tools"):
            continue
        p = params_of(spec.schema())
        props = p.get("properties") or {}
        req = set(p.get("required") or [])
        ps = []
        for k, v in props.items():
            t = v.get("type", "")
            d = (v.get("description") or "")[:70]
            en = f" ∈ {'|'.join(map(str, v['enum']))}" if v.get("enum") else ""
            ps.append(f"{k}{'' if k in req else '?'}: {t}{en}{(' – ' + d) if d else ''}")
        out.append(f"- {n}: " + ("; ".join(ps) if ps else "bez parametrů"))
    if not out:
        return ""
    return ("Pro tuto zprávu se nejspíš hodí (zavolej přes use_tool, pokud nejsou mezi nástroji):\n" + "\n".join(out))


def wants_catalog(preset: str, mode: str = "auto", limited: bool = False) -> bool:
    if mode == "off":
        return False
    if mode == "on":
        return not limited and preset not in ("ollama", "lmstudio")
    return preset in CATALOG_PRESETS and not limited


@dataclass
class Pack:
    """What the router sends to an AI that gets the catalog (instead of the small per-message tool set)."""
    catalog: str
    tools: list[dict]                           # the steady set (everyday tools + use_tool)
    hint: str = ""
    names: set[str] = field(default_factory=set)

    def apply(self, messages: list[dict]) -> list[dict]:
        """The catalog into the unchanging part of the instructions, the hint into the changing part."""
        if not messages or messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str):
            return messages
        sysm = messages[0]["content"]
        static, dyn = (sysm.split(DYN, 1) + [""])[:2] if DYN in sysm else (sysm, "")
        new = static + "\n\n" + self.catalog + DYN + dyn + (("\n\n" + self.hint) if self.hint else "")
        return [{**messages[0], "content": new}, *messages[1:]]


# ------------------------------------------------------------------------------------------ use_tool
def _type_ok(v: Any, t: str) -> bool:
    return {"string": isinstance(v, str), "integer": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": isinstance(v, bool),
            "array": isinstance(v, list), "object": isinstance(v, dict)}.get(t, True)


def coerce(args: dict, schema: dict) -> dict:
    """Small fixes models make: "5" for a number, "true" for a yes/no, one item for a list."""
    props = params_of(schema).get("properties") or {}
    out = dict(args)
    for k, v in args.items():
        t = (props.get(k) or {}).get("type")
        try:
            if t in ("integer", "number") and isinstance(v, str) and re.fullmatch(r"-?\d+([.,]\d+)?", v.strip()):
                f = float(v.replace(",", "."))
                out[k] = int(f) if t == "integer" and f.is_integer() else f
            elif t == "boolean" and isinstance(v, str) and v.lower() in ("true", "false", "ano", "ne"):
                out[k] = v.lower() in ("true", "ano")
            elif t == "array" and not isinstance(v, list) and v is not None:
                out[k] = [v]
            elif t == "integer" and isinstance(v, float) and v.is_integer():
                out[k] = int(v)
        except (ValueError, AttributeError):
            pass
    return out


def check(args: dict, schema: dict) -> list[str]:
    """What is wrong with the arguments ([] = fine)."""
    p = params_of(schema)
    props = p.get("properties") or {}
    errs = [f"chybí povinný parametr „{k}“" for k in p.get("required") or [] if k not in args]
    for k, v in args.items():
        if k not in props:
            close = difflib.get_close_matches(k, list(props), n=1)
            errs.append(f"neznámý parametr „{k}“" + (f" (myslel jsi „{close[0]}“?)" if close else ""))
            continue
        spec = props[k]
        if spec.get("type") and v is not None and not _type_ok(v, spec["type"]):
            errs.append(f"„{k}“ má být {spec['type']}, ne {type(v).__name__}")
        if spec.get("enum") and v not in spec["enum"]:
            errs.append(f"„{k}“ musí být jedno z: {', '.join(map(str, spec['enum']))}")
    return errs


@dataclass
class Unwrapped:
    name: str
    args: dict
    error: str = ""                     # set when the call cannot run (unknown tool / wrong arguments)


def unwrap(registry: dict, allowed: set[str], raw_args: Any) -> Unwrapped:
    """use_tool's arguments → the real tool and its checked arguments."""
    a = raw_args if isinstance(raw_args, dict) else {}
    name = str(a.get("name") or a.get("tool") or "").strip()
    inner = a.get("args", a.get("arguments", {}))
    if isinstance(inner, str):
        try:
            inner = json.loads(inner or "{}")
        except ValueError:
            return Unwrapped(name, {}, "args musí být objekt JSON, např. {\"action\": \"pause\"}")
    if not isinstance(inner, dict):
        inner = {}
    if name not in registry or name not in allowed or name in (USE,):
        close = difflib.get_close_matches(name, [n for n in allowed if n in registry], n=3, cutoff=0.5)
        why = "je vypnutý" if name in registry else "neexistuje"
        return Unwrapped(name, inner, f"Nástroj „{name}“ {why}." + (f" Podobné: {', '.join(close)}." if close else ""))
    schema = registry[name].schema()
    inner = coerce(inner, schema)
    errs = check(inner, schema)
    if errs:
        exact = json.dumps(params_of(schema), ensure_ascii=False)[:1500]
        return Unwrapped(name, inner, f"Parametry pro {name} nesedí: {'; '.join(errs)}. Přesný popis parametrů: {exact}")
    return Unwrapped(name, inner)
