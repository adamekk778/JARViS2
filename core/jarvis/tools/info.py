from __future__ import annotations

import datetime as dt

from .base import ToolResult, tool

DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


@tool("get_time", "Aktuální datum, čas a den v týdnu.", category="info")
async def get_time(ctx) -> ToolResult:
    n = dt.datetime.now()
    return ToolResult(True, f"{DAYS[n.weekday()]} {n:%d. %m. %Y %H:%M}", data=n.isoformat(timespec="seconds"))
