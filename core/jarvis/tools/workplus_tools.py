"""Wave 42 by voice: recurring meetings (are they worth it, how do they go), a folder per meeting, programming exercises,
learning through a project and a private status page for a client."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool


def _has(ctx, table: str) -> bool:
    return bool(ctx.db.one("SELECT name FROM sqlite_master WHERE name=?", (table,)))


def _series(ctx, days: int):
    from .. import workplus

    since = time.time() - days * 86400
    events = ctx.db.all("SELECT * FROM cal_events WHERE start >= ?", (since,)) if _has(ctx, "cal_events") else []
    notes = ctx.db.all("SELECT created, seconds, points, todos, transcript FROM notes WHERE created >= ?", (since,)) if _has(ctx, "notes") else []
    return workplus.meeting_series(events, notes)


@tool("meeting_relevance", "Které opakované schůzky za to stojí: kolik hodin měsíčně zaberou, kolik jich přineslo úkoly nebo "
      "rozhodnutí – a doporučení nechat / zkrátit / zředit / zrušit.", category="kalendář")
async def meeting_relevance(ctx, days: int = 90) -> ToolResult:
    s = _series(ctx, days)
    if not s:
        return ToolResult(True, "Nevidím žádné opakované schůzky (aspoň 3× stejný název).", data=[])
    return ToolResult(True, "; ".join(f"{x['title']}: {x['hours_month']:g} h/měsíc – {x['verdict']} ({x['why']})" for x in s[:5]) + ".", data=s)


@tool("meeting_review", "Jak probíhá opakovaná schůzka: přetahování, jestli výstupů přibývá nebo ubývá a kdo kolik mluví – "
      "z nahraných hovorů.", category="kalendář")
async def meeting_review(ctx, name: str, days: int = 120) -> ToolResult:
    from ..comms import fold

    s = [x for x in _series(ctx, days) if fold(name) in fold(x["title"]) or fold(name) in x["series"]]
    if not s:
        return ToolResult(False, f"Opakovanou schůzku „{name}“ nevidím.")
    x = s[0]
    parts = [f"{x['title']}: {x['count']}× za období, {x['minutes']} min, nahráno {x['recorded']}, přínosných {x['useful']}"]
    if x["avg_overrun_min"] is not None:
        parts.append(f"v průměru {'přetahuje o' if x['avg_overrun_min'] > 0 else 'končí dřív o'} {abs(x['avg_overrun_min']):g} min")
    if x["trend"]:
        parts.append(f"trend: {x['trend']}")
    if x["talk_share"]:
        parts.append("mluví: " + ", ".join(f"{k} {v} %" for k, v in list(x["talk_share"].items())[:4]))
    return ToolResult(True, "; ".join(parts) + f". Doporučení: {x['verdict']}.", data=x)


@tool("meeting_folder", "Složka pro schůzku: zápis (shrnutí, body, úkoly, přepis) a kopie dokumentů, které vznikly nebo se "
      "upravovaly kolem ní.", category="kalendář", perm="files_read")
async def meeting_folder(ctx, meeting: Annotated[str, "název schůzky (poslední s tímto názvem)"], include_files: bool = True) -> ToolResult:
    from .. import workplus
    from ..comms import fold

    ev = None
    if _has(ctx, "cal_events"):
        ev = next((e for e in ctx.db.all("SELECT * FROM cal_events WHERE start <= ? ORDER BY start DESC", (time.time() + 86400,))
                   if fold(meeting) in fold(e["title"])), None)
    note = None
    if _has(ctx, "notes"):
        rows = ctx.db.all("SELECT * FROM notes ORDER BY created DESC")
        note = next((n for n in rows if ev and ev["start"] - 600 <= n["created"] <= ev["end"] + 600), None) or \
            next((n for n in rows if fold(meeting) in fold(n["title"] or "")), None)
    if not ev and not note:
        return ToolResult(False, f"Schůzku „{meeting}“ nevidím v kalendáři ani v nahrávkách.")
    start = ev["start"] if ev else note["created"]
    end = ev["end"] if ev else note["created"] + (note.get("seconds") or 3600)
    related = await asyncio.to_thread(workplus.files_around, workplus._default_roots(), start, end) if include_files else []
    r = await asyncio.to_thread(workplus.meeting_folder, ev["title"] if ev else (note["title"] or meeting), start, note, related, paths.sub("schuzky"))
    return ToolResult(True, f"Složka schůzky: {r['folder']} – zápis{' s přepisem' if note and note.get('transcript') else ''}"
                            + (f", {len(r['copied'])} dokumentů" if r["copied"] else "") + ".", data=r, attachments=[str(Path(r["folder"]) / "schuzka.md")])


@tool("coding_exercise", "Dá programovací úlohu v Pythonu (podle obtížnosti 1–3) se zadáním, ukázkami a skrytými testy. "
      "Řešení pak zkontroluje coding_check.", category="učení")
async def coding_exercise(ctx, level: int = 0, topic: Annotated[str, "konkrétní úloha (např. palindrom), prázdné = náhodná"] = "") -> ToolResult:
    from .. import workplus

    key = next((k for k in workplus.EXERCISES if topic and topic.lower().replace(" ", "_") in k), "")
    ex = workplus.make_exercise(key, max(0, min(level, 3)))
    ctx.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('coding_exercise', ?)", (json.dumps(ex, ensure_ascii=False, default=str),))
    examples = "; ".join(f"solve({', '.join(repr(a) for a in t['args'])}) → {t['expected']!r}" for t in ex["examples"])
    return ToolResult(True, f"Úloha „{ex['title']}“ (obtížnost {ex['level']}): {ex['task']} Příklady: {examples}. "
                            f"Testů je {len(ex['tests'])}. Až budeš mít řešení, pošli mi kód.", data={k: v for k, v in ex.items() if k != "tests"})


def _not_users_code(a: dict, ctx=None) -> bool:
    """The code must be what the user wrote in their last message – code made up by the AI is run only after confirmation."""
    code = " ".join(str(a.get("code", "")).split())
    if not code or ctx is None:
        return True
    last = ctx.db.one("SELECT content FROM messages WHERE role='user' ORDER BY created DESC LIMIT 1") if _has(ctx, "messages") else None
    return not last or code not in " ".join((last["content"] or "").split())


def _check_details(a: dict, ctx=None) -> list[str]:
    return ["Spustí tento kód v odděleném procesu (časový limit 10 s):", str(a.get("code", ""))[:600]]


@tool("coding_check", "Zkontroluje tvoje řešení programovací úlohy skrytými testy (spustí tvůj kód odděleně s časovým limitem).",
      category="učení", perm="shell", danger_if=_not_users_code, details=_check_details)
async def coding_check(ctx, code: str) -> ToolResult:
    from .. import workplus

    row = ctx.db.one("SELECT v FROM kv WHERE k='coding_exercise'")
    if not row:
        return ToolResult(False, "Nejdřív si řekni o úlohu (coding_exercise).")
    ex = json.loads(row["v"])
    r = await asyncio.to_thread(workplus.check_solution, code, ex["tests"])
    if r.get("error"):
        return ToolResult(True, f"Řešení nejde ověřit: {r['error']}", data=r)
    if r["ok"]:
        return ToolResult(True, f"Výborně – všech {r['total']} testů prošlo! Chceš těžší úlohu?", data=r)
    f = r["fails"][0]
    return ToolResult(True, f"Prošlo {r['passed']} z {r['total']}. Například pro {f['args']} čekám {f['expected']!r}, tvoje funkce vrací {f['got']}.", data=r)


@tool("learning_project", "Učení na projektu: k cíli („chci se naučit dělat weby“) vybere projekt s 5 kroky, ke každému co "
      "se naučit a jak poznat hotovo; sleduje postup a kartičky pojmů přidá do opakování.", category="učení")
async def learning_project(ctx, goal: str = "", done_step: int = 0) -> ToolResult:
    from .. import workplus

    p = workplus.learning_project(ctx)
    if goal and (not p or not done_step):
        p = workplus.start_learning_project(ctx, goal)
        steps = " → ".join(m["title"] for m in p["milestones"])
        return ToolResult(True, f"Projekt „{p['title']}“: {steps}. Začni krokem 1: {p['next']['title']} – nauč se {', '.join(p['next']['concepts'])}. "
                                f"Hotovo je, když: {p['next']['check']} Pojmy jsou v kartičkách.", data=p)
    if not p:
        return ToolResult(False, "Žádný rozjetý projekt nemám – řekni, co se chceš naučit.")
    if done_step:
        try:
            p = workplus.complete_milestone(ctx, p["id"], done_step)
        except (KeyError, ValueError) as e:
            return ToolResult(False, str(e))
    if p["finished"]:
        return ToolResult(True, f"Projekt „{p['title']}“ je hotový – gratuluju! 🎉", data=p)
    n = p["next"]
    return ToolResult(True, f"„{p['title']}“: {p['progress']} % hotovo. Další krok {n['n']}: {n['title']} – nauč se {', '.join(n['concepts'])}. "
                            f"Hotovo je, když: {n['check']}", data=p)


@tool("client_portal", "Soukromá stránka pro klienta: jeho nabídky a stav požadavků na jedné adrese, kterou mu pošleš "
      "(nepublikuje se nikam, adresa je tajná). Při dalším spuštění se obnoví na stejné adrese.", category="byznys", perm="network")
async def client_portal(ctx, client: str, note: str = "") -> ToolResult:
    from .. import workplus
    from ..comms import fold
    from ..server.pairing import local_ips
    from .sites import sites_dir

    f = fold(client)
    quotes = [q for q in (ctx.db.all("SELECT * FROM quotes ORDER BY created DESC") if _has(ctx, "quotes") else []) if f in fold(q["client"] or "")]
    reqs = [r for r in (ctx.db.all("SELECT * FROM customer_requests ORDER BY created DESC") if _has(ctx, "customer_requests") else []) if f in fold(r["client"] or "")]
    if not quotes and not reqs:
        return ToolResult(False, f"U klienta „{client}“ nemám žádné nabídky ani požadavky.")
    name = (quotes or reqs)[0]["client"]
    page = workplus.portal_html(name, quotes, reqs, ctx.cfg.general.user_name if hasattr(ctx.cfg.general, "user_name") else "", note)
    r = await asyncio.to_thread(workplus.write_portal, name, page, sites_dir())
    lan, ts = local_ips()
    host = (ts or lan or ["127.0.0.1"])[0]
    url = f"http://{host}:{ctx.cfg.phone.port}/sites/{r['id']}/index.html"
    return ToolResult(True, f"Přehled pro {name}: {len(quotes)} nabídek, {len(reqs)} požadavků. Adresa (jen pro klienta): {url}",
                      data={**r, "url": url}, preview=f"/sites/{r['id']}/index.html")


@tool("exercise_list", "Seznam programovacích úloh, které umím zadat.", category="učení")
async def exercise_list(ctx) -> ToolResult:
    from .. import workplus

    items = [workplus.make_exercise(k, seed=1) for k in workplus.EXERCISES]
    return ToolResult(True, "; ".join(f"{e['title']} ({e['level']})" for e in items) + ".", data=[{"id": e["id"], "title": e["title"], "level": e["level"]} for e in items])

