"""3.14 Multitasking – tools: split into agents that work at the same time (more monitors too), see them, stop them."""
from __future__ import annotations

import asyncio
from typing import Annotated, Literal

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
                          max_agents: Annotated[int, "kolik agentů nejvýš, když je rozděluje koordinátor (1–100)"] = 12,
                          paper: Annotated[bool, "zkušební obchodování: obchody se jen zapisují na virtuální účet, nic se "
                                                 "neklikne (na „zkušebně“, „nanečisto“, „bez peněz“)"] = False) -> ToolResult:
    from ..multitask import of

    mt = of(ctx)
    try:
        s = await mt.start(goal, workers or None, max_agents, paper=paper)
    except (ValueError, PermissionError) as e:
        return ToolResult(False, str(e))
    return _started(mt, s)


def _started(mt, s) -> ToolResult:
    from ..multitask import KIND_LABEL

    kinds = {}
    for w in s.workers:
        kinds[w.kind] = kinds.get(w.kind, 0) + 1
    parts = ", ".join(f"{n}× {KIND_LABEL[k].lower()}" for k, n in kinds.items())
    lines = [f"- {w.name}" + (f" (monitor {w.monitor})" if w.monitor else "") + f": {w.task[:90]}" for w in s.workers[:12]]
    more = f"\n- …a dalších {len(s.workers) - 12}" if len(s.workers) > 12 else ""
    tips = []
    if s.paper:
        tips.append("Zkušební režim: obchody se jen zapisují na virtuální účet (Více → Agenti), nic skutečného se nekoupí.")
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


@tool("multitask_preset", "Spustí hotovou sestavu agentů: obchodni_stul (obchodník + analytik + zprávy, zkušebně), vyzkum "
      "(20 agentů prozkoumá téma), hra_fronta (hlídání fronty + tipy ke hře), porovnani (6 agentů porovná nabídky). "
      "Na „spusť obchodní stůl na BTC“, „ať 20 agentů prozkoumá …“, „porovnej nabídky na …“.", category="agenti",
      danger_if=lambda a: str(a.get("preset", "")) in ("obchodni_stul",) and a.get("paper") is False)
async def multitask_preset(ctx, preset: Annotated[str, "obchodni_stul | vyzkum | hra_fronta | porovnani"],
                           topic: Annotated[str, "co (např. BTC na Binance / Valorant / notebook do 25 000 Kč)"],
                           paper: Annotated[bool, "jen u obchodního stolu: false = skutečný účet (každý obchod schvaluješ)"] = True) -> ToolResult:
    from ..multitask import of

    mt = of(ctx)
    try:
        s = await mt.start_preset(preset, topic, paper if preset == "obchodni_stul" else None)
    except (ValueError, PermissionError) as e:
        return ToolResult(False, str(e))
    return _started(mt, s)


@tool("multitask_tell", "Napíše pokyn agentovi, který už pracuje („řekni analytikovi, ať sleduje i ETH“, „obchodníku, kupuj jen "
      "pod 2 miliony“). Agent ho dostane hned a řídí se jím.", category="agenti")
async def multitask_tell(ctx, agent: Annotated[str, "jméno agenta (nebo „monitor 2“)"], message: Annotated[str, "co mu říct"]) -> ToolResult:
    from ..multitask import of

    w = of(ctx).tell("", agent, message)
    if w is None:
        return ToolResult(False, f"Žádný běžící agent „{agent}“ – podívej se do notche (Více → Agenti).")
    return ToolResult(True, f"Předáno agentovi {w.name}.")


@tool("multitask_schedule", "Naplánuje agenty na čas: „každé ráno v 8 ať 10 agentů projde trhy a zprávy“, „v pátek v 18 spusť "
      "obchodní stůl na BTC“. repeat: once | daily | weekdays | weekly.", category="agenti")
async def multitask_schedule(ctx, time: Annotated[str, "HH:MM nebo datum a čas"],
                             goal: Annotated[str, "co mají agenti udělat (když není sestava)"] = "",
                             preset: Annotated[str, "nebo hotová sestava: obchodni_stul | vyzkum | hra_fronta | porovnani"] = "",
                             topic: Annotated[str, "téma sestavy"] = "",
                             repeat: Literal["once", "daily", "weekdays", "weekly"] = "daily",
                             days: Annotated[list[int], "pro weekly: dny 0=po … 6=ne"] = (),
                             max_agents: Annotated[int, "kolik agentů (1–100)"] = 10) -> ToolResult:
    import datetime as dt

    from ..multitask import PRESETS
    from .timers import parse_when

    if not goal.strip() and preset not in PRESETS:
        return ToolResult(False, "Řekni, co mají agenti udělat, nebo vyber sestavu (" + ", ".join(PRESETS) + ").")
    if preset and preset in PRESETS and not topic.strip():
        return ToolResult(False, f"Sestava {PRESETS[preset]['name']} potřebuje: {PRESETS[preset]['ask']}.")
    when = parse_when(time)
    if repeat == "once":
        spec = {"type": "once", "at": when.timestamp()}
    else:
        dd = {"daily": list(range(7)), "weekdays": [0, 1, 2, 3, 4], "weekly": list(days) or [dt.datetime.now().weekday()]}[repeat]
        spec = {"type": "daily", "time": when.strftime("%H:%M"), "days": dd}
    payload = {"goal": goal.strip(), "preset": preset if preset in PRESETS else "", "topic": topic.strip(),
               "max_agents": max(1, min(int(max_agents or 10), 100))}
    title = (PRESETS[preset]["name"] + f": {topic}") if payload["preset"] else f"Agenti: {goal.strip()[:60]}"
    if getattr(ctx, "scheduler", None) is None:
        return ToolResult(False, "Plánovač teď neběží – zkus to za chvíli znovu.")
    job = ctx.scheduler.add(spec, "multitask", payload, title)
    return ToolResult(True, f"Naplánováno ({job['spec_text']}): {title}", data=job)


@tool("monitor_check", "Test monitorů: na každém monitoru přesune myš doprostřed (bez kliknutí) a ověří, že JARVIS míří "
      "správně a vidí ten monitor. Na „vyzkoušej monitory“, „míří JARVIS dobře na druhý monitor?“.",
      category="ovládání počítače", perm="input")
async def monitor_check(ctx) -> ToolResult:
    from ..multitask import check_monitors

    r = await check_monitors(ctx)
    return ToolResult(r["ok"], r["text"], data=r)


@tool("paper_trade", "Zkušební obchod bez peněz: zapíše nákup/prodej na virtuální účet za danou cenu („zkušebně kup BTC za "
      "1000 Kč při ceně 2 000 000“).", category="finance")
async def paper_trade(ctx, side: Annotated[str, "buy / sell"], symbol: Annotated[str, "např. BTC"],
                      price: Annotated[float, "cena za kus"], czk: Annotated[float, "za kolik Kč (u prodeje prázdné = vše)"] = 0) -> ToolResult:
    from .. import papertrade

    pt = papertrade.of(ctx)
    try:
        t = pt.trade(side, symbol, price, czk, who="JARVIS")
    except ValueError as e:
        return ToolResult(False, str(e))
    word = "Nákup" if t["side"] == "buy" else "Prodej"
    return ToolResult(True, f"{word} {t['qty']} {t['symbol']} za {t['czk']:,.0f} Kč zapsán.\n".replace(",", " ") + pt.describe(),
                      data=t)


@tool("paper_portfolio", "Stav zkušebního obchodování: hodnota virtuálního účtu, zisk/ztráta, co držíš a poslední obchody.",
      category="finance")
async def paper_portfolio(ctx) -> ToolResult:
    from .. import papertrade

    pt = papertrade.of(ctx)
    return ToolResult(True, pt.describe(), data=pt.summary())


@tool("paper_reset", "Začne zkušební obchodování znovu s danou virtuální částkou (výchozí 10 000 Kč).", category="finance")
async def paper_reset(ctx, cash: Annotated[float, "kolik virtuálních Kč na začátek"] = 10000) -> ToolResult:
    from .. import papertrade

    pt = papertrade.of(ctx)
    pt.reset(cash)
    return ToolResult(True, pt.describe())
