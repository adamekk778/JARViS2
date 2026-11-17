"""3.12 Discord: poslat zprávu do kanálu přes webhook (s potvrzením)."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value


def _url() -> str:
    u = value("discord", "webhook").strip()
    if not u.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/", "https://ptb.discord.com/api/webhooks/",
                         "https://canary.discord.com/api/webhooks/")):
        raise ServiceError("Tohle není adresa Discord webhooku (začíná https://discord.com/api/webhooks/…).")
    return u


async def _test(rt: Any) -> str:
    need("discord")
    w = await call("GET", _url())
    return f"Webhook „{w.get('name', '?')}“ funguje."


register("discord", "Discord (webhook)", "discord-logo", [
    {"key": "webhook", "label": "Adresa webhooku", "secret": True, "hint": "https://discord.com/api/webhooks/…"},
], [
    "Na Discordu: nastavení kanálu (ozubené kolo) → Integrace → Webhooky → Nový webhook.",
    "Pojmenuj ho (např. JARVIS) → Kopírovat URL webhooku → vlož sem a ulož.",
], url="", what="Posílání zpráv do kanálu (oznámení, shrnutí) – vždy s potvrzením.", test=_test, group="chat",
    probe={"method": "GET", "url": "https://discord.com/api/webhooks/1/FAKE"})


@tool("discord_send", "Discord: pošle zprávu do kanálu (webhook). Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: str(a.get("text", "")).splitlines()[:20])
@guarded
async def send(ctx, text: Annotated[str, "zpráva (max 2000 znaků)"]) -> ToolResult:
    need("discord")
    await call("POST", _url(), json={"content": text[:2000], "username": "JARVIS"})
    return ToolResult(True, "Zpráva je na Discordu.")
