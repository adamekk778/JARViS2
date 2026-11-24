"""3.12 Propojení: the services JARVIS can work in for you – like the connectors in ChatGPT. Google Workspace, Microsoft
365, Dropbox, payments and invoices (Stripe, Fakturoid, iDoklad, Fio banka), shops and customers (Shopify, WooCommerce,
HubSpot, Pipedrive, Mailchimp, Calendly), tasks and projects (Todoist, Trello, Asana, Linear, Jira, ClickUp, Airtable,
monday.com, Notion, Toggl), the web (GitHub, Supabase, Spaceship, Vercel, Cloudflare, Sentry), messages (Slack,
Telegram, Discord, any webhook) – and any MCP server by its address.

Every key and token lives in the OS secure storage (secrets), never in the config or a log. Reading is free; anything
that changes something outside this PC (sends an e-mail, writes to a database, changes DNS, posts a message) is a
dangerous tool: JARVIS asks first, and a background agent only proposes it into "Ke schválení".
"""
from __future__ import annotations

import functools
import time
from typing import Any, Awaitable, Callable

from .. import secrets

CONNECTORS: dict[str, dict[str, Any]] = {}
TESTS: dict[str, Callable[[Any], Awaitable[str]]] = {}
LAST: dict[str, dict] = {}            # id → {"ok", "detail", "at"} of the last test


class NotConnected(RuntimeError):
    pass


class ServiceError(RuntimeError):
    """The service answered with an error of its own (GraphQL errors, "ok": false…) – the text is already for people."""


GROUPS = {"work": "Google a Microsoft", "money": "Peníze a faktury", "sales": "Prodej a zákazníci",
          "tasks": "Úkoly a projekty", "dev": "Vývoj a weby", "chat": "Zprávy a automatizace", "music": "Hudba",
          "travel": "Cesty a zásilky"}
PROBES: dict[str, dict] = {}          # id → a request with a made-up key (the CI on real Windows: the service must say "wrong key")


def register(cid: str, name: str, icon: str, fields: list[dict], help_steps: list[str], url: str = "",
             oauth: bool = False, what: str = "", test: Callable[[Any], Awaitable[str]] | None = None,
             group: str = "work", prefixes: tuple[str, ...] = (), login: str = "", probe: dict | None = None,
             any_of: list[tuple[str, ...]] | None = None) -> None:
    """fields: [{"key": "token", "label": "…", "secret": True, "hint": "sbp_…", "optional": False}]
    prefixes: the start of this service's tool names (default "<id>_"); login: the sign-in button's text (OAuth)."""
    CONNECTORS[cid] = {"id": cid, "name": name, "icon": icon, "fields": fields, "help": help_steps, "url": url,
                       "oauth": oauth, "what": what, "group": group, "group_name": GROUPS.get(group, group),
                       "prefixes": list(prefixes or (f"{cid}_",)), "login": login or (f"Přihlásit se – {name}" if oauth else ""),
                       "any_of": [list(g) for g in any_of or []]}
    if test:
        TESTS[cid] = test
    if probe:
        PROBES[cid] = probe


def oauth_module(cid: str):
    """The module that signs a browser-login service in (start/finish); its address host (Microsoft and Dropbox want
    "localhost", Spotify wants 127.0.0.1)."""
    import importlib

    if not CONNECTORS.get(cid, {}).get("oauth"):
        raise ValueError("Tahle služba se přihlašuje klíčem, ne přes prohlížeč.")
    return importlib.import_module(f"{__name__}.{cid}")


def redirect_uri(cid: str, port: int) -> str:
    host = getattr(oauth_module(cid), "REDIRECT_HOST", "127.0.0.1")
    return f"http://{host}:{port}/api/oauth/{cid}"


def owner(tool_name: str) -> str | None:
    """Which service a tool belongs to (by its name's start)."""
    for cid, m in CONNECTORS.items():
        if any(tool_name.startswith(p) for p in m.get("prefixes", ())):
            return cid
    return None


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
    if meta.get("any_of") and not any(all(value(cid, k) for k in g) for g in meta["any_of"]):
        return False             # e.g. Shopify: a token – or a Client ID with its secret
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
    forget(cid)


def remove(cid: str) -> None:
    meta = CONNECTORS.get(cid) or {}
    for f in meta.get("fields", []):
        secrets.set(skey(cid, f["key"]), "")
    for extra in ("refresh_token", "access_token"):
        secrets.set(skey(cid, extra), "")
    LAST.pop(cid, None)
    forget(cid)


def forget(cid: str) -> None:
    """New or removed keys: drop the short-lived tokens kept in memory for this service."""
    import sys

    mod = sys.modules.get(f"{__name__}.{cid}")
    if mod is None:
        return
    for name in ("_ACCESS", "_TOKEN"):
        d = getattr(mod, name, None)
        if isinstance(d, dict):
            for k in list(d):
                d[k] = 0.0 if k == "until" else ""
    for name in ("_SLUG", "_CACHE"):
        d = getattr(mod, name, None)
        if isinstance(d, dict):
            d.clear()
    auth = getattr(mod, "AUTH", None)
    if auth is not None and isinstance(getattr(auth, "access", None), dict):
        auth.access.update(token="", until=0.0)


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

    if isinstance(e, (NotConnected, ServiceError)):
        return str(e)[:400]
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        body = _said(e.response)
        if code == 403 and any(w in body.lower() for w in ("insufficient", "scope", "permission_denied")):
            return ("Služba odmítla přístup (403) – chybí oprávnění. U přihlášení přes prohlížeč klikni v Propojení znovu "
                    f"„Přihlásit se“ (přibyla nová oprávnění), u klíče mu přidej potřebná práva. {body}")
        if code in (401, 403):
            return f"Služba odmítla přístup ({code}) – klíč je špatný, vypršel, nebo nemá potřebná oprávnění. {body}"
        if code == 404:
            return f"Nenalezeno (404) – zkontroluj název, adresu nebo ID. {body}"
        if code == 429:
            return "Služba teď hlásí limit dotazů – za chvíli to půjde."
        if code >= 500:
            return f"Služba má teď výpadek ({code}) – zkus to za chvíli. {body}"
        return f"Služba odpověděla chybou {code}: {body}"
    if isinstance(e, httpx.HTTPError):
        return f"Nejde se spojit se službou ({type(e).__name__}). Je PC na internetu a je adresa správně?"
    return f"{type(e).__name__}: {str(e)[:200]}"


def _said(resp) -> str:
    """The service's own error words (JSON "message"/"error"/"detail"…), short; never the request (it can carry a key)."""
    try:
        d = resp.json()
    except Exception:  # noqa: BLE001
        return resp.text[:160].replace("\n", " ") if "<html" not in resp.text[:300].lower() else ""
    found: list[str] = []

    def walk(o: Any, depth: int = 0) -> None:
        if depth > 4 or len(found) > 2:
            return
        if isinstance(o, dict):
            for k in ("message", "error_description", "detail", "error", "title", "errors", "description", "msg"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    found.append(v.strip())
                elif isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(o, list):
            for x in o[:3]:
                walk(x, depth + 1)
    walk(d)
    return " · ".join(dict.fromkeys(found))[:220] if found else str(d)[:160]


TRANSPORT = None          # tests: a fake internet (httpx.MockTransport)


def http(**kw):
    """An HTTP client for the services – with the certificates Windows trusts (an antivirus that checks HTTPS)."""
    import httpx

    from .. import tlsctx

    transport = kw.pop("transport", None) or TRANSPORT
    return httpx.AsyncClient(verify=tlsctx.context(), timeout=kw.pop("timeout", 30), transport=transport, **kw)


async def call(method: str, url: str, *, transport=None, timeout: float = 30, **kw) -> Any:
    """One request to a service: the JSON answer (or {"text": …}); an error status raises (→ friendly())."""
    async with http(transport=transport, timeout=timeout) as c:
        r = await c.request(method, url, **kw)
        r.raise_for_status()
        if not r.content:
            return {}
        if "json" in r.headers.get("content-type", "") or r.content[:1] in (b"{", b"["):
            try:
                return r.json()
            except ValueError:
                pass
        return {"text": r.text[:20000]}


def slim(o: Any, keep: tuple[str, ...] = (), text: int = 300) -> Any:
    """A record cut to what matters: the named keys ("a.b" reaches inside, shown as a_b) – or, when none of them is
    there (a service renamed things), its plain values. Long texts are cut."""
    if not isinstance(o, dict):
        return o

    def cut(v: Any) -> Any:
        return v[:text] + "…" if isinstance(v, str) and len(v) > text else v
    out: dict = {}
    for k in keep:
        v: Any = o
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v not in (None, "", [], {}):
            out[k.replace(".", "_")] = cut(v)
    if out:
        return out
    return {k: cut(v) for k, v in o.items() if isinstance(v, (str, int, float, bool)) and v not in ("", None)}


def guarded(fn):
    """A connector tool: any failure becomes a ToolResult a person can act on (never a stack trace, never the key)."""
    @functools.wraps(fn)
    async def inner(ctx, *a, **kw):
        from ..tools.base import ToolResult

        try:
            return await fn(ctx, *a, **kw)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, friendly(e))
    return inner


def days_ago(days: float):
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=float(days or 0))


REACHED = {200, 400, 401, 403, 409, 415, 422, 429}


async def probe(cid: str, transport=None) -> dict:
    """Is the service's address right and reachable from this PC? A request with a made-up key: the service must answer
    "wrong key" (401/403…) – not "no such address" (404/410) or a connection/certificate error."""
    import httpx

    p = dict(PROBES[cid])
    kw: dict[str, Any] = {k: p[k] for k in ("headers", "json", "data") if k in p}
    if p.get("auth"):
        kw["auth"] = tuple(p["auth"])
    t0 = time.monotonic()
    try:
        async with http(transport=transport, timeout=p.get("timeout", 20)) as c:
            r = await c.request(p.get("method", "GET"), p["url"], **kw)
        ok = r.status_code in REACHED or r.status_code in p.get("accept", ()) or (r.status_code == 404 and "json" in r.headers.get("content-type", "") and p.get("url", "").startswith("https://discord.com"))
        detail = f"{r.status_code} {_said(r)[:120]}"
    except httpx.HTTPError as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    return {"id": cid, "ok": ok, "detail": detail, "ms": round((time.monotonic() - t0) * 1000)}


MODULES = ("google", "microsoft", "dropbox", "stripe", "fakturoid", "idoklad", "fio", "shopify", "woocommerce", "hubspot",
           "pipedrive", "mailchimp", "calendly", "todoist", "trello", "asana", "linear", "atlassian", "clickup", "airtable",
           "monday", "notion", "toggl", "github", "supabase", "spaceship", "vercel", "cloudflare", "sentry", "slack",
           "telegram", "discord", "webhook", "spotify", "shoptet", "zasilkovna", "ppl", "gls", "travelapis", "heureka", "gopay", "comgate", "flexi", "pohoda", "aerodatabox")


def load() -> None:
    """Import every connector (each registers itself and its tools)."""
    import importlib
    import logging

    for m in MODULES:
        try:
            importlib.import_module(f"{__name__}.{m}")
        except Exception as e:  # noqa: BLE001 – one broken connector must not take the others down
            logging.getLogger(__name__).warning("connector %s: %s", m, e)
