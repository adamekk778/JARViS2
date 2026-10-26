"""OMEGA wave 14 by voice: the testing lab – load with simulated users, unusual inputs, a network-fault proxy, memory
leaks, corrupted test data, translations that overflow (and pseudo-localisation), and browser tests: keyboard
accessibility, a device matrix, offline behaviour and scripted user flows with screenshots as evidence."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve

PROXIES: dict[int, dict] = {}


def _out(kind: str) -> Path:
    d = paths.data_dir() / "testlab" / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _evidence(ctx, files: list[str], title: str) -> None:
    tasks = getattr(ctx, "tasks", None)
    if tasks is None or not tasks.current:
        return
    for f in files:
        try:
            tasks.add_artifact(Path(f), f"{title}: {Path(f).name}")
        except OSError:
            continue


def _browser_error(e: Exception) -> ToolResult:
    return ToolResult(False, f"Test v prohlížeči selhal: {str(e).splitlines()[0][:300]}")


# ---------------------------------------------------------------------------------------------- load, fuzz, faults
def _load_details(a: dict, ctx=None) -> list[str]:
    return [f"{a.get('users', 10)} simulovaných uživatelů bude {a.get('seconds', 10)} s posílat požadavky na {a.get('url', '')}.",
            "Jen tvůj počítač nebo místní síť."]


@tool("load_test", "Zátěžový test vlastního serveru (počítač nebo místní síť): N simulovaných uživatelů po T sekund – "
      "odezva (p50/p95/p99), požadavky za sekundu, chyby a kdy se začaly objevovat.", danger=True, category="programování",
      perm="network", details=_load_details)
async def load_test(ctx, url: str, users: int = 10, seconds: int = 10) -> ToolResult:
    from .. import testlab

    try:
        r = await testlab.load_test(ctx.http, url, users, seconds)
    except ValueError as e:
        return ToolResult(False, str(e))
    msg = (f"{r['users']} uživatelů, {r['seconds']} s: {r['requests']} požadavků ({r['rps']}/s), odezva p50 {r['p50_ms']} ms, "
           f"p95 {r['p95_ms']} ms, p99 {r['p99_ms']} ms, chyby {r['error_pct']} %")
    if r["first_failure_s"] is not None:
        msg += f" (první chyba v {r['first_failure_s']}. s)"
    return ToolResult(True, msg + ".", data=r)


def _fuzz_details(a: dict, ctx=None) -> list[str]:
    return [f"Pošle na {a.get('url', '')} ({a.get('method', 'GET')}) neobvyklé hodnoty do: {', '.join(a.get('params') or [])}.",
            "Jen tvůj počítač nebo místní síť. U POST může server data opravdu uložit."]


@tool("fuzz_inputs", "Fuzzing vlastního API / stránky: pošle do parametrů neobvyklé vstupy (prázdné, obří, unicode, SQL, HTML, "
      "null…) a najde ty, na kterých server spadne, nebo je vrátí neošetřené.", danger=True, category="programování",
      perm="network", details=_fuzz_details)
async def fuzz_inputs(ctx, url: str, params: Annotated[list[str], "názvy parametrů / polí"], method: str = "GET",
                      body: Annotated[str, "JSON tělo pro POST/PUT (nepovinné)"] = "") -> ToolResult:
    from .. import testlab

    if method.upper() not in ("GET", "POST", "PUT", "PATCH"):
        return ToolResult(False, "Metoda: GET, POST, PUT nebo PATCH.")
    try:
        jb = json.loads(body) if body else None
        r = await testlab.fuzz(ctx.http, url, params, method.upper(), jb)
    except (ValueError, json.JSONDecodeError) as e:
        return ToolResult(False, str(e))
    if not r["findings"]:
        return ToolResult(True, f"{r['tried']} neobvyklých vstupů – server vše ustál.", data=r)
    return ToolResult(True, f"{len(r['findings'])} problémů z {r['tried']} vstupů: " +
                      "; ".join(f"{f['param']} = {f['input']} → {f['problem']}" for f in r["findings"][:8]) + ".", data=r)


@tool("network_fault_start", "Simulace špatné sítě: na tomto počítači spustí prostředníka (proxy) na cíl host:port, který "
      "zpožďuje, zahazuje spojení, škrtí rychlost nebo dělá úplný výpadek. Aplikaci nasměruj na vrácený port.",
      category="programování", perm="network")
async def network_fault_start(ctx, target: Annotated[str, "cíl host:port"], latency_ms: int = 0, drop_pct: int = 0,
                              kbps: int = 0, down: bool = False, minutes: int = 10) -> ToolResult:
    from .. import testlab

    host, _, port = target.rpartition(":")
    if not host or not port.isdigit():
        return ToolResult(False, "Cíl zadej jako host:port, např. localhost:8000.")
    p = testlab.FaultProxy(host.strip("[]"), int(port), latency_ms, drop_pct, kbps, down)
    local = await p.start()
    minutes = max(1, min(minutes, 120))

    async def expire():
        await asyncio.sleep(minutes * 60)
        await p.stop()
        PROXIES.pop(local, None)
    PROXIES[local] = {"proxy": p, "task": asyncio.create_task(expire()), "target": target}
    faults = ", ".join(x for x in (f"zpoždění {latency_ms} ms" if latency_ms else "", f"zahodí {drop_pct} % spojení" if drop_pct else "",
                                   f"rychlost {kbps} kB/s" if kbps else "", "úplný výpadek" if down else "") if x) or "bez poruch"
    return ToolResult(True, f"Prostředník běží na 127.0.0.1:{local} → {target} ({faults}), sám skončí za {minutes} min.",
                      data={"port": local, "target": target})


@tool("network_fault_stop", "Zastaví simulaci špatné sítě (port, nebo všechny) a řekne, kolik spojení prošlo / zahodil.",
      category="programování", perm="network")
async def network_fault_stop(ctx, port: int = 0) -> ToolResult:
    ports = [port] if port else list(PROXIES)
    if not ports or (port and port not in PROXIES):
        return ToolResult(False, "Žádná simulace neběží.")
    stats = {}
    for pt in ports:
        ent = PROXIES.pop(pt)
        ent["task"].cancel()
        await ent["proxy"].stop()
        stats[pt] = ent["proxy"].stats
    return ToolResult(True, "Zastaveno: " + "; ".join(f"{pt}: {s['connections']} spojení, zahozeno {s['dropped']}" for pt, s in stats.items()) + ".",
                      data=stats)


# ---------------------------------------------------------------------------------------------- memory, data, translations
@tool("memory_leak_check", "Sleduje paměť běžícího programu (název nebo PID, i s podprocesy) po zadanou dobu a vyhodnotí, "
      "jestli neroste jako při úniku paměti.", category="systém", perm="system")
async def memory_leak_check(ctx, process: str, seconds: int = 60, interval: int = 5) -> ToolResult:
    from .. import testlab

    seconds, interval = max(10, min(seconds, 900)), max(1, min(interval, 60))
    try:
        r = await asyncio.to_thread(testlab.watch_memory, process, seconds, interval)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – the process ended or access was denied
        return ToolResult(False, f"Proces nejde sledovat: {e}")
    return ToolResult(True, f"{process}: {r['start_mb']} → {r['end_mb']} MB za {seconds} s ({r['mb_per_min']:+} MB/min, "
                            f"R² {r['r2']}) – {r['verdict']}.", data=r)


@tool("corrupt_test_data", "Z testovacího souboru vyrobí poškozené kopie (prázdný, useknutý, přehozené bity, vynulovaný "
      "blok, neplatné UTF-8, zdvojený, náhodný) do složky. Originál jen čte.", category="programování", perm="files_write")
async def corrupt_test_data(ctx, file: str, folder: Annotated[str, "kam (prázdné = vedle souboru, podsložka poskozene)"] = "") -> ToolResult:
    from .. import testlab

    src = resolve(file)
    if not src.is_file():
        return ToolResult(False, f"Soubor neexistuje: {src}")
    out = resolve(folder) if folder else src.parent / "poskozene"
    r = await asyncio.to_thread(testlab.corrupt_variants, src, out)
    return ToolResult(True, f"{len(r)} poškozených kopií ve {out}: " + ", ".join(v["variant"] for v in r) + ".", data=r)


def _corr_details(a: dict, ctx=None) -> list[str]:
    return [f"Vyrobí poškozené kopie {a.get('file', '')} a na každou spustí: {a.get('command', '')}"]


@tool("corruption_test", "Test odolnosti vůči poškozeným datům: na každou poškozenou kopii souboru spustí tvůj program "
      "({file} v příkazu) a řekne, kde odmítl chybou (dobře), spadl, zamrzl, nebo poškozená data tiše přijal.", danger=True,
      category="programování", perm="shell", details=_corr_details)
async def corruption_test(ctx, file: str, command: Annotated[str, "příkaz s {file}, např. python app.py --load {file}"],
                          timeout: int = 30) -> ToolResult:
    from .. import testlab

    src = resolve(file)
    if not src.is_file():
        return ToolResult(False, f"Soubor neexistuje: {src}")
    try:
        r = await asyncio.to_thread(testlab.corruption_test, src, command, _out("poskozena-data"), max(2, min(timeout, 300)))
    except ValueError as e:
        return ToolResult(False, str(e))
    by = {}
    for x in r["results"]:
        by.setdefault(x["outcome"], []).append(x["variant"])
    msg = "; ".join(f"{k}: {', '.join(v)}" for k, v in by.items())
    verdict = "Program poškozená data zvládá." if not r["bad"] and not r["accepted"] else \
              ("PROBLÉM – spadl nebo zamrzl." if r["bad"] else "Pozor – některá poškozená data přijal bez chyby.")
    return ToolResult(True, f"{verdict} {msg}.", data=r)


@tool("translation_overflow", "Najde překlady, které se nevejdou: výrazně delší než originál (nebo nad zadaný limit) – "
      "typicky useknutá tlačítka. JSON, .po, .properties.", category="programování", perm="files_read")
async def translation_overflow(ctx, source: str, translated: str, ratio: float = 1.3,
                               limits: Annotated[str, "JSON {klíč: max znaků} (nepovinné)"] = "") -> ToolResult:
    from .. import devcheck, testlab

    try:
        s, d = devcheck.load_strings(resolve(source)), devcheck.load_strings(resolve(translated))
        lim = json.loads(limits) if limits else None
    except (OSError, ValueError) as e:
        return ToolResult(False, f"Soubor nejde přečíst: {e}")
    r = testlab.overflow(s, d, max(1.05, ratio), limits=lim)
    if not r:
        return ToolResult(True, f"{len(d)} přeložených textů – žádný výrazně delší.", data=[])
    return ToolResult(True, f"{len(r)} textů se možná nevejde: " + "; ".join(f"{x['key']} „{x['text'][:40]}“ ({x['why']})" for x in r[:8]) + ".", data=r)


@tool("pseudo_localize", "Vytvoří pseudo-překlad souboru s texty (JSON): háčky, o 40 % delší, v závorkách [!! … !!] – "
      "v aplikaci hned uvidíš, co se usekne nebo co zůstalo nepřeložené.", category="programování", perm="files_write")
async def pseudo_localize(ctx, source: str, target: str = "") -> ToolResult:
    from .. import testlab

    src = resolve(source)
    if not src.is_file():
        return ToolResult(False, f"Soubor neexistuje: {src}")
    dst = resolve(target) if target else src.with_name(src.stem + ".pseudo" + src.suffix)
    try:
        r = await asyncio.to_thread(testlab.pseudo_localize, src, dst)
    except (ValueError, json.JSONDecodeError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Pseudo-překlad {r['strings']} textů uložen: {r['path']}.", data=r)


# ---------------------------------------------------------------------------------------------- browser tests
@tool("keyboard_test", "Test ovládání stránky klávesnicí (Tab): pořadí, prvky, na které se klávesnicí nejde dostat, chybějící "
      "viditelné zvýraznění, past (focus trap). Adresa nebo soubor .html.", category="programování", perm="network")
async def keyboard_test(ctx, url: str) -> ToolResult:
    from .. import testlab

    try:
        r = await testlab.keyboard_test(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return _browser_error(e)
    parts = [f"Tabem projdeš {len(r['order'])} prvků"]
    if r["unreachable"]:
        parts.append("klávesnicí nedostupné: " + ", ".join(u["label"] for u in r["unreachable"][:6]))
    if r["no_focus_ring"]:
        parts.append("bez viditelného zvýraznění: " + ", ".join(r["no_focus_ring"][:6]))
    if r["trap"]:
        parts.append(f"focus se zasekne u „{r['trap']}“")
    if r["positive_tabindex"]:
        parts.append("tabindex > 0 mění pořadí: " + ", ".join(r["positive_tabindex"][:4]))
    return ToolResult(True, ("V pořádku. " if r["ok"] else "") + "; ".join(parts) + ".", data=r)


@tool("device_test", "Stránka na telefonu, tabletu, notebooku a monitoru: snímek obrazovky z každého, vodorovné "
      "posouvání, přečnívající prvky, malá tlačítka na dotyk a drobné písmo.", category="programování", perm="network")
async def device_test(ctx, url: str) -> ToolResult:
    from .. import testlab

    out = _out("zarizeni")
    try:
        r = await testlab.device_matrix(url, out)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return _browser_error(e)
    _evidence(ctx, [d["screenshot"] for d in r["devices"]], "Zařízení")
    parts = []
    for d in r["devices"]:
        bad = []
        if d["scroll_x"]:
            bad.append(f"posouvá se do strany ({d['page_width']} px na {d['width']})")
        if d["small_targets"]:
            bad.append(f"malá tlačítka: {', '.join(d['small_targets'][:3])}")
        if d["tiny_text"]:
            bad.append(f"drobné písmo ({len(d['tiny_text'])}×)")
        parts.append(f"{d['device']} {d['size']}: " + ("; ".join(bad) or "v pořádku"))
    return ToolResult(True, " | ".join(parts) + f". Snímky: {out}", data=r)


@tool("offline_test", "Jak se stránka / webová aplikace chová bez internetu: načte ji, odpojí síť a znovu načte – "
      "funguje (service worker, cache), nebo ukáže chybu?", category="programování", perm="network")
async def offline_test(ctx, url: str) -> ToolResult:
    from .. import testlab

    try:
        r = await testlab.offline_test(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return _browser_error(e)
    if r["works_offline"]:
        return ToolResult(True, "Bez internetu funguje" + (" (service worker)" if r["service_worker"] else "") + ".", data=r)
    return ToolResult(True, "Bez internetu NEFUNGUJE" + (f": {r['reload_error']}" if r["reload_error"] else "") +
                      ("" if r["service_worker"] else " – stránka nemá service worker, nic si neukládá.") , data=r)


@tool("user_flow_test", "Simulovaný uživatel: v čistém prohlížeči projde scénář krok po kroku („vyplň Hledat = mléko“, "
      "„klikni na Koupit“, „očekávej KOUPENO“, „jdi na /kosik“…) a po každém kroku uloží snímek jako důkaz.",
      category="programování", perm="network")
async def user_flow_test(ctx, url: str, steps: Annotated[list[str], "kroky scénáře"]) -> ToolResult:
    from .. import testlab

    if not steps:
        return ToolResult(False, "Zadej aspoň jeden krok.")
    out = _out("scenar")
    try:
        r = await testlab.user_flow(url, steps, out)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return _browser_error(e)
    _evidence(ctx, [s["screenshot"] for s in r["steps"]], "Scénář")
    if r["ok"]:
        return ToolResult(True, f"Scénář prošel: {r['total']} kroků za {sum(s['ms'] for s in r['steps'])} ms. Snímky: {out}", data=r)
    bad = next(s for s in r["steps"] if not s["ok"])
    return ToolResult(True, f"Scénář SELHAL v kroku {len(r['steps'])}/{r['total']} „{bad['step']}“: {bad['error']}. Snímky: {out}", data=r)
