"""3.12 Asana: moje úkoly (termíny, projekty); nový úkol s potvrzením. Personal access token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://app.asana.com/api/1.0"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("asana")
    r = await call(method, API + path, json={"data": body} if body is not None else None, params=params or None, transport=transport,
                   headers={"Authorization": f"Bearer {value('asana', 'token')}"})
    return r.get("data", r) if isinstance(r, dict) else r


async def _me() -> dict:
    return await _api("GET", "/users/me", opt_fields="name,workspaces.name")


async def _test(rt: Any) -> str:
    me = await _me()
    return f"Přihlášeno jako {me.get('name')} ({', '.join(w['name'] for w in me.get('workspaces', []))})."


register("asana", "Asana (úkoly a projekty)", "list-checks", [
    {"key": "token", "label": "Personal access token", "secret": True, "hint": "2/…"},
], [
    "V Asaně: profil → My settings → Apps → Developer apps (nebo app.asana.com/0/my-apps) → Create new token.",
    "Zkopíruj token sem a ulož.",
], url="https://app.asana.com/0/my-apps", what="Moje nedokončené úkoly s termíny a projekty; nový úkol jen s potvrzením.", test=_test,
    group="tasks", probe={"method": "GET", "url": API + "/users/me", "headers": {"Authorization": "Bearer FAKE"}})


@tool("asana_tasks", "Asana: moje nedokončené úkoly (termín, projekt).", category="propojení", perm="network")
@guarded
async def tasks(ctx) -> ToolResult:
    me = await _me()
    out = []
    for w in me.get("workspaces", [])[:3]:
        ts = await _api("GET", "/tasks", assignee="me", workspace=w["gid"], completed_since="now", limit=100,
                        opt_fields="name,due_on,projects.name,permalink_url")
        out += [{"task": t.get("name"), "due": t.get("due_on"), "project": ", ".join(p["name"] for p in t.get("projects", [])),
                 "workspace": w["name"], "url": t.get("permalink_url")} for t in ts]
    out.sort(key=lambda t: t["due"] or "9999")
    return ToolResult(True, f"{len(out)} úkolů.", data=out)


@tool("asana_task_create", "Asana: založí úkol (přiřazený mně). Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Úkol: {a.get('name', '')}", f"Termín: {a.get('due', '') or '–'}", *str(a.get("notes", "")).splitlines()[:10]])
@guarded
async def task_create(ctx, name: Annotated[str, "úkol"], due: Annotated[str, "termín YYYY-MM-DD"] = "", notes: Annotated[str, "popis"] = "") -> ToolResult:
    me = await _me()
    w = (me.get("workspaces") or [{}])[0]
    body: dict[str, Any] = {"name": name, "notes": notes, "assignee": "me", "workspace": w.get("gid")}
    if due:
        body["due_on"] = due[:10]
    t = await _api("POST", "/tasks", body)
    return ToolResult(True, f"Úkol „{name}“ je v Asaně.", data={"url": t.get("permalink_url")})
