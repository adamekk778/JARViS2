"""3.12 Atlassian: Jira (moje úkoly, hledání JQL, nový úkol s potvrzením) a Confluence (hledání stránek).
E-mail + API token of your Atlassian account and the site address (firma.atlassian.net)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, need, register, value


def site() -> str:
    s = value("atlassian", "site").strip().lower().replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    return "https://" + (s if "." in s else f"{s}.atlassian.net")


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("atlassian")
    return await call(method, site() + path, json=body, params=params or None, transport=transport,
                      auth=(value("atlassian", "email"), value("atlassian", "token")), headers={"Accept": "application/json"})


async def _test(rt: Any) -> str:
    me = await _api("GET", "/rest/api/3/myself")
    return f"Přihlášeno jako {me.get('displayName', '?')} na {site()}."


register("atlassian", "Jira a Confluence", "kanban", [
    {"key": "site", "label": "Adresa", "secret": False, "hint": "firma.atlassian.net"},
    {"key": "email", "label": "E-mail účtu", "secret": False, "hint": "kterým se do Jiry přihlašuješ"},
    {"key": "token", "label": "API token", "secret": True, "hint": "ATATT…"},
], [
    "Otevři id.atlassian.com/manage-profile/security/api-tokens → Create API token (bez scopes).",
    "Zkopíruj token sem, doplň svůj e-mail a adresu (firma.atlassian.net) a ulož.",
], url="https://id.atlassian.com/manage-profile/security/api-tokens",
    what="Jira: moje úkoly, hledání, nový úkol s potvrzením. Confluence: hledání stránek.", test=_test, group="tasks",
    prefixes=("jira_", "confluence_"))


def _adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]}
                                                     for p in text.split("\n") if p.strip()] or [{"type": "paragraph", "content": []}]}


@tool("jira_issues", "Jira: úkoly podle JQL (výchozí: moje nedokončené).", category="propojení", perm="network")
@guarded
async def issues(ctx, jql: Annotated[str, "JQL dotaz (prázdné = moje nedokončené)"] = "") -> ToolResult:
    q = jql.strip() or "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
    r = await _api("GET", "/rest/api/3/search/jql", jql=q, maxResults=50, fields="summary,status,priority,duedate,assignee,updated,project")
    out = [{"key": i["key"], "title": (i.get("fields") or {}).get("summary"), "status": ((i.get("fields") or {}).get("status") or {}).get("name"),
            "priority": ((i.get("fields") or {}).get("priority") or {}).get("name"), "due": (i.get("fields") or {}).get("duedate"),
            "who": ((i.get("fields") or {}).get("assignee") or {}).get("displayName"), "url": f"{site()}/browse/{i['key']}"}
           for i in r.get("issues", [])]
    return ToolResult(True, f"{len(out)} úkolů.", data=out)


@tool("jira_issue_create", "Jira: založí úkol v projektu. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Projekt: {a.get('project', '')}", f"Název: {a.get('summary', '')}", *str(a.get("description", "")).splitlines()[:15]])
@guarded
async def issue_create(ctx, project: Annotated[str, "klíč projektu (např. WEB)"], summary: Annotated[str, "název"],
                       description: Annotated[str, "popis"] = "") -> ToolResult:
    import httpx

    key = project.strip().upper()
    fields = {"project": {"key": key}, "summary": summary, "description": _adf(description)}
    try:
        r = await _api("POST", "/rest/api/3/issue", {"fields": {**fields, "issuetype": {"name": "Task"}}})
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400:
            raise
        types = await _api("GET", f"/rest/api/3/issue/createmeta/{key}/issuetypes")
        it = next((t for t in (types.get("issueTypes") or types.get("values") or []) if not t.get("subtask")), None)
        if not it:
            raise
        r = await _api("POST", "/rest/api/3/issue", {"fields": {**fields, "issuetype": {"id": it["id"]}}})
    return ToolResult(True, f"Úkol {r.get('key')} založen.", data={"url": f"{site()}/browse/{r.get('key')}"})


@tool("confluence_search", "Confluence: najde stránky podle textu.", category="propojení", perm="network")
@guarded
async def confluence_search(ctx, query: Annotated[str, "co hledat"]) -> ToolResult:
    q = query.replace('"', " ")
    r = await _api("GET", "/wiki/rest/api/search", cql=f'type=page AND text ~ "{q}"', limit=20)
    out = [{"title": (x.get("content") or {}).get("title") or x.get("title"), "excerpt": (x.get("excerpt") or "")[:300],
            "url": site() + "/wiki" + (x.get("url") or ((x.get("content") or {}).get("_links") or {}).get("webui", ""))} for x in r.get("results", [])]
    return ToolResult(True, f"{len(out)} stránek.", data=out)
