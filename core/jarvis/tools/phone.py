from __future__ import annotations

import mimetypes
from pathlib import Path

from .base import ToolResult, tool
from .files import resolve


@tool("send_to_phone", "Pošle zprávu/odkaz jako notifikaci na spárovaný telefon.", category="telefon")
async def send_to_phone(ctx, text: str, title: str = "JARVIS", url: str = "") -> ToolResult:
    from ..mobileplus import clean_text, clean_url

    # OMEGA 726: a notification can sit on a lock screen – no tracking in links, no passwords or keys in the text
    text, url = clean_text(text)["text"], clean_url(url)[0] if url else url
    n = ctx.notify(title, text, url=url, speak=False, target="mobile")
    if n:
        from ..mochiplus import handoff

        handoff(ctx, "phone", title if title != "JARVIS" else (url or text), "link" if url else "text")   # OMEGA 083
    return ToolResult(True, "Odesláno na telefon" if n else "Telefon není připojený – uloženo do chatu")


@tool("send_file", "Pošle soubor z PC do chatu jako přílohu (stáhne si ho na telefonu).", category="telefon")
async def send_file(ctx, path: str) -> ToolResult:
    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    att = await ctx.store.save_path(Path(p), mime)
    return ToolResult(True, f"Posílám {p.name}", attachments=[att.id])


WATCH_QUICK = ("Co mám dnes v plánu?", "Kdy letím?", "Kde mám balík?", "Jaké bude počasí?", "Pusť hudbu")


@tool("watch_ask", "Hodinky Wear OS (přes spárovaný Android telefon): pošle tichou zprávu „Zeptej se JARVISe“ s hotovými "
      "otázkami – na hodinkách ťukneš nebo řekneš otázku a odpověď přijde zase na hodinky (a dá se pokračovat). "
      "Na „dej mi JARVISe na hodinky“, „chci se ptát z hodinek“.", category="telefon")
async def watch_ask(ctx, questions: list[str] | None = None) -> ToolResult:
    """3.17 (návrh 20) the watch: Wear OS shows the phone's notices – a quiet one with a reply (voice on the watch) and
    ready questions is the way in; each answer comes back as a notice you can reply to again."""
    from ..mobileplus import clean_text

    quick = [clean_text(str(q))["text"][:60] for q in (questions or WATCH_QUICK) if str(q).strip()][:5]
    ok = ctx.phone_push("notify", title="JARVIS", body="Zeptej se mě – odpověz na tuhle zprávu, klidně hlasem z hodinek.",
                        quiet=True, quick=quick, actions=[])
    if not ok:
        return ToolResult(False, "Telefon teď není spojený s PC – otevři na něm aplikaci JARVIS (hodinky jdou přes telefon).")
    return ToolResult(True, "Hotovo – na hodinkách (a v telefonu) máš „Zeptej se JARVISe“. Odpověď ti přijde zpátky tam.",
                      data={"quick": quick})
