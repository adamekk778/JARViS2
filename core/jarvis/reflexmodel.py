"""3.16 Místní reflexní model (návrh 19): a small, fast model on this PC (Ollama, e.g. qwen3:1.7b on the graphics
card: ~0.2–0.5 s) decides the clear commands – which tool and with what – before the big AI is asked at all.

It sees only the ~30 tools that fit the words (the selector + memory), answers in JSON with how sure it is, and is
used only when it is very sure, the tool is harmless and its own words are the whole answer ("Pouštím …", "Hlasitost
40 %", "Rozsvíceno."). Anything else – a question, a conversation, something risky, a doubt – goes to the big AI as
before. Off until you pick the model (Nastavení → Mozek → Reflexní model).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SYSTEM = ("Jsi rychlý rozcestník asistenta JARVIS. Dostaneš větu uživatele a seznam nástrojů. Když je věta JASNÝ povel, "
          "který jde splnit jedním nástrojem ze seznamu, vyber ho a vyplň parametry. Otázky, rozhovor, nejasné nebo složené "
          "věci → tool null. Odpověz jen JSON: {\"tool\": \"jméno\" nebo null, \"args\": {...}, \"confidence\": 0.0–1.0}.")
TIMEOUT_S = 1.5
MAX_WORDS = 16


def enabled(rt: Any) -> str:
    """The model's name when the reflex model is on (else '')."""
    return str(getattr(rt.cfg.brain, "reflex_model", "") or "").strip()


def ollama_base(rt: Any) -> str:
    for p in rt.cfg.brain.providers:
        if p.preset == "ollama" and p.base_url:
            return p.base_url.rstrip("/")
    return "http://localhost:11434"


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    tool = d.get("tool")
    try:
        conf = float(d.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    args = d.get("args") if isinstance(d.get("args"), dict) else {}
    return {"tool": tool if isinstance(tool, str) and tool and tool.lower() != "null" else None, "args": args,
            "confidence": max(0.0, min(1.0, conf))}


async def ask(rt: Any, model: str, text: str, lines: list[str], transport: Any = None) -> str:
    """One quick question to the local model (raw text of its answer)."""
    from .llm import pool

    body = {"model": model, "stream": False, "format": "json", "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 160},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "Nástroje:\n" + "\n".join(lines) + f"\n\nVěta: {text}"}]}
    async with pool.client(transport, TIMEOUT_S, True, trust_env=False) as c:
        r = await c.post(ollama_base(rt) + "/api/chat", json=body, timeout=TIMEOUT_S)
    r.raise_for_status()
    return str(((r.json() or {}).get("message") or {}).get("content") or "")


async def route(rt: Any, text: str, candidates: list[str], ok_tool, transport: Any = None) -> tuple[str, dict] | None:
    """(tool, args) to do right away, or None. ok_tool(name, args) says whether the tool may go without the AI."""
    model = enabled(rt)
    if not model or not text or len(text.split()) > MAX_WORDS:
        return None
    from . import tools
    from . import toolcatalog as tc

    names = [n for n in candidates if n in tools.REGISTRY][:30]
    if not names:
        return None
    lines = [tc.signature(n, tools.REGISTRY[n].schema(), 70) for n in names]
    try:
        raw = await ask(rt, model, text, lines, transport)
    except Exception as e:  # noqa: BLE001 – not running / too slow: the big AI answers as usual
        log.debug("reflex model: %s", e)
        return None
    d = parse(raw)
    if not d["tool"] or d["tool"] not in names or d["confidence"] < float(getattr(rt.cfg.brain, "reflex_min_conf", 0.85)):
        return None
    u = tc.unwrap(tools.REGISTRY, set(names), {"name": d["tool"], "args": d["args"]})
    if u.error or not ok_tool(u.name, u.args):
        return None
    return u.name, u.args
