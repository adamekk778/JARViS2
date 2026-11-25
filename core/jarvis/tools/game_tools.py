"""3.13 Herní pomocník – tools: playing time and results, a tip on request, and "dej mi vědět, až najde zápas"."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated

from .base import ToolResult, tool

WATCH_EVERY_S = 6.0
WATCH_MAX_MIN = 30


@tool("game_stats", "Herní statistiky: kolik a co uživatel hrál (posledních N dní), výhry a prohry, které si zapsal.",
      category="hry")
async def game_stats(ctx, days: Annotated[int, "kolik dní zpět (1–90)"] = 7) -> ToolResult:
    from ..gamecoach import describe_stats

    s = ctx.gamecoach.stats(max(1, min(int(days or 7), 90)))
    return ToolResult(True, describe_stats(s), data=s)


@tool("game_result", "Zapíše výsledek zápasu do herních statistik („vyhrál jsem 13:7“, „prohra ve Valorantu“).", category="hry")
async def game_result(ctx, result: Annotated[str, "výhra / prohra / remíza"], score: Annotated[str, "skóre, např. 13:7"] = "",
                      game: Annotated[str, "hra (prázdné = ta, co běží nebo běžela naposled)"] = "") -> ToolResult:
    try:
        r = ctx.gamecoach.log_result(result, score, game)
    except ValueError as e:
        return ToolResult(False, str(e))
    word = {"win": "Výhra", "loss": "Prohra", "draw": "Remíza"}[r["result"]]
    from ..funx import coach_for                         # 3.20 (341) one piece of advice from your own numbers

    tip = coach_for(ctx, r["game"])
    return ToolResult(True, f"{word} v {r['game']}{' ' + score if score else ''} zapsána." + (f" {tip}" if tip else ""), data=r)


@tool("game_tip", "Dá tip ke hře, kterou uživatel právě hraje (nebo ke jmenované), a ukáže ho v notchi.", category="hry")
async def game_tip(ctx, game: Annotated[str, "hra (prázdné = ta, co běží)"] = "") -> ToolResult:
    coach = ctx.gamecoach
    g = (game or coach.game or "").strip()
    if not g:
        return ToolResult(False, "Teď nic nehraješ – řekni, ke které hře chceš tip.")
    tip = coach.next_tip(g)
    coach.show_tip(g, tip)
    return ToolResult(True, tip)


def _yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(re.match(r"^\W*(ano|yes|jo|true)\b", t))


@tool("screen_wait_for", "Hlídá obrazovku a dá vědět (notch + telefon), až se na ní objeví, co uživatel chce – např. „dej mi "
      "vědět, až najde zápas“, „až se dostahuje hra“, „až skončí render“. Dívá se každých pár vteřin, nejvýš 30 minut.",
      category="hry")
async def screen_wait_for(ctx, what: Annotated[str, "co čekat na obrazovce, např. „nalezený zápas / výběr agenta“"],
                       minutes: Annotated[int, "jak dlouho nejvýš hlídat (1–30)"] = 15) -> ToolResult:
    if not ctx.cfg.permissions.screen:
        return ToolResult(False, "Hlídání obrazovky potřebuje oprávnění Obrazovka (Nastavení → Oprávnění).")
    minutes = max(1, min(int(minutes or 15), WATCH_MAX_MIN))

    async def watch() -> None:
        from .computer_use import _shrink

        end = time.monotonic() + minutes * 60
        while time.monotonic() < end:
            try:
                png = await asyncio.to_thread(ctx.platform.screenshot)
                url, _ = await asyncio.to_thread(_shrink, png, 960)
                reply = await ctx.router.complete([
                    {"role": "system", "content": "Odpovídáš jen „ano“ nebo „ne“."},
                    {"role": "user", "content": [{"type": "text", "text": f"Je teď na obrazovce: {what}?"},
                                                 {"type": "image_url", "image_url": {"url": url}}]}], need_vision=True)
                if _yes(reply):
                    ctx.notify("Je to tady", f"{what[:1].upper() + what[1:]} – právě teď na obrazovce.", urgent=True,
                               actions=[{"label": "Ok", "action": "dismiss"}])
                    ctx.phone_push("notify", title="JARVIS: je to tady", body=f"{what} – právě teď na obrazovce PC.")
                    return
            except Exception:  # noqa: BLE001 – one bad look is not the end
                pass
            await asyncio.sleep(WATCH_EVERY_S)
        ctx.notify("Hlídání skončilo", f"Za {minutes} min se „{what}“ neobjevilo.", speak=False)

    from ..background import bg

    bg(watch())
    return ToolResult(True, f"Hlídám obrazovku – jakmile uvidím „{what}“, dám vědět sem i do telefonu (nejvýš {minutes} min).")
