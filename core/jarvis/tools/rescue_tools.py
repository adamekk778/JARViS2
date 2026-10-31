"""OMEGA wave 2 by voice: PC rescue (drivers, crashes, boot, USB, disks, services, security), performance and the
network / security checks. Everything here only reads, except the restore point and the memory test, which ask first."""
from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool

STEPS = ["Sběr dat (jen čtení)", "Vyhodnocení", "Zápis reportu", "Ověření výsledku"]
ALL_AREAS = ["drivers", "crashes", "apps", "boot", "usb", "disks", "services", "security", "network", "restore"]
ALIASES = {"ovladače": "drivers", "ovladace": "drivers", "modrá obrazovka": "crashes", "bsod": "crashes", "pády": "crashes",
           "aplikace": "apps", "start": "boot", "spuštění": "boot", "usb": "usb", "disk": "disks", "disky": "disks",
           "služby": "services", "sluzby": "services", "bezpečnost": "security", "viry": "security", "síť": "network",
           "sit": "network", "internet": "network", "obnova": "restore"}


def _areas(area: str) -> list[str]:
    if not area or area.strip().lower() in ("all", "vše", "vse", "všechno", "celý", "cely"):
        return list(ALL_AREAS)
    out = []
    for a in area.replace(";", ",").split(","):
        a = a.strip().lower()
        a = ALIASES.get(a, a)
        if a in ALL_AREAS and a not in out:
            out.append(a)
    return out


def _fmt(findings: list[dict], limit: int = 6) -> str:
    return " ".join(f["text"] + (f" ({f['fix']})" if f.get("fix") and f["level"] in ("bad", "warn") else "") for f in findings[:limit])


@tool("pc_diagnose", "Záchrana PC: hloubková diagnostika jen pro čtení – oblasti drivers (ovladače a zařízení s chybou), "
      "crashes (modré obrazovky, nečekaná vypnutí, výpisy paměti), apps (padající a zamrzající aplikace), boot (pomalý start, "
      "co ho brzdí), usb (nefunkční USB, odpojující se disky, RAW disk), disks (zdraví disků, SMART, vadné sektory), services "
      "(služby, které nenaběhly), security (Defender, firewall, podezřelý autostart a úlohy, otevřené porty), network, restore "
      "(body obnovy, test paměti). area = jedna nebo víc oddělených čárkou, nebo „all“. Vytvoří report s důkazy a ověří ho. "
      "Na „proč mi padá PC“, „modrá obrazovka“, „nejde USB“, „disk se nezobrazuje“, „pomalý start“, „mám virus?“.",
      category="systém", perm="system")
async def pc_diagnose(ctx, area: Annotated[str, "oblasti, např. 'crashes,drivers' nebo 'all'"] = "all",
                      open_report: bool = False) -> ToolResult:
    from .. import rescue

    areas = _areas(area)
    if not areas:
        return ToolResult(False, f"Neznámá oblast „{area}“. Umím: {', '.join(ALL_AREAS)}.")
    t = ctx.tasks
    t.set_criteria(rescue.CRITERIA)
    t.set_plan(STEPS, 0)
    data = await asyncio.to_thread(rescue.diagnose, areas)
    for r in data["results"]:
        t.add_evidence(f"sonda {r['area']}" if r["area"] != "smart" else "smartctl", r["title"],
                       _fmt(r["findings"], 2) if r["ok"] else r["error"], r["ok"])
    t.set_plan(STEPS, 2)
    path = await asyncio.to_thread(rescue.write_report, data)
    art = t.add_artifact(path, "Diagnostika PC")
    t.set_plan(STEPS, 3)
    t.set_verifying()
    checks = await asyncio.to_thread(rescue.verify_report, path, art["sha256"])
    for crit, ok, val in checks:
        t.add_evidence("ověření souboru", crit, val, ok)
    t.set_plan(STEPS, 4)
    attachments = []
    try:
        att = await ctx.store.save_path(path, mimetypes.guess_type(path.name)[0] or "text/html")
        attachments = [att.id]
    except Exception:
        pass
    if open_report:
        try:
            await asyncio.to_thread(ctx.platform.open_path, str(path))
        except Exception:
            pass
    failed = [c for c, ok, _ in checks if not ok]
    head = "Hlavní zjištění: " + _fmt(data["top"]) if data["top"] else "Nenašel jsem žádný problém."
    measured = sum(1 for r in data["results"] if r["ok"])
    msg = f"{head} Změřeno {measured} z {len(data['results'])} oblastí. Report: {path}."
    if failed:
        return ToolResult(False, msg + f" Ověření neprošlo: {'; '.join(failed)}.", data={"path": str(path)}, attachments=attachments)
    return ToolResult(True, msg, data={"path": str(path), "top": data["top"], "results": [
        {"area": r["area"], "ok": r["ok"], "findings": r["findings"]} for r in data["results"]]}, attachments=attachments)


@tool("explain_crash_code", "Vysvětlí kód modré obrazovky (např. 0x9F, 0x124, VIDEO_TDR_FAILURE) česky: co znamená a co s tím.",
      category="systém")
async def explain_crash_code(ctx, code: Annotated[str, "kód nebo text chyby"]) -> ToolResult:
    from .. import rescue

    name, why = rescue.explain_bugcheck(code)
    if not why:
        hit = next((f"0x{k:X}" for k, (n, _w) in rescue.BUGCHECKS.items() if n.lower() == code.strip().lower()), "")
        if hit:
            name, why = rescue.explain_bugcheck(hit)
    if not why:
        return ToolResult(False, f"Kód „{code}“ neznám. Pošli ho ve tvaru 0x… nebo název (např. MEMORY_MANAGEMENT).")
    return ToolResult(True, f"{name}: {why}.", data={"name": name, "why": why})


@tool("perf_check", "Výkon: co právě brzdí počítač (procesor, škrcení při přehřátí, RAM, disk, grafika, nejnáročnější "
      "programy) a odezva internetu (ping, kolísání, ztráta paketů). Na „proč se mi seká PC / hra“, „co brzdí počítač“.",
      category="systém", perm="system")
async def perf_check(ctx, seconds: Annotated[int, "jak dlouho měřit (2–30 s)"] = 5, network: bool = True) -> ToolResult:
    from .. import perf

    s = await asyncio.to_thread(perf.sample, max(2, min(30, int(seconds))))
    found = perf.bottlenecks(s)
    lat = await asyncio.to_thread(perf.tcp_latency) if network else None
    if lat:
        if lat["avg_ms"] is None:
            found.append({"level": "bad", "text": "Internet neodpovídá (100 % ztráta).", "fix": "", "source": "TCP 1.1.1.1:443"})
        elif lat["avg_ms"] > 80 or lat["jitter_ms"] > 20 or lat["loss_pct"] > 2:
            found.append({"level": "warn", "text": f"Síť: odezva {lat['avg_ms']} ms, kolísání {lat['jitter_ms']} ms, ztráta {lat['loss_pct']} %.",
                          "fix": "Pro hry kabel místo Wi-Fi, zavři stahování a streamování.", "source": "TCP 1.1.1.1:443"})
        else:
            found.append({"level": "ok", "text": f"Síť: odezva {lat['avg_ms']} ms, kolísání {lat['jitter_ms']} ms, ztráta {lat['loss_pct']} %.",
                          "fix": "", "source": "TCP 1.1.1.1:443"})
    try:
        g = (s.get("gpu") or {}).get("gpu")
        ctx.perf.record(s["cpu"], s["ram_pct"], g if isinstance(g, (int, float)) else None, lat and lat["avg_ms"])
    except Exception:
        pass
    return ToolResult(True, _fmt(found, 8), data={"sample": s, "latency": lat, "findings": found})


@tool("perf_benchmark", "Výkon: krátký test výkonu (asi 6 s – procesor, paměť, zápis a čtení disku) a porovnání s minulým "
      "měřením (před/po úpravě). Na „otestuj výkon“, „je PC pomalejší než minule?“.", category="systém", perm="system")
async def perf_benchmark(ctx, label: Annotated[str, "popisek, např. 'po vyčištění'"] = "") -> ToolResult:
    from .. import perf

    prev = ctx.perf.benches(1)
    b = await asyncio.to_thread(perf.benchmark, label)
    ctx.perf.save_bench(b)
    txt = (f"Procesor {b['cpu_score']} bodů, paměť {b['ram_gb_s']} GB/s, zápis {b['disk_write_mb_s']} MB/s, "
           f"čtení {b['disk_read_mb_s']} MB/s (čtení může jít z mezipaměti).")
    if prev:
        txt += " Proti minule: " + "; ".join(perf.compare(prev[0], b)) + "."
    return ToolResult(True, txt, data={"bench": b, "previous": prev[0] if prev else None})


@tool("perf_history", "Výkon v čase: průměr a špičky procesoru, paměti, disku a sítě za posledních N hodin "
      "(JARVIS měří každých 5 minut). Na „jak byl počítač vytížený včera“.", category="systém")
async def perf_history(ctx, hours: Annotated[float, "kolik hodin zpět"] = 24) -> ToolResult:
    s = ctx.perf.summary(hours)
    if not s["samples"]:
        return ToolResult(False, "Zatím nemám žádná měření – JARVIS je zapisuje každých 5 minut, zkus to později.")
    names = {"cpu": ("procesor", "%"), "ram": ("paměť", "%"), "disk_mb_s": ("disk", "MB/s"), "gpu": ("grafika", "%"), "net_ms": ("odezva sítě", "ms")}
    parts = [f"{names[k][0]} průměr {v['avg']} {names[k][1]}, max {v['max']}" for k, v in s.items() if k in names]
    return ToolResult(True, f"Za {hours:g} h ({s['samples']} měření): " + "; ".join(parts) + ".", data=s)


@tool("network_check", "Síťová diagnostika: Wi-Fi signál, rychlost DNS, odezva; s cílem (doména/URL) navíc trasa (tracert), "
      "certifikát HTTPS (platnost, vydavatel), dostupnost webu a co o doméně říkají veřejné DNS (Google, Cloudflare). "
      "Na „proč mi nejde internet“, „je web dole?“, „kdy vyprší certifikát“.", category="síť", perm="network")
async def network_check(ctx, target: Annotated[str, "doména nebo URL (volitelné)"] = "", route: bool = False) -> ToolResult:
    from .. import netdiag, perf

    out: dict = {}
    lines = []
    w = await asyncio.to_thread(netdiag.wifi)
    out["wifi"] = w
    if "signal_pct" in w:
        lines.append(f"Wi-Fi {w.get('ssid', '')}: signál {w['signal_pct']} %" + (" (slabý)" if w["signal_pct"] < 50 else ""))
    dns = await asyncio.to_thread(netdiag.dns_timing)
    out["dns"] = dns
    ok = [d for d in dns if "ms" in d]
    lines.append(f"DNS {round(sum(d['ms'] for d in ok) / len(ok))} ms" if ok else "DNS nefunguje – názvy webů se nepřekládají")
    lat = await asyncio.to_thread(perf.tcp_latency, "1.1.1.1", 443, 6)
    out["latency"] = lat
    lines.append(f"odezva {lat['avg_ms']} ms, ztráta {lat['loss_pct']} %" if lat["avg_ms"] is not None else "internet neodpovídá")
    if target:
        domain = target.strip().removeprefix("https://").removeprefix("http://").split("/")[0]
        h = await netdiag.http_check(ctx, target)
        out["http"] = h
        lines.append(f"{h['url']}: " + (f"funguje (HTTP {h['status']}, {h['ms']} ms)" if h["up"] else f"NEFUNGUJE ({h.get('status') or h.get('error', '')})"))
        tls = await asyncio.to_thread(netdiag.tls_check, domain)
        out["tls"] = tls
        if tls.get("valid"):
            lines.append(f"certifikát platí do {tls['expires']} ({tls['days_left']} dní, {tls['issuer']})")
        else:
            lines.append(f"certifikát: {tls.get('error')}")
        out["public_dns"] = await netdiag.dns_public(ctx, domain)
        lines.append("DNS: " + "; ".join(f"{k} {', '.join(v[:2]) or '—'}" for k, v in out["public_dns"].items()))
        if route:
            hops = await asyncio.to_thread(netdiag.trace, domain)
            out["trace"] = hops
            lost = [h_ for h_ in hops if h_["ip"] == "*"]
            lines.append(f"trasa {len(hops)} skoků" + (f", {len(lost)} neodpovědělo" if lost else ""))
    return ToolResult(True, ". ".join(lines) + ".", data=out)


@tool("check_link", "Bezpečnost: posoudí odkaz (bez otevření) – podvodná doména, napodobení banky nebo obchodu, IP adresa "
      "místo jména, zkracovač, punycode. Na „je tenhle odkaz bezpečný?“.", category="bezpečnost")
async def check_link(ctx, url: Annotated[str, "odkaz"]) -> ToolResult:
    from .. import secutils

    r = secutils.check_link(url)
    verdict = {"ok": "nevidím nic podezřelého", "warn": "pozor, něco je podezřelé", "bad": "vypadá jako podvod – neotvírej"}[r["level"]]
    return ToolResult(True, f"{r['host']}: {verdict}" + (": " + "; ".join(r["reasons"]) if r["reasons"] else "") + ".", data=r)


@tool("check_download", "Bezpečnost: zkontroluje stažený soubor – odkud přišel, čím doopravdy je (podle obsahu, ne přípony), "
      "digitální podpis, otisk SHA-256 a volitelně kontrola Microsoft Defenderem. Na „je tenhle soubor bezpečný?“.",
      category="bezpečnost", perm="files_read")
async def check_download(ctx, path: Annotated[str, "cesta k souboru"], scan: bool = True) -> ToolResult:
    from .. import secutils

    r = await asyncio.to_thread(secutils.check_file, path)
    if "error" in r:
        return ToolResult(False, r["error"])
    if scan:
        r["defender"] = await asyncio.to_thread(secutils.defender_scan, r["path"])
    parts = [f"{Path(r['path']).name}: {r['type']}"]
    if r["origin"]:
        parts.append(f"staženo z {r['origin'][:80]}")
    if r["reasons"]:
        parts.append("pozor: " + "; ".join(r["reasons"]))
    d = r.get("defender") or {}
    if d.get("clean"):
        parts.append("Defender nic nenašel")
    elif d.get("threats"):
        parts.append("DEFENDER NAŠEL HROZBU: " + ", ".join(d["threats"]))
    elif d.get("error"):
        parts.append(f"Defender: {d['error']}")
    return ToolResult(True, ", ".join(parts) + f". SHA-256 {r['sha256'][:16]}…", data=r)


@tool("scan_secrets", "Bezpečnost: najde v projektu uniklé klíče a hesla (API klíče, tokeny GitHubu/AWS, soukromé klíče, "
      "hesla v kódu). Klíč samotný nikdy nevypíše. Na „nemám v kódu heslo?“.", category="bezpečnost", perm="files_read")
async def scan_secrets(ctx, folder: Annotated[str, "složka projektu"]) -> ToolResult:
    from .. import secutils

    if not Path(folder).expanduser().is_dir():
        return ToolResult(False, f"Složka neexistuje: {folder}")
    hits = await asyncio.to_thread(secutils.scan_secrets, folder)
    if not hits:
        return ToolResult(True, "Nenašel jsem žádné klíče ani hesla.", data=[])
    s = "; ".join(f"{h['file']}:{h['line']} {h['kind']}" for h in hits[:8])
    return ToolResult(True, f"Našel jsem {len(hits)} možných tajemství: {s}. Klíče zneplatni a přesuň je do proměnných prostředí.", data=hits)


@tool("verify_copy", "Ověří, že kopie / záloha / přenesené soubory jsou bit po bitu stejné jako originál (SHA-256 každého "
      "souboru). Na „zkontroluj, že se záloha povedla“.", category="soubory", perm="files_read")
async def verify_copy(ctx, source: Annotated[str, "originál"], copy: Annotated[str, "kopie"]) -> ToolResult:
    from .. import secutils

    if not Path(source).expanduser().exists():
        return ToolResult(False, f"Originál neexistuje: {source}")
    r = await asyncio.to_thread(secutils.verify_copy, source, copy)
    if not r["different"] and not r["missing"]:
        return ToolResult(True, f"Kopie je v pořádku: všech {r['files']} souborů je shodných.", data=r)
    return ToolResult(False, f"Kopie NENÍ úplná: {len(r['missing'])} chybí, {len(r['different'])} se liší "
                      f"(např. {', '.join((r['missing'] + r['different'])[:3])}).", data=r)


@tool("data_rescue_plan", "Záchrana dat: když disk umírá nebo hlásí chyby – odhad šance na záchranu podle stavu disku a co "
      "zachránit jako první (tvoje složky seřazené od nejnovější práce). Nic nekopíruje ani nemaže.", category="soubory", perm="files_read")
async def data_rescue_plan(ctx) -> ToolResult:
    from .. import secutils

    from .. import rescue

    plan = await asyncio.to_thread(secutils.rescue_plan, ctx)
    if not plan:
        return ToolResult(False, "Nenašel jsem žádné uživatelské složky.")
    probe = await asyncio.to_thread(rescue.run_probe, "disks")       # OMEGA 703: the chance of getting the data off
    odds = secutils.recovery_odds(probe.get("data") or {}) if probe.get("ok") else []
    lines = [f"{i + 1}. {Path(p['folder']).name} ({p['files']} souborů, {p['bytes'] / 2**30:.1f} GB)" for i, p in enumerate(plan)]
    head = "".join(f"{o['disk']}: šance na záchranu {o['level']} (odhad {o['percent']} – {', '.join(o['reasons'])}). {o['advice']} "
                   for o in odds if o["level"] != "vysoká" or o["reasons"] != ["žádné známky poškození"])
    return ToolResult(True, head + "Pořadí záchrany: " + "; ".join(lines) + ". Kopíruj na jiný disk, nic neformátuj a disk zbytečně "
                      "nezatěžuj. Po kopii to ověřím (verify_copy).", data={"plan": plan, "odds": odds})


@tool("system_integrity_check", "Zkontroluje systémové soubory Windows (DISM /CheckHealth a SFC /VERIFYONLY) – jen kontrola, "
      "nic neopravuje. Trvá i několik minut, potřebuje správce.", category="systém", perm="system")
async def system_integrity_check(ctx) -> ToolResult:
    from .. import rescue

    r = await asyncio.to_thread(rescue.integrity_check)
    if not r.get("ok"):
        return ToolResult(False, r.get("error", "Nepovedlo se."))
    ctx.tasks.add_evidence("DISM /CheckHealth", "úložiště součástí", (r["dism"]["text"] or "")[-160:], r["dism"]["code"] == 0)
    ctx.tasks.add_evidence("SFC /VERIFYONLY", "systémové soubory", (r["sfc"]["text"] or "")[-160:], r["sfc"]["code"] == 0)
    return ToolResult(True, _fmt(r["findings"]), data={"findings": r["findings"]})


def _rp_details(args: dict) -> list[str]:
    return [f"Popis: {args.get('description') or 'JARVIS'}", "Windows uloží stav systému, ke kterému se jde vrátit."]


@tool("create_restore_point", "Vytvoří bod obnovy systému Windows (před instalací ovladače, úpravou nebo aktualizací). "
      "Vyžaduje schválení a práva správce.", danger=True, category="systém", perm="system", details=_rp_details)
async def create_restore_point(ctx, description: Annotated[str, "popis"] = "JARVIS") -> ToolResult:
    from .. import rescue

    ok, msg = await asyncio.to_thread(rescue.create_restore_point, description)
    if ok:
        ctx.tasks.add_evidence("Checkpoint-Computer", "bod obnovy", description, True)
    return ToolResult(ok, msg)


@tool("schedule_memory_test", "Otevře Diagnostiku paměti Windows (test RAM po restartu) – ty zvolíš, jestli restartovat hned. "
      "Na „otestuj paměť“, „mám vadnou RAM?“.", danger=True, category="systém", perm="system",
      details=lambda a: ["Otevře se okno Diagnostika paměti Windows; restart potvrdíš až v něm."])
async def schedule_memory_test(ctx) -> ToolResult:
    import shutil
    import subprocess
    import sys

    if sys.platform != "win32":
        return ToolResult(False, "Jen na Windows.")
    exe = shutil.which("mdsched.exe") or r"C:\Windows\System32\mdsched.exe"
    try:
        subprocess.Popen([exe])
    except OSError as e:
        return ToolResult(False, f"Diagnostiku paměti nejde otevřít: {e}")
    return ToolResult(True, "Otevřel jsem Diagnostiku paměti Windows. Po restartu test proběhne a výsledek ti pak přečtu (pc_diagnose restore).")


@tool("hardware_changes", "Co se změnilo v připojených zařízeních od minula (nová / odpojená USB, monitory, audio, Bluetooth…).",
      category="systém", perm="system")
async def hardware_changes(ctx) -> ToolResult:
    from .. import rescue

    r = await asyncio.to_thread(rescue.run_probe, "devices")
    if not r["ok"]:
        return ToolResult(False, f"Seznam zařízení nejde přečíst: {r['error']}")
    added, removed, now = hw_diff(ctx, rescue.device_snapshot(r["data"]))
    if added is None:
        return ToolResult(True, f"Zapamatoval jsem si {len(now)} zařízení; příště řeknu, co přibylo nebo zmizelo.", data=now)
    if not added and not removed:
        return ToolResult(True, f"Žádná změna ({len(now)} zařízení).", data=now)
    return ToolResult(True, "Nové: " + (", ".join(added) or "nic") + ". Odpojené: " + (", ".join(removed) or "nic") + ".",
                      data={"added": added, "removed": removed})


def hw_diff(rt, now: list[str]) -> tuple[list[str] | None, list[str], list[str]]:
    row = rt.db.one("SELECT v FROM kv WHERE k='hw_seen'")
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('hw_seen', ?)", (json.dumps(now),))
    if not row:
        return None, [], now
    before = set(json.loads(row["v"]))
    return sorted(set(now) - before), sorted(before - set(now)), now
