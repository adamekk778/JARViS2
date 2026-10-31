"""OMEGA wave 8 by voice: what to do next (and in a spare moment), forgotten work, unanswered questions, routines,
deadline risks, effort estimate, what you did today, and whether now is a good time to interrupt."""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


@tool("what_next", "Co dělat teď: návrhy dalšího kroku s důvodem (hořící termíny, kartičky na řadě, nedořešené rozhovory, co "
      "touhle dobou obvykle děláš, co se hodí k aplikaci, ve které právě jsi, zapomenuté úkoly). minutes = jen věci, které stihneš za tolik minut.", category="proaktivita")
async def what_next(ctx, minutes: Annotated[float, "kolik mám času (0 = nezáleží)"] = 0) -> ToolResult:
    from .. import proactive

    try:
        app = await asyncio.to_thread(ctx.platform.foreground_app)      # OMEGA 501: what fits the app in front
    except Exception:  # noqa: BLE001
        app = ""
    s = proactive.next_actions(ctx, minutes, app=app if app and "jarvis" not in app.lower() else "")
    if not s:
        return ToolResult(True, "Nic nehoří – nemám žádný návrh." if not minutes else f"Na {minutes:g} minut nemám nic vhodného.", data=[])
    return ToolResult(True, "\n".join(f"{i + 1}. {x['text']} – {x['why']} (~{x['minutes']} min)" for i, x in enumerate(s[:6])), data=s)


@tool("forgotten_work", "Na co se zapomnělo: mise, které stojí, projekty bez práce a staré položky v seznamech.", category="proaktivita")
async def forgotten_work(ctx, days: int = 7) -> ToolResult:
    from .. import proactive

    f = proactive.forgotten(ctx, max(1, days))
    u = proactive.unfinished_conversations(ctx, 14)
    if not f and not u:
        return ToolResult(True, "Nic zapomenutého jsem nenašel.", data={"forgotten": [], "unanswered": []})
    lines = [x["text"] for x in f[:8]] + [f"Konverzace „{x['title']}“: {x['why']}" for x in u[:5]]
    return ToolResult(True, "\n".join(lines), data={"forgotten": f, "unanswered": u})


@tool("my_routines", "Tvoje rutiny: které aplikace používáš ve stejnou hodinu v řadě dní (všední dny / víkend) – s návrhem "
      "automatizace (např. „ráno otevři poštu“).", category="proaktivita")
async def my_routines(ctx) -> ToolResult:
    from .. import proactive

    r = proactive.routines(ctx)
    if not r:
        return ToolResult(True, "Zatím nemám dost dat (měří se čas v aplikacích po hodinách, potřebuji pár dní).", data=[])
    return ToolResult(True, "\n".join(x["text"] for x in r[:8]) + "\nChceš z některé udělat automatizaci (create_automation)?", data=r)


@tool("deadline_risks", "Které termíny jsou v ohrožení: mise s termínem (kolik zbývá času a kroků) a zkoušky bez opakování.",
      category="proaktivita")
async def deadline_risks(ctx) -> ToolResult:
    from .. import proactive

    r = proactive.deadline_risks(ctx)
    if not r:
        return ToolResult(True, "Nemáš žádné termíny, které bych hlídal.", data=[])
    return ToolResult(True, "\n".join(f"[{x['risk']}] {x['text']}" for x in r), data=r)


@tool("estimate_effort", "Odhad, jak dlouho úkol zabere – podle tvých podobných dokončených misí.", category="proaktivita")
async def estimate_effort(ctx, task: str) -> ToolResult:
    from .. import proactive

    r = proactive.effort_estimate(ctx, task)
    if not r["known"]:
        return ToolResult(True, "Podobný úkol jsme ještě nedělali, odhad z vlastních dat nemám.", data=r)
    return ToolResult(True, f"Podobných úkolů {r['similar']}: obvykle {r['median_minutes']} min a {r['median_actions']} kroků "
                      f"(např. „{r['examples'][0][:60]}“).", data=r)


@tool("day_summary", "Co jsem dnes (nebo včera) udělal: dokončené mise, zprávy, diktování, opakování, kde jsem trávil čas.",
      category="proaktivita")
async def day_summary(ctx, day: Annotated[str, "dnes / včera / RRRR-MM-DD"] = "dnes") -> ToolResult:
    from .. import proactive

    d = dt.date.today() - dt.timedelta(days=1) if day.strip().lower() in ("včera", "vcera") else \
        dt.date.fromisoformat(day) if len(day) == 10 and day[4] == "-" else dt.date.today()
    s = proactive.day_summary(ctx, d)
    parts = [f"{d:%d. %m.}: dokončeno {len(s['missions_done'])} misí" + (f" ({', '.join(m[:40] for m in s['missions_done'][:3])})" if s["missions_done"] else ""),
             f"{s['messages']} zpráv JARVISovi"]
    if s["dictations"]:
        parts.append(f"nadiktováno asi {s['dictated_words']} slov")
    if s["card_reviews"]:
        parts.append(f"{s['card_reviews']} opakování kartiček")
    if s["top_apps"]:
        parts.append("nejvíc času: " + ", ".join(f"{a['app']} {a['minutes']} min" for a in s["top_apps"]))
    return ToolResult(True, ", ".join(parts) + ".", data=s)


@tool("quiet_status", "Je teď vhodná chvíle na hlasová upozornění? (noc, schůzka, soustředění, hra/film přes celou obrazovku)",
      category="proaktivita")
async def quiet_status(ctx) -> ToolResult:
    from .. import proactive

    why = proactive.quiet_reason(ctx)
    on = getattr(ctx.cfg.stark, "smart_quiet", True)
    if not on:
        return ToolResult(True, "Chytré ztišení je vypnuté – JARVIS mluví kdykoli.")
    return ToolResult(True, f"Teď mlčím ({why}); upozornění se jen ukážou. Budík, časovač a připomínky ale vždy řeknu nahlas." if why
                      else "Teď můžu upozornění říkat nahlas.", data={"quiet": bool(why), "reason": why})
