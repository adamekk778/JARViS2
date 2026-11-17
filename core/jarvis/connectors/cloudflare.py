"""3.12 Cloudflare: domény (zóny) a DNS záznamy; změna DNS s potvrzením. API token."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://api.cloudflare.com/client/v4"


async def _api(method: str, path: str, body: Any = None, transport=None, **params) -> Any:
    need("cloudflare")
    r = await call(method, API + path, json=body, params=params or None, transport=transport,
                   headers={"Authorization": f"Bearer {value('cloudflare', 'token')}"})
    if isinstance(r, dict) and r.get("success") is False:
        raise ServiceError("Cloudflare: " + "; ".join(e.get("message", "") for e in r.get("errors", []))[:300])
    return r


async def _test(rt: Any) -> str:
    r = await _api("GET", "/zones", per_page=50)
    return f"Propojeno – {(r.get('result_info') or {}).get('total_count', len(r.get('result', [])))} domén."


register("cloudflare", "Cloudflare (DNS)", "cloud", [
    {"key": "token", "label": "API token", "secret": True, "hint": ""},
], [
    "Otevři dash.cloudflare.com/profile/api-tokens → Create Token → šablona „Edit zone DNS“ (nebo jen Zone:Read + DNS:Read).",
    "Zone Resources: All zones (nebo vybrané) → Continue → Create Token.",
    "Zkopíruj token sem a ulož.",
], url="https://dash.cloudflare.com/profile/api-tokens", what="Domény a DNS záznamy; změna DNS jen s potvrzením.", test=_test, group="dev",
    probe={"method": "GET", "url": API + "/zones", "headers": {"Authorization": "Bearer FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"}})


async def _zone(domain: str) -> dict:
    d = domain.strip().lower().rstrip(".")
    zones = (await _api("GET", "/zones", per_page=50)).get("result", [])
    z = next((x for x in zones if d == x["name"] or d.endswith("." + x["name"])), None)
    if not z:
        raise ServiceError(f"Doménu {domain} v Cloudflare nevidím. Mám: {', '.join(x['name'] for x in zones[:20])}.")
    return z


@tool("cloudflare_zones", "Cloudflare: moje domény (stav, tarif).", category="propojení", perm="network")
@guarded
async def zones(ctx) -> ToolResult:
    zs = (await _api("GET", "/zones", per_page=50)).get("result", [])
    return ToolResult(True, f"{len(zs)} domén.", data=[{"domain": z["name"], "status": z.get("status"), "plan": (z.get("plan") or {}).get("name"),
                                                       "paused": z.get("paused")} for z in zs])


@tool("cloudflare_dns", "Cloudflare: DNS záznamy domény.", category="propojení", perm="network")
@guarded
async def dns(ctx, domain: Annotated[str, "doména"]) -> ToolResult:
    z = await _zone(domain)
    rs = (await _api("GET", f"/zones/{z['id']}/dns_records", per_page=200)).get("result", [])
    return ToolResult(True, f"{len(rs)} záznamů.", data=[{"type": r["type"], "name": r["name"], "value": r["content"], "proxied": r.get("proxied"),
                                                         "ttl": r.get("ttl")} for r in rs])


@tool("cloudflare_dns_set", "Cloudflare: přidá nebo změní DNS záznam (A, AAAA, CNAME, TXT, MX). Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=lambda a: [f"{a.get('domain', '')}: {a.get('type', '')} {a.get('name', '@')} → {a.get('content', '')}",
                                                               f"Přes Cloudflare (proxy): {'ano' if a.get('proxied') else 'ne'}"])
@guarded
async def dns_set(ctx, domain: Annotated[str, "doména"], type: Annotated[str, "A / AAAA / CNAME / TXT / MX"], name: Annotated[str, "název (@ = doména sama, www…)"],  # noqa: A002
                  content: Annotated[str, "hodnota (IP, cíl, text)"], proxied: Annotated[bool, "přes Cloudflare proxy"] = False,
                  priority: Annotated[int, "priorita (jen MX)"] = 10) -> ToolResult:
    z = await _zone(domain)
    full = z["name"] if name in ("", "@") else (name if name.endswith(z["name"]) else f"{name}.{z['name']}")
    t = type.upper()
    body: dict[str, Any] = {"type": t, "name": full, "content": content, "ttl": 1}
    if t in ("A", "AAAA", "CNAME"):
        body["proxied"] = bool(proxied)
    if t == "MX":
        body["priority"] = int(priority)
    existing = (await _api("GET", f"/zones/{z['id']}/dns_records", type=t, name=full)).get("result", [])
    if existing and t != "MX" and t != "TXT":
        await _api("PUT", f"/zones/{z['id']}/dns_records/{existing[0]['id']}", body)
        return ToolResult(True, f"Změněno: {t} {full} → {content}.")
    await _api("POST", f"/zones/{z['id']}/dns_records", body)
    return ToolResult(True, f"Přidáno: {t} {full} → {content}.")
