"""OMEGA wave 27 by voice: the lab – what a chart says, where data columns come from, physics with parameter sweeps,
citation check, experiment design, prototype test plan and results, and a circuit tutor that adapts its level."""
from __future__ import annotations

import asyncio
import time
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _save(name: str, text: str) -> str:
    p = paths.data_dir() / "laborator" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8-sig")
    return str(p)


@tool("chart_insights", "Řekne, co je v datech grafu (CSV nebo hodnoty): jestli roste nebo klesá, kde je zlom, výkyvy, jestli se "
      "něco pravidelně opakuje a které řady se pohybují spolu.", category="věda", perm="files_read")
async def chart_insights(ctx, file: str = "", columns: list[str] | None = None, label_column: str = "",
                         values: dict[str, list[float]] | None = None) -> ToolResult:
    from .. import lab, maker
    from ..science import read_csv

    labels = None
    try:
        if values:
            series = values
        else:
            p = resolve(file)
            if not p.is_file():
                return ToolResult(False, f"Soubor neexistuje: {p}")
            series = await asyncio.to_thread(maker.csv_series, p, columns)
            if label_column:
                header, rows, _, _ = await asyncio.to_thread(read_csv, p)
                if label_column in header:
                    i = header.index(label_column)
                    labels = [r[i] if i < len(r) else "" for r in rows]
                    series.pop(label_column, None)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    series = {k: [v for v in vs if v is not None] for k, vs in series.items()}
    r = lab.chart_insights(series, labels)
    if not r["series"]:
        return ToolResult(False, "Nenašel jsem žádnou číselnou řadu (aspoň 3 hodnoty).")
    return ToolResult(True, r["text"], data=r)


@tool("data_lineage", "Odkud se berou sloupce pohledu nebo dotazu v databázi SQLite: ze kterých tabulek a sloupců vzniká každý "
      "výstupní sloupec (i přes další pohledy) a které sloupce jen filtrují nebo spojují. Databázi jen čte.", category="programování", perm="files_read")
async def data_lineage(ctx, database: str, view: str = "", sql: str = "") -> ToolResult:
    from .. import lab

    p = resolve(database)
    if not p.is_file():
        return ToolResult(False, f"Databáze neexistuje: {p}")
    try:
        r = await asyncio.to_thread(lab.lineage, p, view, sql) if (view or sql) else await asyncio.to_thread(lab.all_lineage, p)
    except (ValueError, Exception) as e:  # noqa: BLE001 – not a database / locked
        return ToolResult(False, str(e)[:200])
    items = r if isinstance(r, list) else [r]
    if not items:
        return ToolResult(True, "Databáze nemá žádné pohledy – zadej dotaz.", data=[])
    msg = " | ".join(f"{x['name']}: " + ", ".join(f"{c['column']} ← {' + '.join(c['from']) or '?'}" for c in x.get("columns", [])[:8])
                     if "columns" in x else f"{x['name']}: {x.get('error')}" for x in items[:5])
    return ToolResult(True, msg + ".", data=r)


@tool("physics_sim", "Fyzikální simulace s parametry: vrh (s odporem vzduchu), kyvadlo (i velké výchylky), pružina s tlumením, "
      "RC článek, chladnutí. Volitelně projede jeden parametr přes hodnoty a najde nejlepší.", category="věda")
async def physics_sim(ctx, model: Annotated[str, "projectile / pendulum / spring / rc / cooling"], params: dict[str, float],
                      sweep_param: str = "", values: list[float] | None = None, output: str = "") -> ToolResult:
    from .. import lab

    try:
        if sweep_param and values:
            r = await asyncio.to_thread(lab.sweep, model, params, sweep_param, values, output)
            return ToolResult(True, f"{output} pro {sweep_param}: " + ", ".join(f"{x[sweep_param]:g} → {x[output]}" for x in r["rows"][:12]) +
                              f". Nejvíc při {sweep_param} = {r['best'][sweep_param]:g}.", data=r)
        r = await asyncio.to_thread(lab.simulate, model, params)
    except KeyError as e:
        return ToolResult(False, f"Chybí parametr {e}.")
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return ToolResult(False, str(e) or "Parametry nedávají smysl.")
    return ToolResult(True, ", ".join(f"{k} {v}" for k, v in r.items()) + ".", data=r)


@tool("citation_check", "Ověří citace v textu nebo seznamu literatury přes Crossref: existuje DOI, sedí název, rok a autor, nebyl "
      "článek stažen; citace bez DOI zkusí dohledat.", category="učení", perm="network")
async def citation_check(ctx, text: str = "", file: str = "") -> ToolResult:
    from .. import lab

    if file:
        p = resolve(file)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        text = p.read_text(encoding="utf-8", errors="replace")
    if not lab.references(text):
        return ToolResult(False, "V textu nevidím žádnou citaci (DOI nebo řádek s rokem a názvem).")
    r = await lab.check_citations(ctx, text)
    bad = [x for x in r if x.get("problems")]
    msg = f"{len(r)} citací, v pořádku {len(r) - len(bad)}."
    if bad:
        msg += " Problémy: " + "; ".join(f"{(x.get('doi') or x['line'][:40])}: {', '.join(x['problems'][:2])}" for x in bad[:6]) + "."
    return ToolResult(True, msg, data=r)


@tool("experiment_design", "Navrhne pokus: všechny kombinace faktorů (nebo polovinu u faktorů o dvou úrovních), opakování, bloky, "
      "náhodné pořadí a podle velikosti efektu kolik opakování je potřeba. Uloží záznamový list CSV.", category="věda")
async def experiment_design(ctx, factors: Annotated[list[dict], "[{name, levels: [...]}]"], replicates: int = 1, seed: int = 1,
                            half_fraction: bool = False, blocks: int = 1, effect: float | None = None, sd: float | None = None) -> ToolResult:
    from .. import lab

    try:
        r = lab.experiment_design(factors, max(1, replicates), seed, half_fraction, blocks, effect, sd)
    except (ValueError, KeyError) as e:
        return ToolResult(False, f"Faktory nesedí: {e}")
    r["sheet"] = _save("pokus", r.pop("csv"))
    msg = f"{r['cells']} kombinací × {r['replicates']} opakování = {r['total']} běhů v náhodném pořadí"
    if r["resolution"]:
        msg += f" (poloviční plán, rozlišení {r['resolution']})"
    if r["power"]:
        msg += f"; na efekt {effect:g} při rozptylu {sd:g} je potřeba {r['power']['runs_total']} běhů"
    return ToolResult(True, msg + f". List: {r['sheet']}.", data=r, attachments=[r["sheet"]])


@tool("prototype_test_plan", "Plán zkoušek prototypu z požadavků: kolik kusů vyzkoušet pro danou spolehlivost a jistotu, pořadí "
      "(nedestruktivní první) a záznamový list CSV.", category="věda")
async def prototype_test_plan(ctx, requirements: Annotated[list[dict], "[{name, min?, max?, unit, method, destructive?}]"],
                              confidence: float = 0.9, reliability: float = 0.9) -> ToolResult:
    from .. import lab

    if not requirements or not 0 < confidence < 1 or not 0 < reliability < 1:
        return ToolResult(False, "Zadej požadavky a jistotu i spolehlivost mezi 0 a 1 (např. 0,9).")
    r = lab.test_plan(requirements, confidence, reliability)
    r["sheet_path"] = _save("zkousky", r.pop("sheet"))
    return ToolResult(True, f"{len(r['plan'])} zkoušek po {r['samples_per_test']} kusech (spolehlivost {reliability:.0%} s jistotou {confidence:.0%}, bez selhání). "
                            f"List: {r['sheet_path']}.", data=r, attachments=[r["sheet_path"]])


@tool("prototype_test_results", "Vyhodnotí naměřené výsledky zkoušek (CSV s požadavkem a hodnotou, nebo seznam): kolik kusů prošlo, "
      "průměr, rozptyl, Cpk a prokázaná spolehlivost.", category="věda", perm="files_read")
async def prototype_test_results(ctx, requirements: list[dict], file: str = "", results: list[dict] | None = None, confidence: float = 0.9) -> ToolResult:
    from .. import lab
    from ..science import column_nums, read_csv

    rows = list(results or [])
    if file:
        p = resolve(file)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        header, data, _, _ = await asyncio.to_thread(read_csv, p)
        h = [x.strip().lower() for x in header]
        ri = next((i for i, x in enumerate(h) if x in ("požadavek", "pozadavek", "requirement")), None)
        vi = next((i for i, x in enumerate(h) if x in ("naměřeno", "nameřeno", "namereno", "value", "hodnota")), None)
        if ri is None or vi is None:
            return ToolResult(False, "V CSV chybí sloupce požadavek a naměřeno.")
        data = [r for r in data if len(r) > max(ri, vi) and r[vi].strip()]
        rows += [{"requirement": r[ri], "value": v} for r, v in zip(data, column_nums([r[vi] for r in data]))]
    r = lab.evaluate_tests(requirements, rows, confidence)
    return ToolResult(True, "; ".join(f"{x['requirement']}: {x['verdict']}" + (f" ({x['passed']}/{x['n']}, Cpk {x['cpk']})" if x.get("n") else "") for x in r) + ".", data=r)


@tool("circuit_tutor", "Procvičování elektrických obvodů s výkladem: dá příklad (Ohmův zákon, sériové, paralelní, smíšené zapojení, "
      "LED), zkontroluje odpověď s jednotkou, vysvětlí postup a obtížnost přizpůsobí tomu, jak ti to jde.", category="učení")
async def circuit_tutor(ctx, answer: Annotated[str, "tvoje odpověď, např. „12 mA“; prázdné = nový příklad"] = "") -> ToolResult:
    from .. import lab

    t = lab.Tutor(ctx)
    if not answer:
        p = t.next()
        return ToolResult(True, f"Úroveň {p['level']}: {p['question']}", data={"level": p["level"], "question": p["question"], "unit": p["unit"]})
    try:
        r = t.answer(answer)
    except ValueError as e:
        return ToolResult(False, str(e))
    head = "Správně!" if r["correct"] else ("Špatná jednotka – čekal jsem " + r["unit"] + "." if not r["unit_ok"] else f"Ne, správně je {r['expected']:.4g} {r['unit']}.")
    lvl = "" if r["level"] == r["level_before"] else (" Jdeme na těžší úroveň." if r["level"] > r["level_before"] else " Vrátíme se o úroveň níž.")
    nxt = t.next()
    return ToolResult(True, f"{head} {r['solution']}{lvl} Další (úroveň {nxt['level']}): {nxt['question']}",
                      data=r | {"next": {"level": nxt["level"], "question": nxt["question"], "unit": nxt["unit"]}})
