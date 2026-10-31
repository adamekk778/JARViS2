"""Work by voice: meetings → pinned to-dos with deadlines (166), search in meetings (566 / 551), deadlines as a calendar file
(171 / 565), a content calendar (446) and the weekly work report (175)."""
from __future__ import annotations

import datetime as dt

from typing import Annotated

from .base import ToolResult, tool


def _note(ctx, ref: str):
    nt = ctx.notetaker
    rows = nt.list()
    if not rows:
        return None
    nid = ref if ref and any(r["id"] == ref for r in rows) else next((r["id"] for r in rows if r["status"] == "done"), None)
    return nt.get(nid) if nid else None


def _save(name: str, text: str):
    from ..pcreport import reports_dir

    d = reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


@tool("meeting_tasks", "Z poslední (nebo zadané) nahrané schůzky udělá připnuté úkoly – i s termínem, když v něm zazněl "
      "(„do pátku“, „do 15. 3.“). Na „udělej z té porady úkoly“.", category="produktivita")
async def meeting_tasks(ctx, note_id: Annotated[str, "id zápisu (prázdné = poslední)"] = "") -> ToolResult:
    from ..comms import due_date
    from ..uiplus import add_pin, split_due

    n = _note(ctx, note_id)
    if not n:
        return ToolResult(False, "Nemám žádnou zpracovanou schůzku.")
    if not n["todos"]:
        return ToolResult(True, f"Ve schůzce „{n['title']}“ jsem žádné úkoly nenašel.")
    made = []
    for t in n["todos"]:
        text, due = split_due(t)
        if due is None and due_date(t):                   # "do pátku", "do 15. 3." → end of that day
            due = dt.datetime.combine(dt.date.fromisoformat(due_date(t)), dt.time(17, 0)).timestamp()
        try:
            made.append(add_pin(ctx, f"{text} ({n['title'][:30]})", due))
        except ValueError as e:
            return ToolResult(bool(made), f"Připnuto {len(made)}, dál to nejde: {e}", data=made)
    return ToolResult(True, f"Připnuto {len(made)} úkolů ze schůzky „{n['title']}“" +
                      (f", {sum(1 for m in made if m['due'])} s termínem" if any(m["due"] for m in made) else "") + ".", data=made)


@tool("search_meetings", "Hledá v nahraných schůzkách a hovorech (přepisy, shrnutí, úkoly) – „kdy jsme se domluvili na ceně“, "
      "„co říkal Petr o termínu“. Vrátí schůzku a větu, kde to padlo.", category="produktivita")
async def search_meetings(ctx, query: str) -> ToolResult:
    from ..notetaker import search_notes

    hits = search_notes(ctx, query)
    if not hits:
        return ToolResult(True, f"Ve schůzkách jsem „{query}“ nenašel.", data=[])
    return ToolResult(True, "; ".join(f"{dt.datetime.fromtimestamp(h['created']).strftime('%d.%m.')} „{h['title']}“: {h['match']}" for h in hits[:5]), data=hits)


@tool("deadlines_calendar", "Termíny misí, zkoušky a připnuté úkoly s datem jako kalendářový soubor .ics – naimportuješ ho do "
      "Google / Outlook kalendáře nebo telefonu (i s připomenutím).", category="produktivita")
async def deadlines_calendar(ctx) -> ToolResult:
    from .. import workreport

    ev = workreport.milestones(ctx)
    if not ev:
        return ToolResult(True, "Nemáš žádné termíny dopředu.", data=[])
    p = _save("terminy.ics", workreport.ics(ev))
    return ToolResult(True, f"{len(ev)} termínů v souboru {p} – otevři ho a kalendář je přidá.", data={"path": str(p), "events": len(ev)},
                      attachments=[str(p)])


@tool("content_calendar", "Plán příspěvků (marketing): rozloží témata do týdnů na zvolené kanály a vytvoří kalendář .ics "
      "s připomenutím den předem.", category="produktivita")
async def content_calendar(ctx, topics: Annotated[list[str], "témata příspěvků v pořadí"], per_week: int = 2,
                           channels: Annotated[list[str] | None, "kanály, např. Instagram, Facebook"] = None,
                           start: Annotated[str, "od kdy (RRRR-MM-DD, prázdné = zítra)"] = "") -> ToolResult:
    from .. import workreport

    if not topics:
        return ToolResult(False, "Napiš aspoň jedno téma.")
    try:
        d0 = dt.date.fromisoformat(start) if start else dt.date.today() + dt.timedelta(days=1)
    except ValueError:
        return ToolResult(False, "Datum zadej jako RRRR-MM-DD.")
    ev = workreport.content_plan(topics, d0, per_week, channels)
    p = _save("obsahovy_kalendar.ics", workreport.ics(ev, "Plán příspěvků"))
    return ToolResult(True, "; ".join(f"{e['start']:%d.%m.} {e['title']}" for e in ev[:8]) + f". Kalendář: {p}",
                      data={"path": str(p), "posts": [{**e, "start": e["start"].isoformat()} for e in ev]}, attachments=[str(p)])


@tool("weekly_report", "Týdenní report práce za minulý týden: dokončené a nedokončené mise, schůzky, čas v aplikacích, "
      "nadiktovaná slova a co tě čeká příští týden – jako soubor k poslání.", category="produktivita")
async def weekly_report(ctx) -> ToolResult:
    from .. import workreport

    r = workreport.weekly_report(ctx)
    p = _save(f"tydenni_report_{r['from']}.md", workreport.report_markdown(r))
    txt = (f"Týden {r['from']} – {r['to']}: hotovo {len(r['done'])} misí" + (f", nedokončeno {len(r['failed'])}" if r["failed"] else "")
           + (f", {len(r['meetings'])} schůzek" if r["meetings"] else "") + (f", nejvíc čas v {r['apps'][0]['app']} ({r['apps'][0]['hours']} h)" if r["apps"] else "")
           + (f"; příští týden {len(r['upcoming'])} termínů" if r["upcoming"] else "") + f". Report: {p}")
    return ToolResult(True, txt, data={**r, "path": str(p)}, attachments=[str(p)])


