"""OMEGA 015: what a blue screen was – read straight from the crash dump file (C:\\Windows\\Minidump\\*.dmp), no debugger
needed. A kernel dump starts with a fixed header that holds the stop code and its four parameters; the code says the
kind of failure and the parameters point at the cause (e.g. a memory address, a driver timeout). Read-only."""
from __future__ import annotations

import datetime as dt
import re
import struct
import sys
from pathlib import Path

# stop code → (name, plain meaning, what to do)
BUGCHECKS: dict[int, tuple[str, str, str]] = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "ovladač sáhl do paměti, kam neměl", "Aktualizuj ovladače (hlavně síť, grafika, zvuk); když to začalo po instalaci něčeho, odinstaluj to."),
    0x1A: ("MEMORY_MANAGEMENT", "chyba ve správě paměti – často vadná RAM", "Spusť Diagnostiku paměti Windows (mdsched) a vyzkoušej moduly RAM jednotlivě; vypni přetaktování / XMP."),
    0x1E: ("KMODE_EXCEPTION_NOT_HANDLED", "ovladač způsobil neošetřenou chybu", "Aktualizuj ovladače; pomůže i kontrola systémových souborů."),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "chyba při volání systému – typicky ovladač grafiky nebo antivir", "Přeinstaluj ovladač grafiky (čistá instalace), zkontroluj antivir třetí strany."),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "čtení z neplatné paměti – vadná RAM nebo ovladač", "Test paměti (mdsched) a aktualizace ovladačů."),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "systémové vlákno ovladače spadlo", "Aktualizuj ovladače; když se to děje při startu, zkus nouzový režim a odinstaluj poslední ovladač."),
    0x7F: ("UNEXPECTED_KERNEL_MODE_TRAP", "procesor hlásil neočekávanou chybu – často hardware nebo přetaktování", "Vypni přetaktování, zkontroluj teploty a RAM."),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "ovladač nezvládl uspání / probuzení", "Aktualizuj ovladače (Wi-Fi, USB, grafika) a BIOS; zkus vypnout rychlé spuštění."),
    0xC2: ("BAD_POOL_CALLER", "ovladač špatně pracuje s pamětí", "Aktualizuj nebo odinstaluj naposledy přidané ovladače (antivir, VPN, virtuální zařízení)."),
    0xC5: ("DRIVER_CORRUPTED_EXPOOL", "ovladač poškodil paměť systému", "Aktualizuj ovladače; zkontroluj RAM."),
    0xD1: ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "ovladač (nejčastěji síťový) sáhl do neplatné paměti", "Aktualizuj ovladač síťové karty / Wi-Fi z webu výrobce."),
    0xEF: ("CRITICAL_PROCESS_DIED", "spadl nezbytný proces Windows", "Kontrola systémových souborů (SFC/DISM) a disku; zkontroluj, jestli disk nehlásí chyby."),
    0xF4: ("CRITICAL_OBJECT_TERMINATION", "ukončil se nezbytný proces – často disk nebo kabel", "Zkontroluj zdraví disku a kabel SATA; zálohuj data."),
    0x7A: ("KERNEL_DATA_INPAGE_ERROR", "systém nenačetl data z disku", "Disk nebo kabel selhává – zálohuj data, zkontroluj zdraví disku a kabel."),
    0x77: ("KERNEL_STACK_INPAGE_ERROR", "systém nenačetl data z disku", "Disk nebo kabel selhává – zálohuj data."),
    0x101: ("CLOCK_WATCHDOG_TIMEOUT", "jedno jádro procesoru přestalo odpovídat", "Vypni přetaktování, aktualizuj BIOS, zkontroluj teploty a napájení."),
    0x116: ("VIDEO_TDR_FAILURE", "grafická karta přestala odpovídat a nešla obnovit", "Čistá instalace ovladače grafiky, kontrola teploty grafiky a napájení; bez přetaktování."),
    0x117: ("VIDEO_TDR_TIMEOUT_DETECTED", "grafická karta neodpověděla včas", "Ovladač grafiky, teploty, napájení."),
    0x119: ("VIDEO_SCHEDULER_INTERNAL_ERROR", "chyba plánovače grafiky", "Čistá instalace ovladače grafiky."),
    0x124: ("WHEA_UNCORRECTABLE_ERROR", "hardware nahlásil neopravitelnou chybu (procesor, RAM, napájení)", "Vypni přetaktování / XMP, zkontroluj teploty, zdroj a aktualizuj BIOS."),
    0x133: ("DPC_WATCHDOG_VIOLATION", "ovladač čekal příliš dlouho – často SSD (firmware) nebo starý ovladač SATA", "Aktualizuj firmware SSD a ovladač řadiče úložiště (Intel RST / AMD SATA)."),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "ovladač poškodil chráněnou strukturu", "Aktualizuj ovladače; test RAM."),
    0x13A: ("KERNEL_MODE_HEAP_CORRUPTION", "ovladač poškodil paměť", "Aktualizuj ovladače (často grafika)."),
    0x154: ("UNEXPECTED_STORE_EXCEPTION", "chyba úložiště – SSD/disk nebo jeho ovladač", "Zkontroluj zdraví disku, firmware SSD a ovladač řadiče."),
    0x19: ("BAD_POOL_HEADER", "poškozená paměť systému", "Ovladače a test RAM."),
    0x24: ("NTFS_FILE_SYSTEM", "chyba souborového systému NTFS", "Kontrola disku (jen čtení) a zdraví disku; zálohuj."),
    0xC000021A: ("WINLOGON_FATAL_ERROR", "selhal přihlašovací proces Windows", "Oprava při spuštění / obnovení systému."),
}


def parse_header(data: bytes) -> dict:
    """The fixed header of a Windows kernel dump. 64-bit: 'PAGE' 'DU64', build at 0x0C, stop code at 0x38, params from
    0x40; 32-bit: 'PAGE' 'DUMP', stop code at 0x20, params from 0x24."""
    if len(data) < 0x60 or data[:4] != b"PAGE":
        if data[:4] == b"MDMP":
            return {"error": "Tohle je výpis aplikace (MDMP), ne modré obrazovky."}
        return {"error": "Soubor není výpis pádu Windows."}
    kind = data[4:8]
    if kind == b"DU64":
        build = struct.unpack_from("<I", data, 0x0C)[0]
        code = struct.unpack_from("<I", data, 0x38)[0]
        params = list(struct.unpack_from("<4Q", data, 0x40))
        bits = 64
    elif kind == b"DUMP":
        build = struct.unpack_from("<I", data, 0x0C)[0]
        code = struct.unpack_from("<I", data, 0x20)[0]
        params = list(struct.unpack_from("<4I", data, 0x24))
        bits = 32
    else:
        return {"error": "Neznámý druh výpisu."}
    name, meaning, fix = BUGCHECKS.get(code, ("", "", ""))
    return {"code": f"0x{code:08X}", "code_int": code, "name": name or "neznámý kód", "meaning": meaning, "fix": fix,
            "params": [f"0x{p:X}" for p in params], "build": build, "bits": bits}


DRIVER_RX = re.compile(rb"((?:[A-Za-z0-9_\-]\x00){2,40}\.\x00[sS]\x00[yY]\x00[sS]\x00)")
CORE = {"ntoskrnl.exe", "hal.dll", "ntkrnlmp.exe", "ci.dll", "clfs.sys", "tm.sys", "pshed.dll", "kdcom.dll", "fltmgr.sys",
        "ksecdd.sys", "cng.sys", "wdf01000.sys", "acpi.sys", "msrpc.sys", "ntfs.sys", "storport.sys", "classpnp.sys", "disk.sys"}


def drivers_in(data: bytes, limit: int = 40) -> list[str]:
    """Third-party driver names present in the dump (from the module lists), core Windows ones left out."""
    seen: list[str] = []
    for m in DRIVER_RX.finditer(data):
        n = m.group(1).decode("utf-16-le", errors="ignore").lower()
        if n not in CORE and n not in seen:
            seen.append(n)
        if len(seen) >= limit:
            break
    return seen


def analyze(path: Path) -> dict:
    p = Path(path)
    try:
        data = p.read_bytes()
    except PermissionError:
        return {"file": p.name, "error": "Výpis smí číst jen správce – spusť JARVIS jako správce."}
    except OSError as e:
        return {"file": p.name, "error": str(e)[:200]}
    r = parse_header(data)
    r.update(file=p.name, time=dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"), bytes=len(data))
    if "error" not in r:
        r["drivers"] = drivers_in(data)
    return r


def dump_folder() -> Path:
    import os

    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Minidump"


def recent(folder: Path | None = None, limit: int = 10) -> list[dict]:
    folder = folder or dump_folder()
    if sys.platform != "win32" and folder == dump_folder():
        return []
    try:
        files = sorted(folder.glob("*.dmp"), key=lambda q: q.stat().st_mtime, reverse=True)[:limit]
    except PermissionError:
        return [{"file": str(folder), "error": "Složku s výpisy smí číst jen správce – spusť JARVIS jako správce."}]
    except OSError:
        return []
    return [analyze(f) for f in files]


def summary(items: list[dict]) -> str:
    ok = [x for x in items if "error" not in x]
    if not items:
        return "Žádné výpisy pádů – Windows od poslední doby modrou obrazovku nezaznamenal."
    if not ok:
        return items[0]["error"]
    counts: dict[str, int] = {}
    for x in ok:
        counts[x["name"]] = counts.get(x["name"], 0) + 1
    top = max(counts, key=counts.get)
    first = next(x for x in ok if x["name"] == top)
    txt = f"{len(ok)} výpisů pádů; nejčastěji {top} ({counts[top]}×) – {first['meaning'] or 'kód ' + first['code']}."
    if first["fix"]:
        txt += f" Co udělat: {first['fix']}"
    if len(counts) > 2:
        txt += " Různé druhy pádů najednou často znamenají hardware (RAM, napájení, přehřátí)."
    return txt
