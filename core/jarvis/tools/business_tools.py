"""OMEGA wave 17 by voice: business – customer segments, lead scoring, the sales funnel, a price quote with VAT (Word),
pricing scenarios, a revenue forecast, customer feedback and project profitability."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


def _f(x: float | None, d: int = 0) -> str:
    if x is None:
        return "?"
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def _file(path: str):
    p = resolve(path)
    if not p.is_file():
        raise ValueError(f"Soubor neexistuje: {p}")
    return p


async def _run(fn, *a):
    try:
        return await asyncio.to_thread(fn, *a), None
    except (ValueError, OSError, KeyError, UnicodeDecodeError) as e:
        return None, ToolResult(False, str(e))


@tool("customer_segments", "Rozdělí zákazníky podle objednávek (CSV: zákazník, datum, částka) na šampiony, věrné, nové, "
      "ohrožené, ztracené… a ke každé skupině řekne, co dělat.", category="byznys", perm="files_read")
async def customer_segments(ctx, file: str) -> ToolResult:
    from .. import business

    try:
        p = _file(file)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(business.rfm, p)
    if err:
        return err
    return ToolResult(True, f"{len(r['customers'])} zákazníků (k {r['as_of']}): " + "; ".join(
        f"{s['segment']} {s['customers']} ({s['share_pct']} % tržeb) → {s['action']}" for s in r["segments"]) + ".", data=r)


@tool("score_leads", "Ohodnotí obchodní příležitosti (CSV leadů) 0–100 podle viditelných pravidel: rozpočet, rozhoduje, "
      "termín, velikost firmy, zapojení – a seřadí je.", category="byznys", perm="files_read")
async def score_leads(ctx, file: str, weights: Annotated[dict[str, float] | None, "váhy pravidel (nepovinné)"] = None) -> ToolResult:
    from .. import business

    try:
        p = _file(file)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(business.score_leads, p, weights)
    if err:
        return err
    return ToolResult(True, f"{len(r['leads'])} leadů, horkých {r['hot']}. Nejlepší: " + "; ".join(
        f"{x['lead']} {x['score']} ({', '.join(x['why']) or '—'})" for x in r["leads"][:5]) + ".", data=r)


@tool("sales_funnel", "Prodejní trychtýř: z počtů ve fázích („návštěva 10000, košík 800, objednávka 200“) nebo z CSV "
      "událostí spočítá konverze, najde největší únik a co by přineslo jeho zlepšení.", category="byznys", perm="files_read")
async def sales_funnel(ctx, stages: Annotated[str, "fáze s počty, nebo pořadí fází pro CSV (oddělené čárkou)"], file: str = "") -> ToolResult:
    from .. import business

    try:
        if file:
            order = [s.strip() for s in stages.split(",") if s.strip()]
            st = await asyncio.to_thread(business.funnel_from_events, _file(file), order)
        else:
            st = business.parse_stages(stages)
        r = business.funnel(st)
    except ValueError as e:
        return ToolResult(False, str(e))
    lk = r["leak"]
    return ToolResult(True, " → ".join(f"{s['from']}→{s['to']} {_f(s['rate_pct'], 1)} %" for s in r["steps"]) +
                      f". Celkem {_f(r['overall_pct'], 2)} %. Největší únik: {lk['from']} → {lk['to']} ({_f(lk['rate_pct'], 1)} %, ztraceno {_f(lk['lost'])}); "
                      f"zlepšení tohoto kroku o 10 % dá o {_f(r['if_leak_plus10'], 1)} víc na konci.", data=r)


def _quote_details(a: dict, ctx=None) -> list[str]:
    return [f"Vytvoří nabídku pro {a.get('client', '')} ({len(a.get('items') or [])} položek) jako dokument Word. Nic se neodesílá."]


@tool("price_quote", "Cenová nabídka jako dokument Word: položky (název, množství, cena za jednotku bez DPH, sazba DPH), sleva, "
      "součty podle sazeb DPH, platnost. Spočítá přesně, nic neodesílá.", category="byznys", perm="files_write", details=_quote_details)
async def price_quote(ctx, client: str, items: Annotated[list[dict], "[{name, qty, unit, price, vat}]"], supplier: str = "",
                      vat_pct: float = 21, discount_pct: float = 0, vat_payer: bool = True, valid_days: int = 30, note: str = "",
                      target: str = "") -> ToolResult:
    from .. import business, paths

    if not items:
        return ToolResult(False, "Nabídka potřebuje aspoň jednu položku.")
    try:
        t = business.quote_totals(items, vat_pct, discount_pct, vat_payer)
    except (KeyError, ValueError, TypeError) as e:
        return ToolResult(False, f"Položky zadej jako name, qty, price (a vat): {e}")
    supplier = supplier or getattr(ctx.cfg.general, "user_name", "") or "Dodavatel"
    number = time.strftime("%Y%m%d-%H%M")
    if target:
        dest = resolve(target)
    else:
        d = paths.data_dir() / "nabidky"
        d.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w-]+", "-", client.lower()).strip("-")[:30] or "klient"
        dest = d / f"nabidka-{slug}-{number}.docx"
    if dest.exists():
        return ToolResult(False, f"{dest.name} už existuje.")
    await asyncio.to_thread(business.quote_docx, dest, t, client, supplier, "Cenová nabídka", valid_days, note, number)
    import docx

    text = "\n".join(p.text for p in docx.Document(str(dest)).paragraphs)
    ok = business._kc(t["total"]) in text
    tasks = getattr(ctx, "tasks", None)
    if tasks is not None and tasks.current:
        tasks.add_artifact(dest, "Cenová nabídka")
    return ToolResult(ok, f"Nabídka pro {client}: bez DPH {business._kc(t['base'])}, DPH {business._kc(t['vat'])}, celkem {business._kc(t['total'])}. "
                          f"Uloženo: {dest}" + ("" if ok else " (POZOR: součet v dokumentu nesedí)"), data={**t, "path": str(dest)})


@tool("pricing_scenarios", "Cenové scénáře: co udělá zdražení / zlevnění s prodejem, tržbami a ziskem (podle pružnosti "
      "poptávky), cena s nejvyšším ziskem a bod zvratu.", category="byznys")
async def pricing_scenarios(ctx, price: float, volume: float, unit_cost: float, fixed_cost: float = 0,
                            elasticity: Annotated[float, "pružnost poptávky (typicky −0,5 až −3)"] = -1.5,
                            changes_pct: list[float] | None = None) -> ToolResult:
    from .. import business

    try:
        r = business.price_scenarios(price, volume, unit_cost, fixed_cost, elasticity if elasticity < 0 else -elasticity, changes_pct)
    except ValueError as e:
        return ToolResult(False, str(e))
    best = max(r["scenarios"], key=lambda s: s["profit"])
    msg = "; ".join(f"{s['change_pct']:+g} %: zisk {_f(s['profit'])}" for s in r["scenarios"])
    msg += f". Ze scénářů nejlepší {best['change_pct']:+g} % (cena {_f(best['price'], 2)})."
    if r["optimal"]:
        msg += f" Teoreticky nejvyšší zisk při ceně {_f(r['optimal']['price'], 2)}."
    if r["break_even_volume"] is not None:
        msg += f" Bod zvratu {_f(r['break_even_volume'])} ks."
    if r["note"]:
        msg += " " + r["note"] + "."
    return ToolResult(True, msg, data=r)


@tool("revenue_forecast", "Předpověď tržeb na další měsíce z historie (CSV: měsíc/datum a částka) – se sezónností, když jsou "
      "aspoň 2 roky dat, a se zpětným testem, jak moc jí věřit.", category="byznys", perm="files_read")
async def revenue_forecast(ctx, file: str, months: int = 6) -> ToolResult:
    from .. import business

    try:
        p = _file(file)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(business.forecast, p, max(1, min(months, 24)))
    if err:
        return err
    return ToolResult(True, f"{r['method']}: " + ", ".join(f"{f['month']} {_f(f['value'])}" for f in r["forecast"]) +
                      (f". Zpětný test na {r['backtest_months']} měs.: odchylka {_f(r['mape_pct'], 1)} % → důvěra {r['trust']}." if r["mape_pct"] is not None else "."), data=r)


@tool("analyze_feedback", "Rozbor zpětné vazby zákazníků (recenze, komentáře – CSV nebo text, nebo seznam): kolik je "
      "pozitivních a negativních, o čem si stěžují (doručení, cena, kvalita, podpora…) a nejhorší ohlasy.", category="byznys", perm="files_read")
async def analyze_feedback(ctx, file: str = "", texts: list[str] | None = None) -> ToolResult:
    from .. import business

    try:
        items = texts or (await asyncio.to_thread(business.feedback_texts, _file(file)) if file else [])
        r = business.feedback(items)
    except ValueError as e:
        return ToolResult(False, str(e))
    tops = "; ".join(f"{t['topic']} {t['mentions']}× (negativně {t['negative']})" for t in r["topics"][:5])
    return ToolResult(True, f"{r['count']} ohlasů: pozitivních {r['positive']}, negativních {r['negative']}, neutrálních {r['neutral']} "
                      f"(saldo {r['nps_like']:+d}). Témata: {tops or '—'}." + (f" Nejhorší: „{r['worst'][0]['text'][:100]}“" if r["negative"] else ""),
                      data={k: v for k, v in r.items() if k != "rows"} | {"rows": r["rows"][:200]})


@tool("project_profitability", "Ziskovost zakázek z výkazu (CSV: projekt, hodiny, sazba, náklady, fakturováno): zisk a marže "
      "každého projektu, skutečná hodinovka a které projekty prodělávají.", category="byznys", perm="files_read")
async def project_profitability(ctx, file: str, hourly_rate: Annotated[float, "sazba, když není ve výkazu"] = 0) -> ToolResult:
    from .. import business

    try:
        p = _file(file)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(business.profitability, p, hourly_rate)
    if err:
        return err
    msg = "; ".join(f"{x['project']}: zisk {_f(x['profit'])}" + (f" ({_f(x['margin_pct'], 1)} %)" if x["margin_pct"] is not None else "") +
                    (f", hodinovka {_f(x['effective_rate'])}" if x["effective_rate"] is not None else "") for x in r["projects"][:8])
    head = f"Celkem tržby {_f(r['revenue'])}, zisk {_f(r['profit'])}" + (f" ({_f(r['margin_pct'], 1)} %)" if r["margin_pct"] is not None else "")
    return ToolResult(True, head + ". " + msg + "." + (f" Prodělávají: {', '.join(r['losing'])}." if r["losing"] else ""), data=r)
