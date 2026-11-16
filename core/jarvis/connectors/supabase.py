"""3.12 Supabase: your projects, their database (SQL), tables and health – through Supabase's Management API with a
personal access token. A read query runs at once; anything that changes data or the schema asks first."""
from __future__ import annotations

import re
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import friendly, http, need, register, value

API = "https://api.supabase.com/v1"
READ_ONLY = re.compile(r"^\s*(select|with|explain|show|values|table)\b", re.I)
WRITES = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|comment|copy|call|do|merge|vacuum|reindex|refresh)\b", re.I)


def is_read(query: str) -> bool:
    """Only reading: one statement that starts like a query and changes nothing (CTEs with DELETE … RETURNING count as writes)."""
    q = re.sub(r"--[^\n]*|/\*.*?\*/", " ", query or "", flags=re.S).strip().rstrip(";")
    return bool(q) and ";" not in q and bool(READ_ONLY.match(q)) and not WRITES.search(q)


async def _test(rt: Any) -> str:
    projects = await _api("GET", "/projects")
    return f"{len(projects)} projektů: " + ", ".join(p.get("name", "?") for p in projects[:5])


register("supabase", "Supabase", "database", [
    {"key": "token", "label": "Access token", "secret": True, "hint": "sbp_…"},
], [
    "Otevři supabase.com/dashboard/account/tokens.",
    "Klikni „Generate new token“, pojmenuj ho JARVIS.",
    "Zkopíruj token (začíná sbp_) sem a ulož.",
], url="https://supabase.com/dashboard/account/tokens",
    what="Projekty, tabulky, SQL dotazy (čtení hned, změny dat jen s potvrzením) a stav databáze.", test=_test)


async def _api(method: str, path: str, body: Any = None, transport=None) -> Any:
    need("supabase")
    async with http(transport=transport) as c:
        r = await c.request(method, API + path, json=body, headers={"Authorization": f"Bearer {value('supabase', 'token')}"})
        r.raise_for_status()
        return r.json() if r.content else {}


@tool("supabase_projects", "Supabase: seznam projektů (databáze, region, stav).", category="propojení", perm="network")
async def projects(ctx) -> ToolResult:
    try:
        ps = await _api("GET", "/projects")
        out = [{"ref": p.get("id") or p.get("ref"), "name": p.get("name"), "region": p.get("region"), "status": p.get("status"),
                "created": p.get("created_at")} for p in ps]
        return ToolResult(True, f"{len(out)} projektů.", data=out)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


def _sql_details(a: dict) -> list[str]:
    return [f"Projekt: {a.get('project_ref', '')}", "SQL:", *str(a.get("query", "")).splitlines()[:30]]


@tool("supabase_sql", "Supabase: spustí SQL v databázi projektu. Čtení (SELECT) proběhne hned; změna dat nebo tabulek "
      "(INSERT, UPDATE, DELETE, ALTER…) se nejdřív zeptá uživatele.", category="propojení", perm="network",
      danger_if=lambda a: not is_read(str(a.get("query", ""))), details=_sql_details)
async def sql(ctx, project_ref: Annotated[str, "ref projektu (ze supabase_projects)"], query: Annotated[str, "SQL dotaz"]) -> ToolResult:
    try:
        rows = await _api("POST", f"/projects/{project_ref}/database/query", {"query": query})
        rows = rows if isinstance(rows, list) else [rows]
        return ToolResult(True, f"{len(rows)} řádků.", data=rows[:200])
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("supabase_tables", "Supabase: tabulky projektu s počtem řádků a velikostí.", category="propojení", perm="network")
async def tables(ctx, project_ref: Annotated[str, "ref projektu"]) -> ToolResult:
    q = ("select schemaname as schema, relname as table, n_live_tup as rows, pg_size_pretty(pg_total_relation_size(relid)) as size "
         "from pg_stat_user_tables order by pg_total_relation_size(relid) desc limit 100")
    return await sql(ctx, project_ref, q)


@tool("supabase_health", "Supabase: stav služeb projektu (databáze, auth, storage…) a velikost databáze.", category="propojení", perm="network")
async def health(ctx, project_ref: Annotated[str, "ref projektu"]) -> ToolResult:
    try:
        h = await _api("GET", f"/projects/{project_ref}/health?services=auth&services=db&services=realtime&services=rest&services=storage")
        size = await _api("POST", f"/projects/{project_ref}/database/query",
                          {"query": "select pg_size_pretty(pg_database_size(current_database())) as size"})
        bad = [s.get("name") for s in h if not s.get("healthy")] if isinstance(h, list) else []
        return ToolResult(True, "Vše běží." if not bad else f"Nefunguje: {', '.join(bad)}", data={"services": h, "size": size})
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))
