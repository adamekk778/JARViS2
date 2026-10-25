"""OMEGA wave 10 by voice: life events, packing by forecast, the best time to be outside, ingredient substitutes, the
shopping list by shop section, a focus report, how hard a text is, and what is still to set up."""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from .base import ToolResult, tool


def _date(s: str) -> dt.date:
    s = s.strip()
    if m := re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{4}))?", s):
        return dt.date(int(m.group(3) or dt.date.today().year), int(m.group(2)), int(m.group(1)))
    return dt.date.fromisoformat(s)


@tool("life_event_plan", "Plán životní události na časové ose (stěhování, svatba, narození dítěte, dovolená, nová práce, "
      "narozeniny, STK): co a kdy zařídit. to_list = zapsat do seznamu.", category="každý den")
async def life_event_plan(ctx, event: str, date: Annotated[str, "datum události"], to_list: str = "") -> ToolResult:
    from .. import everyday

    try:
        p = everyday.life_event(event, _date(date))
    except ValueError as e:
        return ToolResult(False, str(e))
    if to_list:
        from .list_tools import add_items

        add_items(ctx, to_list, [f"{dt.date.fromisoformat(s['date']):%d. %m.} – {s['text']}" for s in p["steps"] if not s["late"]])
    lines = [f"{dt.date.fromisoformat(s['date']):%d. %m.}{' (už mělo být)' if s['late'] else ''}: {s['text']}" for s in p["steps"]]
    return ToolResult(True, f"{p['event'].capitalize()} {dt.date.fromisoformat(p['date']):%d. %m. %Y}:\n" + "\n".join(lines), data=p)


@tool("packing_list", "Co si zabalit: podle počtu nocí, skutečné předpovědi počasí v cíli a aktivit (moře, hory, práce). "
      "to_list = zapsat do seznamu.", category="každý den", perm="network")
async def packing_list(ctx, destination: str, nights: int = 3, activities: str = "", abroad: bool = False, to_list: str = "") -> ToolResult:
    from .. import everyday

    days = None
    try:
        days = (await everyday.forecast(ctx, destination, min(16, nights + 1)))["days"]
    except Exception:  # noqa: BLE001 – without the forecast the list is still useful
        pass
    r = everyday.packing_list(nights, days, activities, abroad)
    if to_list:
        from .list_tools import add_items

        add_items(ctx, to_list, r["items"])
    why = f" (počasí: {', '.join(r['because'])})" if r["because"] else (" (předpověď se nepodařilo zjistit)" if days is None else "")
    return ToolResult(True, f"Na {nights} nocí do {destination}{why}: " + ", ".join(r["items"]) + ".", data=r)


@tool("best_time_outside", "Kdy je nejlepší čas na něco venku (běh, kolo, grilování, výlet, koupání, zahrada, mytí auta) podle "
      "hodinové předpovědi: déšť, teplota, vítr.", category="každý den", perm="network")
async def best_time_outside(ctx, activity: str = "venku", city: str = "", days: int = 3) -> ToolResult:
    from .. import everyday

    try:
        fc = await everyday.forecast(ctx, city or ctx.cfg.general.city, max(1, min(7, days)))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Předpověď nejde zjistit: {e}")
    b = everyday.best_time(fc, activity)
    if not b["best_hours"]:
        return ToolResult(True, "V nejbližších dnech nevychází žádná vhodná hodina.", data=b)
    h = b["best_hours"][0]
    t = dt.datetime.fromisoformat(h["time"])
    alt = ", ".join(f"{dt.datetime.fromisoformat(x['time']):%a %H:%M}" for x in b["best_hours"][1:3])
    return ToolResult(True, f"Na {activity} nejlépe {t:%A %d. %m. v %H:%M}: {h['temp']:.0f} °C, déšť {h['rain_pct']} %, vítr {h['wind']:.0f} km/h."
                      + (f" Jinak {alt}." if alt else ""), data=b)


@tool("ingredient_substitute", "Čím nahradit surovinu v receptu (vejce, máslo, mléko, smetana, prášek do pečiva, droždí, mouka, "
      "cukr…), i veganské a bezlepkové varianty.", category="každý den")
async def ingredient_substitute(ctx, ingredient: str) -> ToolResult:
    from .. import everyday

    s = everyday.substitute(ingredient)
    if not s:
        return ToolResult(False, f"Na „{ingredient}“ ověřenou náhradu v tabulce nemám.")
    return ToolResult(True, f"Místo {ingredient}: " + "; ".join(s) + ".", data=s)


@tool("shopping_by_aisle", "Nákupní seznam seřazený podle oddělení v obchodě (zelenina, pečivo, mléčné, maso, trvanlivé, mražené, "
      "nápoje, drogerie).", category="každý den")
async def shopping_by_aisle(ctx, list_name: str = "nákup") -> ToolResult:
    from .. import everyday
    from .list_tools import items_of

    items = [x["item"] for x in items_of(ctx, list_name)]
    if not items:
        return ToolResult(True, f"Seznam „{list_name}“ je prázdný.", data={})
    g = everyday.by_aisle(items)
    return ToolResult(True, "\n".join(f"{k}: {', '.join(v)}" for k, v in g.items()), data=g)


@tool("focus_report", "Jak ses dnes (nebo včera) soustředil: čas v práci, komunikaci, zábavě a hrách, podíl soustředění a "
      "nejproduktivnější hodina.", category="každý den")
async def focus_report(ctx, day: str = "dnes") -> ToolResult:
    from .. import everyday

    d = dt.date.today() - dt.timedelta(days=1) if day.strip().lower() in ("včera", "vcera") else dt.date.today()
    r = everyday.focus_report(ctx, d)
    if not r["total_min"]:
        return ToolResult(True, "Pro ten den nemám čas v aplikacích (zapíná se v Nastavení → Schopnosti).", data=r)
    txt = f"{d:%d. %m.}: u PC {r['total_min']} min – " + ", ".join(f"{k} {v} min" for k, v in r["minutes"].items())
    if r["focus_pct"] is not None:
        txt += f". Soustředěná práce {r['focus_pct']} %"
    if r["best_hour"] is not None:
        txt += f", nejvíc práce kolem {r['best_hour']}:00"
    return ToolResult(True, txt + ".", data=r)


@tool("reading_level", "Jak náročný je text na čtení (délka vět, dlouhá slova, čas čtení). Na zjednodušení pak použij AI.",
      category="každý den")
async def reading_level(ctx, text: str) -> ToolResult:
    from .. import everyday

    r = everyday.readability(text)
    if not r["words"]:
        return ToolResult(False, "Žádný text.")
    return ToolResult(True, f"Text je {r['level']}: {r['words']} slov, průměrná věta {r['avg_sentence']} slov, dlouhých slov "
                      f"{r['long_words_pct']} %, čtení asi {r['minutes']} min.", data=r)


@tool("setup_check", "Co už JARVIS umí a co je ještě potřeba nastavit (AI, jméno, město, hlas, e-mail, kalendář, telefon, "
      "domácnost, záloha) – s dalším krokem.", category="každý den")
async def setup_check(ctx) -> ToolResult:
    from .. import everyday

    items = everyday.setup_status(ctx)
    todo = [i for i in items if not i["ok"]]
    done = [i["title"] for i in items if i["ok"]]
    if not todo:
        return ToolResult(True, "Všechno je nastavené.", data=items)
    return ToolResult(True, f"Hotovo: {', '.join(done) or 'zatím nic'}.\nZbývá:\n" + "\n".join(f"• {i['title']} – {i['next']}" for i in todo), data=items)
