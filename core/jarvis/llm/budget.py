"""Fitting a request into a provider's per-minute token limit (Groq's free tier: 6 000–30 000 tokens a minute per
model, and the answer's max_tokens counts too).

A normal task with some chat history was ~10 000 tokens – over the 8 000 of Groq's best model, so Groq refused it as
"too large" and JARVIS ended with "limit". Now, for a provider with a known limit, the request is made to fit: a
smaller answer reserve, short tool descriptions, long tool results cut, the oldest chat turns left out (the current
task always stays whole). If it still does not fit, the router picks a model with a bigger limit.
"""
from __future__ import annotations

import json
import re

# Groq's free-tier tokens per minute (2026); a "Limit N" from Groq's own error message overrides these
GROQ_TPM = {"openai/gpt-oss-120b": 8000, "openai/gpt-oss-20b": 8000, "llama-3.3-70b-versatile": 12000,
            "moonshotai/kimi-k2-instruct-0905": 10000, "qwen/qwen3-32b": 6000,
            "meta-llama/llama-4-scout-17b-16e-instruct": 30000, "llama-3.1-8b-instant": 6000}
ANSWER_RESERVE = 1024        # max_tokens for a provider with a small limit (Groq counts it before answering)
HEADROOM = 0.88              # stay this far under the limit (the estimate is rough)


def estimate(messages: list[dict], tools: list[dict] | None) -> int:
    """Rough tokens of a request: ~3 characters a token for Czech JSON (images count ~800)."""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                n += 2400 if p.get("type") == "image_url" else len(p.get("text", ""))
            n += len(json.dumps({k: v for k, v in m.items() if k != "content"}, ensure_ascii=False))
        else:
            n += len(json.dumps(m, ensure_ascii=False))
    if tools:
        n += len(json.dumps(tools, ensure_ascii=False))
    return n // 3 + 20


def limit_from_error(text: str) -> int | None:
    """Groq: "... on tokens per minute (TPM): Limit 8000, Requested 10350" → 8000 (never the per-day limit)."""
    m = re.search(r"tokens per minute[^:]*:\s*Limit\s+(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def requested_from_error(text: str) -> int | None:
    """Groq: "... Limit 8000, Used 0, Requested 10350" → 10350."""
    m = re.search(r"Requested\s+(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    dot = cut.rfind(". ")
    return cut[: dot + 1] if dot > n * 0.5 else cut.rstrip() + "…"


def compact_tools(tools: list[dict]) -> list[dict]:
    """The same tools with short descriptions (first sentence; parameters a few words)."""
    out = []
    for t in tools:
        f = dict(t.get("function", t))
        f["description"] = _short(f.get("description", ""), 110)
        params = json.loads(json.dumps(f.get("parameters") or {}))
        for p in (params.get("properties") or {}).values():
            if isinstance(p, dict) and "description" in p:
                p["description"] = _short(str(p["description"]), 50)
        f["parameters"] = params
        out.append({"type": "function", "function": f} if "function" in t else f)
    return out


def _cut_tool_results(messages: list[dict], n: int) -> list[dict]:
    out = []
    for m in messages:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > n:
            m = {**m, "content": m["content"][:n] + "…(zkráceno kvůli limitu AI)"}
        out.append(m)
    return out


def fit(messages: list[dict], tools: list[dict] | None, limit: int, max_tokens: int) -> tuple[list[dict], list[dict] | None, int]:
    """(messages, tools, max_tokens) that fit `limit` tokens – as close to the original as possible."""
    mt = min(max_tokens, ANSWER_RESERVE)
    room = int(limit * HEADROOM) - mt
    if estimate(messages, tools) <= room:
        return messages, tools, mt
    tools = compact_tools(tools) if tools else tools
    msgs = _cut_tool_results(messages, 2500)
    last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=len(msgs) - 1)
    # the oldest chat turns go first; the system prompt and the current task (last question + its steps) stay
    while estimate(msgs, tools) > room and last_user > 1:
        msgs = msgs[:1] + msgs[2:]
        last_user -= 1
    for n in (1200, 500):
        if estimate(msgs, tools) <= room:
            break
        msgs = _cut_tool_results(msgs, n)
    return msgs, tools, mt
