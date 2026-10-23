from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from .base import ToolResult, tool
from .timers import parse_when


@tool("schedule_task", "Naplánuje úlohu nebo rutinu. JARVIS ji v daný čas sám provede (prompt = co má udělat, např. "
      "'Řekni mi počasí a 3 hlavní zprávy dne'). repeat: once | daily | weekdays | weekly | interval.", category="čas")
async def schedule_task(ctx, prompt: Annotated[str, "co má JARVIS v ten čas udělat"],
                        time: Annotated[str, "HH:MM nebo ISO datum a čas"] = "",
                        repeat: Literal["once", "daily", "weekdays", "weekly", "interval"] = "once",
                        days: Annotated[list[int], "pro weekly: dny 0=po … 6=ne"] = (),
                        interval_minutes: int = 0, title: str = "") -> ToolResult:
    if repeat == "interval":
        spec = {"type": "interval", "minutes": interval_minutes or 60}
    elif repeat == "once":
        spec = {"type": "once", "at": parse_when(time).timestamp()}
    else:
        hhmm = parse_when(time).strftime("%H:%M")
        dd = {"daily": list(range(7)), "weekdays": [0, 1, 2, 3, 4], "weekly": list(days) or [dt.datetime.now().weekday()]}[repeat]
        spec = {"type": "daily", "time": hhmm, "days": dd}
    job = ctx.scheduler.add(spec, "prompt", {"prompt": prompt}, title)
    return ToolResult(True, f"Naplánováno ({job['spec_text']}): {job['title']}", data=job)


@tool("list_scheduled", "Seznam naplánovaných úloh a připomínek.", category="čas")
async def list_scheduled(ctx) -> ToolResult:
    jobs = ctx.scheduler.list()
    return ToolResult(True, f"{len(jobs)} naplánovaných", data=jobs)


@tool("cancel_scheduled", "Zruší naplánovanou úlohu podle id.", category="čas")
async def cancel_scheduled(ctx, id: str) -> ToolResult:  # noqa: A002
    return ToolResult(ctx.scheduler.delete(id), "Zrušeno")
