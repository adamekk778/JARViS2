"""3.12 Spaceship: your domains (expiry, auto-renew), their DNS records and whether a name is free – Spaceship's API
with an API key and secret. Changing DNS asks first."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import friendly, http, need, register, value

API = "https://spaceship.dev/api/v1"


async def _test(rt: Any) -> str:
    d = await _api("GET", "/domains?take=5&skip=0")
    return f"{d.get('total', len(d.get('items', [])))} domén."


register("spaceship", "Spaceship (domény)", "globe", [
    {"key": "key", "label": "API key", "secret": True, "hint": ""},
    {"key": "secret", "label": "API secret", "secret": True, "hint": ""},
], [
    "Otevři spaceship.com → Account → API Manager.",
    "Vytvoř nový API klíč a zaškrtni oprávnění pro Domains a DNS records (čtení, případně zápis).",
    "Zkopíruj API key a API secret sem a ulož.",
], url="https://www.spaceship.com/application/api-manager/",
    what="Domény a kdy vyprší, DNS záznamy (změny jen s potvrzením), volné domény.", test=_test)


async def _api(method: str, path: str, body: Any = None, transport=None) -> Any:
    need("spaceship")
    async with http(transport=transport) as c:
        r = await c.request(method, API + path, json=body,
                            headers={"X-Api-Key": value("spaceship", "key"), "X-Api-Secret": value("spaceship", "secret")})
        r.raise_for_status()
        return r.json() if r.content else {}


@tool("spaceship_domains", "Spaceship: moje domény – kdy vyprší, automatické prodloužení, stav.", category="propojení", perm="network")
async def domains(ctx) -> ToolResult:
    try:
        d = await _api("GET", "/domains?take=100&skip=0")
        out = [{"name": x.get("name"), "expires": x.get("expirationDate"), "auto_renew": x.get("autoRenew"),
                "status": x.get("lifecycleStatus") or x.get("verificationStatus")} for x in d.get("items", [])]
        return ToolResult(True, f"{len(out)} domén.", data=out)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("spaceship_dns", "Spaceship: DNS záznamy domény (A, CNAME, MX, TXT…).", category="propojení", perm="network")
async def dns(ctx, domain: Annotated[str, "doména, např. firma.cz"]) -> ToolResult:
    try:
        d = await _api("GET", f"/dns/records/{domain}?take=200&skip=0")
        return ToolResult(True, f"{len(d.get('items', []))} záznamů.", data=d.get("items", []))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


def record(rtype: str, name: str, val: str, ttl: int = 3600, priority: int = 10) -> dict:
    """One record the way Spaceship wants it (each type names its value differently)."""
    t = rtype.upper()
    r: dict[str, Any] = {"type": t, "name": name or "@", "ttl": int(ttl or 3600)}
    if t in ("A", "AAAA"):
        r["address"] = val
    elif t == "CNAME":
        r["cname"] = val
    elif t == "MX":
        r.update(exchange=val, preference=int(priority or 10))
    else:
        r["value"] = val
    return r


@tool("spaceship_dns_set", "Spaceship: přidá nebo změní DNS záznam domény. Zeptá se uživatele (změna DNS může vypnout web nebo e-mail).",
      danger=True, category="propojení", perm="network",
      details=lambda a: [f"Doména: {a.get('domain', '')}", f"{a.get('type', '')} {a.get('name', '@')} → {a.get('value', '')} (TTL {a.get('ttl', 3600)})"])
async def dns_set(ctx, domain: Annotated[str, "doména"], type: Annotated[str, "typ: A, AAAA, CNAME, MX, TXT"],  # noqa: A002
                  name: Annotated[str, "název, @ = doména sama"], value: Annotated[str, "hodnota (IP, cíl, text)"],
                  ttl: Annotated[int, "TTL v sekundách"] = 3600, priority: Annotated[int, "priorita (jen MX)"] = 10) -> ToolResult:
    try:
        await _api("PUT", f"/dns/records/{domain}", {"force": True, "items": [record(type, name, value, ttl, priority)]})
        return ToolResult(True, f"DNS {type} {name} → {value} u {domain} uloženo.")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))


@tool("spaceship_available", "Spaceship: je doména volná k registraci?", category="propojení", perm="network")
async def available(ctx, domain: Annotated[str, "doména"]) -> ToolResult:
    try:
        d = await _api("GET", f"/domains/{domain}/available")
        free = d.get("result") == "available" or d.get("available") is True
        return ToolResult(True, f"{domain} je {'volná' if free else 'obsazená'}.", data=d)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, friendly(e))
