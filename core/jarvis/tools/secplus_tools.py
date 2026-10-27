"""Wave 39 by voice: app permissions, the security incident timeline, ransomware readiness, consent receipts, the cloud,
rollback rehearsal and better search queries."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _when(ts: float | None) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d. %m. %H:%M") if ts else "?"


@tool("app_permissions", "Které aplikace smí a nedávno použily kameru, mikrofon, polohu, kontakty, nahrávání obrazovky… "
      "(záznamy Windows) – a která to dělá právě teď.", category="bezpečnost", perm="system")
async def app_permissions(ctx, capability: Annotated[str, "kamera / mikrofon / poloha / … (prázdné = vše)"] = "") -> ToolResult:
    from .. import secplus

    data = await asyncio.to_thread(secplus.run_ps, secplus.CONSENT_PS, 60)
    if "error" in data:
        return ToolResult(False, f"Záznamy o oprávněních nejde přečíst: {data['error']}")
    r = secplus.parse_consent(secplus._list(data.get("apps")))
    caps = {k: v for k, v in r["capabilities"].items() if not capability or capability.lower() in k}
    lines = []
    for cap, apps in caps.items():
        used = [a for a in apps if a["last_used"]][:4]
        if used:
            lines.append(f"{cap}: " + ", ".join(f"{a['app']} ({'TEĎ' if a['in_use'] else _when(a['last_used'])})" for a in used))
    head = " ".join(r["flags"][:3])
    return ToolResult(True, (head + " " if head else "") + ("; ".join(lines) or "Žádné záznamy o použití."), data=r)


@tool("security_timeline", "Časová osa bezpečnostních událostí za 30 dní: nálezy a vypnutí Defenderu, nové služby a naplánované úlohy, "
      "vymazané protokoly, neúspěšná přihlášení (i hromadné hádání hesla), nové účty a správci.", category="bezpečnost", perm="system")
async def security_timeline(ctx) -> ToolResult:
    from .. import secplus

    data = await asyncio.to_thread(secplus.run_ps, secplus.EVENTS_PS, 120)
    if "error" in data and len(data) == 1:
        return ToolResult(False, f"Protokoly nejde přečíst: {data['error']}")
    r = secplus.incident_timeline(data)
    top = [e for e in r["events"] if e["severity"] >= 2][:6]
    msg = f"Za 30 dní: {len(r['events'])} událostí, vážných {r['serious']} – {r['verdict']}."
    if top:
        msg += " " + "; ".join(f"{e['time'][:16].replace('T', ' ')} {e['what']}" for e in top)
    if r["failed_logon_bursts"]:
        msg += f" Hromadné pokusy o heslo: {', '.join(r['failed_logon_bursts'][:3])}."
    return ToolResult(True, msg + (" " + " ".join(r["notes"]) if r["notes"] else ""), data=r)


@tool("ransomware_readiness", "Připravenost na ransomware: antivirus, ochrana složek, body obnovení, zálohy (čerstvé a mimo PC) – "
      "skóre, co chybí a krok za krokem, co dělat, když to přijde.", category="bezpečnost", perm="system")
async def ransomware_readiness(ctx, offline_backup: Annotated[bool, "máš zálohu na externím disku / v cloudu s verzemi?"] = False) -> ToolResult:
    from .. import rescue, secplus, secutils

    sec = await asyncio.to_thread(rescue.run_probe, "security")
    res = await asyncio.to_thread(rescue.run_probe, "restore")
    folders = await asyncio.to_thread(secutils.rescue_plan, ctx)
    last = None
    for d in (paths.data_dir() / "zalohy", paths.data_dir() / "backups"):
        if d.is_dir():
            times = [p.stat().st_mtime for p in d.iterdir() if p.is_file()]
            last = max(times + [last or 0]) or last
    r = secplus.ransomware_plan(sec.get("data") or {}, res.get("data") or {}, folders, {"last_backup": last, "offline": offline_backup})
    out = paths.sub("bezpecnost") / f"plan-ransomware-{time.strftime('%Y%m%d')}.txt"
    out.write_text("Plán pro případ ransomwaru\n\n" + "\n".join(f"[{'OK' if c['ok'] else '!!'}] {c['check']}" for c in r["checks"])
                   + "\n\nKdyž to přijde:\n" + "\n".join(r["steps"]) + "\n", encoding="utf-8")
    miss = "; ".join(r["missing"]) or "nic"
    return ToolResult(True, f"Připravenost {r['score']} %. Chybí: {miss}. Plán postupu jsem uložil (vytiskni si ho – při útoku k PC nebudeš moct).",
                      data=r, attachments=[str(out)])


@tool("consents", "Evidence souhlasů: co jsi JARVISovi povolil (dočasná oprávnění, přístup hostů, sdílené složky…), kdy a do kdy – "
      "nebo souhlas odvolá.", category="soukromí")
async def consents(ctx, revoke: Annotated[int, "číslo souhlasu k odvolání (0 = jen vypsat)"] = 0, all_history: bool = False) -> ToolResult:
    from .. import mobileplus, secplus

    if revoke:
        row = next((c for c in secplus.consents(ctx, True) if c["id"] == revoke), None)
        if not row or not secplus.revoke_consent(ctx, revoke):
            return ToolResult(False, f"Souhlas č. {revoke} nevidím nebo už je odvolaný.")
        if row["what"].startswith("Dočasný přístup hosta"):
            for g in mobileplus.list_guests(ctx):
                if g["name"] == row["scope"]:
                    mobileplus.revoke_guest(ctx, g["id"])
        if row["what"].startswith("Dočasné oprávnění"):
            from .. import permissions

            for p, label in permissions.LABELS.items():
                if label in row["what"]:
                    permissions.TEMP_GRANTS.pop(p, None)
        return ToolResult(True, f"Odvoláno: {row['what']} ({row['scope']}).")
    items = secplus.consents(ctx, all_history)
    if not items:
        return ToolResult(True, "Nemáš žádný platný souhlas – nic navíc není povolené.", data={"items": []})
    return ToolResult(True, "; ".join(f"{c['id']}. {c['what']} ({c['scope']}) od {_when(c['ts'])}" + (f" do {_when(c['expires'])}" if c["expires"] else "")
                                      + ("" if c["active"] else " – neplatí") for c in items[:12]), data={"items": items})


@tool("cloud_resources", "Co máš v cloudu (AWS / Azure / Google Cloud): servery, úložiště, zdroje – jen čtení přes tvoje přihlášené "
      "CLI (aws / az / gcloud).", category="síť", perm="network")
async def cloud_resources(ctx, provider: Annotated[str, "aws / azure / gcp"]) -> ToolResult:
    from .. import secplus

    try:
        r = await asyncio.to_thread(secplus.cloud_inventory, provider.lower().strip())
    except (ValueError, FileNotFoundError) as e:
        return ToolResult(False, str(e))
    if not r["items"] and r["errors"]:
        return ToolResult(False, "Cloud neodpověděl: " + "; ".join(r["errors"]) + " (jsi v CLI přihlášený?)")
    kinds: dict[str, int] = {}
    for i in r["items"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    running = [i for i in r["items"] if str(i.get("state") or i.get("status") or "").lower() in ("running", "running ")]
    return ToolResult(True, f"{provider}: {len(r['items'])} zdrojů (" + ", ".join(f"{k}: {n}" for k, n in kinds.items()) + ")"
                      + (f", běží {len(running)} serverů" if running else "") + ".", data=r)


@tool("cloud_costs", "Neobvyklé náklady v cloudu z exportu vyúčtování (CSV s datem, službou a cenou): dny, kdy služba stála výrazně "
      "víc než obvykle, a co stojí nejvíc.", category="síť", perm="files_read")
async def cloud_costs(ctx, file: str) -> ToolResult:
    from .. import secplus

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        r = secplus.cost_anomalies(p.read_text(encoding="utf-8-sig", errors="replace"))
    except ValueError as e:
        return ToolResult(False, str(e))
    top = ", ".join(f"{k} {v:g}" for k, v in list(r["totals"].items())[:4])
    if not r["anomalies"]:
        return ToolResult(True, f"Bez výkyvů. Nejvíc stojí: {top}.", data=r)
    a = r["anomalies"][0]
    return ToolResult(True, f"{len(r['anomalies'])} výkyvů, největší: {a['service']} {a['date']} – {a['cost']:g} místo obvyklých {a['usual']:g}"
                            + (f" ({a['times']}×)" if a["times"] else "") + f". Nejvíc stojí: {top}.", data=r)


def _rb_details(a: dict, ctx=None) -> list[str]:
    return [f"V dočasné kopii projektu {a.get('project')} se přepne na {a.get('to') or 'předchozí verzi'} a spustí: {a.get('test_cmd')}",
            "Tvoje pracovní kopie se nezmění; dočasná kopie se pak smaže."]


@tool("rollback_rehearsal", "Cvičná obnova: předchozí verzi projektu (tag / commit) vyzkouší v dočasné kopii – spustí testy – a připraví "
      "postup návratu. Pracovní kopie se nemění.", category="programování", perm="shell", danger=True, details=_rb_details)
async def rollback_rehearsal(ctx, project: str, test_cmd: str, to: str = "") -> ToolResult:
    from .. import secplus
    from .devlab_tools import _proj

    root = _proj(ctx, project)
    if isinstance(root, ToolResult):
        return root
    try:
        r = await asyncio.to_thread(secplus.rollback_rehearsal, root, test_cmd, to)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    head = f"Návrat z {r['from']} na {r['to']}: testy {'prošly' if r['ok'] else 'NEPROŠLY'} ({r['seconds']} s)."
    return ToolResult(True, head + " Postup: " + " → ".join(r["runbook"]), data=r)


@tool("search_query", "Vymyslí lepší vyhledávací dotazy: přesné fráze, chybové kódy v uvozovkách, operátory (site:, filetype:, OR, -), "
      "české i anglické varianty.", category="web")
async def search_query(ctx, question: str) -> ToolResult:
    from .. import secplus

    r = secplus.optimize_query(question)
    return ToolResult(True, "Zkus: " + " | ".join(r["variants"]) + ". Tipy: " + "; ".join(r["tips"]) + ".", data=r)
