"""OMEGA wave 2: PC Rescue, Windows superpowers, performance and the security center.

Every probe is a fixed, read-only PowerShell script (only Get-* / Select / Where … and a few read-only system tools),
run with no stdin, output to a file and a hard time limit (pcreport.run_quiet). The analyzers turn the raw data into
findings in plain Czech: what is wrong, why it matters and what to do – nothing is changed automatically.
Where Windows needs administrator rights, the finding says so instead of guessing.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from typing import Any, Callable

from .pcreport import run_quiet

PS_HEAD = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$r = @{}
function T($n, [scriptblock]$b) { try { $r[$n] = & $b } catch { $r[$n] = @{ error = $_.Exception.Message } } }
"""
PS_TAIL = "\n$r | ConvertTo-Json -Depth 5 -Compress\n"

PROBES: dict[str, dict[str, Any]] = {
    "drivers": {"title": "Ovladače a zařízení", "timeout": 60, "script": r"""
T 'problems' { @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | Select-Object Name, PNPClass, DeviceID, ConfigManagerErrorCode) }
T 'drivers' { @(Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName } | Select-Object DeviceName, DeviceClass, DriverVersion, @{n='Date'; e={ if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { '' } }}, Manufacturer, IsSigned) }
"""},
    "crashes": {"title": "Pády systému a modré obrazovky", "timeout": 60, "script": r"""
T 'bugchecks' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001; StartTime=(Get-Date).AddDays(-60)} -MaxEvents 30 -ErrorAction SilentlyContinue | Where-Object { $_.ProviderName -like '*WER-SystemErrorReporting*' -or $_.Message -match 'bugcheck' } | Select-Object @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, Message) }
T 'kernel_power' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41; StartTime=(Get-Date).AddDays(-60)} -MaxEvents 50 -ErrorAction SilentlyContinue | Select-Object @{n='Time'; e={ $_.TimeCreated.ToString('s') }}) }
T 'unexpected' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008; StartTime=(Get-Date).AddDays(-60)} -MaxEvents 50 -ErrorAction SilentlyContinue | Select-Object @{n='Time'; e={ $_.TimeCreated.ToString('s') }}) }
T 'dumps' { @(Get-ChildItem -Path "$env:SystemRoot\Minidump" -Filter *.dmp -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name, Length, @{n='Time'; e={ $_.LastWriteTime.ToString('s') }}) }
"""},
    "apps": {"title": "Pády aplikací", "timeout": 60, "script": r"""
T 'app_errors' { @(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddDays(-14)} -MaxEvents 300 -ErrorAction SilentlyContinue | ForEach-Object { $p = $_.Properties; [pscustomobject]@{ App = "$($p[0].Value)"; Module = "$($p[3].Value)"; Time = $_.TimeCreated.ToString('s') } }) }
T 'hangs' { @(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1002; StartTime=(Get-Date).AddDays(-14)} -MaxEvents 200 -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ App = "$($_.Properties[0].Value)"; Time = $_.TimeCreated.ToString('s') } }) }
"""},
    "boot": {"title": "Start Windows", "timeout": 60, "script": r"""
T 'boots' { @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; Id=100} -MaxEvents 10 -ErrorAction Stop | ForEach-Object { $x = [xml]$_.ToXml(); $d = @{}; foreach ($e in $x.Event.EventData.Data) { $d[$e.Name] = $e.'#text' }; [pscustomobject]@{ Time = $_.TimeCreated.ToString('s'); BootMs = [int]$d['BootTime']; MainPathMs = [int]$d['MainPathBootTime']; PostBootMs = [int]$d['BootPostBootTime'] } }) }
T 'slow' { @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; Id=101,102,103,106,109} -MaxEvents 30 -ErrorAction Stop | ForEach-Object { $x = [xml]$_.ToXml(); $d = @{}; foreach ($e in $x.Event.EventData.Data) { $d[$e.Name] = $e.'#text' }; [pscustomobject]@{ Id = $_.Id; Name = "$($d['FriendlyName'])$($d['Name'])"; TotalMs = [int]$d['TotalTime']; DegradationMs = [int]$d['DegradationTime'] } }) }
T 'startup' { @(Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location) }
T 'fast_startup' { (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -ErrorAction Stop).HiberbootEnabled }
T 'last_boot' { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('s') }
"""},
    "usb": {"title": "USB a připojená zařízení", "timeout": 60, "script": r"""
T 'usb_problems' { @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.Status -ne 'OK' -and ($_.Class -in 'USB','DiskDrive','SCSIAdapter','HDC','Volume','WPD' -or $_.InstanceId -like 'USB*') } | Select-Object FriendlyName, Class, Status, InstanceId) }
T 'controllers' { @(Get-CimInstance Win32_USBController | Select-Object Name, Status, Manufacturer) }
T 'pnp_events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-PnP'; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 60 -ErrorAction SilentlyContinue | Where-Object { $_.Id -in 219, 411, 420, 441 } | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
T 'disks' { @(Get-Disk -ErrorAction Stop | Select-Object Number, FriendlyName, @{n='Bus'; e={ "$($_.BusType)" }}, @{n='Style'; e={ "$($_.PartitionStyle)" }}, @{n='Status'; e={ "$($_.OperationalStatus)" }}, @{n='Health'; e={ "$($_.HealthStatus)" }}, IsOffline, Size) }
"""},
    "disks": {"title": "Zdraví disků", "timeout": 90, "script": r"""
T 'physical' { @(Get-PhysicalDisk -ErrorAction Stop | Select-Object DeviceId, FriendlyName, @{n='Media'; e={ "$($_.MediaType)" }}, @{n='Bus'; e={ "$($_.BusType)" }}, @{n='Health'; e={ "$($_.HealthStatus)" }}, @{n='Status'; e={ "$($_.OperationalStatus)" }}, Size) }
T 'reliability' { @(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object { $c = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue; [pscustomobject]@{ DeviceId = $_.DeviceId; Temperature = $c.Temperature; Wear = $c.Wear; ReadErrors = $c.ReadErrorsTotal; WriteErrors = $c.WriteErrorsTotal; PowerOnHours = $c.PowerOnHours } }) }
T 'volumes' { @(Get-Volume -ErrorAction Stop | Where-Object { $_.DriveLetter } | Select-Object @{n='Letter'; e={ "$($_.DriveLetter)" }}, FileSystem, @{n='Health'; e={ "$($_.HealthStatus)" }}, Size, SizeRemaining) }
T 'io_events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 4000 -ErrorAction SilentlyContinue | Where-Object { ($_.ProviderName -in 'disk','Disk' -and $_.Id -in 7, 51, 153) -or ($_.ProviderName -like '*Ntfs*' -and $_.Id -in 55, 98, 140) -or ($_.ProviderName -in 'storahci','stornvme','iaStorA','iaStorAC','storport' -and $_.Id -in 129, 11) } | Select-Object Id, ProviderName, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
T 'crash_times' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008; StartTime=(Get-Date).AddDays(-30)} -MaxEvents 60 -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne 1001 -or $_.ProviderName -like '*WER-SystemErrorReporting*' } | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}) }
"""},
    "services": {"title": "Služby Windows", "timeout": 60, "script": r"""
T 'stopped_auto' { @(Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' -and $_.ExitCode -ne 0 } | Select-Object Name, DisplayName, State, ExitCode) }
T 'scm_events' { @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Service Control Manager'; Level=2; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 100 -ErrorAction SilentlyContinue | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
T 'deps' { @(Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' -and $_.ExitCode -ne 0 } | Select-Object -First 15 Name | ForEach-Object { $s = Get-Service -Name $_.Name -ErrorAction SilentlyContinue; if ($s) { [pscustomobject]@{ Name = $s.Name; Display = $s.DisplayName; Needs = @($s.ServicesDependedOn | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Display = $_.DisplayName; Status = "$($_.Status)" } }); Waiting = @($s.DependentServices | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Display = $_.DisplayName; Status = "$($_.Status)" } }) } } }) }
"""},
    "security": {"title": "Bezpečnost", "timeout": 90, "script": r"""
T 'defender' { Get-MpComputerStatus -ErrorAction Stop | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, AntivirusSignatureAge, @{n='QuickScanAge'; e={ $_.QuickScanAge }}, IsTamperProtected }
T 'cfa' { (Get-MpPreference -ErrorAction Stop).EnableControlledFolderAccess }
T 'threats' { @(Get-MpThreatDetection -ErrorAction Stop | Select-Object -First 20 ThreatID, @{n='Time'; e={ $_.InitialDetectionTime.ToString('s') }}, @{n='Resources'; e={ ($_.Resources -join '; ') }}, ActionSuccess) }
T 'firewall' { @(Get-NetFirewallProfile -ErrorAction Stop | Select-Object Name, Enabled) }
T 'listening' { @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Select-Object LocalAddress, LocalPort, OwningProcess | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; [pscustomobject]@{ Address = $_.LocalAddress; Port = $_.LocalPort; Process = "$($p.ProcessName)"; Path = "$($p.Path)" } }) }
T 'startup' { @(Get-CimInstance Win32_StartupCommand | ForEach-Object { $cmd = $_.Command; $exe = if ($cmd -match '^"([^"]+)"') { $Matches[1] } elseif ($cmd -match '^(\S+\.exe)') { $Matches[1] } else { '' }; $sig = if ($exe -and (Test-Path -LiteralPath $exe)) { "$((Get-AuthenticodeSignature -LiteralPath $exe).Status)" } else { 'Unknown' }; [pscustomobject]@{ Name = $_.Name; Command = $cmd; Location = $_.Location; Exe = $exe; Signature = $sig } }) }
T 'tasks' { @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskPath -notlike '\Microsoft\*' -and $_.State -ne 'Disabled' } | Select-Object -First 40 TaskName, TaskPath, @{n='Action'; e={ ($_.Actions | ForEach-Object { $_.Execute }) -join '; ' }}) }
T 'uac' { (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction Stop).EnableLUA }
T 'rdp' { (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -ErrorAction Stop).fDenyTSConnections }
T 'hotfix' { Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1 HotFixID, @{n='Date'; e={ $_.InstalledOn.ToString('yyyy-MM-dd') }} }
"""},
    "network": {"title": "Síť a internet", "timeout": 60, "script": r"""
T 'adapters' { @(Get-NetAdapter -ErrorAction Stop | Select-Object Name, InterfaceDescription, Status, LinkSpeed, MediaType) }
T 'ipconfig' { @(Get-NetIPConfiguration -ErrorAction Stop | Where-Object { $_.NetAdapter.Status -eq 'Up' } | Select-Object InterfaceAlias, @{n='IPv4'; e={ ($_.IPv4Address.IPAddress -join ', ') }}, @{n='Gateway'; e={ ($_.IPv4DefaultGateway.NextHop -join ', ') }}, @{n='DNS'; e={ ($_.DNSServer.ServerAddresses -join ', ') }}) }
"""},
    "restore": {"title": "Body obnovy", "timeout": 60, "script": r"""
T 'points' { @(Get-ComputerRestorePoint -ErrorAction Stop | Select-Object SequenceNumber, Description, @{n='Time'; e={ [Management.ManagementDateTimeConverter]::ToDateTime($_.CreationTime).ToString('s') }}) }
T 'memtest' { @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-MemoryDiagnostics-Results'} -MaxEvents 5 -ErrorAction SilentlyContinue | Select-Object Id, @{n='Time'; e={ $_.TimeCreated.ToString('s') }}, @{n='Text'; e={ ($_.Message -split "`n")[0] }}) }
"""},
    "devices": {"title": "Seznam zařízení", "timeout": 60, "script": r"""
T 'present' { @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.Class -in 'USB','DiskDrive','Monitor','Mouse','Keyboard','AudioEndpoint','Bluetooth','Camera','Image','Net','Printer','MEDIA','HIDClass','WPD' } | Select-Object FriendlyName, Class, InstanceId) }
"""},
}
ALLOWED = {"Get-CimInstance", "Get-WinEvent", "Get-ChildItem", "Get-ItemProperty", "Get-PnpDevice", "Get-Disk",
           "Get-PhysicalDisk", "Get-StorageReliabilityCounter", "Get-Volume", "Get-MpComputerStatus", "Get-MpPreference",
           "Get-MpThreatDetection", "Get-NetFirewallProfile", "Get-NetTCPConnection", "Get-Process", "Get-AuthenticodeSignature",
           "Get-ScheduledTask", "Get-HotFix", "Get-NetAdapter", "Get-NetIPConfiguration", "Get-ComputerRestorePoint",
           "Get-Date", "Select-Object", "Where-Object", "Sort-Object", "Group-Object", "ForEach-Object", "ConvertTo-Json",
           "Test-Path", "Get-PnpDeviceProperty", "Get-Service"}


def cmdlets(script: str) -> set[str]:
    """Commands actually invoked (at the start of a pipeline stage / block), not provider names like Kernel-PnP."""
    return set(re.findall(r"(?:^|[|{(;=]|\$\()\s*([A-Z][A-Za-z]+-[A-Z][A-Za-z]+)\b", script, re.M))


def run_probe(name: str, runner: Callable[[list[str], float], tuple] = run_quiet) -> dict:
    """One probe → {"ok", "data", "error", "ms"}. Never raises."""
    p = PROBES[name]
    if sys.platform != "win32" and runner is run_quiet:
        return {"ok": False, "data": {}, "error": "Jen na Windows", "ms": 0}
    script = PS_HEAD + p["script"] + PS_TAIL
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    t0 = time.monotonic()
    try:
        code, out, err = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-EncodedCommand", enc], p["timeout"])
    except OSError as e:
        return {"ok": False, "data": {}, "error": str(e)[:300], "ms": 0}
    ms = int((time.monotonic() - t0) * 1000)
    if code is None:
        return {"ok": False, "data": {}, "error": f"neodpovědělo do {p['timeout']} s", "ms": ms}
    out = (out or "").strip()
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError as e:
        return {"ok": False, "data": {}, "error": f"nečitelný výstup: {e}", "ms": ms}
    if not data:
        return {"ok": False, "data": {}, "error": (err or "bez výstupu")[:300], "ms": ms}
    return {"ok": True, "data": data, "error": "", "ms": ms}


# ---------------------------------------------------------------------------------------------- helpers
def L(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, dict) and "error" in v and len(v) == 1:
        return []
    return v if isinstance(v, list) else [v]


def err(v: Any) -> str:
    return v["error"] if isinstance(v, dict) and isinstance(v.get("error"), str) else ""


def needs_admin(msg: str) -> bool:
    return bool(re.search(r"access is denied|přístup byl odepřen|requires elevation|administrator|správce|0x80070005|unauthorized", msg or "", re.I))


def F(level: str, text: str, fix: str = "", source: str = "") -> dict:
    return {"level": level, "text": text, "fix": fix, "source": source}


# Windows stop codes → plain Czech (the most common ones)
BUGCHECKS = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "ovladač sáhl do paměti, kam neměl – nejčastěji vadný nebo starý ovladač (síť, grafika)"),
    0x1A: ("MEMORY_MANAGEMENT", "chyba správy paměti – často vadná RAM nebo přetaktování; spusť test paměti"),
    0x1E: ("KMODE_EXCEPTION_NOT_HANDLED", "neošetřená chyba v ovladači"),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "chyba v ovladači nebo systémové službě – často grafický ovladač"),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "vadná RAM, disk nebo ovladač – test paměti a kontrola disku"),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "ovladač způsobil chybu – podívej se na nedávno aktualizované ovladače"),
    0x7F: ("UNEXPECTED_KERNEL_MODE_TRAP", "hardware (RAM, přehřátí, přetaktování) nebo ovladač"),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "ovladač se nezvládl uspat/probudit – aktualizuj ovladače (Wi-Fi, grafika, USB)"),
    0xC2: ("BAD_POOL_CALLER", "ovladač špatně pracuje s pamětí"),
    0xD1: ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "vadný ovladač – nejčastěji síťový nebo antivir"),
    0xEF: ("CRITICAL_PROCESS_DIED", "spadl důležitý systémový proces – poškozený systém nebo disk; kontrola integrity"),
    0xF4: ("CRITICAL_OBJECT_TERMINATION", "systémový proces skončil – často problém s diskem nebo kabelem"),
    0x116: ("VIDEO_TDR_FAILURE", "grafická karta neodpověděla – ovladač grafiky, přehřátí nebo napájení"),
    0x117: ("VIDEO_TDR_TIMEOUT_DETECTED", "grafická karta zamrzla – ovladač grafiky"),
    0x124: ("WHEA_UNCORRECTABLE_ERROR", "hardwarová chyba (procesor, RAM, přehřátí, napájení, přetaktování)"),
    0x133: ("DPC_WATCHDOG_VIOLATION", "ovladač čekal moc dlouho – často firmware SSD nebo ovladač úložiště"),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "poškozená data v jádře – ovladač nebo RAM"),
    0x13A: ("KERNEL_MODE_HEAP_CORRUPTION", "ovladač poškodil paměť"),
    0x154: ("UNEXPECTED_STORE_EXCEPTION", "problém s diskem nebo pamětí"),
    0x1D8: ("IRQL_UNEXPECTED_VALUE", "ovladač"),
    0x7B: ("INACCESSIBLE_BOOT_DEVICE", "Windows nevidí systémový disk – ovladač řadiče, BIOS (AHCI/RAID) nebo vadný disk"),
    0xC000021A: ("STATUS_SYSTEM_PROCESS_TERMINATED", "poškozené systémové soubory"),
}


def explain_bugcheck(text: str) -> tuple[str, str]:
    """Event 1001 text "The bugcheck was: 0x0000009f (…)" → (name, Czech explanation)."""
    m = re.search(r"0x([0-9a-fA-F]{1,8})", text or "")
    if not m:
        return ("neznámý kód", "")
    code = int(m.group(1), 16)
    name, why = BUGCHECKS.get(code, (f"0x{code:X}", "neznámý kód – vyhledej ho na webu Microsoftu"))
    return name, why


# ---------------------------------------------------------------------------------------------- analyzers
def analyze(name: str, d: dict) -> list[dict]:
    fn = globals().get(f"_an_{name}")
    return fn(d) if fn else []


PNP_CODES = {1: "není správně nastaveno", 3: "ovladač je poškozený nebo chybí paměť", 10: "zařízení nejde spustit",
             12: "nedostatek prostředků", 18: "je potřeba přeinstalovat ovladač", 19: "poškozený záznam v registru",
             22: "zařízení je vypnuté", 24: "zařízení chybí nebo nefunguje", 28: "ovladač není nainstalovaný",
             31: "nefunguje správně, Windows nenačetl ovladač", 39: "ovladač je poškozený nebo chybí",
             43: "Windows zařízení zastavil, protože hlásilo problém (často USB, kabel nebo ovladač)", 45: "zařízení není připojené",
             52: "ovladač nemá platný podpis"}


def _an_drivers(d: dict) -> list[dict]:
    out = []
    probs = L(d.get("problems"))
    for p in probs[:15]:
        code = int(p.get("ConfigManagerErrorCode") or 0)
        if code in (22, 45):
            continue
        out.append(F("bad", f"{p.get('Name') or 'Neznámé zařízení'}: {PNP_CODES.get(code, f'chyba {code}')} (kód {code}).",
                     "Správce zařízení → zařízení → Aktualizovat ovladač; u kódu 28 stáhni ovladač od výrobce, u 43 zkus jiný port/kabel.",
                     "Win32_PnPEntity"))
    drv = L(d.get("drivers"))
    unsigned = [x for x in drv if x.get("IsSigned") is False]
    for x in unsigned[:5]:
        out.append(F("warn", f"Nepodepsaný ovladač: {x.get('DeviceName')} ({x.get('Manufacturer') or '?'}).", "Pokud ho neznáš, stáhni ovladač od výrobce.", "Win32_PnPSignedDriver"))
    old = [x for x in drv if re.fullmatch(r"\d{4}-\d\d-\d\d", x.get("Date") or "") and x["Date"] < "2016-01-01"
           and x.get("DeviceClass") in ("DISPLAY", "NET", "MEDIA", "BLUETOOTH", "USB", "HDC", "SCSIADAPTER")]
    for x in old[:5]:
        out.append(F("info", f"Starý ovladač ({x['Date']}): {x.get('DeviceName')}.", "Zkontroluj, jestli výrobce nemá novější.", "Win32_PnPSignedDriver"))
    if not out:
        out.append(F("ok", f"Všech {len(drv)} ovladačů je v pořádku, žádné zařízení nehlásí chybu.", source="Win32_PnPEntity"))
    return out


def _an_crashes(d: dict) -> list[dict]:
    out = []
    bc = L(d.get("bugchecks"))
    names: dict[str, list[str]] = {}
    for b in bc:
        name, why = explain_bugcheck(b.get("Message", ""))
        names.setdefault(f"{name}|{why}", []).append(b.get("Time", "")[:10])
    for key, days in sorted(names.items(), key=lambda kv: -len(kv[1])):
        name, why = key.split("|", 1)
        out.append(F("bad", f"Modrá obrazovka {name} – {len(days)}× (naposledy {max(days)}). {why.capitalize()}.",
                     "Aktualizuj ovladače (hlavně grafika, síť, čipset) a BIOS; pokud se opakuje, spusť test paměti.", "Get-WinEvent System 1001"))
    kp, unexp = L(d.get("kernel_power")), L(d.get("unexpected"))
    if kp or unexp:
        out.append(F("warn" if len(kp) < 3 else "bad", f"Počítač se {max(len(kp), len(unexp))}× vypnul nečekaně (za 60 dní).",
                     "Když bez modré obrazovky: zdroj, přehřátí nebo výpadek proudu. Zkontroluj teploty a napájení.", "Get-WinEvent System 41, 6008"))
    dumps = L(d.get("dumps"))
    if dumps:
        out.append(F("info", f"Uložené výpisy pádů (minidump): {len(dumps)}, poslední {dumps[0].get('Time', '')[:10]}.",
                     "Podrobný rozbor umí JARVIS, když je nainstalovaný ladicí nástroj Windows (cdb.exe z Windows SDK).", "C:\\Windows\\Minidump"))
    if err(d.get("dumps")) and needs_admin(err(d.get("dumps"))):
        out.append(F("info", "Složku s výpisy pádů smí číst jen správce.", "Spusť JARVIS jako správce pro rozbor výpisů.", "C:\\Windows\\Minidump"))
    if not out:
        out.append(F("ok", "Za posledních 60 dní žádná modrá obrazovka ani nečekané vypnutí.", source="Get-WinEvent"))
    return out


def _an_apps(d: dict) -> list[dict]:
    out = []
    errs = L(d.get("app_errors"))
    by: dict[str, dict] = {}
    for e in errs:
        k = e.get("App") or "?"
        x = by.setdefault(k, {"n": 0, "mods": {}, "last": ""})
        x["n"] += 1
        x["mods"][e.get("Module") or "?"] = x["mods"].get(e.get("Module") or "?", 0) + 1
        x["last"] = max(x["last"], e.get("Time", ""))
    for app, x in sorted(by.items(), key=lambda kv: -kv[1]["n"])[:8]:
        mod = max(x["mods"], key=x["mods"].get)
        hint = ("chyba je v samotné aplikaci – zkus ji aktualizovat nebo přeinstalovat" if mod.lower() == app.lower()
                else f"padá v části {mod}" + (" (grafický ovladač)" if re.search(r"nvwgf|atidxx|amdxx|igd|d3d", mod, re.I) else "")
                + (" (systémová knihovna – poškozená instalace nebo doplněk)" if re.search(r"ntdll|kernelbase|ucrtbase|msvcp|vcruntime", mod, re.I) else ""))
        out.append(F("warn" if x["n"] < 5 else "bad", f"{app} spadl {x['n']}× za 14 dní, {hint}.", "Aktualizuj aplikaci; když padá v ovladači, aktualizuj ovladač.", "Get-WinEvent Application 1000"))
    hangs = L(d.get("hangs"))
    hb: dict[str, int] = {}
    for h_ in hangs:
        hb[h_.get("App") or "?"] = hb.get(h_.get("App") or "?", 0) + 1
    for app, n in sorted(hb.items(), key=lambda kv: -kv[1])[:5]:
        out.append(F("info", f"{app} zamrzl {n}× za 14 dní.", "Zkontroluj zaplnění disku a paměti, když zamrzá.", "Get-WinEvent Application 1002"))
    if not out:
        out.append(F("ok", "Za 14 dní žádná aplikace nespadla ani nezamrzla.", source="Get-WinEvent"))
    return out


def _an_boot(d: dict) -> list[dict]:
    out = []
    boots = L(d.get("boots"))
    if boots:
        last = boots[0]
        secs = (last.get("BootMs") or 0) / 1000
        avg = sum((b.get("BootMs") or 0) for b in boots) / len(boots) / 1000
        lvl = "ok" if secs < 45 else "warn" if secs < 90 else "bad"
        out.append(F(lvl, f"Poslední start trval {secs:.0f} s (průměr posledních {len(boots)}: {avg:.0f} s).",
                     "" if lvl == "ok" else "Vypni zbytečné programy po spuštění a zkontroluj disk (HDD startuje pomalu).",
                     "Diagnostics-Performance 100"))
    elif err(d.get("boots")):
        if needs_admin(err(d.get("boots"))):
            out.append(F("info", "Časy startu smí číst jen správce (log Diagnostics-Performance).", "Spusť JARVIS jako správce.", "Diagnostics-Performance"))
        else:
            out.append(F("info", "Tenhle Windows záznam o době startu nevede (log Diagnostics-Performance chybí nebo je prázdný).", "",
                         "Diagnostics-Performance"))
    slow = sorted(L(d.get("slow")), key=lambda x: -(x.get("DegradationMs") or 0))
    for s_ in slow[:6]:
        if (s_.get("DegradationMs") or 0) > 1000:
            out.append(F("warn", f"Start zdržuje {s_.get('Name') or '?'} o {(s_['DegradationMs']) / 1000:.1f} s.",
                         "Pokud to nepotřebuješ hned po startu, vypni ho v Správci úloh → Po spuštění.", "Diagnostics-Performance 101–109"))
    st = L(d.get("startup"))
    if len(st) > 12:
        out.append(F("warn", f"Se systémem se spouští {len(st)} programů.", "Správce úloh → Po spuštění → vypni, co nepotřebuješ hned.", "Win32_StartupCommand"))
    fs = d.get("fast_startup")
    if fs == 0:
        out.append(F("info", "Rychlé spuštění Windows je vypnuté – start bývá pomalejší.", "Ovládací panely → Možnosti napájení → Zapnout rychlé spuštění (pokud ho nepotřebuješ mít vypnuté).", "registry HiberbootEnabled"))
    if not out:
        out.append(F("ok", "Start Windows je v pořádku.", source="Diagnostics-Performance"))
    return out


def _an_usb(d: dict) -> list[dict]:
    out = []
    for p in L(d.get("usb_problems"))[:10]:
        out.append(F("bad", f"{p.get('FriendlyName') or p.get('InstanceId')}: stav {p.get('Status')}.",
                     "Zkus jiný USB port (vzadu na PC), jiný kabel, bez rozbočovače; pak ovladač ve Správci zařízení.", "Get-PnpDevice"))
    ev = L(d.get("pnp_events"))
    if ev:
        out.append(F("warn", f"Windows {len(ev)}× za týden hlásil problém s připojením zařízení (např. „{(ev[0].get('Text') or '')[:80]}“).",
                     "Opakované odpojování: vadný kabel, napájení USB nebo úsporný režim USB (Možnosti napájení → Selektivní pozastavení USB).",
                     "Kernel-PnP 219/411/420/441"))
    for disk in L(d.get("disks")):
        bus, style, status = disk.get("Bus", ""), disk.get("Style", ""), disk.get("Status", "")
        name = disk.get("FriendlyName") or f"Disk {disk.get('Number')}"
        if disk.get("IsOffline") or status.lower() not in ("online", ""):
            out.append(F("bad", f"{name} ({bus}) je ve stavu {status or 'offline'} – Windows ho nevidí jako použitelný.",
                         "NIC NEFORMÁTUJ. Pokud na něm jsou data, nejdřív je zachraň (JARVIS: plán záchrany dat).", "Get-Disk"))
        elif style.upper() == "RAW":
            out.append(F("bad", f"{name} ({bus}) nemá rozpoznané oddíly (RAW).",
                         "NEFORMÁTUJ ho, i když to Windows nabízí – data mohou jít zachránit. Zkus jiný kabel/port a obnovu dat.", "Get-Disk"))
        if bus.upper() == "USB" and re.search(r"jmicron|asmedia|realtek|usb3\.0|sata|nvme|enclosure", name, re.I):
            out.append(F("info", f"{name} je disk v USB rámečku (převodník).", "Když se odpojuje, zkus napájený rozbočovač nebo jiný kabel; SMART přes převodník často nejde.", "Get-Disk BusType"))
    if not out:
        out.append(F("ok", "USB zařízení a disky jsou v pořádku.", source="Get-PnpDevice, Get-Disk"))
    return out


def _an_disks(d: dict) -> list[dict]:
    out = []
    rel = {str(r.get("DeviceId")): r for r in L(d.get("reliability"))}
    for p in L(d.get("physical")):
        name = p.get("FriendlyName") or "disk"
        h_ = p.get("Health", "")
        if h_ and h_ not in ("Healthy", "0"):
            out.append(F("bad", f"{name}: stav zdraví {h_}.", "Zálohuj data hned a disk vyměň.", "Get-PhysicalDisk"))
        r = rel.get(str(p.get("DeviceId"))) or {}
        if (r.get("Wear") or 0) >= 80:
            out.append(F("bad" if r["Wear"] >= 95 else "warn", f"{name}: opotřebení {r['Wear']} %.", "Plánuj výměnu SSD, zálohuj.", "StorageReliabilityCounter"))
        if (r.get("Temperature") or 0) >= 60:
            out.append(F("warn", f"{name}: teplota {r['Temperature']} °C.", "Zlepši chlazení (SSD nad 70 °C zpomaluje).", "StorageReliabilityCounter"))
        if (r.get("ReadErrors") or 0) + (r.get("WriteErrors") or 0) > 0:
            out.append(F("bad", f"{name}: {r.get('ReadErrors') or 0} chyb čtení a {r.get('WriteErrors') or 0} chyb zápisu.", "Zálohuj data, disk může selhávat.", "StorageReliabilityCounter"))
    for v in L(d.get("volumes")):
        size, free = v.get("Size") or 0, v.get("SizeRemaining") or 0
        if size and free / size < 0.1:
            out.append(F("warn", f"Disk {v.get('Letter')}: volné jen {free / 2**30:.1f} GB z {size / 2**30:.0f} GB.", "Uvolni místo (JARVIS: co zabírá místo, úklid).", "Get-Volume"))
        if v.get("Health") not in (None, "", "Healthy"):
            out.append(F("bad", f"Disk {v.get('Letter')}: stav svazku {v.get('Health')}.", "Spusť kontrolu disku (JARVIS to umí jen pro čtení).", "Get-Volume"))
    ev = L(d.get("io_events"))
    if ev:
        kinds: dict[str, int] = {}
        for e in ev:
            k = {7: "vadné sektory", 51: "chyba stránkování (čtení/zápis)", 153: "opakované I/O", 55: "poškozený souborový systém",
                 98: "kontrola souborového systému", 140: "chyba zápisu NTFS", 129: "reset řadiče (timeout)", 11: "chyba řadiče"}.get(int(e.get("Id") or 0), "chyba disku")
            kinds[k] = kinds.get(k, 0) + 1
        txt = ", ".join(f"{k} {n}×" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
        bad = any(k in kinds for k in ("vadné sektory", "chyba stránkování (čtení/zápis)", "reset řadiče (timeout)"))
        out.append(F("bad" if bad else "warn", f"Systémový log za 30 dní: {txt}.",
                     "Vadné sektory nebo timeouty = zálohuj HNED; timeouty bývají i kabel/napájení. Nic neformátuj.", "Get-WinEvent disk/Ntfs/stor*"))
    for c in disk_crash_links(ev, L(d.get("crash_times"))):
        out.append(F("bad", f"Pád systému {c['crash'].replace('T', ' ')} předcházely chyby disku ({c['errors']}× během {c['minutes']} min před ním).",
                     "Pády nejspíš způsobuje disk nebo jeho kabel/řadič – zálohuj data a vyměň kabel, případně disk.", "Get-WinEvent disk + 41/1001/6008"))
    if err(d.get("reliability")) and needs_admin(err(d.get("reliability"))):
        out.append(F("info", "Podrobné údaje SMART (opotřebení, teplota) smí číst jen správce.", "Spusť JARVIS jako správce.", "StorageReliabilityCounter"))
    if not out:
        out.append(F("ok", "Disky jsou zdravé a bez chyb v logu.", source="Get-PhysicalDisk, Get-WinEvent"))
    return out


def disk_crash_links(io_events: list, crashes: list, window_min: int = 15) -> list[dict]:
    """OMEGA 291: crashes preceded by disk errors within the window → the likely cause."""
    import datetime as dt

    def t(x):
        try:
            return dt.datetime.fromisoformat(str(x.get("Time") or "")[:19])
        except ValueError:
            return None
    errs = [e for e in (t(x) for x in io_events) if e]
    out = []
    for c in crashes:
        ct = t(c)
        if not ct:
            continue
        n = sum(1 for e in errs if dt.timedelta(0) <= ct - e <= dt.timedelta(minutes=window_min))
        if n:
            out.append({"crash": ct.isoformat(), "errors": n, "minutes": window_min})
    return out[:5]


def service_tree(deps: list) -> list[dict]:
    """OMEGA 294: for each stopped automatic service – what it needs that is not running (the likely cause) and what
    else waits on it."""
    out = []
    for s_ in deps:
        needs = L(s_.get("Needs"))
        waiting = L(s_.get("Waiting"))
        out.append({"name": s_.get("Display") or s_.get("Name"),
                    "blocked_by": [n.get("Display") or n.get("Name") for n in needs if str(n.get("Status")) not in ("Running", "4")],
                    "needs": [n.get("Display") or n.get("Name") for n in needs],
                    "affects": [w.get("Display") or w.get("Name") for w in waiting]})
    return out


def _an_services(d: dict) -> list[dict]:
    out = []
    for t_ in service_tree(L(d.get("deps"))):
        if t_["blocked_by"]:
            out.append(F("warn", f"„{t_['name']}“ neběží, protože nejede služba, na které závisí: {', '.join(t_['blocked_by'])}.",
                         f"Nejdřív oprav/spusť {t_['blocked_by'][0]} – „{t_['name']}“ se pak rozběhne s ní.", "Get-Service ServicesDependedOn"))
        if t_["affects"]:
            out.append(F("info", f"Na „{t_['name']}“ čeká: {', '.join(t_['affects'][:6])}.", "", "Get-Service DependentServices"))
    for s_ in L(d.get("stopped_auto"))[:10]:
        out.append(F("warn", f"Služba „{s_.get('DisplayName')}“ se má spouštět sama, ale neběží (kód {s_.get('ExitCode')}).",
                     "Pokud ji nepoužíváš, nevadí; jinak Služby → spustit / restart PC.", "Win32_Service"))
    ev = L(d.get("scm_events"))
    if ev:
        out.append(F("warn", f"Za týden {len(ev)} chyb spouštění služeb (např. „{(ev[0].get('Text') or '')[:90]}“).", "", "Service Control Manager"))
    if not out:
        out.append(F("ok", "Všechny automatické služby běží.", source="Win32_Service"))
    return out


SUSPICIOUS_DIRS = re.compile(r"\\(appdata\\(local\\temp|roaming)|temp|downloads|stažené soubory|public)\\", re.I)


def _an_security(d: dict) -> list[dict]:
    out = []
    av = d.get("defender") if isinstance(d.get("defender"), dict) and not err(d.get("defender")) else None
    if av:
        if not av.get("AntivirusEnabled") or not av.get("RealTimeProtectionEnabled"):
            out.append(F("bad", "Ochrana v reálném čase (Microsoft Defender) je vypnutá.", "Zabezpečení Windows → Ochrana před viry → zapnout.", "Get-MpComputerStatus"))
        if (av.get("AntivirusSignatureAge") or 0) > 7:
            out.append(F("warn", f"Virové definice jsou {av['AntivirusSignatureAge']} dní staré.", "Spusť Windows Update.", "Get-MpComputerStatus"))
        if (av.get("QuickScanAge") or 0) > 14:
            out.append(F("info", f"Rychlá kontrola virů proběhla před {av['QuickScanAge']} dny.", "Spusť rychlou kontrolu v Zabezpečení Windows.", "Get-MpComputerStatus"))
    elif err(d.get("defender")):
        out.append(F("info", "Stav Microsoft Defenderu nejde zjistit (jiný antivirus nebo chybí oprávnění).", "", "Get-MpComputerStatus"))
    if d.get("cfa") == 0:
        out.append(F("info", "Řízený přístup ke složkám (ochrana proti ransomwaru) je vypnutý.", "Zabezpečení Windows → Ochrana proti ransomwaru → zapnout.", "Get-MpPreference"))
    for t in L(d.get("threats"))[:5]:
        out.append(F("bad" if not t.get("ActionSuccess") else "warn", f"Defender našel hrozbu ({t.get('Time', '')[:10]}): {(t.get('Resources') or '')[:120]}.",
                     "Zkontroluj historii ochrany v Zabezpečení Windows.", "Get-MpThreatDetection"))
    for fw in L(d.get("firewall")):
        if fw.get("Enabled") in (False, 0):
            out.append(F("bad", f"Firewall je vypnutý pro síť typu {fw.get('Name')}.", "Zabezpečení Windows → Brána firewall → zapnout.", "Get-NetFirewallProfile"))
    exposed = [x for x in L(d.get("listening")) if x.get("Address") in ("0.0.0.0", "::") and int(x.get("Port") or 0) not in (135, 139, 445, 5040, 7680)
               and int(x.get("Port") or 0) < 49152]
    if exposed:
        names = ", ".join(sorted({f"{x.get('Process') or '?'}:{x.get('Port')}" for x in exposed})[:10])
        out.append(F("info", f"Programy, které přijímají spojení ze sítě: {names}.", "Pokud některý neznáš, zjisti, co to je (a zda má mít přístup ze sítě).", "Get-NetTCPConnection"))
    for s_ in L(d.get("startup")):
        exe, sig = s_.get("Exe") or "", s_.get("Signature") or ""
        if exe and sig not in ("Valid",) and SUSPICIOUS_DIRS.search(exe + "\\"):
            out.append(F("bad", f"Podezřelá položka po spuštění: „{s_.get('Name')}“ spouští nepodepsaný program z {exe}.",
                         "Pokud ji neznáš: Správce úloh → Po spuštění → zakázat a nech soubor zkontrolovat antivirem.", "Win32_StartupCommand + podpis"))
        elif exe and sig in ("NotSigned", "HashMismatch"):
            out.append(F("warn", f"Program po spuštění bez platného podpisu: {s_.get('Name')} ({exe}).", "Ověř, že ho znáš.", "Get-AuthenticodeSignature"))
    for t in L(d.get("tasks")):
        a = t.get("Action") or ""
        if SUSPICIOUS_DIRS.search(a + "\\") or re.search(r"powershell.*(-enc|-e\s|bypass|hidden)", a, re.I):
            out.append(F("bad", f"Podezřelá naplánovaná úloha „{t.get('TaskName')}“: {a[:120]}.", "Pokud ji neznáš, zakaž ji v Plánovači úloh.", "Get-ScheduledTask"))
    if d.get("uac") == 0:
        out.append(F("bad", "Řízení uživatelských účtů (UAC) je vypnuté.", "Zapni ho (Ovládací panely → Uživatelské účty).", "registry EnableLUA"))
    if d.get("rdp") == 0:
        out.append(F("warn", "Vzdálená plocha je zapnutá.", "Pokud ji nepoužíváš, vypni ji (Nastavení → Systém → Vzdálená plocha).", "registry fDenyTSConnections"))
    hf = d.get("hotfix") if isinstance(d.get("hotfix"), dict) else {}
    if hf.get("Date"):
        import datetime as dt

        age = (dt.date.today() - dt.date.fromisoformat(hf["Date"])).days
        if age > 45:
            out.append(F("warn", f"Poslední aktualizace Windows je z {hf['Date']} ({age} dní).", "Spusť Windows Update.", "Get-HotFix"))
    if not out:
        out.append(F("ok", "Ochrana je zapnutá a nic podezřelého jsem nenašel.", source="Defender, firewall, autostart"))
    return out


def _an_network(d: dict) -> list[dict]:
    out = []
    ups = [a for a in L(d.get("adapters")) if a.get("Status") == "Up"]
    if not ups:
        out.append(F("bad", "Žádné síťové připojení není aktivní.", "Zapni Wi-Fi nebo připoj kabel.", "Get-NetAdapter"))
    for c in L(d.get("ipconfig")):
        if not c.get("Gateway"):
            out.append(F("warn", f"{c.get('InterfaceAlias')}: chybí výchozí brána – internet nepůjde.", "Restartuj router / připoj se znovu.", "Get-NetIPConfiguration"))
        if (c.get("IPv4") or "").startswith("169.254."):
            out.append(F("bad", f"{c.get('InterfaceAlias')}: adresa 169.254.x.x – router nepřidělil adresu.", "Restartuj router a odpoj/připoj síť.", "Get-NetIPConfiguration"))
    if not out:
        out.append(F("ok", f"Síť je připojená ({', '.join(a.get('Name', '') for a in ups)}).", source="Get-NetAdapter"))
    return out


def _an_restore(d: dict) -> list[dict]:
    out = []
    pts = L(d.get("points"))
    if pts:
        out.append(F("ok", f"Bodů obnovy: {len(pts)}, poslední {pts[-1].get('Time', '')[:10]} („{pts[-1].get('Description')}“).", source="Get-ComputerRestorePoint"))
    elif err(d.get("points")):
        msg = err(d.get("points"))
        if re.search(r"not supported on this operating system|není v tomto operačním systému podporován", msg, re.I):
            out.append(F("info", "Tahle edice Windows body obnovy nepodporuje (např. Windows Server).", "", "Get-ComputerRestorePoint"))
        else:
            out.append(F("info", "Body obnovy smí číst jen správce." if needs_admin(msg) else "Ochrana systému (body obnovy) je asi vypnutá.",
                         "Vlastnosti systému → Ochrana systému → zapnout pro disk C:.", "Get-ComputerRestorePoint"))
    else:
        out.append(F("warn", "Žádný bod obnovy.", "Před větší změnou vytvoř bod obnovy (JARVIS to umí se schválením).", "Get-ComputerRestorePoint"))
    for m in L(d.get("memtest"))[:2]:
        out.append(F("bad" if m.get("Id") == 1101 or "error" in (m.get("Text") or "").lower() else "ok",
                     f"Test paměti ({m.get('Time', '')[:10]}): {m.get('Text')}", source="MemoryDiagnostics-Results"))
    return out


def _an_devices(d: dict) -> list[dict]:
    n = len(L(d.get("present")))
    return [F("ok", f"Připojeno {n} zařízení (USB, monitory, audio, Bluetooth…).", source="Get-PnpDevice")]


AREAS = {"drivers": "Ovladače", "crashes": "Pády systému", "apps": "Pády aplikací", "boot": "Start", "usb": "USB a disky",
         "disks": "Zdraví disků", "services": "Služby", "security": "Bezpečnost", "network": "Síť", "restore": "Obnova"}


def device_snapshot(d: dict) -> list[str]:
    return sorted({f"{x.get('Class')}: {x.get('FriendlyName')}" for x in L(d.get("present")) if x.get("FriendlyName")})


# ---------------------------------------------------------------------------------------------- optional tools
def smart_data(runner: Callable[[list[str], float], tuple] = run_quiet, exe: str | None = None) -> dict:
    """smartmontools (smartctl) when installed: full S.M.A.R.T. even where Windows hides it. Read-only (-H -A -j)."""
    import shutil

    exe = exe or shutil.which("smartctl") or next((p for p in (r"C:\Program Files\smartmontools\bin\smartctl.exe",)
                                                   if __import__("os").path.isfile(p)), None)
    if not exe:
        return {"available": False}
    _c, out, _e = runner([exe, "--scan", "-j"], 20)
    try:
        devs = [d["name"] for d in json.loads(out or "{}").get("devices", [])]
    except ValueError:
        devs = []
    disks = []
    for dev in devs[:8]:
        _c, out, _e = runner([exe, "-H", "-A", "-i", "-j", dev], 30)
        try:
            j = json.loads(out or "{}")
        except ValueError:
            continue
        attrs = {a.get("name"): (a.get("raw") or {}).get("value") for a in (j.get("ata_smart_attributes") or {}).get("table", [])}
        nv = j.get("nvme_smart_health_information_log") or {}
        disks.append({"device": dev, "model": j.get("model_name", ""), "passed": (j.get("smart_status") or {}).get("passed"),
                      "temp": (j.get("temperature") or {}).get("current"), "hours": (j.get("power_on_time") or {}).get("hours"),
                      "reallocated": attrs.get("Reallocated_Sector_Ct"), "pending": attrs.get("Current_Pending_Sector"),
                      "uncorrectable": attrs.get("Offline_Uncorrectable"), "nvme_used_pct": nv.get("percentage_used"),
                      "media_errors": nv.get("media_errors")})
    return {"available": True, "disks": disks}


def analyze_smart(s: dict) -> list[dict]:
    out = []
    for d in s.get("disks", []):
        name = d.get("model") or d["device"]
        if d.get("passed") is False:
            out.append(F("bad", f"{name}: SMART test NEPROŠEL.", "Okamžitě zálohuj data a disk vyměň.", "smartctl -H"))
        for k, label in (("reallocated", "přemapovaných sektorů"), ("pending", "sektorů čekajících na přemapování"), ("uncorrectable", "neopravitelných sektorů")):
            if (d.get(k) or 0) > 0:
                out.append(F("bad", f"{name}: {d[k]} {label}.", "Disk začíná selhávat – zálohuj hned, nic neformátuj.", "smartctl -A"))
        if (d.get("nvme_used_pct") or 0) >= 80:
            out.append(F("warn", f"{name}: SSD opotřebení {d['nvme_used_pct']} %.", "Plánuj výměnu.", "smartctl NVMe log"))
        if (d.get("media_errors") or 0) > 0:
            out.append(F("bad", f"{name}: {d['media_errors']} chyb média.", "Zálohuj data.", "smartctl NVMe log"))
    if s.get("disks") and not out:
        out.append(F("ok", f"SMART: {len(s['disks'])} disků v pořádku.", source="smartctl"))
    return out


def integrity_check(runner: Callable[[list[str], float], tuple] = run_quiet) -> dict:
    """OMEGA 287: Windows system files – DISM /CheckHealth (seconds) and SFC /VERIFYONLY (minutes). Only checks, never repairs."""
    if sys.platform != "win32" and runner is run_quiet:
        return {"ok": False, "error": "Jen na Windows"}
    res: dict[str, Any] = {}
    code, out, err_ = runner(["dism.exe", "/Online", "/Cleanup-Image", "/CheckHealth"], 300)
    txt = (out or "") + (err_ or "")
    res["dism"] = {"code": code, "text": txt[-500:]}
    code2, out2, err2 = runner(["sfc.exe", "/VERIFYONLY"], 1800)
    t2 = ((out2 or "") + (err2 or "")).replace("\x00", "")
    res["sfc"] = {"code": code2, "text": t2[-800:]}
    findings = []
    if needs_admin(txt + t2) or re.search(r"elevat|740", txt + t2, re.I):
        findings.append(F("info", "Kontrolu systémových souborů smí spustit jen správce.", "Spusť JARVIS jako správce a zkus to znovu.", "DISM, SFC"))
    else:
        if re.search(r"repairable|opravit|corrupt|poškoz", txt, re.I) and not re.search(r"no component store corruption|nebylo zjištěno", txt, re.I):
            findings.append(F("bad", "DISM našel poškození úložiště součástí Windows.", "Oprava: DISM /Online /Cleanup-Image /RestoreHealth (jako správce, se schválením).", "DISM /CheckHealth"))
        if re.search(r"found integrity violations|zjistila narušení integrity", t2, re.I):
            findings.append(F("bad", "SFC našel poškozené systémové soubory.", "Oprava: sfc /scannow (jako správce).", "SFC /VERIFYONLY"))
        elif re.search(r"did not find any integrity violations|nezjistila žádná narušení", t2, re.I):
            findings.append(F("ok", "Systémové soubory jsou v pořádku.", source="SFC /VERIFYONLY"))
        elif code2 is None:
            findings.append(F("info", "SFC nedoběhl v časovém limitu.", "", "SFC"))
    res["findings"] = findings or [F("info", "Výsledek kontroly se nepodařilo přečíst.", "", "DISM, SFC")]
    res["ok"] = True
    return res


RESTORE_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try { Checkpoint-Computer -Description $env:JARVIS_RP_DESC -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop; 'OK' } catch { 'ERR ' + $_.Exception.Message }
"""


def create_restore_point(description: str, runner: Callable[[list[str], float], tuple] = run_quiet) -> tuple[bool, str]:
    """A restore point (needs administrator rights; Windows allows one per 24 h unless the policy says otherwise)."""
    import os

    if sys.platform != "win32" and runner is run_quiet:
        return False, "Jen na Windows."
    os.environ["JARVIS_RP_DESC"] = re.sub(r"[^\w .,:()\-ěščřžýáíéúůťďňĚŠČŘŽÝÁÍÉÚŮŤĎŇ]", "", description)[:60] or "JARVIS"
    enc = base64.b64encode(RESTORE_PS.encode("utf-16-le")).decode()
    code, out, e = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 300)
    out = (out or "").strip()
    if out.endswith("OK"):
        return True, "Bod obnovy je vytvořený."
    msg = out.removeprefix("ERR ") or e or "bez odpovědi"
    if needs_admin(msg):
        return False, "Bod obnovy smí vytvořit jen správce – spusť JARVIS jako správce."
    if re.search(r"1440|24 hours|frequency|četnost", msg, re.I):
        return False, "Windows dovolí jen jeden bod obnovy za 24 hodin a dnes už jeden vznikl."
    if re.search(r"disabled|vypnut|0x80042306", msg, re.I):
        return False, "Ochrana systému je na disku C: vypnutá (Vlastnosti systému → Ochrana systému)."
    return False, f"Nepovedlo se: {msg[:200]}"


# ---------------------------------------------------------------------------------------------- the report
CRITERIA = [
    "Každá zvolená oblast má výsledek nebo vysvětlení, proč chybí",
    "Každé zjištění má zdroj (příkaz / log)",
    "Report je uložený a odpovídá otisku SHA-256",
    "Diagnostika jen četla – příkazy jsou ze seznamu povolených",
]


def diagnose(areas: list[str], runner: Callable[[list[str], float], tuple] = run_quiet, smart: bool = True) -> dict:
    import datetime as dt
    import socket

    results = []
    for a in areas:
        r = run_probe(a, runner)
        if r["ok"]:
            fnd = analyze(a, r["data"])
            for f in fnd:
                f["source"] = f["source"] or f"sonda {a}"
        else:
            fnd = [F("info", f"Nešlo změřit: {r['error']}", "Spusť JARVIS jako správce." if needs_admin(r["error"]) else "", PROBES[a]["title"])]
        results.append({"area": a, "title": PROBES[a]["title"], "ok": r["ok"], "ms": r["ms"], "error": r["error"], "findings": fnd})
    if smart and "disks" in areas:
        s = smart_data(runner) if runner is not run_quiet or sys.platform == "win32" else {"available": False}
        if s.get("available"):
            results.append({"area": "smart", "title": "SMART (smartctl)", "ok": True, "ms": 0, "error": "", "findings": analyze_smart(s)})
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    worst = sorted((f for r in results for f in r["findings"]), key=lambda f: order.get(f["level"], 9))
    return {"host": socket.gethostname(), "created": dt.datetime.now().isoformat(timespec="seconds"), "areas": areas,
            "results": results, "top": [f for f in worst if f["level"] in ("bad", "warn")][:8],
            "commands": sorted(set().union(*(cmdlets(PROBES[a]["script"]) for a in areas)) if areas else set())}


def render_report(data: dict) -> str:
    import html

    e = html.escape
    lvl = {"bad": ("bad", "problém"), "warn": ("warn", "pozor"), "info": ("unk", "info"), "ok": ("ok", "v pořádku")}
    secs = []
    for r in data["results"]:
        items = "".join(f"<li><span class=\"b {lvl[f['level']][0]}\">{lvl[f['level']][1]}</span> {e(f['text'])}"
                        + (f"<div class=fix>Co udělat: {e(f['fix'])}</div>" if f.get("fix") else "")
                        + f"<div class=src>Zdroj: {e(f.get('source') or '')}</div></li>" for f in r["findings"])
        secs.append(f"<section id=\"{e(r['area'])}\"><h2>{e(r['title'])}</h2><ul>{items}</ul>"
                    f"<p class=src>{'změřeno za ' + str(r['ms']) + ' ms' if r['ok'] else 'nezměřeno: ' + e(r['error'])}</p></section>")
    top = "".join(f"<li class={f['level']}>{e(f['text'])}</li>" for f in data["top"]) or "<li class=ok>Nenašel jsem žádný problém.</li>"
    raw = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang=cs><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Diagnostika {e(data['host'])} – {e(data['created'][:16].replace('T', ' '))}</title>
<style>body{{margin:0;font:15px/1.5 system-ui,Segoe UI,sans-serif;background:#0b0b0d;color:#ececf1}}main{{max-width:880px;margin:auto;padding:32px 20px}}
h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:17px;margin:0 0 10px}}section{{background:#16161a;border:1px solid #26262c;border-radius:16px;padding:16px 18px;margin:14px 0}}
ul{{padding-left:0;list-style:none;margin:0}}li{{margin:8px 0}}.b{{font-size:11px;padding:2px 8px;border-radius:99px;font-weight:600;margin-right:6px}}
.ok{{background:#14532d;color:#86efac}}.warn{{background:#713f12;color:#fde68a}}.bad{{background:#7f1d1d;color:#fecaca}}.unk{{background:#27272a;color:#a1a1aa}}
.fix{{color:#d4d4d8;font-size:13px;margin-top:2px}}.src{{color:#71717a;font-size:12px}}#top li.bad{{color:#fca5a5;background:none}}#top li.warn{{color:#fde68a;background:none}}#top li.ok{{background:none}}
@media print{{body{{background:#fff;color:#000}}section{{background:#fff;border-color:#ccc}}}}</style></head><body><main>
<h1>Diagnostika {e(data['host'])}</h1><p class=src>Vytvořil JARVIS {e(data['created'].replace('T', ' '))}. Jen čtení – nic se neměnilo.</p>
<section id=top><h2>Nejdůležitější</h2><ul>{top}</ul></section>
{''.join(secs)}
<p class=src>Použité příkazy: {e(', '.join(data['commands']))}</p>
<script type="application/json" id="jarvis-data">{raw}</script>
</main></body></html>"""


def write_report(data: dict, folder=None):
    import datetime as dt

    from .pcreport import reports_dir

    folder = folder or reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"diagnostika_{dt.datetime.now():%Y-%m-%d_%H-%M-%S}.html"
    path.write_text(render_report(data), encoding="utf-8")
    return path


def verify_report(path, sha256: str) -> list[tuple[str, bool, str]]:
    """The criteria checked against the file on disk."""
    from .tasks import sha256_file

    out = []
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'<script type="application/json" id="jarvis-data">(.*?)</script>', text, re.S)
        data = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
    except (OSError, ValueError):
        data = {}
    res = data.get("results", [])
    missing = [a for a in data.get("areas", []) if not any(r["area"] == a and r["findings"] for r in res)]
    out.append((CRITERIA[0], bool(data) and not missing, "chybí: " + ", ".join(missing) if missing else f"{len(res)} oblastí"))
    nosrc = [f["text"][:40] for r in res for f in r["findings"] if not f.get("source")]
    out.append((CRITERIA[1], bool(data) and not nosrc, "bez zdroje: " + "; ".join(nosrc[:3]) if nosrc else "všechna zjištění"))
    now = sha256_file(path) if path.is_file() else ""
    out.append((CRITERIA[2], now == sha256, now[:16] + "…"))
    extra = set(data.get("commands", [])) - ALLOWED
    out.append((CRITERIA[3], bool(data) and not extra, "navíc: " + ", ".join(extra) if extra else ", ".join(data.get("commands", []))))
    return out
