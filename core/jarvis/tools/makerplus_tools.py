"""Completing partial features by voice: meaning-based file search (316), automatic file versions (328), colours (133 /
282), thumbnails (132), sensor checks and fusion (163 / 486), equations with steps (766 / 106), notebooks (768), concept
maps (464), article comparison (386), research → to-dos (390), learning path by days (452)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


def _out(name: str) -> Path:
    from .. import paths

    d = paths.sub("vystupy")
    d.mkdir(parents=True, exist_ok=True)
    return d / name


@tool("find_by_meaning", "Najde dokumenty podle významu, i když si nepamatuješ přesná slova („ta smlouva o pronájmu bytu“). "
      "S místním modelem pro význam (Ollama) přesněji, jinak podle podobnosti slov.", category="soubory", perm="files_read")
async def find_by_meaning(ctx, query: str, folder: str = "") -> ToolResult:
    from .. import fsplus
    from .fileverse_tools import _folders

    r = await fsplus.semantic_search(ctx, _folders(ctx, folder), query)
    if not r["hits"]:
        return ToolResult(True, "Nic podobného jsem nenašel.", data=r)
    return ToolResult(True, f"Podle {r['mode']}: " + "; ".join(f"{Path(h['path']).name} ({round(h['score'] * 100)} %)" for h in r["hits"][:6]), data=r)


@tool("auto_versions", "Automatické verze souborů: ve zvolené složce JARVIS uloží verzi každého souboru, kdykoli ho uložíš "
      "(dokumenty, tabulky, kód, grafika; 50 verzí na soubor). action: add / remove / list.", category="soubory", perm="files_read")
async def auto_versions(ctx, action: Annotated[str, "add / remove / list"] = "list", folder: str = "") -> ToolResult:
    cur = list(getattr(ctx.cfg.powers, "version_folders", []) or [])
    if action in ("add", "remove"):
        p = resolve(folder)
        if action == "add":
            if not p.is_dir():
                return ToolResult(False, f"Složka neexistuje: {p}")
            cur = cur + [str(p)] if str(p) not in cur else cur
        else:
            cur = [c for c in cur if Path(c) != p]
        ctx.update_config({"powers": {"version_folders": cur}})
        return ToolResult(True, ("Hlídám verze v " if action == "add" else "Už nehlídám ") + str(p) + ". Starší verze obnovíš příkazem „obnov předchozí verzi souboru…“.")
    return ToolResult(True, ("Verze hlídám v: " + ", ".join(cur)) if cur else "Žádná složka se automaticky neverzuje.", data=cur)


@tool("color_info", "Barva: název, RGB, čitelnost na bílé a černé (z kódu #rrggbb, nebo z bodu x,y obrázku / snímku obrazovky); "
      "s image a bez souřadnic vrátí hlavní barvy obrázku jako paletu.", category="design", perm="files_read")
async def color_info(ctx, color: str = "", image: str = "", x: int = -1, y: int = -1, colors: int = 5) -> ToolResult:
    from .. import makerplus

    if image:
        p = resolve(image)
        if not p.is_file():
            return ToolResult(False, f"Obrázek neexistuje: {p}")
        if x >= 0 and y >= 0:
            color = await asyncio.to_thread(makerplus.pixel_color, p, x, y)
        else:
            pal = await asyncio.to_thread(makerplus.palette_from_image, p, max(2, min(10, colors)))
            return ToolResult(True, "Paleta: " + ", ".join(f"{c['hex']} {c['name']} ({c['share']} %)" for c in pal), data=pal)
    if not color:
        return ToolResult(False, "Zadej barvu (#rrggbb) nebo obrázek.")
    from ..design import css_color

    hx = css_color(color) or color
    try:
        d = makerplus.describe_color(hx)
    except (ValueError, IndexError):
        return ToolResult(False, f"Barvě „{color}“ nerozumím.")
    return ToolResult(True, f"{d['hex']} – {d['name']}, RGB {tuple(d['rgb'])}; kontrast s bílou {d['contrast_white']}:1, s černou "
                            f"{d['contrast_black']}:1 → text na ní {'černý' if d['text_on_it'] == '#000000' else 'bílý'}.", data=d)


@tool("make_thumbnail", "Náhledový obrázek k videu (1280×720): fotka nebo barevný přechod, výrazný nadpis ve dvou řádcích a tmavý "
      "pruh pro čitelnost.", category="média", perm="files_write")
async def make_thumbnail(ctx, title: str, image: str = "", accent: str = "#ffcc00") -> ToolResult:
    from .. import makerplus

    bg = resolve(image) if image else None
    out = _out(f"nahled_{dt.datetime.now():%Y%m%d_%H%M%S}.jpg")
    p = await asyncio.to_thread(makerplus.thumbnail, title, out, bg, accent)
    return ToolResult(True, f"Náhled hotový: {p}", data={"path": str(p)}, attachments=[str(p)])


@tool("sensor_check", "Zkontroluje data z čidla a pozná vadu: zamrzlá hodnota, výpadky, mimo fyzikální rozsah, špičky (rušení), "
      "šum, drift. Hodnoty zadej přímo nebo jako soubor CSV (sloupec).", category="věda", perm="files_read")
async def sensor_check(ctx, values: Annotated[list[float | None] | None, "hodnoty v pořadí"] = None, file: str = "", column: str = "",
                       min_value: float | None = None, max_value: float | None = None, rate_hz: float = 1.0) -> ToolResult:
    from .. import makerplus

    vals = values or []
    if file:
        import csv

        p = resolve(file)
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            rows = list(csv.DictReader(f))
        col = column or next((k for k in (rows[0] if rows else {}) if k), "")
        vals = []
        for r in rows:
            try:
                vals.append(float(str(r.get(col, "")).replace(",", ".")))
            except ValueError:
                vals.append(None)
    r = makerplus.sensor_diagnose(vals, min_value, max_value, rate_hz)
    return ToolResult(True, ("Čidlo vypadá v pořádku" if r["ok"] else "Podezřelé: " + "; ".join(r["issues"])) +
                      (f" (min {r['min']:g}, max {r['max']:g}, průměr {r['mean']:.3g})." if "mean" in r else "."), data=r)


@tool("sensor_fuse", "Spojí víc čidel měřících totéž (např. 3 teploměry) do jednoho odhadu: každé váží podle svého šumu, "
      "výpadky jednoho nevadí.", category="věda")
async def sensor_fuse(ctx, series: Annotated[dict[str, list[float | None]], "název čidla → hodnoty"],
                      noise: Annotated[dict[str, float] | None, "známý šum čidel (volitelné)"] = None) -> ToolResult:
    from .. import makerplus

    if len(series) < 2:
        return ToolResult(False, "Potřebuji aspoň dvě čidla.")
    r = makerplus.sensor_fusion(series, noise)
    return ToolResult(True, "Váhy: " + ", ".join(f"{k} {round(v * 100)} %" for k, v in r["weights"].items()) +
                      f". Výsledek: {', '.join(str(x) for x in r['fused'][:8])}{'…' if len(r['fused']) > 8 else ''}", data=r)


@tool("solve_equation", "Vyřeší rovnici prvního nebo druhého stupně krok za krokem jako ve škole (převod, diskriminant, kořeny, "
      "zkouška). Např. „2x + 3 = 11“, „x^2 - 5x + 6 = 0“.", category="učení")
async def solve_equation(ctx, equation: str, variable: str = "x") -> ToolResult:
    from .. import makerplus

    try:
        r = makerplus.solve_steps(equation, variable)
    except (ValueError, ZeroDivisionError) as e:
        return ToolResult(False, str(e))
    sol = ", ".join(str(s).replace(".", ",") if not isinstance(s, str) else s for s in r["solutions"]) or "nemá řešení"
    return ToolResult(True, "\n".join(f"{i + 1}. {s}" for i, s in enumerate(r["steps"])) + f"\nVýsledek: {sol}", data=r)


@tool("run_notebook", "Spustí sešit Jupyter (.ipynb) buňku po buňce bez Jupyteru a uloží kopii s výstupy vedle (…_vystup.ipynb). "
      "Při chybě řekne, která buňka spadla.", danger=True, category="programování", perm="shell",
      details=lambda a, ctx=None: [f"Spustí kód ze sešitu {a.get('path')} (Python na tomhle PC).", "Originál se nezmění."])
async def run_notebook(ctx, path: str, timeout_s: int = 600) -> ToolResult:
    from .. import devops
    from .dev import _run_cmd

    p = resolve(path)
    if not p.is_file() or p.suffix.lower() != ".ipynb":
        return ToolResult(False, "Zadej soubor .ipynb.")
    nb = json.loads(p.read_text(encoding="utf-8"))
    script, cells = devops.notebook_script(nb)
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "nb.py"
        sp.write_text(script, encoding="utf-8")
        code, out = await asyncio.to_thread(_run_cmd, f'"{sys.executable if not getattr(sys, "frozen", False) else "python"}" -X utf8 "{sp}"', p.parent, max(10, min(3600, timeout_s)))
    outs = devops.split_outputs(out)
    dst = p.with_name(p.stem + "_vystup.ipynb")
    dst.write_text(json.dumps(devops.notebook_with_outputs(nb, outs), ensure_ascii=False, indent=1), encoding="utf-8")
    failed = next((i for i, o in outs.items() if "@@JARVIS-FAILED@@" in o), None)
    if failed is not None:
        return ToolResult(False, f"Buňka {cells.index(failed) + 1} spadla:\n" + outs[failed].replace("@@JARVIS-FAILED@@", "")[-1500:],
                          data={"path": str(dst), "failed_cell": failed})
    return ToolResult(code == 0, f"Proběhlo {len(outs)} z {len(cells)} buněk. Výstupy: {dst}", data={"path": str(dst), "cells": len(cells)})


@tool("concept_map", "Mapa pojmů z textu: hlavní pojmy a které spolu souvisí (jak často se objevují společně) – na učení a "
      "pochopení látky.", category="učení", perm="files_read")
async def concept_map(ctx, text: str = "", file: str = "") -> ToolResult:
    from .. import makerplus
    from ..fileuniverse import doc_text
    from ..sysplus import graph_svg

    if file:
        text = await asyncio.to_thread(doc_text, resolve(file), 60000)
    if not text.strip():
        return ToolResult(False, "Dej mi text nebo soubor.")
    g = makerplus.concept_map(text)
    svg = graph_svg({"nodes": [{"id": n["id"], "kind": "projekt", "mentions": n["weight"]} for n in g["nodes"]],
                     "edges": [{"a": e["a"], "b": e["b"], "weight": e["weight"]} for e in g["edges"]]})
    out = _out(f"mapa_pojmu_{dt.datetime.now():%Y%m%d_%H%M%S}.svg")
    out.write_text(svg, encoding="utf-8")
    links = "; ".join(f"{e['a']} – {e['b']}" for e in g["edges"][:6])
    return ToolResult(True, f"Pojmy: {', '.join(n['id'] for n in g['nodes'][:10])}. Souvislosti: {links}. Mapa: {out}",
                      data={**g, "path": str(out)}, attachments=[str(out)])


@tool("compare_articles", "Porovná dva články / texty: v čem se shodují, co má jen jeden, čísla, která se liší, a stejná tvrzení "
      "řečená jinak.", category="výzkum", perm="files_read")
async def compare_articles(ctx, first: str, second: str) -> ToolResult:
    from .. import makerplus
    from ..fileuniverse import doc_text

    def load(x):
        p = resolve(x) if len(x) < 400 else None
        return doc_text(p, 80000) if p and p.is_file() else x
    a, b = await asyncio.to_thread(load, first), await asyncio.to_thread(load, second)
    r = makerplus.compare_texts(a, b)
    txt = f"Shoda pojmů {r['overlap_pct']} %. Jen v prvním: {', '.join(r['only_a'][:6]) or '—'}. Jen ve druhém: {', '.join(r['only_b'][:6]) or '—'}."
    if r["numbers_only_a"] or r["numbers_only_b"]:
        txt += f" Čísla se liší: {', '.join(r['numbers_only_a'][:4])} vs. {', '.join(r['numbers_only_b'][:4])}."
    if r["same_claims"]:
        txt += f" Stejné tvrzení: „{r['same_claims'][0]['a'][:80]}“ ~ „{r['same_claims'][0]['b'][:80]}“."
    return ToolResult(True, txt, data=r)


@tool("research_to_tasks", "Z poznámek nebo závěrů výzkumu vytáhne, co je potřeba udělat („je potřeba ověřit…“, „doporučuji…“), "
      "a s add=true to připne jako úkoly.", category="výzkum", perm="files_read")
async def research_to_tasks(ctx, text: str = "", file: str = "", add: bool = False) -> ToolResult:
    from .. import makerplus
    from ..fileuniverse import doc_text
    from ..uiplus import add_pin

    if file:
        text = await asyncio.to_thread(doc_text, resolve(file), 60000)
    acts = makerplus.research_actions(text)
    if not acts:
        return ToolResult(True, "V textu jsem nenašel nic, co by bylo potřeba udělat.", data=[])
    if add:
        made = []
        for a in acts:
            try:
                made.append(add_pin(ctx, a))
            except ValueError:
                break
        return ToolResult(True, f"Připnuto {len(made)} úkolů: " + "; ".join(acts[:len(made)]), data=made)
    return ToolResult(True, "Co udělat: " + "; ".join(acts) + ". Mám je připnout?", data=acts)


@tool("learning_schedule", "Studijní cesta po dnech: témata v pořadí podle předpokladů (co už umíš se přeskočí) rozložená do dnů "
      "s opakováním po 1, 3 a 7 dnech.", category="učení")
async def learning_schedule(ctx, topics: Annotated[dict[str, list[str]], "téma → jeho předpoklady"], goal: str,
                            per_day: int = 1, known: list[str] | None = None, start: str = "") -> ToolResult:
    from .. import maker

    try:
        r = maker.prerequisites(topics, goal, known)
        d0 = dt.date.fromisoformat(start) if start else dt.date.today()
    except ValueError as e:
        return ToolResult(False, str(e))
    plan: dict[str, list[str]] = {}
    per_day = max(1, per_day)
    for i, t in enumerate(r["order"]):
        day = d0 + dt.timedelta(days=i // per_day)
        plan.setdefault(day.isoformat(), []).append(f"nové: {t}")
        for gap in (1, 3, 7):
            plan.setdefault((day + dt.timedelta(days=gap)).isoformat(), []).append(f"opakovat: {t}")
    days = sorted(plan)
    return ToolResult(True, f"{len(r['order'])} témat za {(len(r['order']) + per_day - 1) // per_day} dní: " +
                      "; ".join(f"{d}: {', '.join(plan[d])}" for d in days[:6]) + ("…" if len(days) > 6 else ""),
                      data={"order": r["order"], "plan": plan, "undefined": r["undefined"]})
