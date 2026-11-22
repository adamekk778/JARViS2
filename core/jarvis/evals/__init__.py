"""Quality evals (návrh 5): ~300 real Czech requests with the expected result, so every version gets a score.

Offline (no AI, runs in CI): the instant commands catch what they should and nothing else, and the tool selector
sends the right tool with each request. Live (`--live`, uses your configured AIs): the AI itself is asked each PICK
request with no tool really run, and its first tool call is compared – per AI, so you see which one is best.

    python -m jarvis.evals --offline              # the CI gate
    python -m jarvis.evals --live --limit 60      # ask the AIs (costs requests on paid keys)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .cases import INSTANT, NOT_INSTANT, PICK


@dataclass
class Score:
    name: str
    total: int = 0
    ok: int = 0
    misses: list[str] = field(default_factory=list)

    def add(self, good: bool, label: str) -> None:
        self.total += 1
        if good:
            self.ok += 1
        else:
            self.misses.append(label)

    @property
    def rate(self) -> float:
        return self.ok / self.total if self.total else 1.0

    def public(self) -> dict:
        return {"name": self.name, "total": self.total, "ok": self.ok, "rate": round(self.rate, 3), "misses": self.misses[:40]}


def eval_instant() -> list[Score]:
    from .. import instant

    caught, left = Score("Okamžité příkazy"), Score("Ostatní jde k AI")
    for text, tool in INSTANT:
        p = instant.plan(text)
        caught.add(bool(p and p.calls and p.calls[0][0] == tool), f"{text!r} → {p.calls[0][0] if p and p.calls else 'AI'} (čekáno {tool})")
    for text in NOT_INSTANT:
        p = instant.plan(text)
        left.add(p is None, f"{text!r} zachytil okamžitý příkaz {p.calls[0][0] if p else ''}")
    return [caught, left]


def eval_pick() -> Score:
    from .. import config, tools
    from ..tools import select

    tools.load_builtin()
    cfg = config.Config()
    from ..permissions import allowed as perm_allowed

    allowed = {n for n, s in tools.REGISTRY.items() if perm_allowed(cfg, s)}
    sc = Score("Výběr nástrojů")
    for text, want in PICK:
        missing = [w for w in want if w not in tools.REGISTRY]
        if len(missing) == len(want):
            sc.add(False, f"{text!r}: nástroj {want} neexistuje")
            continue
        got = select.pick(tools.REGISTRY, allowed, text, [])
        sc.add(any(w in got for w in want), f"{text!r} → chybí {'/'.join(want)}")
    return sc


def offline() -> dict:
    scores = [*eval_instant(), eval_pick()]
    total = sum(s.total for s in scores)
    ok = sum(s.ok for s in scores)
    return {"mode": "offline", "score": round(ok / total, 3) if total else 1.0, "cases": total,
            "parts": [s.public() for s in scores]}


# ---------- live: the AIs themselves ----------
async def _first_call(rt: Any, text: str, only: str | None) -> str:
    from ..prompt import build_system_prompt

    msgs = [{"role": "system", "content": build_system_prompt(rt.cfg, [], False, "")}, {"role": "user", "content": text}]
    schemas = rt.agent._tool_schemas(text)
    async for ch in rt.router.stream(msgs, schemas, **({"only": only} if only else {})):
        if ch.tool_calls:
            return ch.tool_calls[0].name
        if ch.done:
            break
    return ""


async def live(rt: Any, limit: int = 60, providers: list[str] | None = None) -> dict:
    """Each PICK request to each AI (no tool is really run): did it reach for the right tool first?"""
    cases = PICK[:limit]
    provs = providers or [p.id for p in rt.cfg.brain.providers if p.enabled and p.id in rt.cfg.brain.chain]
    out = []
    for pid in provs:
        sc = Score(pid)
        t0 = time.monotonic()
        for text, want in cases:
            try:
                name = await asyncio.wait_for(_first_call(rt, text, pid), 60)
            except Exception as e:  # noqa: BLE001 – a failed request counts as a miss with its reason
                name = f"chyba: {str(e)[:60]}"
            sc.add(name in want, f"{text!r} → {name or 'bez nástroje'} (čekáno {'/'.join(want)})")
        d = sc.public()
        d["seconds"] = round(time.monotonic() - t0, 1)
        out.append(d)
    out.sort(key=lambda d: -d["rate"])
    return {"mode": "live", "cases": len(cases), "providers": out, "best": out[0]["name"] if out else ""}
