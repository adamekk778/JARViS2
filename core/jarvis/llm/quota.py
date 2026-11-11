"""3.12 How much of today's free AI is left – shown next to the AI's logo in the notch ("Groq · 70 %").

Two sources: what the provider says in its answer headers (Groq: requests left today), and JARVIS's own count of
today's tokens against the free tier's daily allowance. The lower of the two is shown – it is an estimate.
"""
from __future__ import annotations

import time

# free tier per day (2026): tokens and requests; Groq counts each model separately
TPD = {"openai/gpt-oss-120b": 200_000, "openai/gpt-oss-20b": 200_000, "llama-3.3-70b-versatile": 100_000,
       "moonshotai/kimi-k2-instruct-0905": 300_000, "qwen/qwen3-32b": 500_000,
       "meta-llama/llama-4-scout-17b-16e-instruct": 500_000, "llama-3.1-8b-instant": 500_000}
RPD = {"gemini-2.5-flash": 250, "gemini-2.5-flash-lite": 1000, "gemini-2.5-pro": 100}
LABEL = {"groq": "Groq", "gemini": "Gemini", "openrouter": "OpenRouter", "openai": "OpenAI", "anthropic": "Claude"}


class Quota:
    def __init__(self):
        self.headers: dict[tuple[str, str], dict] = {}     # (provider, model) → what its last answer said

    def from_headers(self, provider: str, model: str, h) -> None:
        """x-ratelimit-limit-requests / x-ratelimit-remaining-requests = requests per day (Groq)."""
        try:
            lim = int(h.get("x-ratelimit-limit-requests") or 0)
            left = int(h.get("x-ratelimit-remaining-requests") or 0)
        except (TypeError, ValueError):
            return
        if lim > 0:
            self.headers[(provider, model)] = {"req_limit": lim, "req_left": max(0, left), "at": time.time()}

    def left_pct(self, provider: str, preset: str, model: str, used_today: int, calls_today: int) -> int | None:
        """0–100 % of today's free allowance left, or None when nothing is known (paid, local, unknown model)."""
        vals = []
        h = self.headers.get((provider, model))
        if h and time.time() - h["at"] < 6 * 3600:
            vals.append(100 * h["req_left"] / h["req_limit"])
        if preset == "groq" and model in TPD:
            vals.append(100 * (1 - used_today / TPD[model]))
        if preset == "gemini" and model in RPD and not h:
            vals.append(100 * (1 - calls_today / RPD[model]))
        if not vals:
            return None
        return max(0, min(100, round(min(vals))))


def today_for(rt, provider: str, model: str) -> tuple[int, int]:
    """(tokens, calls) JARVIS counted today for this provider + model (the usage ledger estimates ~4 chars/token, so
    ×1.3 to be on the careful side for Czech)."""
    try:
        rows = [r for r in rt.usage.day() if r["provider"] == provider and (r["model"] or "") == (model or "")]
    except Exception:  # noqa: BLE001
        return 0, 0
    return int(sum(r["tok_in"] + r["tok_out"] for r in rows) * 1.3), sum(r["calls"] for r in rows)


def brain_state(rt) -> dict:
    """What the notch shows next to the AI's logo: provider, model, % left today (when known)."""
    last = getattr(rt.router, "last_used", None)
    if not last:
        return {}
    pid, model = last
    q = getattr(rt.router, "quota", None)
    left = None
    if q is not None:                       # never let the "% left" get in the way of an answer
        try:
            pcfg = next((p for p in rt.cfg.brain.providers if p.id == pid), None)
            used, calls = today_for(rt, pid, model)
            left = q.left_pct(pid, pcfg.preset if pcfg else "", model, used, calls)
        except Exception:  # noqa: BLE001
            left = None
    return {"provider": pid, "model": model, "left": left}
