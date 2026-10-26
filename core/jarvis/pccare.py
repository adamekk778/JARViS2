"""OMEGA §02 / §03 / §25 / §26 looking after the PC: which services depend on which (and what a stopped one breaks),
drivers installed lately next to the crashes that started after them (and whether the old driver is still there to go
back to), the power plan and battery, a recovery-media checklist, smooth or stuttering frames in a game log, how fast
an app opens, priority profiles for processes, keeping the window layout over a restart, and noticing an app that
keeps crashing. Every probe here only reads; changes (power plan, priorities, launching an app) are separate tools."""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Callable

from .comms import fold
from .pcreport import run_quiet

CARE_PS = {
    "services": r"""
T 'services' { @(Get-Service -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Display = $_.DisplayName; Status = "$($_.Status)";
  Start = "$($_.StartType)"; Requires = @($_.ServicesDependedOn | ForEach-Object { $_.Name }) } }) }
""",
    "drivers": r"""
T 'installed' { @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-UserPnp'; Id=20001,20003; StartTime=(Get-Date).AddDays(-90)} -MaxEvents 300 -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ Time = $_.TimeCreated.ToString('s'); Id = $_.Id; Text = ($_.Message -replace "`r?`n", ' ') } }) }
T 'signed' { @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction Stop | Where-Object { $_.DeviceName } | ForEach-Object {
  [pscustomobject]@{ Device = $_.DeviceName; Class = "$($_.DeviceClass)"; Version = "$($_.DriverVersion)"; Inf = "$($_.InfName)"; Provider = "$($_.DriverProviderName)";
    Date = $(if ($_.DriverDate) { ([datetime]$_.DriverDate).ToString('yyyy-MM-dd') } else { '' }); Id = "$($_.DeviceID)" } }) }
T 'crashes' { @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008; StartTime=(Get-Date).AddDays(-90)} -MaxEvents 200 -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ Time = $_.TimeCreated.ToString('s'); Id = $_.Id; Provider = $_.ProviderName } }) }
T 'store' { (pnputil /enum-drivers) -join "`n" }
""",
    "recovery": r"""
T 'usb' { @(Get-CimInstance Win32_DiskDrive -ErrorAction Stop | Where-Object { $_.InterfaceType -eq 'USB' } | ForEach-Object { [pscustomobject]@{ Model = $_.Model; GB = [math]::Round($_.Size / 1GB, 1) } }) }
T 'recovery_partition' { @(Get-Partition -ErrorAction Stop | Where-Object { $_.GptType -eq '{de94bba4-06d1-4d40-a16a-bfd50179d6ac}' -or $_.Type -eq 'Recovery' } | ForEach-Object { [pscustomobject]@{ Disk = $_.DiskNumber; GB = [math]::Round($_.Size / 1GB, 2) } }) }
T 'bitlocker' { (New-Object -ComObject Shell.Application).NameSpace($env:SystemDrive + '\').Self.ExtendedProperty('System.Volume.BitLockerProtection') }
T 'system_free_gb' { [math]::Round((Get-PSDrive ($env:SystemDrive.TrimEnd(':'))).Free / 1GB, 1) }
T 'os' { (Get-CimInstance Win32_OperatingSystem).Caption }
""",
}


def probe(name: str, runner: Callable[[list[str], float], tuple] = run_quiet) -> dict:
    from .rescue import PS_HEAD, PS_TAIL

    if sys.platform != "win32" and runner is run_quiet:
        raise ValueError("Tahle diagnostika je jen pro Windows.")
    enc = base64.b64encode((PS_HEAD + CARE_PS[name] + PS_TAIL).encode("utf-16-le")).decode()
    code, out, _err = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], 120)
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


# ============================================================================================== 23 service dependencies
def services_graph(data: dict, focus: str = "") -> dict:
    """Which services need which; automatic services that are stopped and what they leave broken; for `focus`, what
    it needs and what needs it (directly and further down)."""
    svc = {s["Name"]: s for s in L(data.get("services"))}
    needed_by: dict[str, set] = defaultdict(set)
    for s in svc.values():
        for r in L(s.get("Requires")):
            needed_by[r].add(s["Name"])

    def all_dependents(n: str) -> set:
        out, todo = set(), [n]
        while todo:
            for d in needed_by.get(todo.pop(), ()):
                if d not in out:
                    out.add(d)
                    todo.append(d)
        return out
    stopped_auto = [s for s in svc.values() if s.get("Start") == "Automatic" and s.get("Status") != "Running"]
    broken = []
    for s in stopped_auto:
        hit = sorted(d for d in all_dependents(s["Name"]) if svc.get(d, {}).get("Start") == "Automatic")
        broken.append({"service": s["Name"], "display": s.get("Display"), "breaks": hit})
    res: dict[str, Any] = {"services": len(svc), "stopped_automatic": broken,
                           "most_needed": [{"service": n, "display": svc.get(n, {}).get("Display"), "dependents": len(all_dependents(n))}
                                           for n in sorted(needed_by, key=lambda n: -len(all_dependents(n)))[:8]]}
    if focus:
        f = fold(focus)
        hit = next((n for n, s in svc.items() if fold(n) == f or fold(s.get("Display") or "") == f), None) or \
            next((n for n, s in svc.items() if f in fold(n) or f in fold(s.get("Display") or "")), None)
        if not hit:
            raise ValueError(f"Službu „{focus}“ nevidím.")
        needs, todo = [], list(L(svc[hit].get("Requires")))
        while todo:
            n = todo.pop(0)
            if n not in needs:
                needs.append(n)
                todo += L(svc.get(n, {}).get("Requires"))
        res["focus"] = {"service": hit, "display": svc[hit].get("Display"), "status": svc[hit].get("Status"), "needs": needs,
                        "needs_not_running": [n for n in needs if svc.get(n, {}).get("Status") != "Running"],
                        "needed_by": sorted(needed_by.get(hit, ())), "all_dependents": sorted(all_dependents(hit))}
    return res


# ============================================================================================== 287 driver rollback
def parse_store(text: str) -> list[dict]:
    """`pnputil /enum-drivers` → packages. Labels are localised, so the fields are read by position: published
    name, original name, provider, class, class GUID, (extension id …), "date version", signer."""
    out = []
    for block in re.split(r"\n\s*\n", text or ""):
        vals = [ln.split(":", 1)[1].strip() for ln in block.splitlines() if ":" in ln]
        if len(vals) < 6 or not vals[0].lower().startswith("oem"):
            continue
        ver = next((v for v in vals if re.match(r"\d{1,2}/\d{1,2}/\d{4}\s+\S+", v)), "")
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\S+)", ver)
        out.append({"published": vals[0], "original": vals[1].lower(), "provider": vals[2], "class": vals[3],
                    "date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else "", "version": m.group(4) if m else ""})
    return out


def _vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.]", v or "0"))


def driver_suspects(data: dict, days_before: int = 30, now: dt.datetime | None = None) -> dict:
    """Drivers installed in the last 90 days; for each, the system crashes in the 30 days before vs after the
    installation; whether an older version of the same package is still in the driver store (rollback possible)."""
    installs = []
    for e in L(data.get("installed")):
        try:
            t = dt.datetime.fromisoformat(str(e["Time"])[:19])
        except (ValueError, KeyError):
            continue
        inf = re.search(r"([\w\-.]+\.inf)", e.get("Text") or "", re.I)
        dev = re.search(r"(?:Device Instance ID|ID instance zařízení|instance zařízení)\s*([^\s]+)", e.get("Text") or "", re.I)
        installs.append({"time": t, "inf": inf.group(1).lower() if inf else "", "device_id": dev.group(1) if dev else "", "text": (e.get("Text") or "")[:200]})
    crashes = []
    for c in L(data.get("crashes")):
        try:
            crashes.append(dt.datetime.fromisoformat(str(c["Time"])[:19]))
        except (ValueError, KeyError):
            pass
    store = parse_store(data.get("store") if isinstance(data.get("store"), str) else "")
    by_orig = defaultdict(list)
    by_pub = {}
    for s in store:
        by_orig[s["original"]].append(s)
        by_pub[s["published"].lower()] = s
    signed = L(data.get("signed"))
    out = []
    seen = set()
    for ins in sorted(installs, key=lambda x: x["time"], reverse=True):
        dev = next((s for s in signed if ins["device_id"] and s.get("Id", "").lower() == ins["device_id"].lower()), None) or \
            next((s for s in signed if ins["inf"] and s.get("Inf", "").lower() == ins["inf"]), None)
        name = (dev or {}).get("Device") or ins["device_id"] or ins["inf"] or "zařízení"
        if name in seen:
            continue
        seen.add(name)
        before = sum(1 for c in crashes if ins["time"] - dt.timedelta(days=days_before) <= c < ins["time"])
        after = sum(1 for c in crashes if ins["time"] <= c <= ins["time"] + dt.timedelta(days=days_before))
        pkg = by_pub.get(((dev or {}).get("Inf") or ins["inf"]).lower())
        older = []
        if pkg:
            older = sorted([s for s in by_orig[pkg["original"]] if _vkey(s["version"]) < _vkey(pkg["version"])], key=lambda s: _vkey(s["version"]), reverse=True)
        suspect = after >= 2 and after > 2 * before
        out.append({"device": name, "class": (dev or {}).get("Class"), "installed": ins["time"].strftime("%Y-%m-%d %H:%M"),
                    "version": (dev or {}).get("Version") or (pkg or {}).get("version"), "crashes_before": before, "crashes_after": after,
                    "suspect": suspect, "older_in_store": [f"{s['version']} ({s['date']})" for s in older[:3]], "can_roll_back": bool(older)})
    out.sort(key=lambda x: (not x["suspect"], -x["crashes_after"]))
    steps = ["Win + X → Správce zařízení", "najdi zařízení → pravým → Vlastnosti → karta Ovladač", "„Vrátit změny ovladače“ (Roll Back Driver) → důvod → Ano",
             "restartuj a sleduj, jestli pády přestaly", "aktualizace Windows by ho mohla vrátit – ve Windows Update ho dočasně pozastav"]
    return {"drivers": out, "suspects": [d for d in out if d["suspect"]], "steps": steps, "crashes_90d": len(crashes)}


# ============================================================================================== 295 power plan
POWER_SETTINGS = {
    "cpu_min": ("54533251-82be-4824-96c1-47b60b740d00", "893dee8e-2bef-41e0-89c6-b55d0929964c"),
    "cpu_max": ("54533251-82be-4824-96c1-47b60b740d00", "bc5038f7-23e0-4960-96da-33abaf5935ec"),
    "sleep_after": ("238c9fa8-0aad-41ed-83f4-97be242c8f20", "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"),
    "hibernate_after": ("238c9fa8-0aad-41ed-83f4-97be242c8f20", "9d7815a6-7ee4-497e-8888-515a05f02364"),
    "display_off": ("7516b95f-f776-4464-8c53-06167f40cc99", "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"),
    "usb_suspend": ("2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"),
    "pcie_aspm": ("501a4d13-42af-4429-9fd1-a8218c268e20", "ee12f906-d277-404b-b6da-e5fa1a576df5"),
}


def parse_plans(text: str) -> list[dict]:
    """`powercfg /list` → [{guid, name, active}] (the active one is marked with *)."""
    out = []
    for ln in (text or "").splitlines():
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*\(([^)]*)\)\s*(\*)?", ln, re.I)
        if m:
            out.append({"guid": m.group(1).lower(), "name": m.group(2).strip(), "active": bool(m.group(3))})
    return out


def parse_query(text: str) -> tuple[int | None, int | None]:
    """`powercfg /query … sub setting` → (on mains, on battery): the last two hex values are the current indexes."""
    vals = re.findall(r"0x([0-9a-fA-F]+)\s*$", text or "", re.M)
    if len(vals) < 2:
        return None, None
    return int(vals[-2], 16), int(vals[-1], 16)


def parse_battery_xml(xml: str) -> dict | None:
    d = re.search(r"<DesignCapacity>(\d+)</DesignCapacity>", xml or "")
    f = re.search(r"<FullChargeCapacity>(\d+)</FullChargeCapacity>", xml or "")
    c = re.search(r"<CycleCount>(\d+)</CycleCount>", xml or "")
    if not d or not f or int(d.group(1)) == 0:
        return None
    return {"design_mwh": int(d.group(1)), "full_mwh": int(f.group(1)), "health_pct": round(100 * int(f.group(1)) / int(d.group(1)), 1),
            "cycles": int(c.group(1)) if c else None}


def power_state(runner: Callable = run_quiet) -> dict:
    import os
    import tempfile

    code, out, _ = runner(["powercfg", "/list"], 20)
    plans = parse_plans(out)
    settings = {}
    for key, (sub, setting) in POWER_SETTINGS.items():
        _c, o, _e = runner(["powercfg", "/query", "SCHEME_CURRENT", sub, setting], 20)
        settings[key] = dict(zip(("ac", "dc"), parse_query(o)))
    battery = None
    path = os.path.join(tempfile.gettempdir(), f"jarvis-battery-{os.getpid()}.xml")
    try:
        c, _o, _e = runner(["powercfg", "/batteryreport", "/xml", "/output", path], 40)
        if c == 0 and os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                battery = parse_battery_xml(fh.read())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"plans": plans, "settings": settings, "battery": battery}


def power_advice(state: dict, on_battery_pc: bool | None = None) -> dict:
    s, plans = state["settings"], state["plans"]
    active = next((p for p in plans if p["active"]), None)
    laptop = state.get("battery") is not None if on_battery_pc is None else on_battery_pc
    tips = []
    cmax = (s.get("cpu_max") or {}).get("ac")
    if cmax is not None and cmax < 100:
        tips.append(f"v zásuvce je procesor omezený na {cmax} % výkonu – pro plný výkon nastav 100 %")
    cmin = (s.get("cpu_min") or {}).get("ac")
    if cmin is not None and cmin >= 100:
        tips.append("procesor nikdy nezpomalí (minimum 100 %) – zbytečně topí a bere proud")
    sl = s.get("sleep_after") or {}
    if laptop and sl.get("dc") == 0:
        tips.append("na baterii se notebook nikdy neuspí – vybije se v tašce")
    if (s.get("display_off") or {}).get("ac") == 0:
        tips.append("obrazovka se nikdy nevypne")
    if (s.get("usb_suspend") or {}).get("ac") == 1:
        tips.append("USB se smí uspávat – když odpadávají USB zařízení, vypni „Selektivní pozastavení USB“")
    b = state.get("battery")
    if b and b["health_pct"] < 70:
        tips.append(f"baterie má jen {b['health_pct']:g} % původní kapacity – zvaž výměnu")
    return {"active": active, "laptop": laptop, "tips": tips, "battery": b,
            "minutes": {k: {kk: (round(v / 60) if v is not None else None) for kk, v in (s.get(k) or {}).items()} for k in ("sleep_after", "display_off", "hibernate_after")}}


# ============================================================================================== 299 recovery media
def recovery_checklist(data: dict) -> dict:
    usb = L(data.get("usb"))
    big = [u for u in usb if (u.get("GB") or 0) >= 16]
    rp = data.get("recovery_partition")
    bl = data.get("bitlocker")
    items = []
    items.append({"item": "flash disk aspoň 16 GB", "ok": bool(big),
                  "note": f"připojený: {big[0]['Model']} ({big[0]['GB']:g} GB) – vše na něm se smaže" if big else
                  ("připojený je moc malý" if usb else "připoj prázdný USB disk 16 GB a víc")})
    if isinstance(rp, (list, dict)) and not (isinstance(rp, dict) and "error" in rp):
        items.append({"item": "obnovovací oddíl Windows (WinRE)", "ok": bool(L(rp)), "note": "je na disku" if L(rp) else "chybí – o to důležitější je záchranný disk"})
    else:
        items.append({"item": "obnovovací oddíl Windows (WinRE)", "ok": None, "note": "nejde zjistit bez práv správce"})
    if bl in (1, "1", 3, "3", 5, "5"):
        items.append({"item": "klíč pro obnovení BitLockeru", "ok": None,
                      "note": "disk je šifrovaný: bez 48místného klíče se z obnovy k datům nedostaneš – najdeš ho na account.microsoft.com/devices/recoverykey, vytiskni ho"})
    items.append({"item": "záloha dat", "ok": None, "note": "záchranný disk obnoví Windows, ne tvoje soubory – zálohu dělej zvlášť"})
    steps = ["připoj prázdný flash disk", "spusť „Vytvořit jednotku pro obnovení“ (RecoveryDrive.exe) – JARVIS ji otevře",
             "zaškrtni „Zálohovat systémové soubory na jednotku pro obnovení“", "počkej (30–60 min), disk označ a schovej"]
    return {"items": items, "ready": bool(big), "steps": steps, "os": data.get("os"), "free_gb": data.get("system_free_gb")}


# ============================================================================================== 306 frame times
def frame_times(header: list[str], rows: list[list[str]]) -> list[float]:
    from .science import column_nums

    h = [fold(x) for x in header]
    for names, conv in ((("msbetweenpresents", "ms between presents", "frametime", "frame time", "msbetweendisplaychange", "frametimes", "ms"), lambda v: v),
                        (("fps", "framerate"), lambda v: 1000 / v if v else None)):
        i = next((k for k, x in enumerate(h) for n in names if x == n or x.replace(" ", "") == n.replace(" ", "")), None)
        if i is not None:
            vals = [conv(v) if v else None for v in column_nums([r[i] if i < len(r) else "" for r in rows])]
            return [v for v in vals if v is not None and 0 < v < 5000]
    raise ValueError("V logu nevidím sloupec s časem snímku (MsBetweenPresents / FrameTime) ani FPS.")


def frame_report(ms: list[float], target_fps: float = 60) -> dict:
    """Frame times (ms) → average FPS, 1 % and 0.1 % lows (from the slowest frames), stutters (a frame over twice the
    median and over 25 ms), how even the pacing is, and the share of frames slower than the target."""
    if len(ms) < 20:
        raise ValueError("Na rozbor potřebuju aspoň 20 snímků.")
    s = sorted(ms)
    n = len(s)
    total = sum(ms)
    med = statistics.median(ms)

    def low(pct):
        k = max(1, int(math.ceil(n * pct / 100)))
        worst = s[-k:]
        return round(1000 / (sum(worst) / len(worst)), 1)
    stutters = [i for i, v in enumerate(ms) if v > 2 * med and v > 25]
    jitter = statistics.mean(abs(a - b) for a, b in zip(ms, ms[1:]))
    budget = 1000 / target_fps
    per_min = len(stutters) / (total / 60000)
    verdict = ("plynulé" if not stutters and low(1) >= 0.75 * (1000 * n / total) else
               "občas zasekne" if per_min <= 2 else "trhané")
    return {"frames": n, "seconds": round(total / 1000, 1), "avg_fps": round(1000 * n / total, 1), "low_1pct_fps": low(1), "low_01pct_fps": low(0.1),
            "median_ms": round(med, 2), "p99_ms": round(s[min(n - 1, int(n * 0.99))], 2), "max_ms": round(s[-1], 2), "stutters": len(stutters),
            "stutter_at_s": [round(sum(ms[:i]) / 1000, 1) for i in stutters[:10]], "stutters_per_min": round(per_min, 1), "jitter_ms": round(jitter, 2),
            "over_budget_pct": round(100 * sum(1 for v in ms if v > budget) / n, 1), "verdict": verdict}


# ============================================================================================== 308 launch time
def measure_launch(platform, target: str, runs: int = 3, timeout: float = 30, close: bool = True, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Start the app, time until its window shows, close what was started; several runs (the first one is cold)."""
    import os
    import subprocess

    import psutil

    exe = os.path.basename(target).lower()
    stem = exe.removesuffix(".exe")
    times, errors = [], []
    for k in range(runs):
        before = {w.get("hwnd") for w in platform.window_layout()}
        wall0 = time.time()
        t0 = clock()
        try:
            proc = subprocess.Popen([target], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError as e:
            raise ValueError(f"„{target}“ nejde spustit: {e}") from e
        shown = None
        while clock() - t0 < timeout:
            for w in platform.window_layout():
                if w.get("hwnd") in before:
                    continue
                name = os.path.basename(str(w.get("path") or w.get("exe") or "")).lower()
                if name == exe or name.removesuffix(".exe") == stem:
                    shown = w
                    break
            if shown:
                break
            sleep(0.05)
        if shown is None:
            errors.append(f"běh {k + 1}: okno se do {timeout:g} s neukázalo")
        else:
            times.append(round(clock() - t0, 3))
        if close:      # only what this run started: the process itself and same-named ones born after the start
            for p in psutil.process_iter(["pid", "name", "create_time"]):
                try:
                    pname = (p.info["name"] or "").lower()
                    if p.pid == proc.pid or ((pname == exe or pname.removesuffix(".exe") == stem) and p.info["create_time"] >= wall0 - 0.5):
                        p.terminate()
                        p.wait(5)
                except (psutil.Error, OSError):
                    pass
        sleep(1.0)
    if not times:
        raise ValueError("; ".join(errors) or "Měření selhalo.")
    return {"app": exe, "runs": times, "cold_s": times[0], "warm_s": round(statistics.median(times[1:]), 3) if len(times) > 1 else None,
            "errors": errors, "verdict": "rychlé" if times[-1] < 1.5 else "průměrné" if times[-1] < 4 else "pomalé"}


# ============================================================================================== 310 priority profiles
PROFILES = {
    "hra": {"boost": [], "lower": ["onedrive", "dropbox", "googledrivefs", "teams", "ms-teams", "slack", "discord", "steamwebhelper", "epicwebhelper",
                                   "searchindexer", "msedgewebview2", "adobe", "creative cloud", "spotify"],
            "note": "hra dostane přednost; synchronizace a pomocníci jdou dozadu"},
    "práce": {"boost": [], "lower": ["steam", "epicgameslauncher", "battle.net", "origin", "ubisoft", "riotclient", "galaxyclient"],
              "note": "herní spouštěče do pozadí"},
    "tichý": {"boost": [], "lower": ["chrome", "msedge", "firefox", "onedrive", "teams", "slack", "discord", "spotify", "steam", "steamwebhelper"],
              "note": "méně zátěže = tišší ventilátory"},
}


def _levels():
    import psutil

    if sys.platform == "win32":
        return {"low": psutil.BELOW_NORMAL_PRIORITY_CLASS, "normal": psutil.NORMAL_PRIORITY_CLASS, "high": psutil.ABOVE_NORMAL_PRIORITY_CLASS}
    return {"low": 10, "normal": 0, "high": -5}


def apply_profile(name: str, boost: list[str] | None = None, lower: list[str] | None = None, saved: dict | None = None) -> dict:
    """Lower (and raise) the priority of matching processes of this user. Remembers each process's previous priority
    in `saved` so `restore_profile` puts exactly that back."""
    import getpass

    import psutil

    prof = PROFILES.get(name, {"boost": [], "lower": []})
    up = [fold(x) for x in (boost or []) + prof["boost"]]
    down = [fold(x) for x in (lower or []) + prof["lower"]]
    lv = _levels()
    me = getpass.getuser().lower()
    saved = saved if saved is not None else {}
    changed, denied = [], []
    for p in psutil.process_iter(["pid", "name", "username"]):
        try:
            pname = fold(p.info["name"] or "").removesuffix(".exe")
            user = (p.info["username"] or "").lower().split("\\")[-1]
            if not pname or user != me or p.pid == psutil.Process().pid:
                continue
            target = "high" if any(u and u in pname for u in up) else "low" if any(d and d in pname for d in down) else None
            if not target:
                continue
            key = str(p.pid)
            if key not in saved:
                saved[key] = {"name": p.info["name"], "nice": p.nice(), "created": p.create_time()}
            p.nice(lv[target])
            changed.append({"pid": p.pid, "name": p.info["name"], "to": target})
        except psutil.AccessDenied:
            denied.append(p.info.get("name"))
        except (psutil.Error, OSError):
            continue
    return {"profile": name, "changed": changed, "denied": sorted({d for d in denied if d}), "saved": saved}


def restore_profile(saved: dict) -> dict:
    import psutil

    back, gone = [], 0
    for pid, s in list(saved.items()):
        try:
            p = psutil.Process(int(pid))
            if abs(p.create_time() - s["created"]) > 1:              # the pid was reused by another program
                gone += 1
                continue
            p.nice(s["nice"])
            back.append(s["name"])
        except (psutil.Error, OSError):
            gone += 1
    saved.clear()
    return {"restored": back, "ended": gone}


# ============================================================================================== 31 layout over a restart
AUTO = "Před vypnutím"


def autosave_layout(rt) -> bool:
    from . import workspace

    wins = [w for w in rt.platform.window_layout() if w.get("path") or w.get("exe")]
    if len(wins) < 2:
        return False
    workspace.save(rt, AUTO)
    return True


def restore_offer(rt, boot_time: float | None = None) -> dict | None:
    """After a restart: the layout saved before it, if it is newer than a week and older than the boot."""
    import psutil

    from . import workspace

    ws = workspace.get(rt, AUTO)
    if not ws:
        return None
    boot = boot_time if boot_time is not None else psutil.boot_time()
    if ws["updated"] >= boot or time.time() - ws["updated"] > 7 * 86400:
        return None
    told = rt.db.one("SELECT v FROM kv WHERE k='layout_offer'")
    if told and told["v"] == str(int(boot)):                 # offered once after this boot
        return None
    rt.db.exec("INSERT INTO kv VALUES ('layout_offer', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(int(boot)),))
    apps = sorted({w.get("app") or w.get("exe") or "" for w in ws["windows"]} - {""})
    return {"name": AUTO, "apps": apps, "saved": time.strftime("%d. %m. %H:%M", time.localtime(ws["updated"]))}


# ============================================================================================== 32 repeated crashes
def repeated_crashes(app_errors: list[dict], hours: int = 24, threshold: int = 3, now: float | None = None) -> list[dict]:
    now = now or time.time()
    c: Counter = Counter()
    mods: dict[str, Counter] = defaultdict(Counter)
    for e in app_errors:
        try:
            ts = dt.datetime.fromisoformat(str(e.get("Time"))[:19]).timestamp()
        except ValueError:
            continue
        if now - ts <= hours * 3600 and e.get("App"):
            c[e["App"]] += 1
            mods[e["App"]][e.get("Module") or "?"] += 1
    return [{"app": a, "count": n, "module": mods[a].most_common(1)[0][0]} for a, n in c.most_common() if n >= threshold]


def offer_crash_help(rt, app_errors: list[dict], now: float | None = None) -> list[dict]:
    """A program crashed 3× today → offer help once a day per program (notification, nothing is done by itself)."""
    hits = repeated_crashes(app_errors, now=now)
    day = dt.date.fromtimestamp(now or time.time()).isoformat()
    row = rt.db.one("SELECT v FROM kv WHERE k='crash_offers'")
    told = json.loads(row["v"]) if row else {}
    fresh = [h for h in hits if told.get(h["app"]) != day]
    for h in fresh:
        told[h["app"]] = day
        mod = f" (pokaždé v {h['module']})" if h["module"] not in ("?", h["app"]) else ""
        rt.notify("Program opakovaně padá", f"{h['app']} dnes spadl {h['count']}×{mod}. Mám zjistit proč? Řekni „proč padá {h['app'].removesuffix('.exe')}“.",
                  speak=False)
    rt.db.exec("INSERT INTO kv VALUES ('crash_offers', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(told),))
    return fresh
