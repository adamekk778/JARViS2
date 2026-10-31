"""OMEGA wave 13 by voice: the developer lab – dependency risks and known vulnerabilities, SBOM, an update plan, test
coverage, mutation testing, API contracts and breaking changes, a migration preview, code ownership, regressions and
flaky tests, why a build failed, environment snapshots, release notes, feature flags, the module map and the packages
of a monorepo. Only mutation testing / repeated test runs execute anything (the project's own tests, after approval)."""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .dev import resolve_project
from .files import resolve


def _proj(ctx, project: str) -> Path | ToolResult:
    return resolve_project(ctx, project)


def _file(path: str, what: str = "Soubor") -> Path:
    p = resolve(path)
    if not p.is_file():
        raise ValueError(f"{what} neexistuje: {p}")
    return p


async def _run(fn, *a):
    try:
        return await asyncio.to_thread(fn, *a), None
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return None, ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – a parser or git error → a readable answer
        return None, ToolResult(False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------------------------- dependencies
@tool("dependency_risks", "Rizika závislostí projektu (requirements, pyproject, package.json + lock): neomezené verze, "
      "instalace přímo z gitu, instalační skripty, podezřelé názvy podobné populárním balíčkům. Bez internetu, nic nemění.",
      category="programování", perm="files_read")
async def dependency_risks(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    deps, err = await _run(devlab.dependencies, root)
    if err:
        return err
    if not deps:
        return ToolResult(False, "V projektu nevidím requirements.txt, pyproject.toml ani package.json.")
    risks = devlab.dep_risks(root, deps)
    head = f"{len(deps)} závislostí ({sum(1 for d in deps if d['ecosystem'] == 'pypi')} Python, {sum(1 for d in deps if d['ecosystem'] == 'npm')} npm)"
    if not risks:
        return ToolResult(True, head + ". Žádné riziko jsem nenašel.", data={"deps": deps, "risks": []})
    top = sorted(risks, key=lambda r: r["risk"] != "vysoké")
    return ToolResult(True, head + f". Rizika ({len(risks)}): " + "; ".join(f"{r['name']} – {r['why']}" for r in top[:8]) + ".",
                      data={"deps": deps, "risks": risks})


@tool("dependency_vulnerabilities", "Známé zranitelnosti závislostí projektu podle veřejné databáze OSV (osv.dev) – pro "
      "přesně dané verze (pinned nebo z lock souboru).", category="programování", perm="network")
async def dependency_vulnerabilities(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    deps, err = await _run(devlab.dependencies, root)
    if err:
        return err
    exact = [d for d in deps if d["version"]]
    if not exact:
        return ToolResult(False, "Žádná závislost nemá přesnou verzi – bez ní zranitelnosti nejde ověřit (zamkni verze / lock soubor).")
    try:
        async with ctx.http() as c:
            vulns = await devlab.osv_check(c, exact)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Databáze OSV nedostupná: {e}")
    skipped = len(deps) - len(exact)
    tail = f" ({skipped} bez přesné verze jsem přeskočil)" if skipped else ""
    if not vulns:
        return ToolResult(True, f"U {len(exact)} závislostí nejsou známé zranitelnosti{tail}.", data={"vulns": [], "checked": len(exact)})
    return ToolResult(True, f"Zranitelné ({len(vulns)}): " + "; ".join(f"{v['name']} {v['version']}: {', '.join(v['vulns'][:3])}" for v in vulns[:10]) + tail + ".",
                      data={"vulns": vulns, "checked": len(exact)})


@tool("dependency_update_plan", "Plán aktualizace knihoven: zjistí nejnovější verze (PyPI / npm) a seřadí je – nejdřív "
      "bezpečné opravy, pak menší, velké verze po jedné s testy. Nic neinstaluje.", category="programování", perm="network")
async def dependency_update_plan(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    deps, err = await _run(devlab.dependencies, root)
    if err:
        return err
    if not deps:
        return ToolResult(False, "V projektu nevidím závislosti.")
    async with ctx.http() as c:
        latest = await devlab.latest_versions(c, deps)
    plan = devlab.update_plan(deps, latest)
    g = plan["groups"]
    head = f"Opravné {len(g['patch'])}, menší {len(g['minor'])}, velké {len(g['major'])}, aktuální {len(g['aktuální'])}."
    return ToolResult(True, head + (" " + " ".join(plan["steps"][:6]) if plan["steps"] else " Vše je aktuální."), data=plan)


@tool("make_sbom", "Vytvoří soupis softwarových součástí projektu (SBOM, formát CycloneDX JSON) – všechny knihovny s "
      "verzemi a licencemi.", category="programování", perm="files_write")
async def make_sbom(ctx, project: str, target: Annotated[str, "soubor (prázdné = sbom.cdx.json v projektu)"] = "") -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    bom, err = await _run(devlab.sbom, root)
    if err:
        return err
    if not bom["components"]:
        return ToolResult(False, "V projektu nevidím žádné závislosti.")
    out = resolve(target) if target else root / "sbom.cdx.json"
    if out.exists():
        try:
            if json.loads(out.read_text(encoding="utf-8")).get("bomFormat") != "CycloneDX":
                return ToolResult(False, f"{out.name} už existuje a není to SBOM – nepřepíšu ho.")
        except (json.JSONDecodeError, OSError):
            return ToolResult(False, f"{out.name} už existuje a není to SBOM – nepřepíšu ho.")
    out.write_text(json.dumps(bom, ensure_ascii=False, indent=2), encoding="utf-8")
    check = json.loads(out.read_text(encoding="utf-8"))
    ok = check.get("bomFormat") == "CycloneDX" and len(check["components"]) == len(bom["components"])
    return ToolResult(ok, f"SBOM uložen: {out} ({len(bom['components'])} součástí, ověřeno zpětným načtením).",
                      data={"path": str(out), "components": len(bom["components"])})


# ---------------------------------------------------------------------------------------------- tests
@tool("test_coverage", "Přečte report pokrytí testy (coverage.xml, lcov.info nebo coverage.json) a řekne, které soubory "
      "a řádky testy nepokrývají.", category="programování", perm="files_read")
async def test_coverage(ctx, report: str) -> ToolResult:
    from .. import devlab

    try:
        p = _file(report, "Report")
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(devlab.coverage, p)
    if err:
        return err
    worst = [f for f in r["files"] if f["pct"] < 100][:6]
    msg = f"Celkové pokrytí {r['total_pct']} % ({len(r['files'])} souborů)."
    if worst:
        msg += " Nejhůř: " + "; ".join(f"{Path(f['file']).name} {f['pct']} % (chybí ř. {', '.join(f['ranges'][:3])})" for f in worst)
    return ToolResult(True, msg, data=r)


def _mut_details(a: dict, ctx=None) -> list[str]:
    return [f"Zkopíruje projekt {a.get('project', '')} do dočasné složky a v kopii {a.get('max_mutants', 20)}× upraví "
            f"{a.get('file', '')} a spustí testy ({a.get('test_cmd') or 'automaticky zjištěné'}).", "Originál projektu se nemění."]


@tool("mutation_test", "Mutační testy (Python): v kopii projektu postupně mění kód souboru (== na !=, + na −, True na False…) "
      "a pouští testy. Přeživší mutace = místa, která testy ve skutečnosti nehlídají.", danger=True,
      category="programování", perm="shell", details=_mut_details)
async def mutation_test(ctx, project: str, file: Annotated[str, "soubor .py v projektu"], test_cmd: str = "",
                        max_mutants: int = 20) -> ToolResult:
    from .. import devlab
    from .dev import _detect_tests

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    target = (root / file) if not Path(file).is_absolute() else Path(file)
    if not target.is_file() or target.suffix != ".py":
        return ToolResult(False, f"Soubor {target} neexistuje nebo to není Python.")
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return ToolResult(False, "Soubor musí být uvnitř projektu.")
    cmd = test_cmd or _detect_tests(root)
    if not cmd:
        return ToolResult(False, "Nevím, jak spustit testy – zadej test_cmd.")
    if cmd.startswith("python "):
        cmd = f'"{devlab.python_exe()}" ' + cmd[len("python "):]
    r, err = await _run(devlab.mutation_test, root, target, cmd, max(1, min(max_mutants, 60)))
    if err:
        return err
    if not r["ok"]:
        return ToolResult(False, r["error"], data=r)
    msg = f"Skóre {r['score']} %: testy zachytily {r['killed']} z {r['tested']} mutací (v souboru je jich možných {r['total']})."
    if r["survived"]:
        msg += " Nezachyceno: " + "; ".join(f"ř. {s['line']} {s['change']}" for s in r["survived"][:6])
    return ToolResult(True, msg, data=r)


@tool("test_regressions", "Porovná dva výsledky testů (JUnit XML, např. pytest --junitxml): co nově padá, co se opravilo, "
      "co zmizelo a co je výrazně pomalejší.", category="programování", perm="files_read")
async def test_regressions(ctx, before: str, after: str) -> ToolResult:
    from .. import devlab

    try:
        a, b = _file(before, "Výsledek"), _file(after, "Výsledek")
    except ValueError as e:
        return ToolResult(False, str(e))
    ra, err = await _run(devlab.junit, a)
    if err:
        return err
    rb, err = await _run(devlab.junit, b)
    if err:
        return err
    r = devlab.regressions(ra, rb)
    parts = [f"nově padá {len(r['regressions'])}" + (": " + ", ".join(x["test"].split("::")[-1] for x in r["regressions"][:5]) if r["regressions"] else ""),
             f"opraveno {len(r['fixed'])}", f"pořád padá {len(r['still_failing'])}", f"zmizelo {len(r['removed'])}", f"nových {len(r['new'])}"]
    if r["slower"]:
        parts.append("pomalejší " + ", ".join(f"{x['test'].split('::')[-1]} {x['before']:.2f}→{x['after']:.2f} s" for x in r["slower"][:3]))
    return ToolResult(True, "; ".join(parts) + ".", data=r)


@tool("flaky_tests", "Najde nestabilní testy z více běhů stejného kódu (soubory JUnit XML) – testy, které jednou projdou a "
      "jindy ne.", category="programování", perm="files_read")
async def flaky_tests(ctx, results: Annotated[list[str], "soubory JUnit XML z opakovaných běhů"]) -> ToolResult:
    from .. import devlab

    if len(results) < 2:
        return ToolResult(False, "Potřebuju aspoň dva výsledky stejného kódu.")
    runs = []
    for f in results:
        try:
            r, err = await _run(devlab.junit, _file(f, "Výsledek"))
        except ValueError as e:
            return ToolResult(False, str(e))
        if err:
            return err
        runs.append(r)
    fl = devlab.flaky(runs)
    if not fl:
        return ToolResult(True, f"V {len(runs)} bězích se žádný test nechoval nestabilně.", data=[])
    return ToolResult(True, "Nestabilní: " + "; ".join(f"{x['test'].split('::')[-1]} ({x['failed']}/{x['runs']} padl)" for x in fl[:8]) + ".", data=fl)


def _flaky_details(a: dict, ctx=None) -> list[str]:
    return [f"Spustí testy projektu {a.get('project', '')} {a.get('runs', 5)}× za sebou (pytest) a porovná výsledky."]


@tool("find_flaky_tests", "Spustí testy projektu (pytest) několikrát za sebou a najde ty, které se chovají nestabilně.",
      danger=True, category="programování", perm="shell", details=_flaky_details)
async def find_flaky_tests(ctx, project: str, runs: int = 5, tests: Annotated[str, "jen tyto testy (cesta / -k výraz)"] = "") -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    runs = max(2, min(runs, 20))
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-flaky-"))
    results = []
    for i in range(runs):
        out = tmp / f"run{i}.xml"
        cmd = [devlab.python_exe(), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={out}", *([tests] if tests else [])]
        code, text = await asyncio.to_thread(devlab.run_cmd, cmd, root, 900)
        if not out.is_file():
            return ToolResult(False, f"Testy se nespustily (běh {i + 1}): {text[-400:]}")
        results.append(devlab.junit(out))
    fl = devlab.flaky(results)
    total = len(results[0])
    if not fl:
        return ToolResult(True, f"{runs} běhů × {total} testů: žádný nestabilní.", data={"flaky": [], "runs": runs})
    return ToolResult(True, f"{runs} běhů × {total} testů. Nestabilní: " + "; ".join(f"{x['test'].split('::')[-1]} ({x['failed']}/{x['runs']})" for x in fl[:8]) + ".",
                      data={"flaky": fl, "runs": runs})


# ---------------------------------------------------------------------------------------------- API, DB, build
@tool("api_contract_check", "Ověří, že odpověď API odpovídá kontraktu OpenAPI (YAML/JSON): buď zavolá adresu (jen GET), nebo "
      "zkontroluje uloženou odpověď (JSON soubor). Řekne přesně, které pole nesedí.", category="programování", perm="network")
async def api_contract_check(ctx, spec: Annotated[str, "soubor OpenAPI"], url: Annotated[str, "adresa endpointu (GET)"] = "",
                             path: Annotated[str, "cesta API, když kontroluješ soubor (např. /users/1)"] = "",
                             response_file: str = "", status: int = 200) -> ToolResult:
    from .. import devlab

    try:
        sp = await asyncio.to_thread(devlab.load_spec, _file(spec, "Specifikace"))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – broken YAML
        return ToolResult(False, f"Specifikaci nejde přečíst: {e}")
    if url:
        from urllib.parse import urlparse

        try:
            async with ctx.http() as c:
                resp = await c.get(url, timeout=20)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Adresa neodpovídá: {e}")
        api_path = urlparse(url).path
        for srv in sp.get("servers") or []:
            base = urlparse(str(srv.get("url", ""))).path.rstrip("/")
            if base and api_path.startswith(base):
                api_path = api_path[len(base):] or "/"
                break
        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            return ToolResult(False, f"Odpověď ({status}) není JSON.")
    else:
        if not (path and response_file):
            return ToolResult(False, "Zadej adresu (url), nebo cestu API (path) a uloženou odpověď (response_file).")
        try:
            body = json.loads(_file(response_file, "Odpověď").read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            return ToolResult(False, f"Odpověď nejde přečíst: {e}")
        api_path = path
    try:
        r = devlab.check_response(sp, api_path, "GET", status, body)
    except ValueError as e:
        return ToolResult(False, str(e))
    if r["ok"]:
        return ToolResult(True, f"GET {r['path']} ({status}) odpovídá kontraktu.", data=r)
    return ToolResult(True, f"GET {r['path']} ({status}) NEODPOVÍDÁ kontraktu ({len(r['errors'])}): " + "; ".join(r["errors"][:6]) + ".", data=r)


@tool("api_breaking_changes", "Porovná dvě verze kontraktu OpenAPI a řekne, co rozbije stávající klienty (odebrané "
      "endpointy a pole, nové povinné parametry, změněné typy) a co je jen nové.", category="programování", perm="files_read")
async def api_breaking_changes(ctx, old_spec: str, new_spec: str) -> ToolResult:
    from .. import devlab

    try:
        a = await asyncio.to_thread(devlab.load_spec, _file(old_spec, "Specifikace"))
        b = await asyncio.to_thread(devlab.load_spec, _file(new_spec, "Specifikace"))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Specifikaci nejde přečíst: {e}")
    r = devlab.breaking_changes(a, b)
    if r["compatible"]:
        return ToolResult(True, "Nová verze je zpětně kompatibilní." + (f" Nové: {'; '.join(r['added'][:6])}." if r["added"] else ""), data=r)
    return ToolResult(True, f"NEKOMPATIBILNÍ ({len(r['breaking'])}): " + "; ".join(r["breaking"][:8]) + ".", data=r)


@tool("migration_preview", "Náhled databázové migrace (SQLite): pustí SQL na KOPII databáze a ukáže, co se změní ve "
      "struktuře a počtech řádků, jestli prošla a kolik trvala. Originál zůstane.", category="programování", perm="files_read")
async def migration_preview(ctx, database: str, sql: Annotated[str, "SQL migrace nebo cesta k .sql souboru"]) -> ToolResult:
    from .. import devlab
    from .db_tools import _db

    try:
        db = _db(database)
    except ValueError as e:
        return ToolResult(False, str(e))
    if sql.strip().lower().endswith(".sql") and "\n" not in sql:
        try:
            sql = _file(sql.strip(), "Soubor migrace").read_text(encoding="utf-8")
        except ValueError as e:
            return ToolResult(False, str(e))
    r, err = await _run(devlab.migration_preview, db, sql)
    if err:
        return err
    d = r["drift"]
    parts = []
    if d["only_in_b"]:
        parts.append("nové tabulky " + ", ".join(d["only_in_b"]))
    if d["only_in_a"]:
        parts.append("smazané tabulky " + ", ".join(d["only_in_a"]))
    for t, ch in d["changed"].items():
        parts.append(f"{t}: " + ", ".join([*("+" + c for c in ch["added_columns"]), *("−" + c for c in ch["removed_columns"]),
                                            *("index +" + i for i in ch["added_indexes"]), *("index −" + i for i in ch["removed_indexes"])]))
    for t, v in r["rows"].items():
        parts.append(f"{t} řádků {v['before']} → {v['after']}")
    if r["error"]:
        return ToolResult(False, f"Migrace SELŽE: {r['error']}" + (f" (do té doby: {'; '.join(parts)})" if parts else "") + ". Originál beze změny.", data=r)
    return ToolResult(True, f"Migrace projde za {r['seconds']} s: " + ("; ".join(parts) or "beze změny struktury") +
                      (". Kopie po migraci je v pořádku." if r["integrity"] else ". POZOR: kopie po migraci neprošla kontrolou integrity.") +
                      " Originál beze změny.", data=r)


@tool("explain_build_failure", "Vysvětlí, proč selhal build / CI / instalace: najde první skutečnou chybu ve výpisu (text "
      "nebo soubor s logem), co znamená, kde je (soubor:řádek) a co s ní.", category="programování", perm="files_read")
async def explain_build_failure(ctx, log: Annotated[str, "výpis chyby, nebo cesta k souboru s logem"]) -> ToolResult:
    from .. import devlab

    text = log
    if "\n" not in log and len(log) < 400:
        p = resolve(log.strip())
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
    r = devlab.build_failure(text)
    if not r["found"]:
        return ToolResult(True, "Ve výpisu nevidím chybu. Poslední řádky: " + " | ".join(x.strip() for x in r["context"][-3:]), data=r)
    return ToolResult(True, f"Příčina: {r['what']}" + (f" ({r['where']})" if r["where"] else "") + f". Řešení: {r['fix']}. "
                      f"Řádek {r['line_no']}: {r['line'][:160]}", data=r)


# ---------------------------------------------------------------------------------------------- git, env, flags, structure
@tool("code_owners", "Kdo se stará o které části projektu (podle historie gitu), soubory, které zná jen jeden člověk, a "
      "„bus factor“ – kolik lidí drží polovinu práce.", category="programování", perm="files_read")
async def code_owners(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    r, err = await _run(devlab.ownership, root)
    if err:
        return err
    if not r["authors"]:
        return ToolResult(False, "V historii gitu nejsou žádné commity.")
    folders = "; ".join(f"{k}: {v['owner']} ({v['share']} %)" for k, v in list(r["folders"].items())[:8])
    return ToolResult(True, f"Bus factor {r['bus_factor']}. Autoři: " + ", ".join(f"{a} ({n})" for a, n in list(r["authors"].items())[:5]) +
                      f". Složky – {folders}." + (f" Jen jeden autor: {len(r['single_owner'])} souborů." if r["single_owner"] else ""), data=r)


@tool("release_notes", "Sepíše poznámky k vydání z commitů od poslední značky (tagu) nebo od zadaného místa: novinky, "
      "opravy, zásadní změny… (Markdown).", category="programování", perm="files_read")
async def release_notes(ctx, project: str, since: Annotated[str, "tag/commit (prázdné = poslední tag)"] = "", title: str = "") -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    r, err = await _run(devlab.release_notes, root, since, "HEAD", title)
    if err:
        return err
    if not r["commits"]:
        return ToolResult(True, f"Od {r['since'] or 'začátku'} nejsou žádné commity.", data=r)
    return ToolResult(True, r["markdown"], data=r)


def _envdir() -> Path:
    d = paths.data_dir() / "envs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool("environment_snapshot", "Zapíše, na čem kód běží (Windows, Python a jeho balíčky, Node, npm, git, .NET) pod názvem – "
      "pro „u mě to funguje“ srovnání s jiným počítačem. Bez proměnných prostředí (mohou obsahovat hesla).",
      category="programování", perm="files_read")
async def environment_snapshot(ctx, name: str) -> ToolResult:
    from .. import devlab

    if not re.fullmatch(r"[\w\- .]{1,40}", name):
        return ToolResult(False, "Název: písmena, číslice, mezera, pomlčka.")
    snap = await asyncio.to_thread(devlab.env_snapshot)
    f = _envdir() / f"{name}.json"
    f.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return ToolResult(True, f"Prostředí „{name}“ uloženo: {snap['os']}, Python {snap['python']}, {len(snap['packages'])} balíčků, "
                      + ", ".join(f"{k} {v}" for k, v in snap["tools"].items()) + f". Soubor: {f}", data={"path": str(f), **{k: snap[k] for k in ('os', 'python', 'tools')}})


@tool("environment_compare", "Porovná dvě uložená prostředí (název nebo soubor .json z jiného počítače): jiný Windows, "
      "Python, nástroje, balíčky a verze.", category="programování", perm="files_read")
async def environment_compare(ctx, first: str, second: str = "") -> ToolResult:
    from .. import devlab

    def load(n: str) -> dict:
        p = _envdir() / f"{n}.json"
        p = p if p.is_file() else resolve(n)
        if not p.is_file():
            raise ValueError(f"Prostředí „{n}“ nemám uložené.")
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        a = load(first)
        b = load(second) if second else await asyncio.to_thread(devlab.env_snapshot)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        return ToolResult(False, str(e))
    d = devlab.env_diff(a, b)
    if d["same"]:
        return ToolResult(True, "Prostředí jsou stejná.", data=d)
    parts = []
    if d["os"]:
        parts.append(f"systém {d['os'][0]} vs. {d['os'][1]}")
    if d["python"]:
        parts.append(f"Python {d['python'][0]} vs. {d['python'][1]}")
    parts += [f"{k} {v[0] or '—'} vs. {v[1] or '—'}" for k, v in d["tools"].items()]
    pk = d["packages"]
    if pk:
        parts.append(f"{len(pk)} balíčků jinak: " + ", ".join(f"{k} {v[0] or '—'}→{v[1] or '—'}" for k, v in sorted(pk.items())[:8]))
    return ToolResult(True, "; ".join(parts) + ".", data=d)


@tool("feature_flags", "Přepínače funkcí projektu (soubor flags.json): které jsou zapnuté, kde je kód používá, které už "
      "nikdo nepoužívá a které kód volá, ale nejsou definované.", category="programování", perm="files_read")
async def feature_flags(ctx, project: str, flags_file: str = "flags.json") -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    ff = root / flags_file
    if not ff.is_file():
        return ToolResult(False, f"Soubor přepínačů {ff} neexistuje.")
    r, err = await _run(devlab.flags_report, root, ff)
    if err:
        return err
    msg = ", ".join(f"{f['name']} {'ZAP' if f['on'] else 'vyp'} ({f['count']}×)" for f in r["flags"][:12])
    if r["stale"]:
        msg += f". Nepoužívané: {', '.join(r['stale'])}"
    if r["undefined"]:
        msg += f". Nedefinované, ale volané: {', '.join(r['undefined'])}"
    return ToolResult(True, msg + ".", data=r)


def _flag_details(a: dict, ctx=None) -> list[str]:
    return [f"Přepne {a.get('name', '')} na {'ZAPNUTO' if a.get('on') else 'VYPNUTO'} v {a.get('flags_file', 'flags.json')} projektu {a.get('project', '')}."]


@tool("set_feature_flag", "Zapne nebo vypne přepínač funkce v souboru flags.json projektu.", category="programování",
      perm="files_write", details=_flag_details)
async def set_feature_flag(ctx, project: str, name: str, on: bool, flags_file: str = "flags.json") -> ToolResult:
    from .. import devlab
    from .dev import auto_checkpoint

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    ff = root / flags_file
    if not ff.is_file():
        return ToolResult(False, f"Soubor přepínačů {ff} neexistuje.")
    await asyncio.to_thread(auto_checkpoint, ctx, ff)
    r, err = await _run(devlab.flag_set, ff, name, on)
    if err:
        return err
    now = devlab.flag_value(devlab.flags_load(ff).get(name))
    return ToolResult(now == on, f"{name}: {'zapnuto' if on else 'vypnuto'}" + (" (nový přepínač)" if r["before"] is None else "") + ".", data=r)


@tool("module_map", "Mapa projektu: kdo importuje koho (Python, TypeScript/JS), cyklické závislosti, nejzatíženější a "
      "největší moduly – a z toho plán refaktoringu.", category="programování", perm="files_read")
async def module_map(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    r, err = await _run(devlab.module_graph, root)
    if err:
        return err
    if not r["modules"]:
        return ToolResult(False, "V projektu nevidím soubory Python ani TypeScript/JS.")
    msg = f"{r['modules']} modulů, {r['edges']} vazeb, cyklů {len(r['cycles'])}."
    if r["fan_in"]:
        msg += " Nejvíc závislostí na: " + ", ".join(f"{n} ({k})" for n, k in r["fan_in"][:3]) + "."
    if r["plan"]:
        msg += " Plán: " + " ".join(r["plan"][:4])
    return ToolResult(True, msg, data={k: v for k, v in r.items() if k != "graph"} | {"graph_size": len(r["graph"])})


@tool("monorepo_map", "Jaké aplikace a balíčky repozitář obsahuje (npm, Python, Rust, .NET) a které na sobě závisí.",
      category="programování", perm="files_read")
async def monorepo_map(ctx, project: str) -> ToolResult:
    from .. import devlab

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    r, err = await _run(devlab.monorepo, root)
    if err:
        return err
    if not r["count"]:
        return ToolResult(False, "Nevidím žádný balíček (package.json, pyproject.toml, Cargo.toml, .csproj).")
    return ToolResult(True, f"{r['count']} balíčků: " + "; ".join(f"{p['name']} ({p['kind']}, {p['path']})" + (f" → {', '.join(p['internal'])}" if p["internal"] else "")
                                                         for p in r["packages"][:12]) + ".", data=r)


def _container_details(a: dict, ctx=None) -> list[str]:
    return [f"Do projektu {a.get('project')} zapíše Dockerfile, .dockerignore a .devcontainer/devcontainer.json "
            "(existující soubory nepřepíše). Nic nespouští ani nestahuje."]


@tool("container_setup", "Kontejner pro projekt: Dockerfile, .dockerignore a nastavení Dev Containers se stejnou verzí Pythonu / "
      "Node jako na tomhle PC (Python, Node nebo .NET projekt). Bez write jen ukáže, s write=true soubory zapíše (existující "
      "nepřepíše). Na „udělej mi na to Docker“, „ať to jede i jinde“.", category="programování", perm="files_write",
      danger_if=lambda a, ctx=None: bool(a.get("write")), details=_container_details)
async def container_setup(ctx, project: str, write: bool = False) -> ToolResult:
    from .. import devlab

    root = resolve_project(ctx, project)
    if isinstance(root, ToolResult):
        return root
    if not root.is_dir():
        return ToolResult(False, f"Složka neexistuje: {root}")
    snap = await asyncio.to_thread(devlab.env_snapshot)
    try:
        r = devlab.container_files(root, snap)
    except ValueError as e:
        return ToolResult(False, str(e))
    written, kept = [], []
    if write:
        for rel, text in r["files"].items():
            f = root / rel
            if f.exists():
                kept.append(rel)
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
            written.append(rel)
    head = f"Projekt {r['kind']}: " + (f"zapsáno {', '.join(written)}" if written else "náhled souborů")
    if kept:
        head += f"; ponechal jsem existující {', '.join(kept)}"
    body = "\n\n".join(f"{k}:\n{v}" for k, v in r["files"].items())
    return ToolResult(True, head + ". " + " ".join(r["notes"]) + "\n\n" + body[:3000], data={**r, "written": written, "kept": kept})


def coverage_plan(root: Path, out_dir: Path) -> tuple[list[str], Path] | None:
    """OMEGA 334: the commands that run the tests WITH coverage measuring and where the report lands (Python: coverage.py,
    JavaScript: c8). None = unknown project."""
    from .dev import _detect_tests

    test = _detect_tests(root) or ""
    if test.startswith("python"):
        rep = out_dir / "coverage.json"
        return ["python -m coverage run -m pytest -q", f'python -m coverage json -o "{rep}"'], rep
    if test.startswith("npm"):
        return [f'npx --no-install c8 --reporter=lcov --report-dir "{out_dir}" npm test'], out_dir / "lcov.info"
    return None


def _cov_details(a: dict, ctx=None) -> list[str]:
    return [f"Spustí testy projektu {a.get('project')} s měřením pokrytí (Python: coverage, JavaScript: c8).",
            "Testy spouští kód projektu. Report se uloží do dočasné složky, projekt se nemění."]


@tool("measure_coverage", "Spustí testy projektu s měřením pokrytí a řekne, které soubory a řádky testy nepokrývají "
      "(Python přes coverage.py, JavaScript přes c8 – musí být nainstalované v projektu).", danger=True,
      category="programování", perm="shell", details=_cov_details)
async def measure_coverage(ctx, project: str) -> ToolResult:
    from .. import devlab
    from .dev import _run_cmd

    root = resolve_project(ctx, project)
    if isinstance(root, ToolResult):
        return root
    with tempfile.TemporaryDirectory(prefix="jarvis-cov-") as td:
        plan = coverage_plan(root, Path(td))
        if not plan:
            return ToolResult(False, "Pokrytí umím změřit u projektů v Pythonu (pytest) a JavaScriptu (npm test).")
        cmds, rep = plan
        out = ""
        for c in cmds:
            code, o = await asyncio.to_thread(_run_cmd, c, root, 900)
            out += o
            if "No module named coverage" in o:
                return ToolResult(False, "V projektu chybí balíček coverage – nainstaluj ho příkazem: python -m pip install coverage")
            if "c8" in c and code != 0 and not rep.exists():
                return ToolResult(False, "Pro měření pokrytí v JavaScriptu chybí c8 – přidej ho: npm i -D c8")
        if not rep.exists():
            return ToolResult(False, "Report pokrytí nevznikl. Konec výstupu: " + out[-600:])
        r, err = await _run(devlab.coverage, rep)
    if err:
        return err
    worst = [f for f in r["files"] if f["pct"] < 100][:6]
    msg = f"Celkové pokrytí {r['total_pct']} % ({len(r['files'])} souborů)."
    if worst:
        msg += " Nejhůř: " + "; ".join(f"{Path(f['file']).name} {f['pct']} % (chybí ř. {', '.join(f['ranges'][:3])})" for f in worst)
    return ToolResult(True, msg, data=r)
