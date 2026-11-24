"""3.17 PPL (návrh 19): where a PPL parcel is, live – through PPL's official CPL API (api.dhl.com/ecs/ppl/myapi2).

PPL gives the API only to its business customers: the Client ID and Client secret come from your PPL business
representative (or the PPL portal of an e-shop that sends with PPL). Without them JARVIS keeps the tracking link.
Read only: JARVIS asks for a parcel's state by its number, nothing else.
"""
from __future__ import annotations

import time
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, guarded, http, need, register, value

BASE = "https://api.dhl.com/ecs/ppl/myapi2"
TOKEN_URL = BASE + "/login/getAccessToken"
_TOKEN: dict[str, Any] = {"value": "", "until": 0.0, "for": ""}


async def token(transport: Any = None) -> str:
    need("ppl")
    cid, secret = value("ppl", "client_id").strip(), value("ppl", "client_secret").strip()
    if _TOKEN["value"] and _TOKEN["for"] == cid and time.time() < _TOKEN["until"]:
        return str(_TOKEN["value"])
    async with http(transport=transport, timeout=20) as c:
        r = await c.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
                                          "scope": "myapi2"})
    if r.status_code in (400, 401):
        raise ServiceError("PPL nepřijalo Client ID nebo Client secret – zkontroluj je v Nastavení → Propojení → PPL.")
    r.raise_for_status()
    d = r.json()
    _TOKEN.update(value=d.get("access_token", ""), until=time.time() + max(60, int(d.get("expires_in") or 1800) - 60), **{"for": cid})
    if not _TOKEN["value"]:
        raise ServiceError("PPL neposlalo přístupový token.")
    return str(_TOKEN["value"])


async def shipment(number: str, transport: Any = None) -> Any:
    tok = await token(transport)
    async with http(transport=transport, timeout=20) as c:
        r = await c.get(BASE + "/shipment", params={"ShipmentNumbers": number, "Limit": 1, "Offset": 0},
                        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    if r.status_code == 401:
        _TOKEN.update(value="", until=0.0)
    r.raise_for_status()
    return r.json()


def status_of(data: Any) -> tuple[str, str]:
    """(the newest event, its time) from PPL's answer; ("", "") when it does not know the parcel. Defensive: PPL's
    exact schema is only in its partner documentation, so several field names are accepted."""
    items = data if isinstance(data, list) else (data or {}).get("items") or (data or {}).get("data") or []
    items = [x for x in items if isinstance(x, dict)]
    if not items:
        return "", ""
    sh = items[0]
    tt = sh.get("trackAndTrace") if isinstance(sh.get("trackAndTrace"), dict) else {}
    events = [e for e in (tt.get("events") or sh.get("events") or []) if isinstance(e, dict)]
    if events:
        e = max(events, key=lambda ev: str(ev.get("eventDate") or ev.get("date") or ""))
        text = str(e.get("name") or e.get("description") or e.get("statusName") or e.get("code") or "").strip()
        return text, str(e.get("eventDate") or e.get("date") or "")[:16].replace("T", " ")
    return str(tt.get("lastEventName") or sh.get("shipmentState") or "").strip(), ""


async def _test(rt: Any) -> str:
    await token()
    return "Propojeno – PPL přijalo přihlášení."


register("ppl", "PPL (zásilky)", "truck", [
    {"key": "client_id", "label": "Client ID", "secret": True, "hint": "od obchodního zástupce PPL"},
    {"key": "client_secret", "label": "Client secret", "secret": True, "hint": "patří k Client ID"},
], [
    "PPL dává API jen firemním zákazníkům: o Client ID a Client secret (CPL API) požádej obchodního zástupce PPL.",
    "Vlož je sem a ulož – JARVIS pak u zásilek PPL ukazuje, kde právě jsou.",
    "Bez nich JARVIS u PPL drží jen odkaz na sledování.",
], url="https://www.ppl.cz/", what="Kde je zásilka PPL právě teď (jen čtení, podle čísla zásilky).", test=_test, group="sales",
    probe={"method": "POST", "url": TOKEN_URL, "data": "grant_type=client_credentials&client_id=x&client_secret=y&scope=myapi2"})


@tool("ppl_status", "PPL: kde je zásilka právě teď (podle čísla zásilky).", category="propojení", perm="network")
@guarded
async def ppl_status(ctx, number: Annotated[str, "číslo zásilky PPL (11 číslic)"]) -> ToolResult:
    n = "".join(ch for ch in str(number or "") if ch.isdigit())
    text, when = status_of(await shipment(n))
    if not text:
        return ToolResult(False, f"Zásilku {n} PPL nezná (nebo k ní tvůj účet nemá přístup).")
    return ToolResult(True, f"PPL {n}: {text}" + (f" ({when})" if when else "") + ".", data={"number": n, "status": text, "when": when})
