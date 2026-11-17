"""3.12 Calendly: kdo si u tebe zarezervoval schůzku (nadcházející události a hosté) – jen čtení."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.calendly.com"


async def _api(url: str, transport=None, **params) -> Any:
    need("calendly")
    return await call("GET", url if url.startswith("http") else API + url, params=params or None, transport=transport,
                      headers={"Authorization": f"Bearer {value('calendly', 'token')}"})


async def _test(rt: Any) -> str:
    me = (await _api("/users/me")).get("resource") or {}
    return f"Přihlášeno jako {me.get('name', '?')}."


register("calendly", "Calendly (rezervace schůzek)", "calendar-plus", [
    {"key": "token", "label": "Personal access token", "secret": True, "hint": "eyJ…"},
], [
    "V Calendly: Integrations & apps → API and webhooks → Personal access tokens → Generate new token.",
    "Zkopíruj token sem a ulož.",
], url="https://calendly.com/integrations/api_webhooks", what="Nadcházející rezervované schůzky a kdo na ně přijde – jen čtení.",
    test=_test, group="sales", probe={"method": "GET", "url": API + "/users/me", "headers": {"Authorization": "Bearer FAKE"}})


@tool("calendly_events", "Calendly: rezervované schůzky na dny dopředu (kdy, jaký typ, kdo).", category="propojení", perm="network")
@guarded
async def events(ctx, days: Annotated[int, "kolik dní dopředu"] = 14) -> ToolResult:
    me = (await _api("/users/me")).get("resource") or {}
    now = dt.datetime.now(dt.timezone.utc)
    r = await _api("/scheduled_events", user=me.get("uri"), status="active", sort="start_time:asc", count=50,
                   min_start_time=now.isoformat().replace("+00:00", "Z"),
                   max_start_time=(now + dt.timedelta(days=max(1, min(int(days or 14), 90)))).isoformat().replace("+00:00", "Z"))
    out = []
    for i, e in enumerate(r.get("collection", [])):
        guests = []
        if i < 10:
            inv = await _api(f"{e['uri']}/invitees", count=10)
            guests = [f"{g.get('name', '')} <{g.get('email', '')}>" for g in inv.get("collection", [])]
        out.append({"name": e.get("name"), "start": e.get("start_time"), "end": e.get("end_time"),
                    "where": (e.get("location") or {}).get("join_url") or (e.get("location") or {}).get("location"), "guests": guests})
    return ToolResult(True, f"{len(out)} schůzek.", data=out)
