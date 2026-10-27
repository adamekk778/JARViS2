"""Wave 39 – security, privacy and the cloud.

* app permissions (OMEGA 391): which apps may use / recently used the camera, microphone, location… (Windows consent store)
* incident timeline (404): Defender detections, protection switched off, new services, cleared logs, failed logons, new
  accounts, new scheduled tasks – one timeline, most serious first
* ransomware recovery plan (399): how ready the PC is (protected folders, backups, restore points) and what to do if it hits
* consent receipts (676): what you allowed JARVIS (permissions, guests, shared folders…), when, and revoking it
* untrusted integrations (686): MCP servers you have not marked trusted ask before every action and their output is data
* project isolation (688 / 180): while a project is active, file tools stay inside its folder and only its permissions apply
* cloud (710 / 711): resources listed read-only through your own aws / az / gcloud login; cost anomalies from a billing CSV
* rollback rehearsal (715): the previous release checked out in a temporary worktree and its tests run
* search queries (385): better queries – exact phrases, operators, file types, sites, Czech + English variants
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .rescue import ALLOWED, PS_HEAD, PS_TAIL, cmdlets


def run_ps(script: str, timeout: float = 60, runner: Callable | None = None) -> dict:
    """A read-only PowerShell probe (only the cmdlets in rescue.ALLOWED) → parsed JSON."""
    from .pcreport import run_quiet

    bad = cmdlets(script) - ALLOWED
    if bad:
        raise ValueError(f"Nepovolené příkazy: {', '.join(sorted(bad))}")
    if sys.platform != "win32" and runner is None:
        return {"error": "Jen na Windows"}
    enc = base64.b64encode((PS_HEAD + script + PS_TAIL).encode("utf-16-le")).decode()
    code, out, err = (runner or run_quiet)(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], timeout)
    out = (out or "").strip()
    if code is None:
        return {"error": f"neodpovědělo do {timeout:.0f} s"}
    try:
        return json.loads(out[out.find("{"):]) if "{" in out else {"error": (err or "bez výstupu")[:300]}
    except ValueError as e:
        return {"error": f"nečitelný výstup: {e}"}


def _list(v: Any) -> list:
    return [] if v is None or (isinstance(v, dict) and "error" in v) else v if isinstance(v, list) else [v]


# ---------------------------------------------------------------- 391 app permissions
CAPS = {"webcam": "kamera", "microphone": "mikrofon", "location": "poloha", "contacts": "kontakty", "appointments": "kalendář",
        "userAccountInformation": "údaje o účtu", "phoneCall": "telefon", "chat": "zprávy", "radios": "rádia (Bluetooth / Wi-Fi)",
        "broadFileSystemAccess": "všechny soubory", "documentsLibrary": "dokumenty", "picturesLibrary": "obrázky",
        "screenshot": "snímání obrazovky", "graphicsCaptureProgrammatic": "nahrávání obrazovky"}
CONSENT_PS = r"""
T 'apps' { $base = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore'
  @(Get-ChildItem -LiteralPath $base -ErrorAction Stop | ForEach-Object { $cap = $_.PSChildName
    @(Get-ChildItem -LiteralPath $_.PSPath -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
      $p = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
      if ($p.Value -or $p.LastUsedTimeStart) { [pscustomobject]@{ Cap = $cap; App = $_.PSChildName; Value = "$($p.Value)";
        Start = [int64]$p.LastUsedTimeStart; Stop = [int64]$p.LastUsedTimeStop } } }) }) }
"""


def _filetime(v: Any) -> float | None:
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    return (v - 116444736000000000) / 1e7 if v > 116444736000000000 else None


def _app_name(raw: str) -> str:
    if "#" in raw:                        # C:#Program Files#App#app.exe (desktop apps)
        return raw.split("#")[-1]
    return re.sub(r"_[a-z0-9]{13}$", "", raw).split(".")[-1] if "." in raw else raw


def parse_consent(rows: list[dict], now: float | None = None) -> dict:
    now = now or time.time()
    by_cap: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cap = r.get("Cap", "")
        if r.get("App") in ("NonPackaged", cap):
            continue
        used = _filetime(r.get("Start"))
        active = bool(used and (_filetime(r.get("Stop")) or 0) < used)      # started and not stopped = using it right now
        by_cap[CAPS.get(cap, cap)].append({"app": _app_name(r.get("App", "")), "allowed": r.get("Value") != "Deny",
                                           "last_used": used, "in_use": active,
                                           "recent": bool(used and now - used < 7 * 86400)})
    for v in by_cap.values():
        v.sort(key=lambda a: -(a["last_used"] or 0))
    flags = [f"{a['app']} teď používá {cap}" for cap, apps in by_cap.items() for a in apps if a["in_use"]]
    flags += [f"{a['app']} použil {cap} v posledních 7 dnech" for cap in ("kamera", "mikrofon", "poloha", "nahrávání obrazovky")
              for a in by_cap.get(cap, []) if a["recent"] and not a["in_use"]]
    return {"capabilities": dict(by_cap), "flags": flags[:30]}


# ---------------------------------------------------------------- 404 incident timeline
EVENTS_PS = r"""
T 'defender' { @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Windows Defender/Operational'; Id=1116,1117,5001,5010,5012,5007; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 200 -ErrorAction SilentlyContinue | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0..3] -join ' ' }}) }
T 'system' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=7045,104; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 100 -ErrorAction SilentlyContinue | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0..2] -join ' ' }}) }
T 'security' { @(Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625,4720,4732,1102,4740; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 200 -ErrorAction Stop | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
T 'tasks' { @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'; Id=106; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 50 -ErrorAction SilentlyContinue | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
"""
EVENT_INFO = {  # id: (severity 3 = high, label)
    1116: (3, "Defender našel hrozbu"), 1117: (2, "Defender zasáhl proti hrozbě"), 5001: (3, "Ochrana v reálném čase VYPNUTA"),
    5010: (3, "Kontrola malwaru vypnuta"), 5012: (3, "Kontrola virů vypnuta"), 5007: (1, "Změna nastavení Defenderu"),
    7045: (2, "Nainstalovaná nová služba"), 104: (3, "Vymazán systémový protokol"), 1102: (3, "Vymazán bezpečnostní protokol"),
    4625: (1, "Neúspěšné přihlášení"), 4720: (3, "Vytvořen nový uživatelský účet"), 4732: (2, "Uživatel přidán do skupiny (např. správců)"),
    4740: (2, "Účet zablokován po špatných heslech"), 106: (1, "Naplánována nová úloha"),
}


def incident_timeline(data: dict) -> dict:
    events = []
    for log in ("defender", "system", "security", "tasks"):
        for e in _list(data.get(log)):
            try:
                eid = int(e.get("Id"))
            except (TypeError, ValueError):
                continue
            sev, label = EVENT_INFO.get(eid, (1, f"Událost {eid}"))
            events.append({"time": e.get("Time", ""), "id": eid, "severity": sev, "what": label, "detail": str(e.get("Text", ""))[:220], "log": log})
    failed = [e for e in events if e["id"] == 4625]
    bursts = []
    if len(failed) >= 10:                 # many failed logons in an hour = someone guessing passwords
        times = sorted(e["time"] for e in failed)
        for i in range(len(times) - 9):
            if times[i + 9][:13] == times[i][:13]:
                bursts.append(times[i][:13] + ":00")
        bursts = sorted(set(bursts))
    events.sort(key=lambda e: e["time"], reverse=True)
    serious = [e for e in events if e["severity"] == 3]
    notes = []
    if isinstance(data.get("security"), dict) and "error" in data["security"]:
        notes.append("Bezpečnostní protokol (přihlášení, účty) jde číst jen s oprávněním správce.")
    verdict = "vyžaduje pozornost" if serious or bursts else "nic vážného" if events else "žádné události"
    return {"events": events[:200], "serious": len(serious), "failed_logon_bursts": bursts, "verdict": verdict, "notes": notes}


# ---------------------------------------------------------------- 399 ransomware recovery plan
def ransomware_plan(security: dict, restore: dict, folders: list[dict], backups: dict) -> dict:
    checks = []
    d = security.get("defender") if isinstance(security.get("defender"), dict) else {}
    checks.append(("Antivirus a ochrana v reálném čase", bool(d.get("AntivirusEnabled") and d.get("RealTimeProtectionEnabled"))))
    checks.append(("Řízený přístup ke složkám (ochrana dokumentů před ransomwarem)", security.get("cfa") in (1, True, "1", "Enabled")))
    checks.append(("Ochrana proti neoprávněným změnám", bool(d.get("IsTamperProtected"))))
    rps = _list(restore.get("points") if isinstance(restore, dict) else None)
    checks.append(("Body obnovení systému", bool(rps)))
    last = backups.get("last_backup")
    fresh = bool(last and time.time() - last < 8 * 86400)
    checks.append(("Záloha mladší než týden", fresh))
    checks.append(("Záloha mimo počítač (externí disk / cloud s historií verzí)", bool(backups.get("offline"))))
    score = round(100 * sum(ok for _, ok in checks) / len(checks))
    total = sum(f.get("bytes", 0) for f in folders)
    todo = [name for name, ok in checks if not ok]
    steps = [
        "1. Hned odpoj počítač od sítě (Wi-Fi i kabel) – ať se šifrování nešíří na další zařízení a síťové disky.",
        "2. Nevypínej ho natvrdo a NEplať výkupné – data se často stejně nevrátí.",
        "3. Vyfoť zprávu útočníků (název a přípona souborů) – podle ní jde zjistit, o jaký ransomware jde a jestli existuje dešifrovač (nomoreransom.org).",
        "4. Z jiného, čistého zařízení změň hesla k e-mailu, bance a účtům.",
        "5. Počítač vyčisti (nejlépe přeinstaluj Windows) a teprve pak připoj zálohu a obnov z ní – nejnovější data jako první:",
    ] + [f"   – {Path(f['folder']).name}: {f['files']} souborů, {f['bytes'] / 1e9:.1f} GB" for f in folders[:6]] + [
        "6. Nahlas incident (Policie ČR / NÚKIB u firmy) a zkontroluj ostatní zařízení v síti.",
    ]
    return {"score": score, "checks": [{"check": n, "ok": ok} for n, ok in checks], "missing": todo,
            "data_gb": round(total / 1e9, 1), "steps": steps}


# ---------------------------------------------------------------- 676 consent receipts
SCHEMA = ("CREATE TABLE IF NOT EXISTS consents (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, what TEXT, scope TEXT, granted INTEGER, "
          "source TEXT, expires REAL, revoked REAL)")


def record_consent(rt, what: str, scope: str = "", granted: bool = True, source: str = "", expires: float | None = None) -> int:
    rt.db.exec(SCHEMA)
    return rt.db.exec("INSERT INTO consents (ts, what, scope, granted, source, expires) VALUES (?,?,?,?,?,?)",
                      (time.time(), what[:120], scope[:400], int(granted), source[:60], expires)).lastrowid


def consents(rt, include_old: bool = False) -> list[dict]:
    rt.db.exec(SCHEMA)
    rows = rt.db.all("SELECT * FROM consents ORDER BY ts DESC LIMIT 500")
    now = time.time()
    out = []
    for r in rows:
        active = r["granted"] and not r["revoked"] and (not r["expires"] or r["expires"] > now)
        if include_old or active:
            out.append({**r, "granted": bool(r["granted"]), "active": bool(active)})
    return out


def revoke_consent(rt, cid: int) -> bool:
    rt.db.exec(SCHEMA)
    return rt.db.exec("UPDATE consents SET revoked=? WHERE id=? AND revoked IS NULL", (time.time(), cid)).rowcount > 0


# ---------------------------------------------------------------- 688 / 180 project isolation
PATH_ARGS = ("path", "file", "folder", "src", "dst", "source", "target", "directory", "root", "project", "current", "save", "telemetry", "log_file")


def project_blocks(rt, spec, args: dict) -> str | None:
    """While an isolated project is active: permission areas outside its profile, and paths outside its folder, are refused."""
    lim = getattr(rt.cfg, "limits", None)
    if not lim or not getattr(lim, "project_isolation", False) or not getattr(rt, "knowledge", None):
        return None
    name = rt.knowledge.current_project()
    proj = rt.knowledge.project(name) if name else None
    if not proj:
        return None
    from .permissions import LABELS, required

    allowed = (getattr(lim, "project_perms", {}) or {}).get(proj["name"])
    if allowed is not None:
        bad = next((p for p in required(spec) if p not in allowed), None)
        if bad:
            return f"V projektu „{proj['name']}“ je „{LABELS.get(bad, bad)}“ vypnuté (Nastavení → Oprávnění → projekty)."
    folder = (proj.get("folder") or "").strip()
    if folder:
        from .tools.files import resolve

        base = Path(os.path.expandvars(os.path.expanduser(folder))).resolve()
        for k, v in (args or {}).items():
            if k in PATH_ARGS and isinstance(v, str) and v.strip() and not v.startswith(("http://", "https://")):
                p = resolve(v).resolve()
                if p != base and base not in p.parents:
                    return f"Projekt „{proj['name']}“ je oddělený – mimo jeho složku {base} teď nesahám."
    return None


# ---------------------------------------------------------------- 710 / 711 cloud
CLOUD_CMDS = {
    "aws": [["aws", "ec2", "describe-instances", "--output", "json", "--query", "Reservations[].Instances[].{id:InstanceId,type:InstanceType,state:State.Name}"],
            ["aws", "s3api", "list-buckets", "--output", "json", "--query", "Buckets[].Name"]],
    "azure": [["az", "resource", "list", "--output", "json", "--query", "[].{name:name,type:type,group:resourceGroup,location:location}"]],
    "gcp": [["gcloud", "compute", "instances", "list", "--format=json(name,status,zone,machineType)"],
            ["gcloud", "storage", "buckets", "list", "--format=json(name,location)"]],
}


def cloud_inventory(provider: str, runner=subprocess.run) -> dict:
    cmds = CLOUD_CMDS.get(provider)
    if not cmds:
        raise ValueError("Umím aws, azure, gcp.")
    exe = shutil.which(cmds[0][0]) if runner is subprocess.run else cmds[0][0]
    if not exe:
        raise FileNotFoundError(f"Chybí příkaz {cmds[0][0]} – nainstaluj CLI svého cloudu a přihlas se v něm (JARVIS nic sám nestahuje a hesla nezadává).")
    items, errors = [], []
    for cmd in cmds:
        r = runner([exe, *cmd[1:]], capture_output=True, text=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            errors.append((r.stderr or "").strip().splitlines()[-1:][0][:200] if r.stderr else f"chyba {r.returncode}")
            continue
        try:
            data = json.loads(r.stdout or "[]")
        except ValueError:
            continue
        kind = " ".join(cmd[1:3])
        for x in data if isinstance(data, list) else [data]:
            items.append({"kind": kind, **(x if isinstance(x, dict) else {"name": x})})
    return {"provider": provider, "items": items, "errors": errors}


def cost_anomalies(text: str, z_limit: float = 3.0) -> dict:
    """Billing CSV (date, service, cost – any provider's export with similar columns) → daily spikes per service."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV je prázdné.")
    cols = {c.lower().strip(): c for c in rows[0]}
    pick = lambda *names: next((cols[n] for n in cols if any(x in n for x in names)), None)  # noqa: E731
    dc, sc, cc = pick("date", "datum", "usagestart", "day"), pick("service", "služba", "product", "metercategory"), pick("cost", "náklad", "amount", "pretax")
    if not dc or not cc:
        raise ValueError("V CSV chybí sloupec s datem nebo cenou.")
    daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        try:
            v = float(str(r[cc]).replace(",", ".").replace(" ", ""))
        except ValueError:
            continue
        daily[(r[sc] if sc else "celkem") or "?"][str(r[dc])[:10]] += v
    out, totals = [], {}
    for svc, days in daily.items():
        vals = [days[d] for d in sorted(days)]
        totals[svc] = round(sum(vals), 2)
        if len(vals) < 5:
            continue
        for d in sorted(days)[3:]:
            prev = [days[x] for x in sorted(days) if x < d][-14:]
            med = statistics.median(prev)
            mad = statistics.median([abs(x - med) for x in prev]) or max(0.01, med * 0.1)
            z = (days[d] - med) / (1.4826 * mad)
            if z > z_limit and days[d] - med > 1:
                out.append({"service": svc, "date": d, "cost": round(days[d], 2), "usual": round(med, 2), "times": round(days[d] / med, 1) if med else None})
    out.sort(key=lambda x: -(x["cost"] - x["usual"]))
    return {"anomalies": out[:20], "totals": dict(sorted(totals.items(), key=lambda x: -x[1])[:15])}


# ---------------------------------------------------------------- 715 rollback rehearsal
def rollback_rehearsal(repo: Path, test_cmd: str, to: str = "", timeout: int = 900, run=subprocess.run) -> dict:
    """The previous release (or `to`) checked out in a temporary worktree; its tests run there; your working copy untouched."""
    import tempfile

    def git(*a: str) -> str:
        r = run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise ValueError((r.stderr or "git selhal").strip()[:300])
        return r.stdout.strip()
    def describe(ref: str) -> str:
        try:
            return git("describe", "--tags", "--abbrev=0", ref)
        except ValueError:
            return ""
    current = describe("HEAD") or git("rev-parse", "--short", "HEAD")
    target = to or describe(f"{current}^") if describe("HEAD") else to
    if not target:
        target = git("rev-parse", "--short", "HEAD~1") if git("rev-list", "--count", "HEAD") != "1" else ""
    if not target:
        raise ValueError("Není na co se vrátit – v repozitáři chybí předchozí verze (tag nebo commit).")
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-rollback-"))
    try:
        git("worktree", "add", "--detach", str(tmp / "wt"), target)
        t0 = time.monotonic()
        r = run(test_cmd, shell=True, cwd=str(tmp / "wt"), capture_output=True, text=True, timeout=timeout)
        took = round(time.monotonic() - t0, 1)
        out = (r.stdout or "") + (r.stderr or "")
    finally:
        try:
            git("worktree", "remove", "--force", str(tmp / "wt"))
        except ValueError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    runbook = [f"Současná verze: {current}, návrat na: {target}.", f"git checkout {target}  (nebo nasazení buildu této verze)",
               "Databázové migrace mezi verzemi vrať podle jejich down skriptů – JARVIS je nespouští.", f"Ověř: {test_cmd}"]
    return {"ok": r.returncode == 0, "from": current, "to": target, "seconds": took, "tests_tail": out[-2000:], "runbook": runbook}


# ---------------------------------------------------------------- 385 search queries
SYNONYMS = {"návod": ["jak", "tutorial", "how to"], "chyba": ["error", "nefunguje", "problém"], "levný": ["cheap", "nejlevnější", "sleva"],
            "recenze": ["review", "zkušenosti", "hodnocení"], "srovnání": ["vs", "comparison", "porovnání"], "zdarma": ["free", "open source"]}
STOP = {"a", "i", "v", "ve", "na", "se", "s", "z", "do", "je", "jak", "co", "pro", "the", "of", "to", "in", "how"}


def optimize_query(question: str, prefer_cz: bool = True) -> dict:
    q = " ".join(question.split())
    quoted = re.findall(r"„([^“]+)“|\"([^\"]+)\"", q)
    phrases = [a or b for a, b in quoted]
    errs = re.findall(r"(0x[0-9A-Fa-f]{6,8}|[A-Z_]{4,}_[A-Z_]+|\b[A-Z][a-zA-Z]+(?:Error|Exception)\b)", q)
    words = [w for w in re.findall(r"[\wěščřžýáíéůú.+#-]+", q.lower()) if w not in STOP and len(w) > 1]
    core = " ".join(dict.fromkeys(words))
    variants = [core]
    if errs:
        variants.insert(0, " ".join(f'"{e}"' for e in errs) + " " + " ".join(w for w in words if w.lower() not in (e.lower() for e in errs))[:60])
    for p in phrases:
        variants.append(f'"{p}" ' + " ".join(w for w in words if w not in p.lower().split())[:60])
    for w, syn in SYNONYMS.items():
        if w in words:
            variants.append(core.replace(w, f"({w} OR {' OR '.join(syn)})"))
    tips = []
    if re.search(r"\b(pdf|dokument|manuál|manual|příručka)\b", q, re.I):
        variants.append(core + " filetype:pdf")
        tips.append("filetype:pdf najde přímo dokumenty")
    if re.search(r"\b(reddit|fórum|forum|zkušenosti)\b", q, re.I):
        variants.append(core + " site:reddit.com")
        tips.append("site:reddit.com pro zkušenosti lidí")
    if re.search(r"\b(úřad|zákon|dotace|daně|daň)\b", q, re.I):
        variants.append(core + " site:gov.cz")
        tips.append("site:gov.cz pro oficiální informace")
    if re.search(r"\b(202[0-9]|letos|nejnovější|aktuální)\b", q, re.I):
        tips.append("omez výsledky na poslední rok (nástroje vyhledávače)")
    tips.append("-slovo vyřadí nechtěné výsledky, \"přesná fráze\" v uvozovkách")
    return {"variants": [v.strip() for v in dict.fromkeys(variants) if v.strip()][:6], "tips": tips}
