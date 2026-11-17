"""3.12 GitHub: repositories, issues and pull requests with a personal access token. Opening an issue or commenting
asks first."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import friendly, http, need, register, value

API = "https://api.github.com"


async def _test(rt: Any) -> str:
    me = await _api("GET", "/user")
    return f"Přihlášeno jako {me.get('login')}."


register("github", "GitHub", "github-logo", [
    {"key": "token", "label": "Personal access token", "secret": True, "hint": "github_pat_… nebo ghp_…"},
], [
    "Otevři github.com/settings/tokens → Fine-grained tokens → Generate new token.",
    "Vyber repozitáře a oprávnění Issues, Pull requests a Contents (čtení; zápis jen pokud chceš zakládat issues).",
    "Zkopíruj token sem a ulož.",
], url="https://github.com/settings/personal-access-tokens/new",
    what="Repozitáře, issues a pull requesty; nové issue nebo komentář jen s potvrzením.", test=_test, group="dev",
    probe={"method": "GET", "url": API + "/user", "headers": {"Authorization": "Bearer FAKE"}})


async def _api(method: str, path: str, body: Any = None, transport=None) -> Any:
    need("github")
    async with http(transport=transport) as c:
        r = await c.request(method, API + path, json=body, headers={"Authorization": f"Bearer {value('github', 'token')}",
                                                                    "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        return r.json() if r.content else {}


@tool("github_repos", "GitHub: moje repozitáře (projekty) – naposledy změněné.", category="propojení", perm="network")
async def repos(ctx) -> ToolResult:
    try:
        rs = await _api("GET", "/user/repos?sort=pushed&per_page=30")
        return ToolResult(True, f"{len(rs)} repozitářů.", data=[{"name": r["full_name"], "private": r.get("private"),
                          "pushed": r.get("pushed_at"), "issues": r.get("open_issues_count")} for r in rs])
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("github_issues", "GitHub: issues (úkoly, chyby) nebo pull requesty repozitáře.", category="propojení", perm="network")
async def issues(ctx, repo: Annotated[str, "vlastník/repozitář"], state: Annotated[str, "open / closed / all"] = "open",
                 pulls: Annotated[bool, "jen pull requesty"] = False) -> ToolResult:
    try:
        path = f"/repos/{repo}/pulls?state={state}&per_page=30" if pulls else f"/repos/{repo}/issues?state={state}&per_page=30"
        items = await _api("GET", path)
        return ToolResult(True, f"{len(items)} položek.", data=[{"number": i["number"], "title": i["title"], "by": (i.get("user") or {}).get("login"),
                          "updated": i.get("updated_at"), "url": i.get("html_url")} for i in items])
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("github_issue_create", "GitHub: založí nové issue. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Repozitář: {a.get('repo', '')}", f"Název: {a.get('title', '')}", *str(a.get("body", "")).splitlines()[:20]])
async def issue_create(ctx, repo: Annotated[str, "vlastník/repozitář"], title: Annotated[str, "název"], body: Annotated[str, "popis"] = "") -> ToolResult:
    try:
        i = await _api("POST", f"/repos/{repo}/issues", {"title": title, "body": body})
        return ToolResult(True, f"Issue #{i['number']} založeno.", data={"url": i.get("html_url")})
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))
