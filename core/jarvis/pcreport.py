"""OMEGA §6 first mission: "Zjisti stav mého počítače, připrav report a ulož ho".

Read-only diagnostics through real system tools (psutil everywhere; on Windows one PowerShell process with a fixed,
read-only script: Get-CimInstance, Get-PhysicalDisk, Get-WinEvent, Get-HotFix). Every value carries its source and the
time it was measured; what cannot be measured says "neznámé" and why. The report is an HTML file with the raw data
embedded as JSON; verification re-reads the file and checks the acceptance criteria.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import paths

SECTIONS = [("system", "Systém"), ("cpu", "Procesor"), ("memory", "Paměť"), ("disks", "Disky"), ("battery", "Baterie"),
            ("network", "Síť"), ("processes", "Nejnáročnější procesy"), ("events", "Chyby v systémovém logu"),
            ("updates", "Aktualizace Windows"), ("startup", "Programy po spuštění"), ("devices", "Zařízení a ovladače")]
CRITERIA = [
    "Report je uložený jako soubor a není prázdný",
    "Report obsahuje všech 11 částí diagnostiky",
    "Každá část má zdroj a čas měření (nebo vysvětlení, proč chybí)",
    "Soubor odpovídá otisku SHA-256 zapsanému při uložení",
    "Diagnostika jen četla – použité příkazy jsou ze seznamu povolených (Get-*)",
]
# The whole Windows probe. Only Get-* cmdlets and Select/Where/Sort/Group/Measure; nothing here changes the system.
PS_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$r = @{}
function T($n, [scriptblock]$b) { try { $r[$n] = & $b } catch { $r[$n] = @{ error = $_.Exception.Message } } }
T 'os' { Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, @{n='LastBoot'; e={ $_.LastBootUpTime.ToString('s') }} }
T 'cpu' { @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed) }
T 'gpu' { @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, Status) }
T 'physical' { @(Get-PhysicalDisk | Select-Object FriendlyName, @{n='MediaType'; e={ "$($_.MediaType)" }}, @{n='Health'; e={ "$($_.HealthStatus)" }}, @{n='Status'; e={ "$($_.OperationalStatus)" }}, Size) }
T 'events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2; StartTime=(Get-Date).AddDays(-1)} -MaxEvents 1000 -ErrorAction SilentlyContinue | Group-Object ProviderName | Sort-Object Count -Descending | Select-Object -First 5 Name, Count) }
T 'shutdowns' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41; StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue).Count }
T 'hotfix' { Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1 HotFixID, @{n='Date'; e={ $_.InstalledOn.ToString('yyyy-MM-dd') }} }
T 'startup' { @(Get-CimInstance Win32_StartupCommand | Select-Object Name, Location) }
T 'problems' { @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | Select-Object Name, ConfigManagerErrorCode) }
$r | ConvertTo-Json -Depth 4 -Compress
"""
ALLOWED_CMDLETS = {"Get-CimInstance", "Get-PhysicalDisk", "Get-WinEvent", "Get-HotFix", "Get-Date", "Select-Object",
                   "Where-Object", "Sort-Object", "Group-Object", "ConvertTo-Json"}


def cmdlets_used(script: str = PS_SCRIPT) -> set[str]:
    return set(re.findall(r"\b[A-Z][a-z]+-[A-Z][A-Za-z]+\b", script))


def reports_dir() -> Path:
    if os.environ.get("JARVIS_HOME"):
        d = paths.data_dir() / "Reporty"
    else:
        docs = Path.home() / "Documents"
        d = (docs if docs.is_dir() else Path.home()) / "JARVIS" / "Reporty"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _gb(n: float) -> str:
    return f"{n / 2**30:.1f} GB"


def run_quiet(cmd: list[str], timeout: float) -> tuple[int | None, str, str]:
    """Run a helper program with no stdin and output into temp files, then wait at most `timeout` seconds.
    (Pipes + inherited stdin can hang forever: PowerShell waits for input, and a killed process's children may keep
    the pipe open so reading it never ends.) → (exit code or None on timeout, stdout, stderr)"""
    import tempfile

    flags: dict = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    if cmd and os.path.basename(cmd[0]).lower() in ("powershell.exe", "powershell"):
        # Started from PowerShell 7, PSModulePath points at PS7's modules and Windows PowerShell 5.1 then fails to load
        # its own (e.g. Get-AuthenticodeSignature). Without the variable 5.1 rebuilds its default path.
        flags["env"] = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, **flags)
        try:
            code: int | None = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            code = None
        out.seek(0)
        err.seek(0)
        return code, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def run_windows_probe(timeout: float = 90) -> dict:
    """One read-only PowerShell process → the parsed JSON (or {"error": …})."""
    if sys.platform != "win32":
        return {"error": "Jen na Windows"}
    enc = base64.b64encode(PS_SCRIPT.encode("utf-16-le")).decode()
    try:
        code, out, err = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-EncodedCommand", enc], timeout)
    except OSError as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}
    if code is None:
        return {"error": f"PowerShell neodpověděl do {timeout:.0f} s"}
    out = out.strip()
    try:
        return json.loads(out[out.find("{"):]) if "{" in out else {"error": (err or "bez výstupu")[:300]}
    except ValueError as e:
        return {"error": f"Nečitelný výstup: {e}"[:300]}


def _list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _sec(sid: str, rows: list[tuple[str, str]], source: str, ok: bool | None = True, note: str = "") -> dict:
    title = dict(SECTIONS)[sid]
    return {"id": sid, "title": title, "rows": [[str(a), str(b)] for a, b in rows], "source": source, "ts": _now(),
            "ok": ok, "note": note}


def collect(win: dict | None = None, trace=None) -> dict:
    """All sections. `win` = the Windows probe result (None → run it here; {} on other systems).
    `trace(name)` is called before each measurement (the CI selftest uses it to show where time goes)."""
    trace = trace or (lambda _name: None)
    import platform as pf
    import socket

    import psutil

    if win is None:
        win = run_windows_probe() if sys.platform == "win32" else {"error": "Jen na Windows"}
    werr = win.get("error") if isinstance(win.get("error"), str) else ""
    secs: list[dict] = []

    def wsec(sid: str, key: str, source: str, build) -> None:
        v = win.get(key)
        if werr or v is None:
            secs.append(_sec(sid, [], source, None, werr or "Údaj není k dispozici."))
        elif isinstance(v, dict) and v.get("error"):
            secs.append(_sec(sid, [], source, None, f"Nepodařilo se změřit: {v['error'][:200]}"))
        else:
            secs.append(build(v))

    # ---- system ----
    trace("system")
    osv = win.get("os") if isinstance(win.get("os"), dict) and not win["os"].get("error") else {}
    boot = dt.datetime.fromtimestamp(psutil.boot_time())
    rows = [("Počítač", socket.gethostname()), ("Systém", osv.get("Caption") or f"{pf.system()} {pf.release()}"),
            ("Verze", osv.get("Version") or pf.version()), ("Spuštěn od", boot.strftime("%d.%m.%Y %H:%M")),
            ("Doba běhu", f"{(time.time() - psutil.boot_time()) / 3600:.1f} h")]
    secs.append(_sec("system", rows, "psutil.boot_time, platform" + (", Get-CimInstance Win32_OperatingSystem" if osv else "")))

    # ---- cpu ----
    trace("cpu")
    load = psutil.cpu_percent(interval=1.0)
    cpu_rows = [("Vytížení (1 s)", f"{load:.0f} %"), ("Jádra / vlákna", f"{psutil.cpu_count(False)} / {psutil.cpu_count()}")]
    wc = _list(win.get("cpu")) if not werr and not (isinstance(win.get("cpu"), dict) and win["cpu"].get("error")) else []
    if wc:
        cpu_rows.insert(0, ("Model", str(wc[0].get("Name", "")).strip()))
    elif pf.processor():
        cpu_rows.insert(0, ("Model", pf.processor()))
    try:
        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
    except Exception:
        temps = {}
    hot = max((t.current for v in temps.values() for t in v if t.current), default=None)
    cpu_rows.append(("Teplota", f"{hot:.0f} °C" if hot else "neznámá (Windows ji bez ovladače výrobce neposkytuje)"))
    secs.append(_sec("cpu", cpu_rows, "psutil.cpu_percent, psutil.sensors_temperatures" + (", Win32_Processor" if wc else ""),
                     load < 90))

    # ---- memory ----
    trace("memory")
    vm = psutil.virtual_memory()
    secs.append(_sec("memory", [("Celkem", _gb(vm.total)), ("Použito", f"{vm.percent:.0f} % ({_gb(vm.used)})"),
                                ("Volné", _gb(vm.available))], "psutil.virtual_memory", vm.percent < 85))

    # ---- disks ----
    trace("disks")
    drows, dok = [], True
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        dok = dok and u.percent < 90
        drows.append((part.mountpoint, f"{u.percent:.0f} % plno, volno {_gb(u.free)} z {_gb(u.total)}"))
    phys = _list(win.get("physical")) if not werr and not (isinstance(win.get("physical"), dict) and win["physical"].get("error")) else []
    for d in phys:
        health = str(d.get("Health", ""))
        dok = dok and health in ("Healthy", "0", "")
        drows.append((f"Fyzický disk: {d.get('FriendlyName', '?')}", f"{d.get('MediaType', '')} · stav {health or 'neznámý'}"))
    secs.append(_sec("disks", drows, "psutil.disk_usage" + (", Get-PhysicalDisk" if phys else ""), dok,
                     "" if phys else "Zdraví fyzických disků (SMART) jen na Windows."))

    # ---- battery ----
    trace("battery")
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat is None:
        secs.append(_sec("battery", [("Baterie", "není (stolní PC) nebo ji systém nehlásí")], "psutil.sensors_battery", None))
    else:
        secs.append(_sec("battery", [("Nabití", f"{bat.percent:.0f} %"), ("Napájení", "připojeno" if bat.power_plugged else "z baterie")],
                         "psutil.sensors_battery", bat.percent > 15 or bool(bat.power_plugged)))

    # ---- network ----
    trace("network")
    nrows = []
    for name, st in psutil.net_if_stats().items():
        if st.isup and not name.lower().startswith(("lo", "loopback")):
            addrs = [a.address for a in psutil.net_if_addrs().get(name, []) if a.family == socket.AF_INET]
            nrows.append((name, f"zapnuto{', ' + ', '.join(addrs) if addrs else ''}{f', {st.speed} Mb/s' if st.speed else ''}"))
    secs.append(_sec("network", nrows[:8], "psutil.net_if_stats, psutil.net_if_addrs", bool(nrows)))

    # ---- processes ----
    trace("processes")
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["name"] or "?", p.info["memory_info"].rss if p.info["memory_info"] else 0))
        except (psutil.Error, OSError):
            pass
    procs.sort(key=lambda x: -x[1])
    secs.append(_sec("processes", [(n, f"{m / 2**20:.0f} MB RAM") for n, m in procs[:6]], "psutil.process_iter (paměť)"))

    # ---- Windows-only parts ----
    trace("windows parts")
    def ev(v):
        groups = _list(v)
        n = sum(int(g.get("Count", 0)) for g in groups)
        sd = win.get("shutdowns")
        rows = [("Chyby za 24 h", str(n))] + [(f"· {g.get('Name', '?')}", f"{g.get('Count', 0)}×") for g in groups]
        if isinstance(sd, int):
            rows.append(("Neočekávaná vypnutí (30 dní)", str(sd)))
        return _sec("events", rows, "Get-WinEvent System (úroveň Chyba/Kritická), událost 41", n < 20 and not (isinstance(sd, int) and sd > 2))
    wsec("events", "events", "Get-WinEvent", ev)

    def upd(v):
        d = v.get("Date", "") if isinstance(v, dict) else ""
        age = (dt.date.today() - dt.date.fromisoformat(d)).days if re.fullmatch(r"\d{4}-\d\d-\d\d", d or "") else None
        return _sec("updates", [("Poslední aktualizace", f"{v.get('HotFixID', '?')} z {d or '?'}"),
                                ("Před", f"{age} dny" if age is not None else "neznámé")], "Get-HotFix", age is None or age < 60)
    wsec("updates", "hotfix", "Get-HotFix", upd)

    def start(v):
        items = _list(v)
        return _sec("startup", [("Počet", str(len(items)))] + [(f"· {i.get('Name', '?')}", str(i.get("Location", ""))) for i in items[:12]],
                    "Get-CimInstance Win32_StartupCommand", len(items) < 15)
    wsec("startup", "startup", "Win32_StartupCommand", start)

    def dev(v):
        items = _list(v)
        gpus = _list(win.get("gpu")) if not (isinstance(win.get("gpu"), dict) and win["gpu"].get("error")) else []
        rows = [("Grafika", f"{g.get('Name', '?')} (ovladač {g.get('DriverVersion', '?')})") for g in gpus]
        rows += [("Zařízení s chybou", str(len(items)))] + [(f"· {i.get('Name', '?')}", f"kód {i.get('ConfigManagerErrorCode')}") for i in items[:10]]
        return _sec("devices", rows, "Win32_PnPEntity (ConfigManagerErrorCode), Win32_VideoController", not items)
    wsec("devices", "problems", "Win32_PnPEntity", dev)

    order = [s for s, _ in SECTIONS]
    secs.sort(key=lambda s: order.index(s["id"]))
    return {"created": _now(), "host": socket.gethostname(), "sections": secs, "findings": findings(secs),
            "commands": sorted(cmdlets_used()) if sys.platform == "win32" else ["psutil (Python)"]}


def findings(secs: list[dict]) -> list[dict]:
    """Plain-language conclusions. Suggestions only — nothing here is done automatically."""
    out = []
    for s in secs:
        if s["ok"] is False:
            tips = {"cpu": "Procesor je teď hodně vytížený – podívej se, který program ho bere (Správce úloh).",
                    "memory": "Dochází operační paměť – zavři nepoužívané programy nebo karty prohlížeče.",
                    "disks": "Na disku dochází místo nebo hlásí problém – ulož si zálohu a nech JARVISe ukázat, co zabírá místo.",
                    "battery": "Baterie je skoro vybitá – připoj nabíječku.",
                    "network": "Žádné aktivní síťové připojení.",
                    "events": "Systém hlásí víc chyb nebo neočekávaná vypnutí – stojí za to projít Prohlížeč událostí.",
                    "updates": "Windows se dlouho neaktualizoval – spusť Windows Update.",
                    "startup": "Hodně programů se spouští se systémem – to zpomaluje start.",
                    "devices": "Některé zařízení má problém s ovladačem – podívej se do Správce zařízení."}
            out.append({"level": "warn", "section": s["id"], "text": tips.get(s["id"], f"{s['title']}: zkontrolovat.")})
    if not out:
        out.append({"level": "ok", "section": "", "text": "Všechno, co šlo změřit, je v pořádku."})
    unknown = [s["title"] for s in secs if s["ok"] is None and not s["rows"]]
    if unknown:
        out.append({"level": "info", "section": "", "text": "Nešlo změřit: " + ", ".join(unknown) + "."})
    return out


def render_html(data: dict) -> str:
    e = html.escape
    sec_html = []
    for s in data["sections"]:
        badge = {True: ("ok", "v pořádku"), False: ("warn", "pozor"), None: ("unk", "neznámé")}[s["ok"]]
        rows = "".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in s["rows"]) or \
            f"<tr><td colspan=2 class=muted>{e(s['note'] or 'Bez údajů.')}</td></tr>"
        note = f"<p class=muted>{e(s['note'])}</p>" if s["note"] and s["rows"] else ""
        sec_html.append(f"<section id=\"{s['id']}\"><h2>{e(s['title'])} <span class=\"b {badge[0]}\">{badge[1]}</span></h2>"
                        f"<table>{rows}</table>{note}<p class=src>Zdroj: {e(s['source'])} · změřeno {e(s['ts'])}</p></section>")
    fnd = "".join(f"<li class=\"{f['level']}\">{e(f['text'])}</li>" for f in data["findings"])
    raw = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang=cs><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Stav počítače {e(data['host'])} – {e(data['created'][:16].replace('T', ' '))}</title>
<style>body{{margin:0;font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#0b0b0d;color:#ececf1}}main{{max-width:880px;margin:auto;padding:32px 20px}}
h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:17px;margin:0 0 10px;display:flex;gap:10px;align-items:center}}
section{{background:#16161a;border:1px solid #26262c;border-radius:16px;padding:16px 18px;margin:14px 0}}
table{{width:100%;border-collapse:collapse}}th{{text-align:left;font-weight:500;color:#a1a1aa;width:42%;padding:4px 8px 4px 0;vertical-align:top}}td{{padding:4px 0}}
.b{{font-size:11px;padding:2px 8px;border-radius:99px;font-weight:600}}.ok{{background:#14532d;color:#86efac}}.warn{{background:#713f12;color:#fde68a}}.unk{{background:#27272a;color:#a1a1aa}}
.src,.muted{{color:#71717a;font-size:12px;margin:8px 0 0}}ul.f{{padding-left:18px}}ul.f li.warn{{color:#fde68a}}ul.f li.ok{{color:#86efac}}ul.f li.info{{color:#a1a1aa}}
@media print{{body{{background:#fff;color:#000}}section{{background:#fff;border-color:#ccc}}}}</style></head><body><main>
<h1>Stav počítače {e(data['host'])}</h1><p class=muted>Vytvořil JARVIS {e(data['created'].replace('T', ' '))}. Jen čtení – nic se neměnilo.</p>
<section id=findings><h2>Shrnutí</h2><ul class=f>{fnd}</ul></section>
{''.join(sec_html)}
<p class=src>Použité příkazy: {e(', '.join(data['commands']))}</p>
<script type="application/json" id="jarvis-data">{raw}</script>
</main></body></html>"""


def write_report(data: dict, folder: Path | None = None) -> Path:
    folder = folder or reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = folder / f"stav-pc_{stamp}.html"
    path.write_text(render_html(data), encoding="utf-8")
    return path


def verify(path: Path, sha256: str) -> list[tuple[str, bool, str]]:
    """The acceptance criteria, checked against the file on disk (not against what we meant to write)."""
    from .tasks import sha256_file

    out: list[tuple[str, bool, str]] = []
    exists = path.is_file() and path.stat().st_size > 0
    out.append((CRITERIA[0], exists, f"{path} · {path.stat().st_size if path.is_file() else 0} B"))
    if not exists:
        return out + [(c, False, "soubor chybí") for c in CRITERIA[1:]]
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<script type="application/json" id="jarvis-data">(.*?)</script>', text, re.S)
    try:
        data = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
    except ValueError:
        data = {}
    ids = {s.get("id") for s in data.get("sections", [])}
    missing = [t for sid, t in SECTIONS if sid not in ids or f'id="{sid}"' not in text]
    out.append((CRITERIA[1], not missing, "chybí: " + ", ".join(missing) if missing else f"{len(SECTIONS)} částí"))
    bad = [s.get("title", "?") for s in data.get("sections", []) if not s.get("source") or not s.get("ts")
           or (not s.get("rows") and not s.get("note"))]
    out.append((CRITERIA[2], bool(data) and not bad, "bez zdroje/času: " + ", ".join(bad) if bad else "všechny části"))
    now_sha = sha256_file(path)
    out.append((CRITERIA[3], now_sha == sha256, now_sha[:16] + "…"))
    used = set(data.get("commands", []))
    extra = sorted(c for c in used if "-" in c and c not in ALLOWED_CMDLETS)
    out.append((CRITERIA[4], not extra, "navíc: " + ", ".join(extra) if extra else ", ".join(sorted(used)) or "psutil"))
    return out
