from __future__ import annotations

import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


@tool("set_timer", "Nastaví časovač (minutka). Ozve se hlasem, v notchi a na telefonu.", category="čas")
async def set_timer(ctx, seconds: Annotated[int, "délka v sekundách"], label: str = "Časovač") -> ToolResult:
    t = ctx.timers.add(seconds, label)
    m, s = divmod(seconds, 60)
    return ToolResult(True, f"Časovač {label} na {m} min {s} s" if m else f"Časovač {label} na {s} s", data=t)


@tool("list_timers", "Seznam běžících časovačů.", category="čas")
async def list_timers(ctx) -> ToolResult:
    return ToolResult(True, f"{len(ctx.timers.list())} časovačů", data=ctx.timers.list())


@tool("cancel_timer", "Zruší časovač (podle id nebo názvu, prázdné = všechny).", category="čas")
async def cancel_timer(ctx, id_or_label: str = "") -> ToolResult:  # noqa: A002
    n = ctx.timers.cancel(id_or_label)
    return ToolResult(n > 0, f"Zrušeno: {n}")


def parse_when(when: str) -> dt.datetime:
    now = dt.datetime.now()
    w = when.strip()
    for fmt in ("%H:%M", "%H.%M"):
        try:
            t = dt.datetime.strptime(w, fmt).time()
            d = dt.datetime.combine(now.date(), t)
            return d if d > now else d + dt.timedelta(days=1)
        except ValueError:
            pass
    return dt.datetime.fromisoformat(w)


@tool("set_reminder", "Připomínka na konkrétní čas ('18:30' nebo ISO '2026-10-24T09:00'). Ozve se hlasem a na telefonu.",
      category="čas")
async def set_reminder(ctx, text: str, when: Annotated[str, "HH:MM nebo ISO datum a čas"]) -> ToolResult:
    at = parse_when(when)
    job = ctx.scheduler.add_once(at, kind="notify", payload={"title": "Připomínka", "body": text})
    return ToolResult(True, f"Připomenu {at:%d.%m. %H:%M}: {text}", data=job)
