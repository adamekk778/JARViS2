"""3.18 GLS (návrh 16): where a GLS parcel is, live – with the Track & Trace API key GLS gives after a registration
(gls-group.eu → Register API access). The key goes into the keyring; without it JARVIS keeps the tracking link.
Read only: the state of a parcel by its number."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, guarded, http, need, register, value

BASE = "https://api-tt.de.gls-group.com/app/service/open/rest/{country}/{lang}/rstt001"


async def track(number: str, transport: Any = None) -> Any:
    need("gls")
    country = (value("gls", "country") or "CZ").strip().upper()[:2]
    async with http(transport=transport, timeout=20) as c:
        r = await c.get(BASE.format(country=country, lang="cs" if country == "CZ" else "en"), params={"match": number},
                        headers={"x-api-key": value("gls", "api_key").strip(), "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise ServiceError("GLS nepřijalo klíč API – zkontroluj ho v Nastavení → Propojení → GLS.")
    r.raise_for_status()
    return r.json()


def status_of(data: Any) -> tuple[str, str]:
    """(the newest event with its place, its time) from GLS's tuStatus answer; ("", "") when it does not know it."""
    items = (data or {}).get("tuStatus") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return "", ""
    tu = items[0]
    hist = [h for h in tu.get("history") or [] if isinstance(h, dict)]
    if hist:
        h = max(hist, key=lambda x: f"{x.get('date', '')} {x.get('time', '')}")
        city = ((h.get("address") or {}).get("city") or "").strip()
        text = str(h.get("evtDscr") or "").strip()
        when = f"{h.get('date', '')} {str(h.get('time', ''))[:5]}".strip()
        if text:
            return text + (f" ({city})" if city else ""), when
    bar = tu.get("progressBar") or {}
    return str(bar.get("statusText") or bar.get("statusInfo") or "").strip(), ""


async def _test(rt: Any) -> str:
    try:
        await track("00000000000")
    except ServiceError:
        raise
    except Exception:  # noqa: BLE001 – a made-up number may give 404: the key itself was accepted
        pass
    return "Propojeno – GLS přijalo klíč."


register("gls", "GLS (zásilky)", "truck", [
    {"key": "api_key", "label": "Klíč API (Track & Trace)", "secret": True, "hint": "od GLS po registraci"},
    {"key": "country", "label": "Země", "secret": False, "hint": "CZ", "optional": True},
], [
    "Zaregistruj se u GLS pro Track & Trace API (gls-group.eu → Register API access) – klíč přijde e-mailem.",
    "Vlož klíč sem a ulož – JARVIS pak u zásilek GLS ukazuje, kde právě jsou.",
], url="https://gls-group.eu/DE/en/register-api-access", what="Kde je zásilka GLS právě teď (jen čtení).", test=_test,
    group="sales")


@tool("gls_status", "GLS: kde je zásilka právě teď (podle čísla zásilky).", category="propojení", perm="network")
@guarded
async def gls_status(ctx, number: Annotated[str, "číslo zásilky GLS"]) -> ToolResult:
    n = "".join(ch for ch in str(number or "") if ch.isalnum())
    text, when = status_of(await track(n))
    if not text:
        return ToolResult(False, f"Zásilku {n} GLS nezná.")
    return ToolResult(True, f"GLS {n}: {text}" + (f" ({when})" if when else "") + ".", data={"number": n, "status": text, "when": when})
