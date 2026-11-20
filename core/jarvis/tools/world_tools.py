"""3.13 Přehled o světě – tools: what is going on (JARVIS's own reading of the news) and asking Google with sources."""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


def _when(ts: float) -> str:
    try:
        return dt.datetime.fromtimestamp(float(ts)).strftime("%d. %m. %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


@tool("world_news", "Co se teď děje ve světě: přehled a čerstvé titulky ze zpráv, které JARVIS sám pravidelně čte "
      "(Česko, svět, technologie, AI, hry, sport… i vlastní zájmy). Na „co je nového“, „co se děje“, „zprávy o …“.",
      category="web")
async def world_news(ctx, topic: Annotated[str, "téma: cz / world / tech / ai / business / science / sport / games, "
                                                 "nebo vlastní slovo (např. Valorant); prázdné = vše"] = "",
                     hours: Annotated[int, "jak čerstvé (hodiny, 1–168)"] = 24) -> ToolResult:
    from .. import worldwatch

    ww = ctx.world
    hours = max(1, min(int(hours or 24), 168))
    t = (topic or "").strip()
    tid = ""
    if t:
        low = t.lower()
        tid = next((k for k, (label, _u) in worldwatch.TOPICS.items() if low in (k, label.lower())), "")
        if not tid:
            tid = next((f for f, _l, _u in ww.feeds() if f == f"i:{low}"), "")
    items = ww.headlines(tid, hours, 12) if (tid or not t) else []
    if t and not items:
        # not one of its feeds (or a topic switched off): read the news about it right now
        try:
            raw = await ww.fetch_query(t, url=worldwatch.TOPICS[tid][1] if tid in worldwatch.TOPICS else "")
            items = raw[:12]
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Zprávy o „{t}“ se teď nepodařilo načíst ({e}). Zkus web_search.")
    if not items and not t and ww.enabled():
        try:
            await ww.refresh()
            items = ww.headlines("", hours, 12)
        except Exception:  # noqa: BLE001
            items = []
    digest = ww.digest() if not t else {}
    lines = [f"- {h['title']} ({h.get('source') or '?'}, {_when(h.get('published', 0))})" for h in items]
    head = ""
    if digest.get("text"):
        head = f"Můj přehled ({_when(digest.get('at', 0))}):\n{digest['text']}\n\n"
    if not lines and not head:
        return ToolResult(False, "Zatím nemám načtené žádné zprávy – zkus web_search, nebo za chvíli znovu.")
    return ToolResult(True, head + ("Titulky:\n" + "\n".join(lines) if lines else ""),
                      data={"digest": digest.get("text", ""), "items": items})


@tool("google_ask", "Zeptá se Googlu (přes Gemini s Google vyhledáváním) a vrátí odpověď z dnešního webu i se zdroji. "
      "Na otázky, kde záleží na aktuálnosti a přesnosti: výsledky, ceny, kurzy, kdo vyhrál, kdy vychází, co se stalo. "
      "Bez klíče Gemini hledá přes web_search.", category="web")
async def google_ask(ctx, question: Annotated[str, "otázka celou větou"]) -> ToolResult:
    from .. import worldwatch
    from .web import _ddg

    try:
        r = await worldwatch.google_answer(ctx, question)
        if r["text"]:
            src = "\n".join(f"- {s['title'] or s['url']}: {s['url']}" for s in r["sources"][:5])
            return ToolResult(True, r["text"] + (f"\n\nZdroje:\n{src}" if src else ""), data=r)
    except LookupError:
        pass                       # no Gemini key: the plain web search below
    except Exception as e:  # noqa: BLE001 – Google down or out of limit: the plain web search below
        import logging

        logging.getLogger(__name__).debug("google_ask: %s", e)
    try:
        res = await asyncio.to_thread(_ddg, question, 6, False)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Na internet se teď nedostanu ({e}).")
    items = [{"title": x.get("title"), "url": x.get("href") or x.get("url"), "snippet": x.get("body") or ""} for x in res]
    if not items:
        return ToolResult(False, f"Na „{question}“ jsem nic nenašel.")
    text = "\n".join(f"- {i['title']}: {i['snippet']} ({i['url']})" for i in items)
    return ToolResult(True, f"Výsledky hledání (bez Gemini, odpověz z nich):\n{text}", data={"text": "", "sources": items})


@tool("world_interest", "Přidá nebo odebere téma, které má JARVIS sledovat ve zprávách („sleduj zprávy o Valorantu“, "
      "„přestaň sledovat Bitcoin“).", category="web")
async def world_interest(ctx, topic: Annotated[str, "téma, např. Valorant / Sparta Praha / Bitcoin"],
                         add: Annotated[bool, "true = sledovat, false = přestat"] = True) -> ToolResult:
    t = (topic or "").strip()
    if not t:
        return ToolResult(False, "Řekni, jaké téma mám sledovat.")
    cur = [x for x in ctx.cfg.world.interests if x.strip().lower() != t.lower()]
    if add:
        if len(cur) >= 8:
            return ToolResult(False, "Sleduji už 8 vlastních témat – nějaké nejdřív odeber.")
        cur.append(t)
    ctx.update_config({"world": {"interests": cur}})
    if add:
        from ..background import bg

        bg(ctx.world.refresh())
        return ToolResult(True, f"Budu sledovat zprávy o „{t}“ – přehled o nich mám od teď v každé odpovědi.")
    return ToolResult(True, f"Zprávy o „{t}“ už nesleduji.")
