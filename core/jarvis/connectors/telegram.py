"""3.12 Telegram (bot): co ti lidé napsali botovi / do skupin s botem, a poslat zprávu (s potvrzením). Bot token od @BotFather."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value


async def _api(method: str, transport=None, **body) -> Any:
    need("telegram")
    r = await call("POST", f"https://api.telegram.org/bot{value('telegram', 'token')}/{method}", json=body or None, transport=transport)
    if not r.get("ok"):
        raise ServiceError(f"Telegram: {r.get('description', 'chyba')}")
    return r.get("result")


async def _test(rt: Any) -> str:
    me = await _api("getMe")
    return f"Bot @{me.get('username')} funguje."


register("telegram", "Telegram (bot)", "telegram-logo", [
    {"key": "token", "label": "Bot token", "secret": True, "hint": "123456:ABC…"},
    {"key": "chat_id", "label": "Výchozí chat (nepovinné)", "secret": False, "hint": "id chatu nebo @kanal", "optional": True},
], [
    "V Telegramu napiš @BotFather → /newbot → název a uživatelské jméno bota.",
    "Zkopíruj token, který pošle, sem a ulož.",
    "Napiš svému botovi cokoli (nebo ho přidej do skupiny) – JARVIS pak zprávy uvidí a zjistí id chatu.",
], url="https://t.me/BotFather", what="Zprávy pro tvého bota a ze skupin s ním; poslat zprávu jen s potvrzením.", test=_test, group="chat",
    probe={"method": "GET", "url": "https://api.telegram.org/bot123456:FAKE/getMe"})


@tool("telegram_messages", "Telegram: poslední zprávy, které přišly botovi (od koho, z jakého chatu, id chatu).", category="propojení",
      perm="network")
@guarded
async def messages(ctx) -> ToolResult:
    ups = await _api("getUpdates", limit=100, allowed_updates=["message", "channel_post"])
    out = []
    for u in ups or []:
        m = u.get("message") or u.get("channel_post") or {}
        if not m:
            continue
        chat, who = m.get("chat") or {}, m.get("from") or {}
        out.append({"chat_id": chat.get("id"), "chat": chat.get("title") or chat.get("username") or chat.get("first_name"),
                    "from": " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x) or who.get("username"),
                    "text": (m.get("text") or m.get("caption") or "")[:500], "date": m.get("date")})
    return ToolResult(True, f"{len(out)} zpráv.", data=out[-50:])


@tool("telegram_send", "Telegram: pošle zprávu botem do chatu. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Chat: {a.get('chat_id', '') or 'výchozí'}", *str(a.get("text", "")).splitlines()[:20]])
@guarded
async def send(ctx, text: Annotated[str, "zpráva"], chat_id: Annotated[str, "id chatu (prázdné = výchozí)"] = "") -> ToolResult:
    cid = chat_id or value("telegram", "chat_id")
    if not cid:
        return ToolResult(False, "Nevím, kam poslat – napiš botovi zprávu a vyber chat z telegram_messages, nebo nastav výchozí chat.")
    await _api("sendMessage", chat_id=cid, text=text[:4000])
    return ToolResult(True, "Zpráva odeslána.")
