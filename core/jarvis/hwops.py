"""OMEGA §52 / §53 hardware incidents and site operations: the USB tree (controllers → hubs → devices) with power and
reset problems, NVMe / SATA error logs and a heat map of where on a disk the read errors are, a read-only plan for
copying data off a failing disk, a hardware incident report for a repair shop – and for websites: hosting health (DNS,
mail records, certificate, security headers, uptime timeline), a log explorer that groups repeated errors, the
difference between two deployments, and whether backups are really arriving.

Everything here only reads. Probes are fixed PowerShell scripts (no generated commands)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from . import paths
from .pcreport import run_quiet

HW_PS = {
    "usb_tree": r"""
T 'devices' { @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.InstanceId -like 'USB*' -or $_.Class -in 'USB','HIDClass','DiskDrive','WPD','Image','Media','Bluetooth' } | ForEach-Object {
  $par = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue).Data
  $code = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_ProblemCode -ErrorAction SilentlyContinue).Data
  [pscustomobject]@{ Name = $_.FriendlyName; Class = "$($_.Class)"; Status = "$($_.Status)"; Id = $_.InstanceId; Parent = "$par"; Problem = [int]$code } }) }
T 'controllers' { @(Get-PnpDevice -PresentOnly -Class USB -ErrorAction Stop | Where-Object { $_.FriendlyName -match 'Host Controller|xHCI|eXtensible|hostitelský' } | Select-Object FriendlyName, InstanceId, @{n='Status'; e={ "$($_.Status)" }}) }
T 'events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-14)} -MaxEvents 3000 -ErrorAction SilentlyContinue | Where-Object { $_.ProviderName -in 'USBHUB3','USBXHCI','Microsoft-Windows-Kernel-PnP','Microsoft-Windows-USB-USBHUB3' -and $_.Level -le 3 } | Select-Object -First 80 Id, ProviderName, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
""",
    "storage": r"""
T 'disks' { @(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object { $c = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
  [pscustomobject]@{ DeviceId = $_.DeviceId; Name = $_.FriendlyName; Bus = "$($_.BusType)"; Media = "$($_.MediaType)"; Health = "$($_.HealthStatus)"; Size = $_.Size;
    Serial = "$($_.SerialNumber)".Trim(); Firmware = "$($_.FirmwareVersion)"; Temperature = $c.Temperature; TempMax = $c.TemperatureMax; Wear = $c.Wear;
    ReadErrors = $c.ReadErrorsTotal; ReadUncorrected = $c.ReadErrorsUncorrected; WriteErrors = $c.WriteErrorsTotal; PowerOnHours = $c.PowerOnHours; StartStop = $c.StartStopCycleCount } }) }
T 'events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-60)} -MaxEvents 8000 -ErrorAction SilentlyContinue | Where-Object { ($_.ProviderName -in 'disk','Disk' -and $_.Id -in 7, 11, 15, 51, 52, 153, 154, 157) -or ($_.ProviderName -in 'storahci','stornvme','iaStorA','iaStorAC','iaStorAVC','storport','nvme' -and $_.Id -in 11, 129, 130) -or ($_.ProviderName -like '*Ntfs*' -and $_.Id -in 55, 98, 140) } | Select-Object -First 400 Id, ProviderName, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -replace "`r?`n", ' ') }}) }
T 'system' { $cs = Get-CimInstance Win32_ComputerSystem; $b = Get-CimInstance Win32_BIOS; $os = Get-CimInstance Win32_OperatingSystem
  [pscustomobject]@{ Maker = $cs.Manufacturer; Model = $cs.Model; Serial = "$($b.SerialNumber)".Trim(); Bios = $b.SMBIOSBIOSVersion; Os = "$($os.Caption) $($os.Version)"; RamGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) } }
""",
}


def probe(name: str, runner: Callable[[list[str], float], tuple] = run_quiet) -> dict:
    from .rescue import PS_HEAD, PS_TAIL

    if sys.platform != "win32" and runner is run_quiet:
        raise ValueError("Tahle diagnostika je jen pro Windows.")
    enc = base64.b64encode((PS_HEAD + HW_PS[name] + PS_TAIL).encode("utf-16-le")).decode()
    code, out, err = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], 120)
    if code is None:
        raise ValueError("Diagnostika neodpověděla do 2 minut.")
    out = (out or "").strip()
    try:
        return json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError as e:
        raise ValueError(f"Nečitelný výstup diagnostiky: {e}") from e


def L(v: Any) -> list:
    if v is None or (isinstance(v, dict) and "error" in v):
        return []
    return v if isinstance(v, list) else [v]


# ============================================================================================== 691 / 692 USB
PROBLEM_CODES = {10: "nejde spustit", 22: "vypnuté", 24: "chybí / nepřipojené", 28: "chybí ovladač", 31: "ovladač nefunguje",
                 43: "zařízení ohlásilo chybu (často napájení nebo kabel)", 45: "nepřipojené", 52: "nepodepsaný ovladač"}
POWER_TEXT = re.compile(r"power|napájen|surge|přepětí|overcurrent|reset|resetován|enumerat|descriptor|deskriptor", re.I)


def usb_tree(data: dict) -> dict:
    devs = L(data.get("devices"))
    by_id = {d["Id"]: d for d in devs}
    children: dict[str, list] = defaultdict(list)
    for d in devs:
        children[d.get("Parent") or ""].append(d)
    roots = [c for c in L(data.get("controllers"))]
    lines: list[str] = []
    problems = []

    def walk(node_id: str, depth: int) -> None:
        for ch in sorted(children.get(node_id, []), key=lambda x: x.get("Name") or ""):
            p = int(ch.get("Problem") or 0)
            mark = f"  ⚠ {PROBLEM_CODES.get(p, f'kód {p}')}" if p else ""
            lines.append("  " * depth + f"{ch.get('Name') or ch['Id']}{mark}")
            if p:
                problems.append({"device": ch.get("Name") or ch["Id"], "code": p, "meaning": PROBLEM_CODES.get(p, ""), "power_suspect": p in (10, 43)})
            if depth < 8:
                walk(ch["Id"], depth + 1)
    for c in roots:
        lines.append(c.get("FriendlyName") or c["InstanceId"])
        walk(c["InstanceId"], 1)
    orphans = [d for d in devs if d.get("Parent") not in by_id and d["Id"] not in {c["InstanceId"] for c in roots}
               and d.get("Parent") not in {c["InstanceId"] for c in roots}]
    power_events = [e for e in L(data.get("events")) if POWER_TEXT.search(str(e.get("Text", "")))]
    advice = []
    if any(p["power_suspect"] for p in problems) or power_events:
        advice.append("Zařízení s chybou připoj přímo do zadního portu počítače (ne přes rozbočovač), nebo použij rozbočovač s vlastním napájením.")
        advice.append("V Plánu napájení vypni „Selektivní pozastavení USB“ a v Správci zařízení u kořenových rozbočovačů zakaž úsporu energie.")
    return {"tree": lines, "problems": problems, "power_events": power_events[:20], "devices": len(devs), "controllers": len(roots),
            "unplaced": len(orphans), "advice": advice}


# ============================================================================================== 695 / 696 / 701 storage
EVENT_MEANING = {("disk", 7): "vadný blok", ("disk", 11): "chyba řadiče", ("disk", 15): "zařízení nepřipravené", ("disk", 51): "chyba při stránkování",
                 ("disk", 52): "disk hlásí blížící se selhání", ("disk", 153): "operace se musela opakovat", ("disk", 154): "chyba hardwaru",
                 ("disk", 157): "disk byl nečekaně odpojen", ("stornvme", 11): "chyba řadiče NVMe", ("storahci", 129): "reset zařízení (SATA)",
                 ("stornvme", 129): "reset zařízení (NVMe)", ("storport", 129): "reset zařízení", ("ntfs", 55): "poškozená struktura souborů",
                 ("ntfs", 98): "svazek potřebuje kontrolu", ("ntfs", 140): "zápis metadat selhal"}
LBA = re.compile(r"(?:logical block address|logické adrese bloku|LBA)\s*(0x[0-9a-fA-F]+|\d+)", re.I)
DISKNUM = re.compile(r"Harddisk(\d+)|disk (\d+)|DR(\d+)", re.I)


def storage_report(data: dict) -> dict:
    disks = L(data.get("disks"))
    events = L(data.get("events"))
    per: dict[str, Counter] = defaultdict(Counter)
    lbas: dict[str, list[int]] = defaultdict(list)
    timeline = []
    for e in events:
        prov = str(e.get("ProviderName", "")).lower().replace("microsoft-windows-", "")
        prov = "ntfs" if "ntfs" in prov else prov
        meaning = EVENT_MEANING.get((prov, int(e.get("Id", 0))), f"{prov} {e.get('Id')}")
        m = DISKNUM.search(str(e.get("Text", "")))
        disk = next((g for g in m.groups() if g), "?") if m else "?"
        per[disk][meaning] += 1
        lm = LBA.search(str(e.get("Text", "")))
        if lm:
            lbas[disk].append(int(lm.group(1), 16) if lm.group(1).lower().startswith("0x") else int(lm.group(1)))
        timeline.append({"time": e.get("Time"), "disk": disk, "what": meaning})
    out_disks = []
    for d in disks:
        did = str(d.get("DeviceId"))
        issues = []
        if str(d.get("Health")) not in ("Healthy", "0", ""):
            issues.append(f"stav {d.get('Health')}")
        if (d.get("Wear") or 0) >= 80:
            issues.append(f"opotřebení {d['Wear']} %")
        if (d.get("ReadUncorrected") or 0) > 0:
            issues.append(f"{d['ReadUncorrected']} neopravitelných chyb čtení")
        if (d.get("Temperature") or 0) >= 65:
            issues.append(f"teplota {d['Temperature']} °C")
        if per.get(did):
            issues.append("v logu: " + ", ".join(f"{k} {v}×" for k, v in per[did].most_common(3)))
        out_disks.append({"id": did, "name": d.get("Name"), "bus": d.get("Bus"), "health": d.get("Health"), "size_gb": round((d.get("Size") or 0) / 1e9),
                          "temperature": d.get("Temperature"), "wear": d.get("Wear"), "power_on_hours": d.get("PowerOnHours"),
                          "firmware": d.get("Firmware"), "serial": d.get("Serial"), "issues": issues,
                          "heatmap": heatmap(lbas.get(did, []), (d.get("Size") or 0) // 512) if lbas.get(did) else ""})
    return {"disks": out_disks, "events_by_disk": {k: dict(v) for k, v in per.items()}, "timeline": sorted(timeline, key=lambda x: x["time"] or "")[-60:],
            "system": data.get("system") if isinstance(data.get("system"), dict) and "error" not in data.get("system", {}) else {}}


def heatmap(lbas: list[int], total_sectors: int, cells: int = 40) -> str:
    """Where on the disk the read errors are: one character per 1/40 of the surface (· none, ░ few, ▒ more, █ many)."""
    if not lbas or total_sectors <= 0:
        return ""
    bins = [0] * cells
    for x in lbas:
        bins[min(cells - 1, int(x / total_sectors * cells))] += 1
    top = max(bins)
    return "".join("·" if b == 0 else "░" if b <= top / 3 else "▒" if b <= 2 * top / 3 else "█" for b in bins)


# ============================================================================================== 699 read-only imaging
def imaging_plan(source_gb: float, used_gb: float, dest_free_gb: float, health: str, folders: list[dict], source_letter: str = "D") -> dict:
    """A careful plan: never write to the failing disk, most valuable data first, short sessions, then (if the target
    is big enough) a full image with a tool that skips bad areas first."""
    steps = ["Nic na vadný disk neukládej, nespouštěj na něm kontrolu ani defragmentaci (chkdsk /f by mohl data zničit).",
             "Disk připoj napřímo (ne přes rozbočovač), u externích disků s vlastním napájením."]
    fail = health.lower() not in ("healthy", "ok", "")
    total = 0.0
    picks = []
    for f in folders:
        gb = f["bytes"] / 1e9
        if total + gb <= dest_free_gb * 0.9:
            picks.append(f["folder"])
            total += gb
    if picks:
        steps.append("Nejdřív zkopíruj nejcennější složky (od posledně používaných), soubory, které nejdou přečíst, přeskakuj:")
        for p in picks:
            name = Path(p).name
            steps.append(f'  robocopy "{p}" "<CÍL>\\{name}" /E /R:0 /W:0 /COPY:DT /XJ /NP /LOG+:"<CÍL>\\kopie.log"')
    image_fits = dest_free_gb >= source_gb * 1.02
    if image_fits:
        steps.append("Pak celý obraz disku nástrojem, který vadná místa nejdřív přeskočí a vrátí se k nim nakonec "
                     "(GNU ddrescue z Linuxového USB, nebo HDD Raw Copy Tool ve Windows). Zdroj vždy jen pro čtení.")
    else:
        steps.append(f"Na celý obraz disku ({source_gb:.0f} GB) cíl nestačí ({dest_free_gb:.0f} GB volno) – drž se kopírování složek.")
    steps += ["Pracuj v kratších dávkách a sleduj teplotu disku; když disk cvaká nebo mizí, přestaň a zvaž profesionální záchranu dat.",
              "Po kopii zkontroluj kopie (verify_copy) a teprve pak řeš opravu nebo výměnu disku."]
    return {"steps": steps, "first_folders": picks, "first_gb": round(total, 1), "image_fits": image_fits, "failing": fail}


# ============================================================================================== 705 incident report
def incident_report(storage: dict, usb: dict | None, rescue_findings: list[dict] | None, note: str = "") -> str:
    sysi = storage.get("system") or {}
    now = dt.datetime.now()
    rows = [f"# Hardwarový protokol – {now:%d. %m. %Y %H:%M}", "",
            f"**Počítač:** {sysi.get('Maker', '?')} {sysi.get('Model', '')}, sériové číslo {sysi.get('Serial', '?')}, BIOS {sysi.get('Bios', '?')}",
            f"**Systém:** {sysi.get('Os', '?')}, RAM {sysi.get('RamGB', '?')} GB", ""]
    if note:
        rows += [f"**Popis problému od uživatele:** {note}", ""]
    rows += ["## Disky", "| Disk | Sběrnice | Stav | Teplota | Opotřebení | Hodiny | Firmware | Sériové č. | Zjištění |", "|---|---|---|---|---|---|---|---|---|"]
    for d in storage.get("disks", []):
        rows.append(f"| {d['name']} ({d['size_gb']} GB) | {d['bus']} | {d['health']} | {d['temperature'] or '?'} °C | {d['wear'] if d['wear'] is not None else '?'} % | "
                    f"{d['power_on_hours'] or '?'} | {d['firmware'] or '?'} | {d['serial'] or '?'} | {'; '.join(d['issues']) or '—'} |")
        if d.get("heatmap"):
            rows.append(f"\nMapa chyb čtení disku {d['name']}: `{d['heatmap']}` (začátek → konec disku)\n")
    if storage.get("timeline"):
        rows += ["", "## Události disků (posledních 60 dní)"] + [f"- {e['time']} disk {e['disk']}: {e['what']}" for e in storage["timeline"][-25:]]
    if usb:
        rows += ["", "## USB"] + ([f"- {p['device']}: {p['meaning'] or 'kód ' + str(p['code'])}" for p in usb.get("problems", [])] or ["- bez problémů"])
        if usb.get("power_events"):
            rows += [f"- {e.get('Time')}: {e.get('Text')}" for e in usb["power_events"][:10]]
    if rescue_findings:
        rows += ["", "## Další zjištění"] + [f"- [{f.get('level')}] {f.get('text')}" for f in rescue_findings[:30]]
    rows += ["", "_Protokol vytvořil JARVIS jen čtením – na počítači nic neměnil._"]
    return "\n".join(rows) + "\n"


# ============================================================================================== 712 / 720 hosting
SEC_HEADERS = {"strict-transport-security": "HSTS (vynucení https)", "content-security-policy": "CSP (ochrana proti XSS)",
               "x-content-type-options": "X-Content-Type-Options", "x-frame-options": "X-Frame-Options (ochrana proti vložení do rámu)",
               "referrer-policy": "Referrer-Policy"}


async def doh(client, name: str, rtype: str) -> list[str]:
    try:
        r = await client.get("https://dns.google/resolve", params={"name": name, "type": rtype}, headers={"accept": "application/dns-json"}, timeout=8)
        return [a.get("data", "").strip('"') for a in (r.json().get("Answer") or [])]
    except Exception:  # noqa: BLE001
        return []


async def hosting_health(client, domain: str, tls: Callable[[str], dict]) -> dict:
    import asyncio

    d = re.sub(r"^https?://", "", domain.strip()).split("/")[0].lower()
    issues, ok = [], []
    a, aaaa, mx, txt, dmarc = await asyncio.gather(doh(client, d, "A"), doh(client, d, "AAAA"), doh(client, d, "MX"), doh(client, d, "TXT"),
                                                   doh(client, f"_dmarc.{d}", "TXT"))
    if not a and not aaaa:
        issues.append("doména nemá IP adresu (A/AAAA) – web neběží nebo DNS chybí")
    spf = [t for t in txt if t.lower().startswith("v=spf1")]
    if mx:
        if not spf:
            issues.append("chybí SPF záznam – e-maily z domény můžou padat do spamu a jdou snadno podvrhnout")
        elif len(spf) > 1:
            issues.append("víc SPF záznamů – platí jen jeden, sjednoť je")
        if not any(t.lower().startswith("v=dmarc1") for t in dmarc):
            issues.append("chybí DMARC (_dmarc) – doporučeno aspoň p=none s hlášením")
        else:
            ok.append("SPF a DMARC v pořádku")
    t = await asyncio.to_thread(tls, d)
    if not t.get("valid"):
        issues.append(f"certifikát: {t.get('error', 'neplatný')}")
    elif t["days_left"] < 14:
        issues.append(f"certifikát vyprší za {t['days_left']} dní")
    else:
        ok.append(f"certifikát platí ještě {t['days_left']} dní")
    http = {}
    try:
        t0 = time.perf_counter()
        r = await client.get(f"http://{d}/", follow_redirects=True, timeout=15)
        http = {"status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000), "final": str(r.url)}
        if not str(r.url).startswith("https://"):
            issues.append("web nepřesměruje http → https")
        if r.status_code >= 400:
            issues.append(f"web vrací chybu {r.status_code}")
        missing = [label for h, label in SEC_HEADERS.items() if h not in {k.lower() for k in r.headers}]
        http["missing_headers"] = missing
        if missing:
            issues.append("chybí bezpečnostní hlavičky: " + ", ".join(missing))
        if http["ms"] > 2000:
            issues.append(f"pomalá odpověď ({http['ms']} ms)")
    except Exception as e:  # noqa: BLE001
        issues.append(f"web neodpovídá: {type(e).__name__}")
        http = {"status": None, "error": type(e).__name__}
    return {"domain": d, "a": a, "aaaa": aaaa, "mx": mx, "spf": spf, "dmarc": dmarc, "tls": t, "http": http, "issues": issues, "ok": ok,
            "up": bool(http.get("status")) and http["status"] < 500}


CHECKS_SQL = "CREATE TABLE IF NOT EXISTS site_checks (site TEXT, ts REAL, up INTEGER, status INTEGER, ms INTEGER, note TEXT)"


def record_check(rt, site: str, up: bool, status: int | None, ms: int | None, note: str = "") -> None:
    rt.db.exec(CHECKS_SQL)
    rt.db.exec("INSERT INTO site_checks VALUES (?,?,?,?,?,?)", (site, time.time(), int(up), status, ms, note[:200]))


def outage_timeline(rt, site: str, days: int = 30) -> dict:
    rt.db.exec(CHECKS_SQL)
    rows = rt.db.all("SELECT ts, up, status, note FROM site_checks WHERE site=? AND ts>=? ORDER BY ts", (site, time.time() - days * 86400))
    outages, cur = [], None
    for r in rows:
        if not r["up"] and cur is None:
            cur = {"from": r["ts"], "to": None, "checks": 1, "status": r["status"], "note": r["note"]}
        elif not r["up"]:
            cur["checks"] += 1
        elif cur is not None:
            cur["to"] = r["ts"]
            outages.append(cur)
            cur = None
    if cur is not None:
        outages.append(cur)
    up = sum(1 for r in rows if r["up"])
    return {"checks": len(rows), "uptime_pct": round(100 * up / len(rows), 2) if rows else None,
            "outages": [{**o, "from_s": dt.datetime.fromtimestamp(o["from"]).strftime("%d. %m. %H:%M"),
                         "minutes": round(((o["to"] or time.time()) - o["from"]) / 60), "ongoing": o["to"] is None} for o in outages]}


# ============================================================================================== 713 logs
TS_RX = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
LEVEL_RX = re.compile(r"\b(CRITICAL|FATAL|ERROR|ERR|WARNING|WARN|INFO|DEBUG|TRACE)\b", re.I)
NORMALISE = [(re.compile(r"0x[0-9a-f]+", re.I), "<hex>"), (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I), "<uuid>"),
             (re.compile(r"\b\d+(\.\d+)?\b"), "<n>"), (re.compile(r"'[^']*'|\"[^\"]*\""), "<str>")]
LEVELS = {"critical": 5, "fatal": 5, "error": 4, "err": 4, "warning": 3, "warn": 3, "info": 2, "debug": 1, "trace": 0}


def explore_logs(files: list[Path], level: str = "warning", pattern: str = "", since: str = "", limit_lines: int = 200_000) -> dict:
    """Merge log files, keep lines at or above `level` (and matching `pattern`, after `since`), group repeated errors by
    their shape (numbers, ids and quoted values masked) with first / last time and count."""
    want = LEVELS.get(level.lower(), 3)
    rx = re.compile(pattern, re.I) if pattern else None
    groups: dict[str, dict] = {}
    n = kept = 0
    per_file: Counter = Counter()
    for f in files:
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            last_ts = ""
            for line in fh:
                n += 1
                if n > limit_lines:
                    break
                ts = TS_RX.search(line)
                if ts:
                    last_ts = ts.group(1).replace("T", " ")
                lv = LEVEL_RX.search(line)
                lvl = LEVELS.get(lv.group(1).lower(), 2) if lv else (4 if "Traceback" in line or "Exception" in line else -1)
                if lvl < want or (since and last_ts and last_ts < since) or (rx and not rx.search(line)):
                    continue
                kept += 1
                per_file[f.name] += 1
                msg = line[lv.end():].strip(" :-]|") if lv else line.strip()
                shape = msg
                for r, rep in NORMALISE:
                    shape = r.sub(rep, shape)
                shape = shape[:160]
                g = groups.setdefault(shape, {"shape": shape, "example": msg[:240], "count": 0, "first": last_ts, "last": last_ts,
                                              "level": lv.group(1).upper() if lv else "?", "files": set()})
                g["count"] += 1
                g["last"] = last_ts or g["last"]
                g["files"].add(f.name)
    out = sorted(groups.values(), key=lambda g: (-LEVELS.get(g["level"].lower(), 0), -g["count"]))
    for g in out:
        g["files"] = sorted(g["files"])
    return {"lines": n, "matched": kept, "groups": out[:50], "distinct": len(out), "per_file": dict(per_file)}


# ============================================================================================== 714 deployments
SECRET_KEY = re.compile(r"pass|secret|token|key|pwd|heslo|credential|private", re.I)


def _hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _config(p: Path) -> dict[str, str] | None:
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if p.suffix == ".json":
        try:
            def flat(o, pre=""):
                out = {}
                if isinstance(o, dict):
                    for k, v in o.items():
                        out.update(flat(v, f"{pre}{k}."))
                else:
                    out[pre.rstrip(".")] = json.dumps(o, ensure_ascii=False)
                return out
            return flat(json.loads(text))
        except ValueError:
            return None
    if p.name.startswith(".env") or p.suffix in (".env", ".ini", ".properties", ".cfg"):
        return {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r"^\s*([\w.\-]+)\s*[=:]\s*(.*)$", text, re.M)}
    return None


def deploy_diff(a: Path, b: Path, max_files: int = 20000) -> dict:
    def index(root: Path) -> dict[str, Path]:
        out = {}
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for f in files:
                p = Path(dirpath) / f
                out[str(p.relative_to(root)).replace("\\", "/")] = p
                if len(out) >= max_files:
                    return out
        return out
    ia, ib = index(a), index(b)
    added = sorted(set(ib) - set(ia))
    removed = sorted(set(ia) - set(ib))
    changed, config = [], {}
    for k in sorted(set(ia) & set(ib)):
        pa, pb = ia[k], ib[k]
        if pa.stat().st_size != pb.stat().st_size or _hash(pa) != _hash(pb):
            changed.append(k)
            ca, cb = _config(pa), _config(pb)
            if ca is not None and cb is not None:
                diff = {}
                for key in sorted(set(ca) | set(cb)):
                    if ca.get(key) != cb.get(key):
                        mask = bool(SECRET_KEY.search(key))
                        diff[key] = ["•••" if mask and ca.get(key) is not None else ca.get(key), "•••" if mask and cb.get(key) is not None else cb.get(key)]
                if diff:
                    config[k] = diff
    size = lambda idx: sum(p.stat().st_size for p in idx.values())  # noqa: E731
    return {"added": added, "removed": removed, "changed": changed, "config": config, "files": [len(ia), len(ib)],
            "bytes": [size(ia), size(ib)], "same": not (added or removed or changed)}


# ============================================================================================== 716 backups
def backup_check(folder: Path, expect_hours: float = 26, pattern: str = "") -> dict:
    rx = re.compile(pattern, re.I) if pattern else None
    files = [p for p in folder.rglob("*") if p.is_file() and (not rx or rx.search(p.name))]
    if not files:
        return {"ok": False, "files": 0, "issues": ["ve složce nejsou žádné zálohy"]}
    files.sort(key=lambda p: p.stat().st_mtime)
    sizes = [p.stat().st_size for p in files]
    newest = files[-1]
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    issues = []
    if age_h > expect_hours:
        issues.append(f"poslední záloha je stará {age_h:.0f} h (čekám každých {expect_hours:g} h)")
    empty = [p.name for p in files if p.stat().st_size == 0]
    if empty:
        issues.append(f"prázdné zálohy: {', '.join(empty[-3:])}")
    if len(sizes) >= 3:
        med = sorted(sizes[:-1])[len(sizes[:-1]) // 2]
        if med and sizes[-1] < med * 0.5:
            issues.append(f"poslední záloha je o {100 - round(100 * sizes[-1] / med)} % menší než obvykle – možná je neúplná")
    gaps = [(b.stat().st_mtime - a.stat().st_mtime) / 3600 for a, b in zip(files, files[1:])]
    missed = sum(1 for g in gaps if g > expect_hours * 1.8)
    if missed:
        issues.append(f"{missed}× vynechaná záloha (mezera víc než {expect_hours * 1.8:.0f} h)")
    return {"ok": not issues, "files": len(files), "newest": newest.name, "newest_age_h": round(age_h, 1), "newest_bytes": sizes[-1],
            "issues": issues, "total_gb": round(sum(sizes) / 1e9, 2)}


def report_path(kind: str) -> Path:
    d = paths.data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.md"
