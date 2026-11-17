"""3.12 Vlastní webhook (Make, Zapier, n8n, Pipedream…): JARVIS pošle data do tvé automatizace – a ta už udělá cokoli
(zápis do CRM, SMS, faktura…). Each sending asks first: what happens next is up to the automation."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value


async def _send(payload: dict) -> Any:
    need("webhook")
    url = value("webhook", "url").strip()
    if not url.startswith("https://"):
        raise ServiceError("Adresa webhooku musí začínat https://")
    return await call("POST", url, json=payload, timeout=20)


register("webhook", "Vlastní automatizace (webhook)", "plugs-connected", [
    {"key": "url", "label": "Adresa webhooku", "secret": True, "hint": "https://hook.eu1.make.com/… nebo https://hooks.zapier.com/…"},
    {"key": "name", "label": "Co automatizace dělá (pro JARVISe)", "secret": False, "hint": "např. „zapíše lead do CRM a pošle SMS“", "optional": True},
], [
    "V Make / Zapier / n8n založ scénář se spouštěčem „Webhook“ (Custom webhook / Catch Hook).",
    "Zkopíruj jeho adresu sem, napiš, co automatizace dělá, a ulož.",
    "Pak stačí říct „pošli to do automatizace“ – JARVIS se vždy zeptá, než ji spustí.",
], url="", what="Spustí tvou automatizaci v Make, Zapieru nebo n8n s daty od JARVISe – vždy s potvrzením.", group="chat")


@tool("webhook_send", "Vlastní automatizace (Make/Zapier/n8n): pošle data do webhooku a spustí ji. Zeptá se uživatele.", danger=True,
      category="propojení", perm="network",
      details=lambda a: [f"Automatizace: {value('webhook', 'name') or 'webhook'}", f"Text: {a.get('text', '')}",
                         *[f"{k}: {v}" for k, v in (a.get("data") or {}).items()][:20]])
@guarded
async def send(ctx, text: Annotated[str, "hlavní zpráva / popis"], data: Annotated[dict, "další hodnoty {\"klic\": hodnota} (nepovinné)"] = None) -> ToolResult:  # type: ignore[assignment]
    r = await _send({"text": text, "data": data or {}, "source": "JARVIS"})
    return ToolResult(True, "Automatizace spuštěna." + (f" Odpověď: {str(r)[:200]}" if r else ""))
