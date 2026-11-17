"""3.12 Linear: moje issues (stav, priorita, termín); nové issue s potvrzením. Personal API key."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://api.linear.app/graphql"


async def gql(query: str, variables: dict | None = None, transport=None) -> dict:
    need("linear")
    r = await call("POST", API, json={"query": query, "variables": variables or {}}, transport=transport,
                   headers={"Authorization": value("linear", "key")})
    if r.get("errors"):
        raise ServiceError("Linear: " + "; ".join(e.get("message", "") for e in r["errors"])[:300])
    return r.get("data") or {}


async def _test(rt: Any) -> str:
    d = await gql("{ viewer { name email } }")
    return f"Přihlášeno jako {d['viewer']['name']}."


register("linear", "Linear (issues)", "lightning", [
    {"key": "key", "label": "Personal API key", "secret": True, "hint": "lin_api_…"},
], [
    "V Linearu: Settings → Account → Security & access → Personal API keys → New API key.",
    "Zkopíruj klíč sem a ulož.",
], url="https://linear.app/settings/account/security", what="Moje rozpracované issues; nové issue jen s potvrzením.", test=_test,
    group="tasks", probe={"method": "POST", "url": API, "json": {"query": "{ viewer { id } }"}, "headers": {"Authorization": "lin_api_FAKE"}})


@tool("linear_issues", "Linear: moje nedokončené issues (stav, priorita, termín, tým).", category="propojení", perm="network")
@guarded
async def issues(ctx) -> ToolResult:
    d = await gql("""{ viewer { assignedIssues(first: 100, filter: { state: { type: { nin: ["completed", "canceled"] } } }) {
        nodes { identifier title url priorityLabel dueDate state { name } team { key } } } } }""")
    out = [{"id": i["identifier"], "title": i["title"], "state": (i.get("state") or {}).get("name"), "priority": i.get("priorityLabel"),
            "due": i.get("dueDate"), "team": (i.get("team") or {}).get("key"), "url": i.get("url")}
           for i in ((d.get("viewer") or {}).get("assignedIssues") or {}).get("nodes", [])]
    return ToolResult(True, f"{len(out)} issues.", data=out)


@tool("linear_issue_create", "Linear: založí issue v týmu. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Tým: {a.get('team', '')}", f"Název: {a.get('title', '')}", *str(a.get("description", "")).splitlines()[:15]])
@guarded
async def issue_create(ctx, team: Annotated[str, "klíč nebo název týmu (např. ENG)"], title: Annotated[str, "název"],
                       description: Annotated[str, "popis (markdown)"] = "") -> ToolResult:
    teams = (await gql("{ teams { nodes { id key name } } }")).get("teams", {}).get("nodes", [])
    t = next((x for x in teams if team.lower() in (x["key"].lower(), x["name"].lower())), None) or (teams[0] if len(teams) == 1 else None)
    if not t:
        return ToolResult(False, f"Tým „{team}“ nevidím. Týmy: {', '.join(x['key'] for x in teams)}.")
    d = await gql("mutation($i: IssueCreateInput!) { issueCreate(input: $i) { success issue { identifier url } } }",
                  {"i": {"teamId": t["id"], "title": title, "description": description}})
    iss = (d.get("issueCreate") or {}).get("issue") or {}
    return ToolResult(True, f"Issue {iss.get('identifier')} založeno.", data={"url": iss.get("url")})
