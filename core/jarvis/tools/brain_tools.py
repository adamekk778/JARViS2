"""OMEGA wave 5 by voice: specialist agents (delegate, a team with handover), deep research with checked citations,
alternatives / risks / assumptions, several AI models compared, a goal turned into a tracked plan, and the real checks
the specialists use (read-only SQL, accessibility audit, translation check)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


@tool("list_agents", "Seznam specialistů, kterým může JARVIS předat práci (architekt, tester, výkon, databáze, devops, "
      "dokumentace, přístupnost, překlady, výzkum, bezpečnost) a jaké mají nástroje.", category="agenti")
async def list_agents(ctx) -> ToolResult:
    from .. import agents

    return ToolResult(True, "; ".join(f"{a['name']} ({k})" for k, a in agents.AGENTS.items()),
                      data={k: {"name": a["name"], "role": a["role"], "tools": a["tools"]} for k, a in agents.AGENTS.items()})


@tool("delegate_to_agent", "Předá úkol specialistovi (architekt, tester, vykon, databaze, devops, dokumentace, pristupnost, "
      "preklady, vyzkum, bezpecnost). Pracuje se svými nástroji stejnými pravidly (potvrzování, oprávnění) a vrátí "
      "výsledek. Na „ať to otestuje tester“, „nech architekta posoudit projekt“.", category="agenti")
async def delegate_to_agent(ctx, agent: Annotated[str, "který specialista"], task: Annotated[str, "co přesně má udělat"],
                            context: str = "") -> ToolResult:
    from .. import agents

    key = agents.find(agent)
    if not key:
        return ToolResult(False, f"Specialistu „{agent}“ neznám. Mám: {', '.join(agents.AGENTS)}.")
    r = await agents.run(ctx, key, task, context)
    used = ", ".join(sorted({c["name"] for c in r["tools"]})) or "žádné"
    return ToolResult(r["ok"], f"{r['agent']} ({r['seconds']} s, nástroje: {used}): {r['answer']}",
                      data={k: r[k] for k in ("agent", "answer", "tools")}, attachments=r["attachments"])


@tool("agent_team", "Tým specialistů za sebou: každý dostane výsledek předchozího (např. architekt navrhne → tester ověří → "
      "dokumentace sepíše). steps = seznam {agent, task}, max 6.", category="agenti")
async def agent_team(ctx, steps: Annotated[list[dict], "[{agent, task}]"]) -> ToolResult:
    from .. import agents

    rs = await agents.team(ctx, steps)
    return ToolResult(all(r["ok"] for r in rs), "\n\n".join(f"**{r['agent']}**: {r['answer']}" for r in rs),
                      data=[{k: r.get(k) for k in ("agent", "answer", "ok")} for r in rs])


@tool("agent_swarm", "Tým specialistů najednou: koordinátor rozdělí cíl mezi specialisty (programátor, 3D, elektronika, "
      "tester, výzkum, architekt…), co na sobě nezávisí, dělají zároveň, a nakonec výsledky spojí. Na „ať na tom "
      "pracuje celý tým“, „udělejte to společně“. Každý dodržuje stejná pravidla (potvrzení, oprávnění).", category="agenti")
async def agent_swarm(ctx, goal: Annotated[str, "co má tým udělat"]) -> ToolResult:
    from .. import agents

    try:
        r = await agents.swarm(ctx, goal)
    except (ValueError, json.JSONDecodeError) as e:
        return ToolResult(False, f"Tým se nepodařilo sestavit: {e}")
    waves = " → ".join(" + ".join(agents.AGENTS[a]["name"] for a in w) for w in r["waves"])
    atts = [a for x in r["results"] for a in x.get("attachments", [])]
    return ToolResult(r["ok"], f"Postup týmu: {waves}.\n\n{r['summary']}", attachments=atts,
                      data={"waves": r["waves"], "results": [{k: x.get(k) for k in ("agent", "answer", "ok", "seconds")} for x in r["results"]]})


@tool("deep_research", "Hloubkový výzkum: víc vyhledávání, přečte nejlepší zdroje a sepíše report, kde je každé tvrzení "
      "doložené citací [n] na skutečně přečtený zdroj; citace zkontroluje a report uloží. Na „zjisti všechno o…“, "
      "„udělej rešerši“.", category="web", perm="network")
async def deep_research(ctx, question: Annotated[str, "otázka"], max_sources: int = 6) -> ToolResult:
    from .. import thinking

    try:
        r = await thinking.deep_research(ctx, question, max(2, min(10, max_sources)))
    except ValueError as e:
        return ToolResult(False, str(e))
    art = ctx.tasks.add_artifact(Path(r["path"]), "Výzkumný report")
    c = r["check"]
    ctx.tasks.add_evidence("kontrola citací", "každá citace odkazuje na přečtený zdroj", f"{c['citations']} citací, neplatné: {c['invalid'] or 'žádné'}", c["ok"])
    note = "" if c["ok"] else " Pozor: některé citace nesedí – ber report opatrně."
    return ToolResult(True, f"{r['report'][:1500]}\n\nZdroje: " + "; ".join(f"[{i + 1}] {s['url']}" for i, s in enumerate(r["sources"]))
                      + f"\nReport: {r['path']}.{note}", data={**r, "sha256": art["sha256"]})


@tool("compare_options", "Varianty řešení: 3 různé cesty k cíli s kroky, plusy, minusy, rizikem, náklady, časem, předpoklady a "
      "důsledky; seřadí je, řekne co chybí vědět a jak moc si je jistý. Na „jak bys to udělal“, „co je lepší“, „mám "
      "koupit/zvolit…“.", category="agenti")
async def compare_options(ctx, goal: Annotated[str, "cíl nebo rozhodnutí"], context: str = "") -> ToolResult:
    from .. import thinking

    try:
        d = await thinking.compare_options(ctx, goal, context)
    except ValueError as e:
        return ToolResult(False, str(e))
    lines = []
    for o in d["options"]:
        lines.append(f"• {o.get('name')}: riziko {o.get('risk', '?')}/5 ({o.get('risk_why', '')}); + {', '.join(o.get('pros') or [])}; − {', '.join(o.get('cons') or [])}")
    txt = "\n".join(lines) + f"\nDoporučuji: {d['ranking'][0]} – {d.get('why_best', '')}. Jistota {d['confidence']} % ({d.get('confidence_why', '')})."
    if d.get("missing_info"):
        txt += " Chybí vědět: " + "; ".join(d["missing_info"]) + "."
    return ToolResult(True, txt, data=d)


@tool("check_assumptions", "Najde v plánu skryté předpoklady, jejich riziko a jak je ověřit.", category="agenti")
async def check_assumptions(ctx, plan: Annotated[str, "plán nebo záměr"]) -> ToolResult:
    from .. import thinking

    try:
        d = await thinking.check_assumptions(ctx, plan)
    except ValueError as e:
        return ToolResult(False, str(e))
    a = sorted(d.get("assumptions") or [], key=lambda x: -int(x.get("risk") or 0))
    return ToolResult(True, "\n".join(f"• {x.get('text')} (riziko {x.get('risk')}/5) – ověřit: {x.get('how_to_verify')}" for x in a), data=a)


@tool("ask_models", "Položí stejnou otázku několika AI modelům (poskytovatelům v Nastavení → Mozek) a porovná je: kde se "
      "shodují, kde ne, společná odpověď a jistota podle shody. Na „zeptej se víc AI“, „ověř to u jiného modelu“.",
      category="agenti", perm="network")
async def ask_models(ctx, question: Annotated[str, "otázka"]) -> ToolResult:
    from .. import thinking

    d = await thinking.ask_models(ctx, question)
    if not d["compared"]:
        one = next((a["answer"] for a in d["answers"] if a.get("answer")), "")
        return ToolResult(bool(one), (one + "\n\n" if one else "") + d["note"], data=d)
    txt = f"Shoda modelů {d['agreement']} % (jistota {d['confidence']}). {d['consensus']}"
    if d["disagree"]:
        txt += "\nRozdíly: " + "; ".join(d["disagree"])
    return ToolResult(True, txt, data=d)


@tool("goal_plan", "Režim cíle: z cíle udělá plán po fázích s akceptačními kritérii a riziky a založí z něj sledovanou misi "
      "(kritéria a kroky uvidíš v Úkolech). Pak postupně plň kroky. Na „chci …, naplánuj to“, „pomoz mi dosáhnout …“.",
      category="agenti")
async def goal_plan(ctx, goal: Annotated[str, "cíl"]) -> ToolResult:
    from .. import thinking

    try:
        d = await thinking.goal_plan(ctx, goal)
    except ValueError as e:
        return ToolResult(False, str(e))
    ctx.tasks.set_criteria(d.get("criteria") or [f"Cíl splněn: {goal}"])
    ctx.tasks.set_plan(d["flat_steps"], 0)
    txt = "\n".join(f"{ph.get('name')}: " + "; ".join((s.get("text") if isinstance(s, dict) else str(s)) for s in ph.get("steps") or [])
                    for ph in d.get("phases") or [])
    txt += "\nHotovo, když: " + "; ".join(d.get("criteria") or [])
    if d.get("needs_from_user"):
        txt += "\nPotřebuji od tebe: " + "; ".join(d["needs_from_user"])
    return ToolResult(True, txt + f"\nPrvní krok: {d.get('first_step', d['flat_steps'][0])}", data=d)


# ---------------------------------------------------------------------------------------------- the specialists' checks
@tool("sql_query", "Dotaz do databáze SQLite JEN PRO ČTENÍ (SELECT/WITH/PRAGMA/EXPLAIN). Bez dotazu vrátí schéma (tabulky a "
      "indexy).", category="soubory", perm="files_read")
async def sql_query(ctx, path: Annotated[str, "soubor .db / .sqlite"], query: str = "") -> ToolResult:
    from .. import devcheck

    p = resolve(path)
    try:
        if not query:
            s = await asyncio.to_thread(devcheck.sql_schema, p)
            return ToolResult(True, f"{len(s)} tabulek/indexů: " + ", ".join(x["name"] for x in s), data=s)
        r = await asyncio.to_thread(devcheck.sql_query, p, query)
    except (ValueError, Exception) as e:  # noqa: BLE001 – sqlite errors are user-facing
        return ToolResult(False, str(e)[:300])
    return ToolResult(True, f"{len(r['rows'])} řádků ({', '.join(r['columns'])})" + (" – zkráceno" if r["truncated"] else ""), data=r)


@tool("a11y_check", "Kontrola přístupnosti webové stránky (soubor .html nebo adresa): popisky obrázků, formuláře, kontrast, "
      "nadpisy, odkazy, jazyk, ovládání klávesnicí – podle WCAG, s číslem pravidla a řádkem.", category="web", perm="files_read")
async def a11y_check(ctx, path_or_url: Annotated[str, "soubor nebo URL"]) -> ToolResult:
    from .. import devcheck

    src = path_or_url.strip()
    if src.startswith(("http://", "https://")):
        async with ctx.http() as c:
            r = await c.get(src, timeout=20)
        html = r.text
    else:
        p = resolve(src)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        html = p.read_text(encoding="utf-8", errors="replace")
    d = devcheck.a11y_audit(html)
    bad = [i for i in d["issues"] if i["level"] == "bad"]
    head = f"Skóre přístupnosti {d['score']}/100: {len(bad)} chyb, {len(d['issues']) - len(bad)} upozornění."
    return ToolResult(True, head + (" " + "; ".join(f"ř. {i['line']}: {i['text']} (WCAG {i['rule']})" for i in d["issues"][:8]) if d["issues"] else " Nic jsem nenašel."), data=d)


@tool("check_translation", "Zkontroluje překlad souboru s texty aplikace (JSON, .po, .properties) proti originálu: chybějící "
      "klíče, rozbité zástupné znaky ({name}, %s), nepřeložené texty.", category="soubory", perm="files_read")
async def check_translation(ctx, source: Annotated[str, "originál"], translated: Annotated[str, "překlad"]) -> ToolResult:
    from .. import devcheck

    try:
        r = await asyncio.to_thread(devcheck.check_translation, resolve(source), resolve(translated))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    parts = [f"{r['keys']} klíčů"]
    for k, label in (("missing", "chybí"), ("placeholders", "rozbité zástupné znaky"), ("untranslated", "nepřeloženo"), ("extra", "navíc")):
        if r[k]:
            parts.append(f"{label} {len(r[k])} ({', '.join(r[k][:4])})")
    return ToolResult(r["ok"], ("Překlad je v pořádku: " if r["ok"] else "Překlad má chyby: ") + ", ".join(parts) + ".", data=r)
