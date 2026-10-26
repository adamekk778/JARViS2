"""OMEGA wave 19 by voice: local AI (speed of installed models, quantisation by graphics memory, what fits where, warm-up,
the best embedding model, answer accuracy) and the local document workspace (index, search, answers with citations)."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


async def _models(ctx, names: list[str] | None, embedding: bool | None = None) -> list[str] | ToolResult:
    from .. import localai

    try:
        inst = await localai.installed(ctx)
    except Exception as e:  # noqa: BLE001 – Ollama not running
        return ToolResult(False, f"Ollama neběží nebo neodpovídá ({type(e).__name__}). Spusť ji v Nastavení → Mozek → Místní AI.")
    have = [m["name"] for m in inst if embedding is None or m["embedding"] == embedding]
    if names:
        missing = [n for n in names if n not in have and f"{n}:latest" not in have]
        if missing:
            return ToolResult(False, f"Tyhle modely nemáš nainstalované: {', '.join(missing)}. JARVIS sám nic nestahuje.")
        return names
    if not have:
        return ToolResult(False, "Nemáš nainstalovaný žádný " + ("embedding " if embedding else "") + "model.")
    return have


@tool("local_model_benchmark", "Změří rychlost nainstalovaných místních modelů (Ollama): tokeny za sekundu, načtení, jestli "
      "běží na grafice. Nic nestahuje.", category="mozek", perm="system")
async def local_model_benchmark(ctx, models: list[str] | None = None) -> ToolResult:
    from .. import localai

    names = await _models(ctx, models, embedding=False)
    if isinstance(names, ToolResult):
        return names
    r = await localai.benchmark(ctx, names[:6])
    ok = [x for x in r if x["ok"]]
    if not ok:
        return ToolResult(False, "Žádný model neodpověděl: " + "; ".join(f"{x['model']}: {x['error']}" for x in r), data=r)
    return ToolResult(True, "; ".join(f"{x['model']} {x['tok_s']} tok/s ({'GPU' if x['on_gpu'] else 'CPU'}, načtení {x['load_s']} s)" for x in ok) +
                      ("" if len(ok) == len(r) else f". Selhalo: {', '.join(x['model'] for x in r if not x['ok'])}") + ".", data=r)


@tool("quantization_advice", "Jakou kvantizaci (Q4, Q5, Q8…) zvolit pro model dané velikosti, aby se vešel do grafiky / paměti "
      "tohoto PC, kolik zabere a jak rychlý bude.", category="mozek")
async def quantization_advice(ctx, model: Annotated[str, "název nebo velikost, např. llama3.1:8b nebo 14b"], vram_gb: float = 0, ram_gb: float = 0,
                              context: int = 4096) -> ToolResult:
    from .. import localai

    pb = localai.params_from_name(model if "b" in model.lower() else model + "b")
    if not pb:
        return ToolResult(False, "Z názvu nepoznám velikost modelu – napiš ji, např. 8b.")
    hw = await asyncio.to_thread(localai.hardware) if not (vram_gb and ram_gb) else {}
    v, r = vram_gb or hw.get("vram_gb", 0), ram_gb or hw.get("ram_gb", 8)
    a = localai.quant_advice(pb, v, r, context)
    b = a["best"]
    msg = f"{pb:g} mld. parametrů, grafika {v:g} GB, RAM {r:g} GB: "
    msg += f"doporučuji {b['quant']} ({b['size_gb']} GB, potřeba {b['need_gb']} GB, {b['where']}) – {a['speed_hint']}." if b else "na tomhle PC nepoběží rozumně."
    if v and v <= 4.3 and not vram_gb:
        msg += " (Windows u některých karet hlásí max. 4 GB – když máš víc, zadej vram_gb.)"
    return ToolResult(True, msg, data=a)


@tool("local_models_fit", "Které nainstalované místní modely se vejdou celé do grafiky, které poběží napůl na procesoru a "
      "které se nevejdou vůbec.", category="mozek", perm="system")
async def local_models_fit(ctx, vram_gb: float = 0, ram_gb: float = 0, context: int = 4096) -> ToolResult:
    from .. import localai

    try:
        inst = await localai.installed(ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Ollama neběží nebo neodpovídá ({type(e).__name__}).")
    if not inst:
        return ToolResult(True, "Nemáš nainstalovaný žádný místní model.", data=[])
    hw = await asyncio.to_thread(localai.hardware) if not (vram_gb and ram_gb) else {}
    rows = localai.compatibility(inst, vram_gb or hw.get("vram_gb", 0), ram_gb or hw.get("ram_gb", 8), context)
    return ToolResult(True, "; ".join(f"{m['name']} ({m['size_gb']} GB) → {m['where']}" for m in rows) + ".", data=rows)


@tool("warm_up_model", "Načte místní model do paměti dopředu (a nechá ho tam zadanou dobu), aby první odpověď byla hned.",
      category="mozek", perm="system")
async def warm_up_model(ctx, model: str = "", keep_minutes: int = 30) -> ToolResult:
    from .. import localai

    name = model or ctx.local.model
    names = await _models(ctx, [name])
    if isinstance(names, ToolResult):
        return names
    try:
        r = await localai.warm_up(ctx, name, f"{max(1, min(keep_minutes, 24 * 60))}m")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Model se nenačetl: {e}")
    return ToolResult(r["loaded"], f"{name} připraven: načtení {r['load_s']} s, teď odpovídá za {r['ready_s']} s" +
                      (f", {r['vram_gb']} GB v grafice" if r["vram_gb"] else ", běží na procesoru") + f", zůstane {keep_minutes} min.", data=r)


@tool("compare_embedding_models", "Porovná nainstalované embedding modely (pro hledání podle významu) na českém testu: "
      "trefí správnou pasáž? Rozměr a rychlost. Doporučí nejlepší.", category="mozek", perm="system")
async def compare_embedding_models(ctx, models: list[str] | None = None) -> ToolResult:
    from .. import localai

    names = await _models(ctx, models, embedding=None if models else True)
    if isinstance(names, ToolResult):
        return names
    r = await localai.embedding_compare(ctx, names[:6])
    ok = [x for x in r if x["ok"]]
    if not ok:
        return ToolResult(False, "Žádný model nevrátil vektory: " + "; ".join(f"{x['model']}: {x['error']}" for x in r), data=r)
    best = ok[0]
    return ToolResult(True, "; ".join(f"{x['model']}: trefa {int(100 * x['recall_at_1'])} %, {x['dims']} rozměrů, {x['texts_per_s']} textů/s" for x in ok) +
                      f". Doporučuji {best['model']} (Nastavení → Paměť → model pro hledání podle významu).", data=r)


@tool("test_model_accuracy", "Otestuje místní modely na otázkách se známou odpovědí (výchozí sada, nebo vlastní otázky) – "
      "kolik odpověděly správně a kde chybovaly.", category="mozek", perm="system")
async def test_model_accuracy(ctx, models: list[str] | None = None,
                              questions: Annotated[list[dict] | None, "[{q: otázka, a: [správné odpovědi]}]"] = None) -> ToolResult:
    from .. import localai

    names = await _models(ctx, models, embedding=False)
    if isinstance(names, ToolResult):
        return names
    tests = [(x["q"], x["a"] if isinstance(x["a"], list) else [x["a"]]) for x in questions] if questions else None
    r = await localai.accuracy(ctx, names[:4], tests)
    ok = [x for x in r if x["ok"]]
    if not ok:
        return ToolResult(False, "Žádný model neodpověděl.", data=r)
    return ToolResult(True, "; ".join(f"{x['model']}: {x['correct']}/{x['total']} správně ({x['seconds']} s)" for x in ok) + ".", data=r)


# ---------------------------------------------------------------------------------------------- documents
@tool("index_documents", "Zaindexuje složku tvých dokumentů (PDF, Word, text, Markdown, CSV, web, kód) pro hledání a odpovědi "
      "s citacemi. Dokumenty zůstávají v PC; opakované spuštění zpracuje jen změny.", category="paměť", perm="files_read")
async def index_documents(ctx, folder: str, workspace: Annotated[str, "název pracovního prostoru (prázdné = název složky)"] = "") -> ToolResult:
    from .. import docsearch

    root = resolve(folder)
    if not root.is_dir():
        return ToolResult(False, f"Složka neexistuje: {root}")
    r = await asyncio.to_thread(docsearch.index_folder, ctx, root, workspace)
    msg = (f"Prostor „{r['workspace']}“: {r['files']} souborů, {r['chunks']} úryvků (nové {r['added']}, změněné {r['updated']}, beze změny "
           f"{r['unchanged']}, odstraněné {r['removed']}).")
    if r["failed"]:
        msg += " Nešlo přečíst: " + "; ".join(f"{f['file']} ({f['error']})" for f in r["failed"][:5]) + "."
    return ToolResult(True, msg, data=r)


@tool("search_documents", "Najde v zaindexovaných dokumentech pasáže k dotazu (i bez háčků a v jiném tvaru slova).",
      category="paměť", perm="files_read")
async def search_documents(ctx, query: str, workspace: str = "", limit: int = 6) -> ToolResult:
    from .. import docsearch

    hits = await asyncio.to_thread(docsearch.search, ctx, query, workspace, max(1, min(limit, 20)))
    if not hits:
        return ToolResult(True, "Nic jsem nenašel." + ("" if docsearch.workspaces(ctx) else " Nejdřív zaindexuj složku (index_documents)."), data=[])
    return ToolResult(True, "\n".join(f"{h['file']} ({h['loc']}): {h['text'][:160].strip()}…" for h in hits), data=hits)


@tool("ask_documents", "Odpoví na otázku jen z tvých zaindexovaných dokumentů – každé tvrzení s odkazem na zdroj (soubor, "
      "stránka); když to v dokumentech není, řekne to.", category="paměť", perm="files_read")
async def ask_documents(ctx, question: str, workspace: str = "") -> ToolResult:
    from .. import docsearch

    if not docsearch.workspaces(ctx):
        return ToolResult(False, "Zatím nemám zaindexované žádné dokumenty – řekni „zaindexuj složku …“.")
    r = await docsearch.answer(ctx, question, workspace)
    src = "; ".join(f"[{s['n']}] {s['file']} {s['loc']}" for s in r["sources"])
    warn = ""
    if r["check"]["invalid"]:
        warn = f" (POZOR: odkazy {r['check']['invalid']} neexistují – odpověď ber s rezervou)"
    elif r["check"]["uncited_sentences"] and not r["check"]["not_found"]:
        warn = " (některá tvrzení nemají zdroj)"
    return ToolResult(True, r["answer"] + (f"\n\nZdroje: {src}" if src else "") + warn, data=r)


@tool("document_workspaces", "Seznam zaindexovaných pracovních prostorů dokumentů.", category="paměť")
async def document_workspaces(ctx) -> ToolResult:
    from .. import docsearch

    ws = docsearch.workspaces(ctx)
    return ToolResult(True, "; ".join(f"{w['workspace']} ({w['files']} souborů, {w['chunks']} úryvků)" for w in ws) or "Žádné.", data=ws)
