"""3.14 Multitasking – tools: split into agents that work at the same time (more monitors too), see them, stop them."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


def agents_word(n: int) -> str:
    """Czech: 1 agenta, 2–4 agenty, 5+ agentů (whom JARVIS started)."""
    return f"{n} agenta" if n == 1 else f"{n} agenty" if 2 <= n <= 4 else f"{n} agentů"


def _has_screen(args: dict) -> bool:
    return any(isinstance(w, dict) and str(w.get("kind", "")).lower() == "screen" for w in (args.get("workers") or []))


@tool("list_monitors", "Seznam monitorů připojených k PC (číslo, rozlišení, který je hlavní) – pro práci na víc monitorech.",
      category="ovládání počítače", perm="screen")
async def list_monitors(ctx) -> ToolResult:
    mons = await asyncio.to_thread(ctx.platform.monitors)
    lines = [f"Monitor {m['index']}: {m['width']}×{m['height']}{' (hlavní)' if m.get('primary') else ''}" for m in mons]
    return ToolResult(True, "\n".join(lines) or "Žádný monitor.", data=mons)


@tool("multitask_start", "Multitasking: rozdělí se na víc agentů, kteří pracují ZÁROVEŇ na pozadí (až 100) – uživatel s tebou "
      "mezitím dál mluví. Na „dělej víc věcí najednou“, „na jednom monitoru … a na druhém …“, „rozděl se na agenty“, „ať na "
      "tom pracuje 20 agentů“. Druhy agentů: work (hledá, počítá, píše – bez myši), screen (ovládá myší a klávesnicí jeden "
      "monitor: aplikace, menu hry, obchodní platforma), watch (jen sleduje jeden monitor a hodnotí ho, např. „vyplatí se, "
      "nebo ne“). Bez workers je rozdělí koordinátor sám (max_agents). Peníze (nákup, prodej, platba, obchod) vždy schvaluje "
      "uživatel.", category="agenti", danger_if=_has_screen)
async def multitask_start(ctx, goal: Annotated[str, "celý cíl, např. „na monitoru 1 obchoduj, na monitoru 2 hlídej, jestli se to vyplatí“"],
                          workers: Annotated[list[dict], "agenti: [{name, kind: work|screen|watch, task, monitor (1 = hlavní), "
                                                         "app, minutes}] – prázdné = rozdělí koordinátor"] = None,
                          max_agents: Annotated[int, "kolik agentů nejvýš, když je rozděluje koordinátor (1–100)"] = 12) -> ToolResult:
    from ..multitask import KIND_LABEL, of

    mt = of(ctx)
    try:
        s = await mt.start(goal, workers or None, max_agents)
    except (ValueError, PermissionError) as e:
        return ToolResult(False, str(e))
    kinds = {}
    for w in s.workers:
        kinds[w.kind] = kinds.get(w.kind, 0) + 1
    parts = ", ".join(f"{n}× {KIND_LABEL[k].lower()}" for k, n in kinds.items())
    lines = [f"- {w.name}" + (f" (monitor {w.monitor})" if w.monitor else "") + f": {w.task[:90]}" for w in s.workers[:12]]
    more = f"\n- …a dalších {len(s.workers) - 12}" if len(s.workers) > 12 else ""
    tips = []
    if any(w.kind == "screen" for w in s.workers):
        tips.append("Ovládající agenti se střídají o jednu myš a klávesnici; hru dej do režimu „Okno bez okrajů“, jinak ji klik "
                    "na jiném monitoru schová. Každý nákup, prodej nebo platbu ti dám nejdřív ke schválení.")
    slots = mt.state()["parallel"]
    if len(s.workers) > slots:
        tips.append(f"Najednou se AI ptá {slots} agentů (Nastavení → Mozek → Multitasking), ostatní se střídají.")
    return ToolResult(True, f"Spustil jsem {agents_word(len(s.workers))} ({parts}), pracují na pozadí – uvidíš je v notchi (Více → "
                            f"Agenti) a na konci dám vědět.\n" + "\n".join(lines) + more + ("\n\n" + " ".join(tips) if tips else ""),
                      data={"session": s.id, "workers": [w.public() for w in s.workers]})


@tool("multitask_status", "Co teď dělají agenti multitaskingu: kdo běží, co zjistil, verdikty sledujících agentů, shrnutí.",
      category="agenti")
async def multitask_status(ctx) -> ToolResult:
    from ..multitask import of

    st = of(ctx).state()
    if not st["sessions"]:
        return ToolResult(True, "Žádní agenti teď neběží.", data=st)
    out = []
    for s in st["sessions"][:3]:
        c = s["count"]
        out.append(f"„{s['goal'][:80]}“ – běží {c['running']}, čeká {c['waiting']}, hotovo {c['done']}, chyba {c['failed']}, "
                   f"zastaveno {c['stopped']}")
        for w in s["workers"][:15]:
            where = f" monitor {w['monitor']}" if w["monitor"] else ""
            said = (w["verdict"] + " · " if w["verdict"] else "") + (w["last"] or "")[:140]
            out.append(f"  - {w['name']} [{w['state']}]{where}: {said}")
        if s["summary"]:
            out.append(f"  Shrnutí: {s['summary'][:600]}")
    return ToolResult(True, "\n".join(out), data=st)


@tool("multitask_stop", "Zastaví agenty multitaskingu – všechny, nebo jednoho podle jména („zastav agenta na monitoru 2“).",
      category="agenti")
async def multitask_stop(ctx, name: Annotated[str, "jméno agenta (prázdné = všechny)"] = "") -> ToolResult:
    from ..multitask import of

    mt = of(ctx)
    if not name.strip():
        n = mt.stop(why="Zastaveno na tvůj pokyn.")
        return ToolResult(True, f"Zastavil jsem {agents_word(n)}." if n else "Žádní agenti neběží.")
    low = name.strip().lower()
    n = 0
    for s in mt.sessions.values():
        for w in s.workers:
            if low in w.name.lower() or low == f"monitor {w.monitor}" or low == str(w.monitor):
                n += mt.stop(s.id, w.id, "Zastaveno na tvůj pokyn.")
    return ToolResult(bool(n), f"Zastavil jsem {agents_word(n)}." if n else f"Agenta „{name}“ nevidím.")
