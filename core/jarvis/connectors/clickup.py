"""3.12 ClickUp: moje úkoly ve všech workspacech; nový úkol s potvrzením. Personal API token (pk_…)."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.clickup.com/api/v2"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("clickup")
    return await call(method, API + path, json=body, params=params or None, transport=transport,
                      headers={"Authorization": value("clickup", "token")})


async def _test(rt: Any) -> str:
    u = (await _api("GET", "/user")).get("user") or {}
    return f"Přihlášeno jako {u.get('username', '?')}."


register("clickup", "ClickUp", "check-circle", [
    {"key": "token", "label": "Personal API token", "secret": True, "hint": "pk_…"},
], [
    "V ClickUpu: avatar → Settings → Apps → API Token → Generate.",
    "Zkopíruj token (pk_…) sem a ulož.",
], url="https://app.clickup.com/settings/apps", what="Moje úkoly (stav, termín, seznam); nový úkol jen s potvrzením.", test=_test,
    group="tasks", probe={"method": "GET", "url": API + "/user", "headers": {"Authorization": "pk_FAKE"}})


def _ms(v: Any) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000).strftime("%Y-%m-%d %H:%M") if v else None
    except (TypeError, ValueError):
        return None


@tool("clickup_tasks", "ClickUp: moje otevřené úkoly (stav, termín, seznam).", category="propojení", perm="network")
@guarded
async def tasks(ctx) -> ToolResult:
    me = (await _api("GET", "/user")).get("user") or {}
    out = []
    for team in (await _api("GET", "/team")).get("teams", [])[:3]:
        r = await _api("GET", f"/team/{team['id']}/task", **{"assignees[]": me.get("id"), "subtasks": "true", "order_by": "due_date"})
        out += [{"id": t.get("id"), "task": t.get("name"), "status": (t.get("status") or {}).get("status"), "due": _ms(t.get("due_date")),
                 "list": (t.get("list") or {}).get("name"), "list_id": (t.get("list") or {}).get("id"), "url": t.get("url"),
                 "workspace": team.get("name")} for t in r.get("tasks", [])]
    return ToolResult(True, f"{len(out)} úkolů.", data=out)


@tool("clickup_task_create", "ClickUp: založí úkol v seznamu (list_id najdeš u úkolů). Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=lambda a: [f"Seznam: {a.get('list_id', '')}", f"Úkol: {a.get('name', '')}"])
@guarded
async def task_create(ctx, list_id: Annotated[str, "id seznamu (list_id z clickup_tasks)"], name: Annotated[str, "úkol"],
                      description: Annotated[str, "popis"] = "", due: Annotated[str, "termín YYYY-MM-DD"] = "") -> ToolResult:
    body: dict[str, Any] = {"name": name, "description": description}
    if due:
        body["due_date"] = int(dt.datetime.fromisoformat(due[:10] + "T12:00:00").timestamp() * 1000)
    t = await _api("POST", f"/list/{list_id}/task", body)
    return ToolResult(True, f"Úkol „{name}“ je v ClickUpu.", data={"url": t.get("url")})
