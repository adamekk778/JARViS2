"""update_plan: the model announces the steps of a multi-step task so the user can follow them (spec §4.2)."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("update_plan", "Ukáže uživateli plán vícekrokového úkolu a průběh: zavolej na začátku se seznamem kroků a pak "
      "po každém dokončeném kroku znovu se stejným seznamem a novým indexem current. Nic neprovádí.",
      category="info", perm="apps")
async def update_plan(ctx, steps: Annotated[list[str], "kroky úkolu, krátce česky"],
                      current: Annotated[int, "index kroku, na kterém se právě pracuje (0 = první)"] = 0,
                      note: Annotated[str, "poznámka k aktuálnímu kroku"] = "") -> ToolResult:
    tasks = getattr(ctx, "tasks", None)
    if tasks is not None:
        tasks.set_plan(steps, current, note)
    total = len(steps)
    return ToolResult(True, f"Plán: krok {min(current + 1, total)}/{total}" if total else "Plán vyprázdněn")
