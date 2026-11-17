"""3.12 Todoist: úkoly na dnes, po termínu, podle filtru; přidat nebo odškrtnout úkol (s potvrzením). API v1."""
from __future__ import annotations

import re
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.todoist.com/api/v1"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("todoist")
    return await call(method, API + path, json=body, params=params or None, transport=transport,
                      headers={"Authorization": f"Bearer {value('todoist', 'token')}"})


async def _all(path: str, **params) -> list[dict]:
    out, cursor = [], None
    for _ in range(10):
        r = await _api("GET", path, **params, **({"cursor": cursor} if cursor else {}))
        out += r.get("results", []) if isinstance(r, dict) else (r or [])
        cursor = r.get("next_cursor") if isinstance(r, dict) else None
        if not cursor:
            break
    return out


async def _test(rt: Any) -> str:
    ps = await _all("/projects")
    return f"Propojeno – {len(ps)} projektů."


register("todoist", "Todoist (úkoly)", "check-square", [
    {"key": "token", "label": "API token", "secret": True, "hint": "40 znaků"},
], [
    "V Todoistu: Nastavení → Integrace → Pro vývojáře → API token.",
    "Zkopíruj ho sem a ulož.",
], url="https://app.todoist.com/app/settings/integrations/developer", what="Úkoly na dnes, po termínu a podle filtru; přidat a odškrtnout s potvrzením.",
    test=_test, group="tasks", probe={"method": "GET", "url": API + "/projects", "headers": {"Authorization": "Bearer FAKE"}})


@tool("todoist_tasks", "Todoist: úkoly podle filtru (výchozí: dnes a po termínu).", category="propojení", perm="network")
@guarded
async def tasks(ctx, filter: Annotated[str, "filtr Todoistu, např. „today | overdue“, „7 days“, „#Práce“, „p1“"] = "today | overdue") -> ToolResult:
    projects = {p["id"]: p.get("name") for p in await _all("/projects")}
    items = await _all("/tasks/filter", query=filter or "today | overdue")
    out = [{"id": t.get("id"), "task": t.get("content"), "due": (t.get("due") or {}).get("date"), "project": projects.get(t.get("project_id")),
            "priority": 5 - int(t.get("priority") or 1), "note": (t.get("description") or "")[:200]} for t in items]
    return ToolResult(True, f"{len(out)} úkolů.", data=out)


@tool("todoist_add", "Todoist: přidá úkol (termín slovy, např. „zítra v 9“). Zeptá se uživatele.", danger=True, category="propojení",
      perm="network", details=lambda a: [f"Úkol: {a.get('task', '')}", f"Termín: {a.get('due', '') or '–'}", f"Projekt: {a.get('project', '') or 'Doručené'}"])
@guarded
async def add(ctx, task: Annotated[str, "úkol"], due: Annotated[str, "termín: 2026-11-20, 2026-11-20T09:00 nebo anglicky slovy (tomorrow 9am)"] = "",
              project: Annotated[str, "projekt (nepovinné)"] = "", priority: Annotated[int, "priorita 1 (nejvyšší) – 4"] = 4) -> ToolResult:
    body: dict[str, Any] = {"content": task, "priority": 5 - max(1, min(int(priority or 4), 4))}
    d = due.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        body["due_date"] = d
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}(:\d{2})?", d):
        body["due_datetime"] = (d.replace(" ", "T") + (":00" if d.count(":") == 1 else ""))
    elif d:
        body["due_string"] = d
    if project:
        pid = next((p["id"] for p in await _all("/projects") if project.lower() in (p.get("name") or "").lower()), None)
        if pid:
            body["project_id"] = pid
    t = await _api("POST", "/tasks", body)
    return ToolResult(True, f"Úkol „{task}“ je v Todoistu.", data={"id": t.get("id")})


@tool("todoist_done", "Todoist: odškrtne (dokončí) úkol podle id. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Dokončit úkol: {a.get('task_id', '')}"])
@guarded
async def done(ctx, task_id: Annotated[str, "id úkolu z todoist_tasks"]) -> ToolResult:
    await _api("POST", f"/tasks/{task_id}/close")
    return ToolResult(True, "Úkol je odškrtnutý.")
