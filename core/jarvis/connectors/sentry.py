"""3.12 Sentry: chyby v aplikacích (nevyřešené, nejčastější za den) – jen čtení. Auth token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value


def host() -> str:
    h = (value("sentry", "host") or "sentry.io").strip().replace("https://", "").strip("/")
    return "https://" + h


async def _api(path: str, transport=None, **params) -> Any:
    need("sentry")
    return await call("GET", host() + "/api/0" + path, params=params or None, transport=transport,
                      headers={"Authorization": f"Bearer {value('sentry', 'token')}"})


async def _org() -> str:
    if value("sentry", "org"):
        return value("sentry", "org")
    orgs = await _api("/organizations/")
    return orgs[0]["slug"] if orgs else ""


async def _test(rt: Any) -> str:
    orgs = await _api("/organizations/")
    return f"Propojeno – organizace {', '.join(o['slug'] for o in orgs) or '?'}."


register("sentry", "Sentry (chyby v aplikacích)", "bug", [
    {"key": "token", "label": "Auth token", "secret": True, "hint": "sntryu_…"},
    {"key": "org", "label": "Organizace (nepovinné)", "secret": False, "hint": "slug z adresy", "optional": True},
    {"key": "host", "label": "Server (nepovinné)", "secret": False, "hint": "sentry.io nebo de.sentry.io", "optional": True},
], [
    "Otevři sentry.io → Settings → Account → Personal Tokens (User Auth Tokens) → Create New Token.",
    "Scopes: org:read, project:read, event:read → Create → zkopíruj token sem a ulož.",
], url="https://sentry.io/settings/account/api/auth-tokens/", what="Nevyřešené chyby v aplikacích – kolikrát, kolika lidem, odkdy. Jen čtení.",
    test=_test, group="dev", probe={"method": "GET", "url": "https://sentry.io/api/0/organizations/", "headers": {"Authorization": "Bearer FAKE"}})


@tool("sentry_issues", "Sentry: nevyřešené chyby za posledních 24 h / 14 dní, nejčastější první.", category="propojení", perm="network")
@guarded
async def issues(ctx, period: Annotated[str, "24h / 14d"] = "24h", project: Annotated[str, "projekt (nepovinné)"] = "") -> ToolResult:
    org = await _org()
    q = "is:unresolved" + (f" project:{project}" if project else "")
    r = await _api(f"/organizations/{org}/issues/", query=q, statsPeriod=period if period in ("24h", "14d") else "24h", sort="freq", limit=25)
    out = [{"title": i.get("title"), "where": i.get("culprit"), "count": i.get("count"), "users": i.get("userCount"),
            "first": i.get("firstSeen"), "last": i.get("lastSeen"), "project": (i.get("project") or {}).get("slug"),
            "level": i.get("level"), "url": i.get("permalink")} for i in (r if isinstance(r, list) else [])]
    return ToolResult(True, f"{len(out)} nevyřešených chyb.", data=out)
