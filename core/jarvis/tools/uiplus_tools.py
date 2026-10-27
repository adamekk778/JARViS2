"""Wave 33 by voice: small pinned to-dos shown in the notch (OMEGA 093) and the quick actions for the app in front (089)."""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


def _when(ts: float | None) -> str:
    if not ts:
        return ""
    d = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    day = "dnes" if d.date() == today else "zítra" if d.date() == today + dt.timedelta(days=1) else d.strftime("%d. %m.")
    return f" ({day} {d:%H:%M})"


@tool("pin_task", "Připne malý úkol do notche (volitelně s časem: „v 15:30“, „zítra v 9“, „za 20 minut“); v ten čas připomene.",
      category="rozhraní")
async def pin_task(ctx, text: Annotated[str, "co připnout"], when: Annotated[str, "kdy, prázdné = bez času"] = "") -> ToolResult:
    from .. import uiplus

    if when.strip():
        due = uiplus.parse_due(when)
    else:
        text, due = uiplus.split_due(text)
    try:
        p = uiplus.add_pin(ctx, text, due)
    except ValueError as e:
        return ToolResult(False, str(e))
    uiplus.publish_pins(ctx)
    return ToolResult(True, f"Připnuto do notche: {p['text']}{_when(p['due'])}.", data=p)


@tool("pinned_tasks", "Co mám připnuté v notchi (malé úkoly a jejich časy).", category="rozhraní")
async def pinned_tasks(ctx) -> ToolResult:
    from .. import uiplus

    pins = uiplus.list_pins(ctx)
    if not pins:
        return ToolResult(True, "V notchi nemáš nic připnutého.", data={"items": []})
    return ToolResult(True, "Připnuté: " + "; ".join(f"{i}. {p['text']}{_when(p['due'])}" for i, p in enumerate(pins, 1)) + ".",
                      data={"items": pins})


@tool("pin_done", "Odškrtne připnutý úkol jako hotový (podle pořadí nebo části textu).", category="rozhraní")
async def pin_done(ctx, which: Annotated[str, "pořadí (1, 2…) nebo část textu"]) -> ToolResult:
    from .. import uiplus

    p = uiplus.find_pin(ctx, which.strip())
    if not p:
        return ToolResult(False, f"Mezi připnutými nevidím „{which}“.")
    uiplus.set_done(ctx, p["id"])
    uiplus.publish_pins(ctx)
    return ToolResult(True, f"Hotovo: {p['text']}.")


@tool("unpin_task", "Odepne úkol z notche bez odškrtnutí (podle pořadí nebo části textu).", category="rozhraní")
async def unpin_task(ctx, which: Annotated[str, "pořadí nebo část textu"]) -> ToolResult:
    from .. import uiplus

    p = uiplus.find_pin(ctx, which.strip())
    if not p:
        return ToolResult(False, f"Mezi připnutými nevidím „{which}“.")
    uiplus.remove_pin(ctx, p["id"])
    uiplus.publish_pins(ctx)
    return ToolResult(True, f"Odepnuto: {p['text']}.")


@tool("app_quick_actions", "Jaké rychlé akce nabízí notch pro aplikaci, která je teď vepředu.", category="rozhraní")
async def app_quick_actions(ctx) -> ToolResult:
    from .. import uiplus

    c = uiplus.app_context(ctx)
    names = ", ".join(a["label"] for a in c["actions"])
    return ToolResult(True, f"Pro {c['app'] or 'aktuální okno'}: {names}.", data=c)
