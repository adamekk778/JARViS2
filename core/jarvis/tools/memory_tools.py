from __future__ import annotations

import datetime as dt
from typing import Annotated

from .base import ToolResult, tool


def _source(ctx) -> str:
    """Where a fact came from (OMEGA 042): the conversation and the day."""
    mem = ctx.memory
    try:
        row = ctx.db.one("SELECT title FROM conversations WHERE id=?", (mem.current_conversation,))
    except Exception:  # noqa: BLE001 – a minimal context in tests
        row = None
    title = (row or {}).get("title") or "konverzace"
    return f"řekl jsi v konverzaci „{title}“ {dt.date.today():%d. %m. %Y}"


@tool("remember", "Zapamatuje si trvale fakt o uživateli (jméno, preference, důležité věci). Uloží i odkud to ví a do "
      "které kategorie to patří; když to odporuje dřívějšímu faktu, zeptej se uživatele, co platí.", category="paměť")
async def remember(ctx, fact: str, project: Annotated[str, "jen pro projekt (prázdné = aktuální projekt / obecně)"] = "") -> ToolResult:
    from ..redact import looks_secret

    if looks_secret(fact):
        return ToolResult(False, "Hesla, PINy a klíče si z bezpečnostních důvodů nepamatuji.")
    know = getattr(ctx, "knowledge", None)
    if know is None:
        ctx.memory.remember(fact)
        return ToolResult(True, f"Zapamatováno: {fact}")
    r = know.add_fact(fact, _source(ctx), project or None)
    if not r["stored"]:
        return ToolResult(r["reason"] == "už to vím", {"už to vím": "Tohle už vím.", "soukromý režim": "Jsi v soukromém režimu – nic si neukládám."}.get(r["reason"], "Nic jsem neuložil."))
    if r["conflicts"]:
        old = "; ".join(c["text"] for c in r["conflicts"])
        return ToolResult(True, f"Zapamatováno ({r['category']}). Pozor, dřív jsem si zapsal: „{old}“. Zeptej se, co platí – "
                          "staré můžu smazat (resolve_memory_conflict).", data=r)
    return ToolResult(True, f"Zapamatováno ({r['category']}): {fact}", data=r)


@tool("forget", "Zapomene fakt (podle části textu).", category="paměť")
async def forget(ctx, fact: str) -> ToolResult:
    n = ctx.memory.forget(fact)
    return ToolResult(n > 0, f"Zapomenuto: {n}")


@tool("search_history", "Prohledá historii konverzací.", category="paměť")
async def search_history(ctx, query: str) -> ToolResult:
    hits = ctx.memory.search(query, limit=15)
    return ToolResult(True, f"{len(hits)} zpráv", data=hits)


KIND = {"chat": "chat", "fact": "paměť", "dictation": "diktování", "call": "hovor", "mission": "mise"}


@tool("search_memory", "Prohledá VŠECHNO, co JARVIS má: konverzace, zapamatovaná fakta, diktování, nahrané hovory a mise. "
      "Nevadí jiný tvar slova ani chybějící diakritika; s místním modelem v Ollamě hledá i podle významu. Na „kdy jsme "
      "se bavili o…“, „co jsem říkal o…“, „najdi, kde jsem diktoval…“.", category="paměť")
async def search_memory(ctx, query: Annotated[str, "co hledat"], limit: int = 10) -> ToolResult:
    know = ctx.knowledge
    hits = know.search(query, limit)
    sem = await know.semantic(query, limit) if len(hits) < limit else {"available": False, "hits": []}
    seen = {(h["kind"], h["ref"]) for h in hits}
    hits += [h for h in sem["hits"] if (h["kind"], h["ref"]) not in seen][:limit - len(hits)]
    if not hits:
        return ToolResult(True, "Nic jsem nenašel." + ("" if sem.get("available") else " (Hledání podle významu půjde, až bude v Ollamě model na embeddingy.)"), data=[])
    lines = [f"{KIND.get(h['kind'], h['kind'])} {dt.datetime.fromtimestamp(h['ts']):%d. %m. %Y}: {h['title']} – {h['snippet']}" for h in hits[:limit]]
    return ToolResult(True, "\n".join(lines), data=hits)


@tool("memory_timeline", "Časová osa dne: konverzace, mise, diktování, nahrané hovory, co si JARVIS zapamatoval, kde jsi "
      "trávil čas. Na „co jsem včera dělal“, „co jsme dneska řešili“.", category="paměť")
async def memory_timeline(ctx, day: Annotated[str, "dnes, včera, nebo datum RRRR-MM-DD / D. M."] = "dnes") -> ToolResult:
    import re

    d = dt.date.today()
    s = day.strip().lower()
    if s in ("včera", "vcera"):
        d -= dt.timedelta(days=1)
    elif s in ("předevčírem", "predevcirem"):
        d -= dt.timedelta(days=2)
    elif re.fullmatch(r"\d{4}-\d\d-\d\d", s):
        d = dt.date.fromisoformat(s)
    elif m := re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{4}))?", s):
        d = dt.date(int(m.group(3) or d.year), int(m.group(2)), int(m.group(1)))
    ev = ctx.knowledge.timeline(d)
    if not ev:
        return ToolResult(True, f"{d:%d. %m. %Y} jsem nic nezaznamenal.", data=[])
    return ToolResult(True, f"{d:%d. %m. %Y}: " + "; ".join(f"{dt.datetime.fromtimestamp(e['ts']):%H:%M} {e['text']}" for e in ev[:20]), data=ev)


@tool("memory_conflicts", "Rozpory v paměti: fakta, která si odporují (např. dvě různé adresy). Ukáže je, ať uživatel řekne, co platí.",
      category="paměť")
async def memory_conflicts(ctx) -> ToolResult:
    cs = ctx.knowledge.open_conflicts()
    if not cs:
        return ToolResult(True, "V paměti nejsou žádné rozpory.", data=[])
    return ToolResult(True, "; ".join(f"#{c['id']}: dřív „{c['old_text']}“, nově „{c['new_text']}“" for c in cs), data=cs)


@tool("resolve_memory_conflict", "Vyřeší rozpor v paměti podle uživatele: keep = new (platí nové, staré smaž), old (platí "
      "staré), both (obojí je pravda).", category="paměť")
async def resolve_memory_conflict(ctx, id: int, keep: Annotated[str, "new / old / both"] = "new") -> ToolResult:
    try:
        r = ctx.knowledge.resolve_conflict(int(id), keep)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, {"new": "Platí nové, staré jsem smazal.", "old": "Platí staré, nové jsem smazal.", "both": "Nechávám obojí."}[r["kept"]])


@tool("memory_overview", "Co JARVIS o uživateli ví, rozdělené do kategorií (Rodina, Práce, Zdraví, Preference…), s původem "
      "každé informace.", category="paměť")
async def memory_overview(ctx) -> ToolResult:
    cats = ctx.knowledge.by_category()
    if not cats:
        return ToolResult(True, "Zatím si nic nepamatuji.", data={})
    return ToolResult(True, "; ".join(f"{k}: {len(v)}" for k, v in sorted(cats.items(), key=lambda kv: -len(kv[1]))),
                      data={k: [{"text": f["text"], "source": f["source"], "project": f["project"]} for f in v] for k, v in cats.items()})


# ---------------------------------------------------------------------------------------------- projects
@tool("project_create", "Založí projekt s vlastní pamětí (fakta, konverzace ve složce projektu, mise, soubory). Volitelně "
      "složka na disku a poznámka, o co jde.", category="paměť")
async def project_create(ctx, name: str, folder: str = "", note: str = "", switch: bool = True) -> ToolResult:
    try:
        p = ctx.knowledge.create_project(name, folder, note)
    except ValueError as e:
        return ToolResult(False, str(e))
    if switch:
        ctx.knowledge.switch(p["name"])
    return ToolResult(True, f"Projekt „{p['name']}“ založen" + (" a je aktuální." if switch else "."), data=p)


@tool("project_switch", "Přepne aktuální projekt (jeho fakta a poznámka se použijí v odpovědích, ostatní projekty ne). "
      "Prázdný název = bez projektu.", category="paměť")
async def project_switch(ctx, name: str = "") -> ToolResult:
    try:
        p = ctx.knowledge.switch(name)
    except ValueError as e:
        names = ", ".join(x["name"] for x in ctx.knowledge.projects())
        return ToolResult(False, f"{e} Projekty: {names or 'žádné'}.")
    return ToolResult(True, f"Pracujeme na projektu „{p['name']}“." if p else "Teď bez projektu.")


@tool("project_list", "Seznam projektů a který je aktuální.", category="paměť")
async def project_list(ctx) -> ToolResult:
    ps, cur = ctx.knowledge.projects(), ctx.knowledge.current_project()
    if not ps:
        return ToolResult(True, "Zatím žádné projekty.", data=[])
    return ToolResult(True, ", ".join(f"{p['name']}{' (aktuální)' if p['name'] == cur else ''}" for p in ps), data=ps)


@tool("project_resume", "Navázání na projekt: poslední konverzace a co jsem naposledy odpověděl, rozdělané mise, nedávno "
      "změněné soubory projektu, zapamatovaná fakta a doporučený další krok. Na „kde jsme skončili s …“.", category="paměť")
async def project_resume(ctx, name: str = "") -> ToolResult:
    know = ctx.knowledge
    name = name or know.current_project()
    if not name:
        return ToolResult(False, "Který projekt? " + (", ".join(p["name"] for p in know.projects()) or "Zatím žádné nemám."))
    try:
        r = know.resume(name)
    except ValueError as e:
        return ToolResult(False, str(e))
    know.switch(r["project"]["name"])
    parts = [f"Projekt {r['project']['name']}."]
    if r["conversations"]:
        parts.append("Naposledy: „" + r["conversations"][0]["title"] + f"“ ({dt.datetime.fromtimestamp(r['conversations'][0]['updated']):%d. %m.}).")
    if r["last_answer"]:
        parts.append(f"Moje poslední odpověď: {r['last_answer'][:200]}")
    open_t = [t for t in r["tasks"] if t["status"] not in ("done", "cancelled")]
    if open_t:
        parts.append("Rozdělané mise: " + ", ".join(t["goal"][:60] for t in open_t[:3]) + ".")
    if r["files"]:
        from pathlib import Path

        parts.append("Nedávné soubory: " + ", ".join(Path(f["path"]).name for f in r["files"][:4]) + ".")
    if r["facts"]:
        parts.append("Vím: " + "; ".join(r["facts"][:5]) + ".")
    parts.append(f"Další krok: {r['next']}.")
    return ToolResult(True, " ".join(parts), data=r)
