"""OMEGA 154 / 178 / 678: what JARVIS sends to AI providers, how much it costs, and the daily limit.

Providers do not report usage while streaming, so tokens are estimated (characters / 4) — always labelled
"odhad". Prices are what the user enters per provider (per 1 million tokens); local models cost nothing.
"""
from __future__ import annotations

import datetime as dt
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (day TEXT, provider TEXT, model TEXT, calls INT, tok_in INT, tok_out INT,
  images INT, PRIMARY KEY (day, provider, model));
"""
CHARS_PER_TOKEN = 4


def _text_chars(messages: list[dict]) -> tuple[int, int]:
    chars = images = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if part.get("type") == "text":
                    chars += len(part.get("text", ""))
                elif part.get("type") == "image_url":
                    images += 1
        for tc in m.get("tool_calls") or []:
            chars += len(str(tc.get("function", {}).get("arguments", "")))
    return chars, images


class Usage:
    def __init__(self, rt):
        self.rt = rt
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)

    def record(self, provider: str, model: str, messages: list[dict], out_chars: int) -> None:
        chars, images = _text_chars(messages)
        day = dt.date.today().isoformat()
        self.rt.db.exec(
            "INSERT INTO llm_usage VALUES (?,?,?,1,?,?,?) ON CONFLICT(day, provider, model) DO UPDATE SET "
            "calls=calls+1, tok_in=tok_in+excluded.tok_in, tok_out=tok_out+excluded.tok_out, images=images+excluded.images",
            (day, provider, model or "", chars // CHARS_PER_TOKEN, out_chars // CHARS_PER_TOKEN, images))

    def day(self, day: str | None = None) -> list[dict]:
        day = day or dt.date.today().isoformat()
        return self.rt.db.all("SELECT * FROM llm_usage WHERE day=? ORDER BY provider", (day,))

    def history(self, days: int = 30) -> list[dict]:
        since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
        return self.rt.db.all("SELECT day, SUM(calls) calls, SUM(tok_in) tok_in, SUM(tok_out) tok_out FROM llm_usage "
                              "WHERE day>=? GROUP BY day ORDER BY day", (since,))

    def price(self, provider: str) -> float:
        from .llm.presets import PRESETS

        cfg = self.rt.cfg
        p = next((x for x in cfg.brain.providers if x.id == provider), None)
        if p is not None and PRESETS.get(p.preset, {}).get("local"):
            return 0.0
        return float(cfg.limits.prices.get(provider, 0.0))

    def cost(self, rows: list[dict]) -> float:
        return sum((r["tok_in"] + r["tok_out"]) / 1e6 * self.price(r["provider"]) for r in rows)

    def today(self) -> dict:
        rows = self.day()
        tokens = sum(r["tok_in"] + r["tok_out"] for r in rows)
        return {"day": dt.date.today().isoformat(), "rows": rows, "tokens": tokens, "cost": round(self.cost(rows), 2),
                "currency": self.rt.cfg.limits.currency, "limit_tokens": self.rt.cfg.limits.ai_daily_tokens,
                "limit_cost": self.rt.cfg.limits.ai_daily_cost, "estimate": True}

    def blocked(self, provider_cfg) -> str:
        """Why this provider must be skipped now ("" = go). Over the limit only free/local providers still answer."""
        lim = self.rt.cfg.limits
        if not (lim.ai_daily_tokens or lim.ai_daily_cost) or self.price(provider_cfg.id) == 0 and not lim.ai_daily_tokens:
            return ""
        t = self.today()
        if lim.ai_daily_cost and t["cost"] >= lim.ai_daily_cost and self.price(provider_cfg.id) > 0:
            return f"denní limit {lim.ai_daily_cost:g} {lim.currency} vyčerpán"
        if lim.ai_daily_tokens and t["tokens"] >= lim.ai_daily_tokens and self.price(provider_cfg.id) > 0:
            return f"denní limit {lim.ai_daily_tokens} tokenů vyčerpán"
        if lim.ai_daily_tokens and t["tokens"] >= lim.ai_daily_tokens * 1.5:
            return "denní limit tokenů vyčerpán (i pro bezplatné)"
        return ""

    def estimate(self, steps: int, provider: str | None = None) -> dict:
        """A rough price of a request with `steps` AI rounds, from today's average per call."""
        rows = self.rt.db.all("SELECT SUM(calls) c, SUM(tok_in) i, SUM(tok_out) o FROM llm_usage")
        r = rows[0] if rows else {}
        calls = r.get("c") or 0
        per_call = ((r.get("i") or 0) + (r.get("o") or 0)) / calls if calls else 3000
        prov = provider or (self.rt.router.last_used[0] if getattr(self.rt.router, "last_used", None) else "")
        tokens = int(per_call * max(1, steps))
        return {"tokens": tokens, "cost": round(tokens / 1e6 * self.price(prov), 3), "currency": self.rt.cfg.limits.currency,
                "provider": prov, "estimate": True, "ts": time.time()}
