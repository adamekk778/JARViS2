"""3.12 Toggl Track: kolik času jsem na čem strávil (dnes, týden), co právě běží; spustit/zastavit stopky s potvrzením."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.track.toggl.com/api/v9"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("toggl")
    return await call(method, API + path, json=body, params=params or None, transport=transport, auth=(value("toggl", "token"), "api_token"))


async def _test(rt: Any) -> str:
    me = await _api("GET", "/me")
    return f"Přihlášeno jako {me.get('fullname', '?')}."


register("toggl", "Toggl Track (čas)", "timer", [
    {"key": "token", "label": "API token", "secret": True, "hint": "32 znaků"},
], [
    "V Togglu: Profile settings → dole „API Token“ → zkopíruj.",
    "Vlož ho sem a ulož.",
], url="https://track.toggl.com/profile", what="Kolik času na čem (dnes, týden), co právě běží; stopky jen s potvrzením.", test=_test,
    group="tasks", probe={"method": "GET", "url": API + "/me", "auth": ["FAKE", "api_token"]})


@tool("toggl_report", "Toggl: kolik času na čem za posledních N dní (podle projektů) a co právě běží.", category="propojení", perm="network")
@guarded
async def report(ctx, days: Annotated[int, "kolik dní zpět (1 = dnes)"] = 1) -> ToolResult:
    today = dt.date.today()
    start = today - dt.timedelta(days=max(1, int(days or 1)) - 1)
    entries = await _api("GET", "/me/time_entries", start_date=start.isoformat(), end_date=(today + dt.timedelta(days=1)).isoformat())
    projects = {p["id"]: p["name"] for p in (await _api("GET", "/me/projects") or [])}
    now = dt.datetime.now(dt.timezone.utc)
    per: dict[str, float] = {}
    running = None
    for e in entries or []:
        sec = e.get("duration") or 0
        if sec < 0:
            sec = (now - dt.datetime.fromisoformat(e["start"].replace("Z", "+00:00"))).total_seconds()
            running = {"what": e.get("description"), "project": projects.get(e.get("project_id")), "minutes": round(sec / 60)}
        key = projects.get(e.get("project_id")) or e.get("description") or "(bez projektu)"
        per[key] = per.get(key, 0) + sec
    hours = {k: round(v / 3600, 2) for k, v in sorted(per.items(), key=lambda x: -x[1])}
    return ToolResult(True, f"Celkem {round(sum(per.values()) / 3600, 1)} h.", data={"hours": hours, "running": running})


@tool("toggl_timer", "Toggl: spustí stopky na činnost nebo zastaví běžící. Zeptá se uživatele.", danger=True, category="propojení",
      perm="network", details=lambda a: [("Spustit: " + a.get("description", "")) if a.get("action", "start") == "start" else "Zastavit běžící stopky"])
@guarded
async def timer(ctx, action: Annotated[str, "start / stop"] = "start", description: Annotated[str, "na čem pracuješ"] = "") -> ToolResult:
    me = await _api("GET", "/me")
    wid = me.get("default_workspace_id")
    if action == "stop":
        cur = await _api("GET", "/me/time_entries/current")
        if not cur:
            return ToolResult(True, "Žádné stopky neběží.")
        await _api("PATCH", f"/workspaces/{cur['workspace_id']}/time_entries/{cur['id']}/stop")
        return ToolResult(True, f"Zastaveno: {cur.get('description') or ''}.")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    await _api("POST", f"/workspaces/{wid}/time_entries", {"created_with": "JARVIS", "description": description, "start": now,
                                                           "duration": -1, "workspace_id": wid})
    return ToolResult(True, f"Stopky běží: {description}.")
