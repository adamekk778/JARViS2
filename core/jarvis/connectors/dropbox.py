"""3.12 Dropbox: find, list and read your files. Sign-in in the browser with your own free Dropbox app (PKCE, only the
App key – no secret). Read-only."""
from __future__ import annotations

import json
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, http, register
from .oauth import Pkce

API = "https://api.dropboxapi.com/2"
REDIRECT_HOST = "localhost"
AUTH = Pkce("dropbox", "https://www.dropbox.com/oauth2/authorize", "https://api.dropboxapi.com/oauth2/token", "",
            client_field="app_key", extra={"token_access_type": "offline"}, name="Dropbox")
start, finish = AUTH.start, AUTH.finish


async def _api(path: str, body: Any = None, transport=None) -> Any:
    return await call("POST", API + path, json=body, headers=await AUTH.headers(transport), transport=transport)


async def _test(rt: Any) -> str:
    me = await _api("/users/get_current_account")
    return f"Přihlášeno jako {(me.get('name') or {}).get('display_name', '?')}."


register("dropbox", "Dropbox", "dropbox-logo", [
    {"key": "app_key", "label": "App key", "secret": False, "hint": "z dropbox.com/developers/apps"},
], [
    "Otevři dropbox.com/developers/apps → Create app → Scoped access → Full Dropbox → název (např. JARVIS-tvojejmeno).",
    "Záložka Permissions: zaškrtni files.metadata.read a files.content.read → Submit.",
    "Záložka Settings → OAuth 2 Redirect URIs: přidej přesně http://localhost:8765/api/oauth/dropbox",
    "Zkopíruj „App key“ sem, ulož a klikni „Přihlásit se Dropboxem“.",
], url="https://www.dropbox.com/developers/apps", oauth=True, what="Hledání, procházení a čtení souborů v Dropboxu.",
    test=_test, group="work", login="Přihlásit se Dropboxem",
    probe={"method": "POST", "url": API + "/users/get_current_account", "headers": {"Authorization": "Bearer FAKE"}})


def _entry(e: dict) -> dict:
    return {"path": e.get("path_display"), "name": e.get("name"), "folder": e.get(".tag") == "folder", "size": e.get("size"),
            "modified": e.get("server_modified")}


@tool("dropbox_search", "Dropbox: najde soubory a složky podle názvu nebo obsahu.", category="propojení", perm="network")
@guarded
async def search(ctx, query: Annotated[str, "co hledat"]) -> ToolResult:
    r = await _api("/files/search_v2", {"query": query, "options": {"max_results": 25}})
    out = [_entry((m.get("metadata") or {}).get("metadata") or {}) for m in r.get("matches", [])]
    return ToolResult(True, f"{len(out)} výsledků.", data=out)


@tool("dropbox_list", "Dropbox: co je ve složce (prázdné = hlavní složka).", category="propojení", perm="network")
@guarded
async def list_folder(ctx, path: Annotated[str, "složka, např. /Firma/Faktury"] = "") -> ToolResult:
    p = path.strip().rstrip("/")
    r = await _api("/files/list_folder", {"path": "" if p in ("", "/") else (p if p.startswith("/") else "/" + p), "limit": 200})
    out = [_entry(e) for e in r.get("entries", [])]
    return ToolResult(True, f"{len(out)} položek.", data=out)


@tool("dropbox_read", "Dropbox: přečte textový soubor nebo dokument Word (.docx).", category="propojení", perm="network")
@guarded
async def read(ctx, path: Annotated[str, "cesta k souboru, např. /Poznámky/plan.txt"]) -> ToolResult:
    from .microsoft import docx_text

    headers = {**await AUTH.headers(), "Dropbox-API-Arg": json.dumps({"path": path}, ensure_ascii=True)}
    async with http() as c:
        r = await c.post("https://content.dropboxapi.com/2/files/download", headers=headers)
        r.raise_for_status()
    if len(r.content) > 15_000_000:
        return ToolResult(False, "Soubor je moc velký na přečtení.")
    text = docx_text(r.content) if path.lower().endswith(".docx") else r.content.decode("utf-8", "replace")
    return ToolResult(True, path, data={"path": path, "text": text[:15000]})
