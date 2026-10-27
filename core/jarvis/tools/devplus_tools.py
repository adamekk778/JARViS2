"""Wave 36 by voice: migrations, backend performance, staging, canary, property tests, crash reproduction, battery,
browser compatibility and file relationships."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .devlab_tools import _file, _proj, _run
from .files import resolve


def _out(name: str, ext: str) -> Path:
    return paths.sub("vyvoj") / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}{ext}"


@tool("db_migration", "Vygeneruje SQL migraci, která převede databázi SQLite na strukturu jiné (nové tabulky, sloupce, indexy). "
      "Mazání dat jen jako zakomentované řádky. Nic nespouští – vyzkoušej náhledem migrace.", category="databáze", perm="files_read")
async def db_migration(ctx, current: Annotated[str, "současná databáze"], target: Annotated[str, "databáze s cílovou strukturou"]) -> ToolResult:
    from .. import devplus

    try:
        a, b = _file(current, "Databáze"), _file(target, "Databáze")
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(devplus.migration_sql, a, b)
    if err:
        return err
    if r["same"]:
        return ToolResult(True, "Struktura je stejná – migrace není potřeba.", data=r)
    out = _out("migrace", ".sql")
    out.write_text(r["sql"], encoding="utf-8")
    return ToolResult(True, f"Migrace: {r['statements']} příkazů" + (f", {r['risky']} rizikových kroků zakomentováno (mazání / změna typu)" if r["risky"] else "")
                      + ". Před spuštěním ji vyzkoušej na kopii (náhled migrace).", data=r, attachments=[str(out)])


@tool("backend_performance", "Výkon backendu: z access logu (nginx / Apache s časem odpovědi) najde nejpomalejší a nejvytíženější "
      "endpointy a chybovost, nebo změří odezvu tvých místních adres.", category="programování", perm="files_read")
async def backend_performance(ctx, log_file: Annotated[str, "access log"] = "", urls: Annotated[str, "místní adresy oddělené čárkou"] = "") -> ToolResult:
    from .. import devplus

    if log_file:
        try:
            p = _file(log_file, "Log")
        except ValueError as e:
            return ToolResult(False, str(e))
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-200_000:]
        r = devplus.endpoint_stats(lines)
        if not r["parsed"]:
            return ToolResult(False, "V logu nevidím požadavky ve formátu „GET /cesta HTTP/1.1“ 200.")
        top = r["endpoints"][:5]
        msg = "; ".join(f"{e['endpoint']} – {e['requests']}×" + (f", p95 {e['p95_ms']} ms" if e["p95_ms"] is not None else "")
                        + (f", chyby {e['error_pct']} %" if e["errors"] else "") for e in top)
        note = "" if r["with_times"] else " (Log neobsahuje čas odpovědi – přidej $request_time do formátu logu.)"
        return ToolResult(True, f"{r['parsed']} požadavků. Nejvíc času: {msg}.{note}", data=r)
    targets = [u.strip() for u in urls.split(",") if u.strip()]
    if not targets:
        return ToolResult(False, "Zadej access log nebo místní adresy.")
    try:
        async with ctx.http() as c:
            r = await devplus.time_urls(c, targets[:20])
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, "Odezva: " + "; ".join(f"{x['url']} medián {x['median_ms']} ms" for x in r) + ".", data={"urls": r})


@tool("staging_preview", "Připraví testovací nasazení projektu: Dockerfile, docker-compose a .env šablonu (jen názvy proměnných, "
      "žádné hodnoty) a postup. Jen ukáže, nic nezapisuje.", category="programování", perm="files_read")
async def staging_preview(ctx, project: str) -> ToolResult:
    from .. import devplus

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    files, err = await _run(devplus.staging_files, root)
    if err:
        return err
    import json

    st, envs = json.loads(files.pop("_stack")), json.loads(files.pop("_env"))
    return ToolResult(True, f"Projekt typu {st['kind']}, start „{st['start'] or 'statický web'}“, {len(envs)} proměnných prostředí. "
                            f"Soubory: {', '.join(files)}. Řekni „vytvoř testovací nasazení“ a uložím je do projektu.", data={"files": files, "stack": st, "env": envs})


def _staging_details(a: dict, ctx=None) -> list[str]:
    return [f"Do projektu {a.get('project')} zapíše Dockerfile.staging, docker-compose.staging.yml, .env.staging.example a STAGING.md.",
            "Existující soubory se stejným názvem nepřepíše."]


@tool("staging_create", "Zapíše do projektu soubory pro testovací nasazení (Dockerfile, compose, .env šablona, postup). "
      "Nic nepřepisuje.", category="programování", perm="files_write", danger=True, details=_staging_details)
async def staging_create(ctx, project: str) -> ToolResult:
    from .. import devplus

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    files, err = await _run(devplus.staging_files, root)
    if err:
        return err
    written, kept = [], []
    for name, text in files.items():
        if name.startswith("_"):
            continue
        p = root / name
        if p.exists():
            kept.append(name)
            continue
        p.write_text(text, encoding="utf-8")
        written.append(name)
    return ToolResult(True, f"Zapsáno: {', '.join(written) or 'nic'}" + (f"; ponecháno beze změny: {', '.join(kept)}" if kept else "") +
                      ". Vyplň .env.staging (testovací hodnoty) a spusť podle STAGING.md.", data={"written": written, "kept": kept})


@tool("canary_check", "Postupné nasazení (canary): porovná chybovost a odezvu nové verze se starou a doporučí pustit dál, počkat, "
      "nebo vrátit – i s dalším podílem provozu (1 → 5 → 25 → 50 → 100 %).", category="programování")
async def canary_check(ctx, old_requests: int, old_errors: int, new_requests: int, new_errors: int,
                       old_p95_ms: float = 0, new_p95_ms: float = 0, current_pct: float = 5) -> ToolResult:
    from .. import devplus

    r = devplus.canary_decision({"requests": old_requests, "errors": old_errors, "p95_ms": old_p95_ms or None},
                                {"requests": new_requests, "errors": new_errors, "p95_ms": new_p95_ms or None})
    nxt = devplus.canary_next(current_pct, r["decision"])
    return ToolResult(True, f"{r['decision'].capitalize()}: {r['reason']} Další podíl provozu: {nxt:g} %.", data={**r, "next_pct": nxt})


def _prop_details(a: dict, ctx=None) -> list[str]:
    return [f"Spustí tvůj kód {a.get('file')} (funkci {a.get('function')}) v odděleném procesu s náhodnými vstupy.",
            "Kód se vykoná – pouštěj jen vlastní projekty."]


@tool("property_test", "Testy vlastností (property-based, Python): funkci zavolá stovkami náhodných vstupů podle typů parametrů a "
      "ověří vlastnost – nespadne / f(f(x)) = f(x) / inverze vrátí vstup / výsledek seřazený. Ukáže protipříklady.",
      category="programování", perm="shell", danger=True, details=_prop_details)
async def property_test(ctx, file: Annotated[str, "soubor .py"], function: Annotated[str, "název funkce"],
                        property: Annotated[str, "no_crash / idempotent / roundtrip / sorted"] = "no_crash",  # noqa: A002
                        inverse: Annotated[str, "inverzní funkce (pro roundtrip)"] = "", runs: int = 300) -> ToolResult:
    from .. import devplus

    try:
        p = _file(file, "Soubor")
        r = await asyncio.to_thread(devplus.property_test, p, function, property, inverse, max(10, min(runs, 2000)))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    if r.get("error"):
        return ToolResult(False, "Test se nepodařilo spustit: " + r["error"][-300:])
    if r["ok"]:
        return ToolResult(True, f"{r['runs']} náhodných vstupů, vlastnost „{r['property']}“ platí vždy.", data=r)
    ex = r["fails"][0]
    return ToolResult(True, f"Protipříklad ({len(r['fails'])}): vstup {ex['args']} → {ex['problem']}.", data=r)


@tool("crash_repro", "Rozbor pádu: z chybového výpisu (Python traceback / JavaScript stack) najde místo ve tvém kódu, řetězec volání "
      "a připraví kostru testu, který pád zopakuje.", category="programování", perm="files_read")
async def crash_repro(ctx, crash: Annotated[str, "chybový výpis nebo cesta k souboru s ním"], project: str = "") -> ToolResult:
    from .. import devplus

    text = crash
    if len(crash) < 300 and "\n" not in crash and resolve(crash).is_file():
        text = resolve(crash).read_text(encoding="utf-8", errors="replace")[-50000:]
    root = None
    if project:
        root = _proj(ctx, project)
        if isinstance(root, ToolResult):
            return root
    r = devplus.parse_crash(text, root)
    if not r["frames"]:
        return ToolResult(False, "Ve výpisu nevidím řetězec volání (traceback / stack).")
    c = r["culprit"]
    msg = f"{r['exception']} – v {Path(c['file']).name}:{c['line']} ({c['func']})."
    if len(r["own_frames"]) > 1:
        msg += " Cesta: " + " → ".join(f["func"] for f in r["own_frames"][-5:]) + "."
    atts = []
    if r["test"]:
        out = _out("test_repro", ".py")
        out.write_text(r["test"], encoding="utf-8")
        atts.append(str(out))
        msg += " Kostru testu jsem přiložil – doplň do ní vstup, se kterým to spadlo."
    return ToolResult(True, msg, data=r, attachments=atts)


_BAT: dict = {}


@tool("battery_profiler", "Spotřeba baterie notebooku: „start“ začne měřit (na baterii), „výsledek“ řekne, kolik % za hodinu ubývá, "
      "na jak dlouho to vystačí a které programy nejvíc vytěžovaly procesor.", category="systém", perm="system")
async def battery_profiler(ctx, action: Annotated[str, "start / výsledek / stop"] = "výsledek") -> ToolResult:
    from .. import devplus

    if action == "start":
        if _BAT.get("task") and not _BAT["task"].done():
            return ToolResult(True, "Už měřím.")
        _BAT["samples"] = [await asyncio.to_thread(devplus.battery_sample)]
        if _BAT["samples"][0]["percent"] is None:
            return ToolResult(False, "Tenhle počítač nemá baterii.")

        async def loop():
            while len(_BAT["samples"]) < 720:            # max 6 hours at 30 s
                await asyncio.sleep(30)
                _BAT["samples"].append(await asyncio.to_thread(devplus.battery_sample))
        _BAT["task"] = asyncio.get_running_loop().create_task(loop())
        return ToolResult(True, "Měřím spotřebu. Nech notebook běžet na baterii aspoň 20 minut a pak se zeptej na výsledek.")
    samples = _BAT.get("samples") or []
    if action == "stop" and _BAT.get("task"):
        _BAT["task"].cancel()
    r = devplus.battery_profile(samples)
    if not r["ok"]:
        return ToolResult(False, r["reason"] + (" Řekni „start“." if not samples else ""))
    top = ", ".join(f"{t['app']} {t['share_pct']} %" for t in r["top"][:5])
    left = f", vydrží ještě asi {r['hours_left']} h" if r["hours_left"] else ""
    return ToolResult(True, f"Za {r['hours']} h ubylo {r['drop_pct']} % ({r['pct_per_hour']} %/h{left}). Procesor nejvíc: {top}.", data=r)


@tool("browser_compat", "Kompatibilita webu napříč prohlížeči: stránku otevře v Chromiu, Firefoxu a WebKitu (Safari), porovná chyby, "
      "neúspěšné požadavky, rychlost načtení a vzhled (snímky a rozdíly).", category="programování", perm="network")
async def browser_compat(ctx, url: str) -> ToolResult:
    from .. import devplus

    out = paths.sub("vyvoj") / f"kompatibilita-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        r = await devplus.engine_matrix(url, out)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Prohlížeče se nepodařilo spustit: {e}")
    parts = []
    for eng, x in r["engines"].items():
        if not x.get("available"):
            parts.append(f"{eng}: není nainstalovaný")
        elif x.get("error"):
            parts.append(f"{eng}: chyba ({x['error'][:60]})")
        else:
            bad = len(x["errors"]) + len(x["console"])
            parts.append(f"{eng}: {x['load_ms']} ms" + (f", {bad} chyb" if bad else "") + (f", {len(x['failed_requests'])} nenačtených" if x["failed_requests"] else ""))
    diff = "; ".join(f"{k} {v} % jinak" for k, v in r["visual_diff_pct"].items() if v is not None)
    return ToolResult(True, "; ".join(parts) + (f". Vzhled: {diff}." if diff else "."), data=r, attachments=r["screenshots"])


@tool("file_relations", "Vztahy souborů ve složce: co k sobě patří (stejný název v jiném formátu, zmínka nebo použití v jiném "
      "souboru, stejný obsah), hlavní uzly a osamocené soubory – i jako obrázek grafu.", category="soubory", perm="files_read")
async def file_relations(ctx, folder: str) -> ToolResult:
    from .. import devplus

    d = resolve(folder)
    if not d.is_dir():
        return ToolResult(False, f"Složka {d} neexistuje.")
    r, err = await _run(devplus.file_relations, d)
    if err:
        return err
    svg = _out("vztahy", ".svg")
    svg.write_text(devplus.relations_svg(r), encoding="utf-8")
    kinds: dict[str, int] = {}
    for e in r["edges"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    hubs = ", ".join(f"{h['file']} ({h['links']})" for h in r["hubs"][:3])
    return ToolResult(True, f"{r['files']} souborů, {len(r['edges'])} vazeb (" + ", ".join(f"{k}: {n}" for k, n in kinds.items()) + ")."
                      + (f" Nejvíc propojené: {hubs}." if hubs else "") + (f" Bez vazby: {len(r['lonely'])}." if r["lonely"] else ""),
                      data=r, attachments=[str(svg)])
