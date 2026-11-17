"""3.12 Vercel: projekty a nasazení (deploye) – co běží, co spadlo. Jen čtení. Access token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value

API = "https://api.vercel.com"


async def _api(path: str, transport=None, **params) -> Any:
    need("vercel")
    if value("vercel", "team"):
        params["teamId" if value("vercel", "team").startswith("team_") else "slug"] = value("vercel", "team")
    return await call("GET", API + path, params=params or None, transport=transport, headers={"Authorization": f"Bearer {value('vercel', 'token')}"})


async def _test(rt: Any) -> str:
    u = (await _api("/v2/user")).get("user") or {}
    return f"Přihlášeno jako {u.get('username', '?')}."


register("vercel", "Vercel (weby)", "triangle", [
    {"key": "token", "label": "Access token", "secret": True, "hint": ""},
    {"key": "team", "label": "Tým (nepovinné)", "secret": False, "hint": "team_… nebo název týmu z adresy", "optional": True},
], [
    "Otevři vercel.com/account/settings/tokens → Create Token (scope: tvůj účet nebo tým, platnost dle sebe).",
    "Zkopíruj token sem a ulož. Projekty týmu? Doplň tým (z adresy vercel.com/<tým>).",
], url="https://vercel.com/account/settings/tokens", what="Projekty a nasazení – co je online, co spadlo a proč. Jen čtení.", test=_test,
    group="dev", probe={"method": "GET", "url": API + "/v2/user", "headers": {"Authorization": "Bearer FAKE"}})


@tool("vercel_projects", "Vercel: projekty (framework, poslední změna).", category="propojení", perm="network")
@guarded
async def projects(ctx) -> ToolResult:
    r = await _api("/v9/projects", limit=50)
    out = [{"name": p.get("name"), "framework": p.get("framework"), "updated": p.get("updatedAt"),
            "domains": [d for d in (p.get("alias") or [])][:3] if isinstance(p.get("alias"), list) else None} for p in r.get("projects", [])]
    return ToolResult(True, f"{len(out)} projektů.", data=out)


@tool("vercel_deployments", "Vercel: poslední nasazení (stav READY/ERROR, adresa, kdy) – volitelně jednoho projektu.", category="propojení",
      perm="network")
@guarded
async def deployments(ctx, project: Annotated[str, "název projektu (nepovinné)"] = "") -> ToolResult:
    params: dict[str, Any] = {"limit": 30}
    if project:
        params["app"] = project
    r = await _api("/v6/deployments", **params)
    out = [{"project": d.get("name"), "state": d.get("state") or d.get("readyState"), "url": "https://" + d["url"] if d.get("url") else None,
            "target": d.get("target"), "created": d.get("created"), "by": (d.get("creator") or {}).get("username"),
            "commit": ((d.get("meta") or {}).get("githubCommitMessage") or "")[:120]} for d in r.get("deployments", [])]
    bad = sum(1 for d in out if d["state"] == "ERROR")
    return ToolResult(True, f"{len(out)} nasazení" + (f", {bad} spadlo" if bad else "") + ".", data=out)
