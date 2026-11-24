"""3.14 Mozek jako ve filmu: night learning, the life timeline, missions over days, what-if simulations."""
from __future__ import annotations

import time
from typing import Annotated

from .base import ToolResult, tool


# ---------------------------------------------------------------------------------------------- 52 night learning
@tool("night_learn", "Noční učení: co se JARVIS naučil z chyb (opravy uživatele, co neuměl, co selhávalo) – poslední noc, nebo "
      "projde dnešek hned teď. „Co ses v noci naučil?“", category="mozek")
async def night_learn(ctx, now: Annotated[bool, "projít to hned teď (jinak ukázat poslední noc)"] = False) -> ToolResult:
    from .. import nightlearn

    if now:
        r = await nightlearn.run(ctx)
    else:
        r = nightlearn.last(ctx)
        if not r:
            return ToolResult(True, "Zatím jsem žádnou noc neučil – proběhne v noci při údržbě, nebo řekni „projdi dnešní chyby“.")
    text = nightlearn.morning_line(ctx, now=r.get("at")) or (
        f"Prošel jsem {r.get('corrections', 0)} oprav a {r.get('cant', 0)} věcí, které jsem neuměl – nic nového k zapamatování.")
    return ToolResult(True, text, data=r)


# ---------------------------------------------------------------------------------------------- 53 the life timeline
@tool("life_day", "Paměť života: co jsem dělal v určitý den („co jsem dělal minulé úterý“, „včera“, „12. 11.“) – aplikace a okna "
      "s časem, poznámky, hovory a cesty toho dne. Jen když je Paměť života zapnutá; data jsou šifrovaná a jen v PC.",
      category="paměť")
async def life_day(ctx, day: Annotated[str, "který den: dnes, včera, minulé úterý, 12. 11. …"] = "včera") -> ToolResult:
    from .. import lifelog

    if not getattr(ctx.cfg.privacy, "life_log", False):
        return ToolResult(True, "Paměť života je vypnutá. Zapneš ji v Nastavení → Soukromí (nebo „zapni paměť života“) – "
                          "pak si budu šifrovaně a jen v tomhle PC pamatovat, na čem jsi pracoval.")
    d = lifelog.parse_day(day)
    if d is None:
        return ToolResult(False, "Nerozumím, který den – řekni třeba „včera“, „minulé úterý“ nebo „12. 11.“.")
    s = lifelog.day_summary(ctx, d)
    return ToolResult(True, lifelog.describe_day(s), data=s)


@tool("life_note", "Zapíše poznámku do Paměti života („zapiš do deníku, že jsem dnes dokončil prezentaci“).", category="paměť")
async def life_note(ctx, text: Annotated[str, "co zapsat"]) -> ToolResult:
    from .. import lifelog

    if not getattr(ctx.cfg.privacy, "life_log", False):
        return ToolResult(False, "Paměť života je vypnutá – nejdřív ji zapni („zapni paměť života“).")
    lifelog.add(ctx, "note", {"text": text.strip()[:500]})
    return ToolResult(True, "Zapsáno do paměti života.")


@tool("life_log_set", "Zapne nebo vypne Paměť života (šifrovaný deník dní u PC, jen v tomto PC), nastaví, kolik dní se drží, "
      "nebo ji celou smaže.", category="paměť", perm="files_write",
      danger_if=lambda a: str(a.get("action", "")).lower() in ("wipe", "smazat"))
async def life_log_set(ctx, action: Annotated[str, "on / off / wipe (smazat vše)"], days: Annotated[int, "kolik dní držet (0 = beze změny)"] = 0) -> ToolResult:
    from .. import lifelog

    a = (action or "").strip().lower()
    patch: dict = {}
    if a in ("on", "zapnout", "zapni"):
        patch["life_log"] = True
    elif a in ("off", "vypnout", "vypni"):
        patch["life_log"] = False
    elif a in ("wipe", "smazat", "smaž"):
        n = lifelog.wipe(ctx)
        return ToolResult(True, f"Paměť života smazána ({n} záznamů) i s klíčem.")
    if int(days or 0) > 0:
        patch["life_log_days"] = max(1, min(int(days), 3650))
    if patch:
        ctx.update_config({"privacy": patch})
    p = ctx.cfg.privacy
    return ToolResult(True, ("Paměť života je zapnutá" if p.life_log else "Paměť života je vypnutá") +
                      f", drží {p.life_log_days} dní. Šifrovaná (AES-GCM, klíč v trezoru Windows), nikam se neposílá; "
                      "hesla, bankovnictví a anonymní okna se nezapisují.")


# ---------------------------------------------------------------------------------------------- 54 missions over days
@tool("quest_start", "Dlouhá mise na dny: JARVIS každých pár hodin udělá další krok (hledá, čte, porovnává – nic nekupuje ani "
      "neposílá), pamatuje si průběh a dá vědět, jen když najde něco nového. „Hlídej byty 2+kk v Brně do 6 mil.“, "
      "„celý týden sleduj zprávy o…“.", category="agenti")
async def quest_start(ctx, goal: Annotated[str, "co hlídat / zjišťovat a kdy dát vědět"],
                      every_hours: Annotated[float, "jak často krok (hodiny, min. 1)"] = 6,
                      days: Annotated[float, "jak dlouho (dny, max. 60)"] = 7) -> ToolResult:
    from .. import quests

    try:
        q = quests.start(ctx, goal, every_hours, days)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Mise č. {q['id']} běží: {q['goal']}. Krok každých {q['every_h']:g} h, nejdéle {days:g} dní; "
                      "ozvu se, až bude něco nového.", data=q)


@tool("quests_list", "Běžící dlouhé mise: co hlídají, kolik kroků udělaly a co naposledy našly.", category="agenti")
async def quests_list(ctx) -> ToolResult:
    from .. import quests

    qs = quests.listing(ctx)
    if not qs:
        return ToolResult(True, "Žádná dlouhá mise neběží.", data=[])
    lines = []
    for q in qs:
        left = max(0, (q["until"] - time.time()) / 86400)
        lines.append(f"č. {q['id']}: {q['goal']} – {q['runs']} kroků, zbývá {left:.1f} dne"
                     + (f"; naposledy: {q['last_report']}" if q["last_report"] else ""))
    return ToolResult(True, "\n".join(lines), data=qs)


@tool("quest_stop", "Zastaví dlouhou misi (podle čísla nebo slova z cíle).", category="agenti")
async def quest_stop(ctx, which: Annotated[str, "číslo mise nebo slovo z cíle"] = "") -> ToolResult:
    from .. import quests

    q = quests.find(ctx, which)
    if q is None:
        return ToolResult(False, "Takovou běžící misi nemám – řekni číslo (seznam: „jaké mise běží“).")
    quests.stop(ctx, q["id"])
    return ToolResult(True, f"Mise č. {q['id']} zastavena: {q['goal']}.")


# ---------------------------------------------------------------------------------------------- 55 what if
@tool("what_if", "Simulace „co když“ s grafem – spočítá přesně: spoření/investice (měsíční vklad, úrok, roky, inflace), úvěr/"
      "hypotéka (částka, úrok, roky – splátka a úroky), čas (minut denně → hodin a dní ročně) a projekt (úkoly s odhady dní → kdy "
      "bude doopravdy hotovo). Umí porovnat dvě varianty (b_rate_pct, b_years, b_monthly).", category="info")
async def what_if(ctx, kind: Annotated[str, "savings / loan / time / project"],
                  monthly: Annotated[float, "spoření: měsíční vklad (Kč)"] = 0, years: Annotated[float, "počet let"] = 10,
                  rate_pct: Annotated[float, "roční úrok / výnos v %"] = 0, start: Annotated[float, "spoření: počáteční částka"] = 0,
                  inflation_pct: Annotated[float, "spoření: inflace v % ročně (0 = nepočítat)"] = 0,
                  amount: Annotated[float, "úvěr: půjčená částka"] = 0,
                  minutes_per_day: Annotated[float, "čas: minut denně"] = 0,
                  tasks: Annotated[list[dict], "projekt: [{name, best, likely, worst}] ve dnech"] | None = None,
                  b_rate_pct: Annotated[float, "druhá varianta: úrok (-1 = bez druhé varianty)"] = -1,
                  b_years: Annotated[float, "druhá varianta: roky (-1 = stejné)"] = -1,
                  b_monthly: Annotated[float, "druhá varianta: měsíční vklad (-1 = stejný)"] = -1) -> ToolResult:
    import datetime as dt

    from .. import paths, whatif

    k = (kind or "").lower()
    b: dict = {}
    if b_rate_pct >= 0:
        b["rate_pct"] = b_rate_pct
    if b_years > 0:
        b["years"] = b_years
    if b_monthly >= 0 and k.startswith(("sav", "spo", "inv")):
        b["monthly"] = b_monthly
    try:
        if k.startswith(("sav", "spo", "inv")):
            res = whatif.run("savings", {"monthly": monthly, "years": years, "rate_pct": rate_pct, "start": start,
                                         "inflation_pct": inflation_pct}, b or None)
        elif k.startswith(("loan", "uv", "úv", "hyp")):
            if amount <= 0:
                return ToolResult(False, "Řekni, kolik si chceš půjčit.")
            res = whatif.run("loan", {"amount": amount, "rate_pct": rate_pct, "years": years}, b or None)
        elif k.startswith(("time", "cas", "čas")):
            res = whatif.run("time", {"minutes_per_day": minutes_per_day, "years": years})
        elif k.startswith(("proj",)):
            if not tasks:
                return ToolResult(False, "Vyjmenuj úkoly projektu s odhady (nejlépe / nejspíš / nejhůř ve dnech).")
            res = whatif.run("project", {"tasks": tasks})
        else:
            return ToolResult(False, "Umím spoření, úvěr, čas a projekt.")
    except (TypeError, ValueError) as e:
        return ToolResult(False, f"Tohle spočítat neumím: {e}")
    out = paths.sub("grafy") / f"co-kdyz-{dt.datetime.now():%Y%m%d-%H%M%S}.svg"
    out.write_text(res["svg"], encoding="utf-8")
    att = await ctx.store.save(out.name, res["svg"].encode(), "image/svg+xml", conv_id=ctx.memory.current_conversation) \
        if getattr(ctx, "store", None) else None
    return ToolResult(True, res["text"], data={k2: v for k2, v in res["data"].items()}, attachments=[att.id] if att else [])
