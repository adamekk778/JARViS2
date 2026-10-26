"""OMEGA wave 22 by voice: hardware incidents (USB tree and power, NVMe / SATA error logs with a heat map, a read-only
copy plan for a failing disk, a report for the repair shop) and site operations (hosting health, outage timeline,
log explorer, deployment difference, backups really arriving). Everything only reads."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


async def _probe(name: str):
    from .. import hwops

    try:
        return await asyncio.to_thread(hwops.probe, name), None
    except ValueError as e:
        return None, ToolResult(False, str(e))


@tool("usb_check", "Strom USB: řadiče → rozbočovače → zařízení, která mají problém (napájení, reset, ovladač), a co s tím. "
      "Jen čte.", category="systém", perm="system")
async def usb_check(ctx) -> ToolResult:
    from .. import hwops

    data, err = await _probe("usb_tree")
    if err:
        return err
    r = hwops.usb_tree(data)
    msg = f"{r['controllers']} řadičů, {r['devices']} zařízení. "
    msg += ("Problémy: " + "; ".join(f"{p['device']} – {p['meaning'] or 'kód ' + str(p['code'])}" for p in r["problems"][:6]) + ". ") if r["problems"] else "Žádné zařízení nehlásí chybu. "
    if r["power_events"]:
        msg += f"V logu {len(r['power_events'])} událostí s napájením / resetem portu. "
    return ToolResult(True, msg + " ".join(r["advice"]), data=r)


@tool("disk_errors", "Chybový záznam disků (NVMe i SATA): vadné bloky, resety řadiče, opakované čtení, teplota, opotřebení, "
      "a mapa, kde na disku jsou chyby čtení. Jen čte.", category="systém", perm="system")
async def disk_errors(ctx) -> ToolResult:
    from .. import hwops

    data, err = await _probe("storage")
    if err:
        return err
    r = hwops.storage_report(data)
    parts = []
    for d in r["disks"]:
        parts.append(f"{d['name']} ({d['bus']}, {d['size_gb']} GB): " + ("; ".join(d["issues"]) if d["issues"] else "bez chyb") +
                     (f" | mapa chyb {d['heatmap']}" if d["heatmap"] else ""))
    return ToolResult(True, " || ".join(parts) or "Žádný disk nenalezen.", data=r)


@tool("disk_copy_plan", "Plán, jak bezpečně dostat data z umírajícího disku: nic na něj nezapisovat, nejdřív nejcennější složky "
      "(příkazy robocopy, které vadná místa přeskočí), pak obraz celého disku, když cíl stačí.", category="systém", perm="files_read")
async def disk_copy_plan(ctx, source_gb: float, destination: Annotated[str, "kam kopírovat (disk nebo složka)"], used_gb: float = 0,
                         health: str = "Warning") -> ToolResult:
    import shutil

    from .. import hwops, secutils

    dest = resolve(destination)
    probe = dest if dest.exists() else dest.anchor and Path(dest.anchor)
    try:
        free = shutil.disk_usage(probe).free / 1e9
    except (OSError, TypeError):
        return ToolResult(False, f"Cíl {dest} nevidím – připoj disk, kam se má kopírovat.")
    folders = await asyncio.to_thread(secutils.rescue_plan, ctx)
    r = hwops.imaging_plan(source_gb, used_gb or source_gb, free, health, folders)
    return ToolResult(True, f"Cíl má volno {free:.0f} GB. " + " ".join(r["steps"]).replace("<CÍL>", str(dest)), data={**r, "dest_free_gb": round(free, 1)})


@tool("hardware_report", "Protokol pro servis: počítač (model, sériové číslo, BIOS), disky se stavem a chybami, události disků, "
      "USB problémy a další zjištění – uloží jako soubor, který můžeš poslat technikovi.", category="systém", perm="system")
async def hardware_report(ctx, problem: Annotated[str, "tvými slovy, co se děje"] = "") -> ToolResult:
    from .. import hwops, rescue

    storage, err = await _probe("storage")
    if err:
        return err
    usb, _ = await _probe("usb_tree")
    try:
        diag = await asyncio.to_thread(rescue.diagnose, ["crashes", "drivers", "boot"], rescue.run_quiet, False)
        findings = [f for res in diag.get("results", []) for f in res.get("findings", []) if f.get("level") in ("bad", "warn")]
    except Exception:  # noqa: BLE001 – the report still has disks and USB
        findings = []
    text = hwops.incident_report(hwops.storage_report(storage), hwops.usb_tree(usb) if usb else None, findings, problem)
    f = hwops.report_path("hw-protokol")
    f.write_text(text, encoding="utf-8")
    tasks = getattr(ctx, "tasks", None)
    if tasks is not None and tasks.current:
        tasks.add_artifact(f, "Hardwarový protokol")
    return ToolResult(True, f"Protokol uložen: {f} (SHA-256 {hashlib.sha256(f.read_bytes()).hexdigest()[:12]}…).", data={"path": str(f)})


# ---------------------------------------------------------------------------------------------- sites
@tool("hosting_health", "Zdraví webu a domény: DNS, e-mailové záznamy (MX, SPF, DMARC), certifikát, přesměrování na https, "
      "bezpečnostní hlavičky, rychlost. Zapíše výsledek do historie dostupnosti.", category="web", perm="network")
async def hosting_health(ctx, domain: str) -> ToolResult:
    from .. import hwops, netdiag

    async with ctx.http() as c:
        r = await hwops.hosting_health(c, domain, netdiag.tls_check)
    hwops.record_check(ctx, r["domain"], r["up"], r["http"].get("status"), r["http"].get("ms"), "; ".join(r["issues"])[:200])
    msg = f"{r['domain']}: " + ("běží" if r["up"] else "NEBĚŽÍ") + (f" ({r['http'].get('status')}, {r['http'].get('ms')} ms)" if r["http"].get("status") else "")
    if r["issues"]:
        msg += ". Problémy: " + "; ".join(r["issues"])
    if r["ok"]:
        msg += ". V pořádku: " + "; ".join(r["ok"])
    return ToolResult(True, msg + ".", data=r)


@tool("outage_timeline", "Historie výpadků webu z JARVISových kontrol (hosting_health a hlídání): dostupnost v %, kdy a jak "
      "dlouho web neběžel.", category="web")
async def outage_timeline(ctx, domain: str, days: int = 30) -> ToolResult:
    import re as _re

    from .. import hwops

    d = _re.sub(r"^https?://", "", domain.strip()).split("/")[0].lower()
    r = hwops.outage_timeline(ctx, d, days)
    if not r["checks"]:
        return ToolResult(True, f"Pro {d} zatím nemám žádné kontroly – spusť hosting_health nebo hlídání webu.", data=r)
    msg = f"{d}: {r['checks']} kontrol, dostupnost {r['uptime_pct']} %."
    if r["outages"]:
        msg += " Výpadky: " + "; ".join(f"{o['from_s']} ({o['minutes']} min{', trvá' if o['ongoing'] else ''})" for o in r["outages"][-8:])
    return ToolResult(True, msg, data=r)


@tool("explore_logs", "Projde logy (soubor nebo složku) a seskupí opakované chyby a varování podle podoby: kolikrát, kdy poprvé "
      "a naposledy, ve kterých souborech.", category="programování", perm="files_read")
async def explore_logs(ctx, path: str, level: Annotated[str, "error / warning / info"] = "warning", pattern: str = "",
                       since: Annotated[str, "od kdy, např. 2026-10-20"] = "") -> ToolResult:
    from .. import hwops

    p = resolve(path)
    if p.is_dir():
        files = sorted([f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in (".log", ".txt", ".out", ".err", "")], key=lambda f: f.stat().st_mtime)[-50:]
    elif p.is_file():
        files = [p]
    else:
        return ToolResult(False, f"Neexistuje: {p}")
    try:
        r = await asyncio.to_thread(hwops.explore_logs, files, level, pattern, since)
    except Exception as e:  # noqa: BLE001 – a bad regex
        return ToolResult(False, f"Nejde zpracovat: {e}")
    if not r["matched"]:
        return ToolResult(True, f"{r['lines']} řádků, nic na úrovni {level} a výš.", data=r)
    return ToolResult(True, f"{r['lines']} řádků, {r['matched']} odpovídá, {r['distinct']} různých hlášek. Nejčastější: " +
                      "; ".join(f"[{g['level']}] {g['example'][:90]} – {g['count']}× ({g['first'] or '?'} → {g['last'] or '?'})" for g in r["groups"][:5]), data=r)


@tool("deploy_diff", "Porovná dvě nasazení / verze (složky): přidané, odebrané a změněné soubory a rozdíly v konfiguraci "
      "(.env, json, ini) – hesla a klíče zamaskuje.", category="programování", perm="files_read")
async def deploy_diff(ctx, before: str, after: str) -> ToolResult:
    from .. import hwops

    a, b = resolve(before), resolve(after)
    if not a.is_dir() or not b.is_dir():
        return ToolResult(False, "Zadej dvě existující složky.")
    r = await asyncio.to_thread(hwops.deploy_diff, a, b)
    if r["same"]:
        return ToolResult(True, f"Nasazení jsou shodná ({r['files'][0]} souborů).", data=r)
    msg = f"Přidáno {len(r['added'])}, odebráno {len(r['removed'])}, změněno {len(r['changed'])} souborů."
    if r["config"]:
        msg += " Konfigurace: " + "; ".join(f"{f}: " + ", ".join(f"{k} {v[0]}→{v[1]}" for k, v in list(d.items())[:4]) for f, d in list(r["config"].items())[:3])
    return ToolResult(True, msg, data=r)


@tool("check_backups", "Dorazily zálohy? Projde složku se zálohami: jak stará je poslední, vynechané dny, prázdné nebo podezřele "
      "malé zálohy.", category="soubory", perm="files_read")
async def check_backups(ctx, folder: str, every_hours: float = 24, pattern: str = "") -> ToolResult:
    from .. import hwops

    p = resolve(folder)
    if not p.is_dir():
        return ToolResult(False, f"Složka neexistuje: {p}")
    r = await asyncio.to_thread(hwops.backup_check, p, every_hours * 1.1, pattern)
    if r["ok"]:
        return ToolResult(True, f"Zálohy v pořádku: {r['files']} souborů, poslední {r['newest']} před {r['newest_age_h']} h.", data=r)
    return ToolResult(True, "POZOR: " + "; ".join(r["issues"]) + ".", data=r)
