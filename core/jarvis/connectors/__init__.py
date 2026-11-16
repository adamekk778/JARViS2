"""3.12 Propojení: the services JARVIS can work in for you – like the connectors in ChatGPT. Google (Gmail, Kalendář,
Disk, Dokumenty, Tabulky, Kontakty), Supabase, Spaceship, GitHub, Notion, Slack, and any MCP server by its address.

Every key and token lives in the OS secure storage (secrets), never in the config or a log. Reading is free; anything
that changes something outside this PC (sends an e-mail, writes to a database, changes DNS, posts a message) is a
dangerous tool: JARVIS asks first, and a background agent only proposes it into "Ke schválení".
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from .. import secrets

CONNECTORS: dict[str, dict[str, Any]] = {}
TESTS: dict[str, Callable[[Any], Awaitable[str]]] = {}
LAST: dict[str, dict] = {}            # id → {"ok", "detail", "at"} of the last test


class NotConnected(RuntimeError):
    pass


def register(cid: str, name: str, icon: str, fields: list[dict], help_steps: list[str], url: str = "",
             oauth: bool = False, what: str = "", test: Callable[[Any], Awaitable[str]] | None = None) -> None:
    """fields: [{"key": "token", "label": "…", "secret": True, "hint": "sbp_…"}]"""
    CONNECTORS[cid] = {"id": cid, "name": name, "icon": icon, "fields": fields, "help": help_steps, "url": url,
                       "oauth": oauth, "what": what}
    if test:
        TESTS[cid] = test


def skey(cid: str, field: str) -> str:
    return f"conn.{cid}.{field}"


def value(cid: str, field: str) -> str:
    return secrets.get(skey(cid, field)) or ""


def configured(cid: str) -> bool:
    meta = CONNECTORS.get(cid)
    if not meta:
        return False
    if not all(value(cid, f["key"]) for f in meta["fields"] if not f.get("optional")):
        return False
    return bool(value(cid, "refresh_token")) if meta.get("oauth") else True


def need(cid: str) -> None:
    if not configured(cid):
        name = CONNECTORS.get(cid, {}).get("name", cid)
        raise NotConnected(f"{name} není propojený – připoj ho v Nastavení → Propojení (stačí jednou).")


def status() -> list[dict]:
    out = []
    for cid, m in CONNECTORS.items():
        out.append({**{k: v for k, v in m.items() if k != "fields"},
                    "fields": [{k: v for k, v in f.items()} | {"set": bool(value(cid, f["key"]))} for f in m["fields"]],
                    "connected": configured(cid), "last": LAST.get(cid)})
    return out


def save(cid: str, values: dict) -> None:
    meta = CONNECTORS.get(cid)
    if not meta:
        raise ValueError("Takové propojení neznám.")
    for f in meta["fields"]:
        v = str(values.get(f["key"], "") or "").strip()
        if v:
            secrets.set(skey(cid, f["key"]), v)
    LAST.pop(cid, None)


def remove(cid: str) -> None:
    meta = CONNECTORS.get(cid) or {}
    for f in meta.get("fields", []):
        secrets.set(skey(cid, f["key"]), "")
    for extra in ("refresh_token", "access_token"):
        secrets.set(skey(cid, extra), "")
    LAST.pop(cid, None)


async def test(rt: Any, cid: str) -> dict:
    fn = TESTS.get(cid)
    if not configured(cid):
        res = {"ok": False, "detail": "Ještě není propojené."}
    elif fn is None:
        res = {"ok": True, "detail": "Uloženo."}
    else:
        try:
            res = {"ok": True, "detail": await fn(rt)}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "detail": friendly(e)}
    LAST[cid] = {**res, "at": time.time()}
    return res


def friendly(e: Exception) -> str:
    """An error as words a person can act on (never the token)."""
    import httpx

    if isinstance(e, NotConnected):
        return str(e)
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        body = e.response.text[:160].replace("\n", " ")
        if code in (401, 403):
            return f"Služba odmítla přístup ({code}) – klíč je špatný, vypršel, nebo nemá potřebná oprávnění. {body}"
        if code == 404:
            return f"Nenalezeno (404) – zkontroluj název nebo ID. {body}"
        if code == 429:
            return "Služba teď hlásí limit – za chvíli to půjde."
        return f"Služba odpověděla chybou {code}: {body}"
    if isinstance(e, httpx.HTTPError):
        return f"Nejde se spojit se službou ({type(e).__name__}). Je PC na internetu?"
    return f"{type(e).__name__}: {str(e)[:200]}"


TRANSPORT = None          # tests: a fake internet (httpx.MockTransport)


def http(**kw):
    """An HTTP client for the services – with the certificates Windows trusts (an antivirus that checks HTTPS)."""
    import httpx

    from .. import tlsctx

    transport = kw.pop("transport", None) or TRANSPORT
    return httpx.AsyncClient(verify=tlsctx.context(), timeout=kw.pop("timeout", 30), transport=transport, **kw)


def load() -> None:
    """Import every connector (each registers itself and its tools)."""
    import importlib
    import logging

    for m in ("google", "supabase", "spaceship", "github", "notion", "slack"):
        try:
            importlib.import_module(f"{__name__}.{m}")
        except Exception as e:  # noqa: BLE001 – one broken connector must not take the others down
            logging.getLogger(__name__).warning("connector %s: %s", m, e)
