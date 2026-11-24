"""3.14 Ovládání PC+ (návrhy 81–83, 86–90).

- what takes the disk, as a map of rectangles (a squarified treemap, SVG) – the biggest folders at a glance
- programs installed / removed through winget: a preview of the exact package first, everything JARVIS installed
  is remembered and can be removed again ("vrať, co jsi nainstaloval")
- Windows services: start type changed only with its previous value remembered → "vrať službu"
- before / after: a baseline of the PC (startup programs, memory in use when idle, free disk, processes) saved
  before an optimisation and compared after it – proof that it helped (or that it did not)
- the graphics driver: its version and age, and the vendor's page when it is older than half a year (never
  downloads or installs anything by itself)
- devices with a problem and the resources (IRQ, memory, I/O) they share – the conflict map
- live FPS while playing: PresentMon (when installed) for the game's process → a live pill in the notch
- a project with its own window layout: switching to the project restores it
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)
WIN = sys.platform == "win32"
Runner = Callable[[list[str], int], subprocess.CompletedProcess]


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ps(script: str, timeout: int = 40, runner: Runner | None = None) -> Any:
    out = (runner or _run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    txt = (out.stdout or "").strip()
    try:
        return json.loads(txt) if txt else None
    except ValueError:
        return None


# ---------- 89: the disk as a map ----------
def folder_sizes(root: str | Path, max_entries: int = 40, time_limit: float = 20.0) -> list[dict]:
    """Sizes of the direct children of `root` (files and folders, recursively summed), biggest first."""
    root = Path(root)
    deadline = time.monotonic() + time_limit
    out: list[dict[str, Any]] = []

    def size_of(p: Path) -> int:
        total = 0
        stack = [p]
        while stack and time.monotonic() < deadline:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if e.is_symlink():
                                continue
                            if e.is_dir(follow_symlinks=False):
                                stack.append(Path(e.path))
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        return total

    try:
        children = list(os.scandir(root))
    except OSError as err:
        raise ValueError(f"složku nejde přečíst: {err}") from err
    for ch in children:
        try:
            if ch.is_symlink():
                continue
            s = size_of(Path(ch.path)) if ch.is_dir(follow_symlinks=False) else ch.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        out.append({"name": ch.name, "path": ch.path, "bytes": s, "dir": ch.is_dir(follow_symlinks=False)})
    out.sort(key=lambda x: -int(x["bytes"]))
    return out[:max_entries]


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap rectangles (Bruls et al.) for values sorted biggest first."""
    rects: list[tuple[float, float, float, float]] = []
    vals = [v for v in values if v > 0]
    total = sum(vals)
    if not vals or w <= 0 or h <= 0:
        return rects
    scale = w * h / total
    areas = [v * scale for v in vals]

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row)

    def lay(row: list[float], x: float, y: float, w: float, h: float):
        s = sum(row)
        if w >= h:                     # a column on the left
            cw = s / h
            yy = y
            for r in row:
                rects.append((x, yy, cw, r / cw))
                yy += r / cw
            return x + cw, y, w - cw, h
        rh = s / w                     # a row on the top
        xx = x
        for r in row:
            rects.append((xx, y, r / rh, rh))
            xx += r / rh
        return x, y + rh, w, h - rh

    row: list[float] = []
    i = 0
    while i < len(areas):
        side = min(w, h)
        a = areas[i]
        if not row or worst(row + [a], side) <= worst(row, side):
            row.append(a)
            i += 1
        else:
            x, y, w, h = lay(row, x, y, w, h)
            row = []
    if row:
        lay(row, x, y, w, h)
    return rects


def human(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "kB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


COLORS = ["#4f8dff", "#3ddc97", "#ffb547", "#ff5d63", "#a78bfa", "#2ee6ff", "#f472b6", "#94a3b8"]


def treemap_svg(items: list[dict], title: str = "", width: int = 960, height: int = 600) -> str:
    rects = squarify([float(i["bytes"]) for i in items], 0, 30, width, height - 30)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Segoe UI, sans-serif">',
             f'<rect width="{width}" height="{height}" fill="#0b0d14"/>',
             f'<text x="10" y="20" fill="#e9eef3" font-size="15" font-weight="600">{escape(title)}</text>']
    for k, (it, (x, y, w, h)) in enumerate(zip([i for i in items if i["bytes"] > 0], rects)):
        c = COLORS[k % len(COLORS)]
        parts.append(f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{max(0, w - 2):.1f}" height="{max(0, h - 2):.1f}" rx="6" '
                     f'fill="{c}" fill-opacity="0.82"><title>{escape(it["name"])} – {human(it["bytes"])}</title></rect>')
        if w > 70 and h > 34:
            parts.append(f'<text x="{x + 8:.1f}" y="{y + 20:.1f}" fill="#0b0d14" font-size="13" font-weight="600">'
                         f'{escape(it["name"][:int(w / 8)])}</text>')
            parts.append(f'<text x="{x + 8:.1f}" y="{y + 36:.1f}" fill="#0b0d14" font-size="12">{human(it["bytes"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------- 82: winget with a ledger ----------
def parse_winget_search(text: str) -> list[dict]:
    """`winget search` table → [{name, id, version, source}] (columns found from the header line)."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    head = next((i for i, ln in enumerate(lines) if re.search(r"\bId\b", ln) and re.search(r"\bVer", ln)), -1)
    if head < 0:
        return []
    h = lines[head]
    cols = [m.start() for m in re.finditer(r"\S+", h)]
    names = re.findall(r"\S+", h)
    out = []
    for ln in lines[head + 2:]:
        if not ln.strip() or set(ln.strip()) <= set("-"):
            continue
        cells = []
        for j, start in enumerate(cols):
            end = cols[j + 1] if j + 1 < len(cols) else len(ln)
            cells.append(ln[start:end].strip())
        row = dict(zip([n.lower() for n in names], cells))
        if row.get("id"):
            out.append({"name": row.get("name", ""), "id": row["id"], "version": row.get("version", ""),
                        "source": row.get("source", "")})
    return out


LEDGER = "winget_installed"


def ledger(rt: Any) -> list[dict]:
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (LEDGER,))
    try:
        return json.loads(row["v"]) if row else []
    except ValueError:
        return []


def _save_ledger(rt: Any, items: list[dict]) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (LEDGER, json.dumps(items[-100:], ensure_ascii=False)))


def winget(args: list[str], runner: Runner | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    if not WIN and runner is None:
        raise RuntimeError("winget je jen ve Windows")
    return (runner or _run)(["winget", *args, "--disable-interactivity"], timeout)


def install(rt: Any, pkg_id: str, runner: Runner | None = None) -> dict:
    r = winget(["install", "--id", pkg_id, "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"],
               runner)
    ok = r.returncode == 0
    if ok:
        _save_ledger(rt, [x for x in ledger(rt) if x["id"] != pkg_id] + [{"id": pkg_id, "ts": time.time()}])
    return {"ok": ok, "output": ((r.stdout or "") + (r.stderr or ""))[-600:]}


def uninstall(rt: Any, pkg_id: str, runner: Runner | None = None) -> dict:
    r = winget(["uninstall", "--id", pkg_id, "--exact", "--silent"], runner)
    ok = r.returncode == 0
    if ok:
        _save_ledger(rt, [x for x in ledger(rt) if x["id"] != pkg_id])
    return {"ok": ok, "output": ((r.stdout or "") + (r.stderr or ""))[-600:]}


# ---------- 83: services with their previous start type ----------
SVC_LEDGER = "services_changed"
START_TYPES = ("Automatic", "Manual", "Disabled")
PROTECTED = {"windefend", "wuauserv", "eventlog", "rpcss", "lsm", "samss", "winmgmt", "bfe", "mpssvc", "cryptsvc",
             "dhcp", "dnscache", "nsi", "power", "profsvc", "schedule", "sense", "wscsvc", "securityhealthservice"}


def service_state(name: str, runner: Runner | None = None) -> dict | None:
    d = _ps(f"Get-Service -Name '{name.replace(chr(39), '')}' -ErrorAction Stop | Select-Object Name,DisplayName,Status,"
            "@{n='StartType';e={$_.StartType.ToString()}} | ConvertTo-Json -Compress", runner=runner)
    return d if isinstance(d, dict) else None


def set_service(rt: Any, name: str, start_type: str, runner: Runner | None = None) -> dict:
    if start_type not in START_TYPES:
        raise ValueError(f"typ spuštění musí být jeden z {', '.join(START_TYPES)}")
    if name.lower() in PROTECTED:
        raise ValueError(f"službu {name} JARVIS nemění – drží zabezpečení nebo chod Windows")
    cur = service_state(name, runner)
    if not cur:
        raise ValueError(f"službu {name} jsem nenašel")
    prev = str(cur.get("StartType", ""))
    (runner or _run)(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                      f"Set-Service -Name '{cur['Name']}' -StartupType {start_type}"], 60)
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (SVC_LEDGER,))
    led = json.loads(row["v"]) if row else {}
    led.setdefault(cur["Name"], prev)                    # the ORIGINAL value stays, even after several changes
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (SVC_LEDGER, json.dumps(led)))
    return {"name": cur["Name"], "was": prev, "now": start_type}


def revert_service(rt: Any, name: str, runner: Runner | None = None) -> dict:
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (SVC_LEDGER,))
    led = json.loads(row["v"]) if row else {}
    key = next((k for k in led if k.lower() == name.lower()), None)
    if not key:
        raise ValueError(f"u služby {name} jsem nic neměnil")
    (runner or _run)(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                      f"Set-Service -Name '{key}' -StartupType {led[key]}"], 60)
    led.pop(key)
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (SVC_LEDGER, json.dumps(led)))
    return {"name": key, "now": led.get(key, "") or "původní"}


# ---------- 86: before / after ----------
def snapshot(rt: Any) -> dict:
    import psutil

    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(Path.home().anchor or "/"))
    procs = len(psutil.pids())
    startup = 0
    try:
        from .tools import REGISTRY  # noqa: F401 – startup apps are counted where the platform offers it
        sa = rt.platform.startup_apps() if hasattr(rt.platform, "startup_apps") else []
        startup = len(sa or [])
    except Exception:  # noqa: BLE001
        startup = 0
    return {"ts": time.time(), "ram_used_pct": round(vm.percent, 1), "ram_used_gb": round((vm.total - vm.available) / 2**30, 2),
            "disk_free_gb": round(du.free / 2**30, 1), "processes": procs, "startup_apps": startup,
            "boot_s": round(time.time() - psutil.boot_time())}


def save_baseline(rt: Any, label: str = "") -> dict:
    snap = {**snapshot(rt), "label": label[:60]}
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('pc_baseline', ?)", (json.dumps(snap),))
    return snap


def compare(rt: Any) -> dict:
    row = rt.db.one("SELECT v FROM kv WHERE k='pc_baseline'")
    if not row:
        raise ValueError("nejdřív ulož stav před změnou (pc_baseline)")
    before = json.loads(row["v"])
    after = snapshot(rt)
    better = {"ram_used_pct": -1, "ram_used_gb": -1, "disk_free_gb": 1, "processes": -1, "startup_apps": -1}
    rows = []
    for k, sign in better.items():
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            d = round(a - b, 2)
            rows.append({"what": k, "before": b, "after": a, "delta": d, "better": (d * sign) > 0, "same": d == 0})
    return {"before": before, "after": after, "rows": rows, "label": before.get("label", "")}


# ---------- 87: the graphics driver ----------
VENDOR_PAGE = {"nvidia": "https://www.nvidia.com/Download/index.aspx", "amd": "https://www.amd.com/en/support/download/drivers.html",
               "radeon": "https://www.amd.com/en/support/download/drivers.html",
               "intel": "https://www.intel.com/content/www/us/en/support/detect.html"}


def gpu_drivers(runner: Runner | None = None, now: float | None = None) -> list[dict]:
    d = _ps("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,"
            "@{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}} | ConvertTo-Json -Compress", runner=runner)
    rows = d if isinstance(d, list) else [d] if isinstance(d, dict) else []
    out = []
    for r in rows:
        name = str(r.get("Name") or "")
        if not name or "basic display" in name.lower() or "remote" in name.lower():
            continue
        age = None
        try:
            import datetime as dt

            age = (dt.datetime.fromtimestamp(now or time.time()) - dt.datetime.strptime(str(r.get("DriverDate")), "%Y-%m-%d")).days
        except (ValueError, TypeError):
            pass
        vendor = next((v for v in VENDOR_PAGE if v in name.lower()), "")
        out.append({"name": name, "version": r.get("DriverVersion"), "date": r.get("DriverDate"), "age_days": age,
                    "old": bool(age and age > 183), "page": VENDOR_PAGE.get(vendor, "")})
    return out


# ---------- 88: the conflict map ----------
CONFLICT_PS = r"""
$bad = Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } |
  Select-Object Name, DeviceID, ConfigManagerErrorCode
$alloc = Get-CimInstance Win32_PnPAllocatedResource | ForEach-Object {
  @{ dev = ($_.Dependent.DeviceID); res = ($_.Antecedent.CimClass.CimClassName + ':' + (
      $_.Antecedent.IRQNumber, $_.Antecedent.StartingAddress, $_.Antecedent.Name | Where-Object { $_ } | Select-Object -First 1)) } }
@{ bad = @($bad); alloc = @($alloc) } | ConvertTo-Json -Depth 4 -Compress
"""
CM_ERRORS = {1: "není správně nastavené", 3: "ovladač je poškozený nebo chybí paměť", 10: "nejde spustit", 12: "nemá dost volných "
             "prostředků (konflikt)", 14: "potřebuje restart", 18: "ovladač je potřeba přeinstalovat", 22: "je vypnuté", 24: "chybí nebo "
             "není připojené", 28: "nemá ovladač", 31: "ovladač nejde načíst", 43: "Windows ho zastavil (hlásí chybu)", 45: "není připojené"}


def conflicts(runner: Runner | None = None) -> dict:
    d = _ps(CONFLICT_PS, timeout=60, runner=runner) or {}
    bad = d.get("bad") or []
    bad = bad if isinstance(bad, list) else [bad]
    alloc = d.get("alloc") or []
    alloc = alloc if isinstance(alloc, list) else [alloc]
    by_res: dict[str, set[str]] = {}
    for a in alloc:
        if isinstance(a, dict) and a.get("res") and a.get("dev"):
            by_res.setdefault(str(a["res"]), set()).add(str(a["dev"]))
    bad_ids = {str(b.get("DeviceID")) for b in bad if isinstance(b, dict)}
    shared = [{"resource": r, "devices": sorted(devs)} for r, devs in by_res.items() if len(devs) > 1 and devs & bad_ids]
    return {"problems": [{"name": b.get("Name"), "id": b.get("DeviceID"), "code": b.get("ConfigManagerErrorCode"),
                          "meaning": CM_ERRORS.get(int(b.get("ConfigManagerErrorCode") or 0), "chyba zařízení")}
                         for b in bad if isinstance(b, dict)], "shared": shared[:20]}


# ---------- 81: live FPS ----------
def fps_from_presentmon(lines: list[str]) -> float | None:
    """CSV rows of PresentMon (MsBetweenPresents / msBetweenPresents column) → frames a second over the rows."""
    if len(lines) < 2:
        return None
    head = [h.strip().lower() for h in lines[0].split(",")]
    col = next((i for i, h in enumerate(head) if h in ("msbetweenpresents", "frametime", "msbetweenappstart")), None)
    if col is None:
        return None
    vals = []
    for ln in lines[1:]:
        cells = ln.split(",")
        try:
            v = float(cells[col])
            if 0 < v < 1000:
                vals.append(v)
        except (ValueError, IndexError):
            continue
    if not vals:
        return None
    return round(1000.0 / (sum(vals) / len(vals)), 1)


def find_presentmon(configured: str = "") -> str | None:
    for c in (configured, shutil.which("PresentMon"), shutil.which("PresentMon-2.3.0-x64"),
              r"C:\Program Files\Intel\PresentMon\PresentMonApplication\PresentMon.exe"):
        if c and Path(c).exists():
            return c
    return None


class FpsWatch:
    """While a game runs and PresentMon is installed: its FPS (and the CPU temperature) in the notch, every 2 s."""

    def __init__(self, rt: Any):
        self.rt = rt
        self.proc: subprocess.Popen | None = None
        self.on = False

    def start(self, exe_name: str) -> dict:
        pm = find_presentmon(getattr(self.rt.cfg.games, "presentmon", ""))
        if not pm:
            return {"ok": False, "message": "Na FPS je potřeba PresentMon (zdarma od Intelu) – nainstaluj ho a zkus to znovu."}
        self.stop()
        self.proc = subprocess.Popen([pm, "--process_name", exe_name, "--output_stdout", "--stop_existing_session",
                                      "--v1_metrics"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.on = True
        asyncio.get_running_loop().create_task(self._read(exe_name))
        return {"ok": True, "message": f"Měřím FPS hry {exe_name} – v notchi."}

    async def _read(self, game: str) -> None:
        from .notchplus import live

        head = ""
        buf: list[str] = []
        last = time.monotonic()
        proc = self.proc
        while self.on and proc and proc.poll() is None and proc.stdout:
            line = await asyncio.to_thread(proc.stdout.readline)
            if not line:
                break
            if not head:
                head = line.strip()
                continue
            buf.append(line.strip())
            if time.monotonic() - last >= 2:
                fps = fps_from_presentmon([head, *buf])
                buf = []
                last = time.monotonic()
                if fps:
                    live(self.rt, "fps", game[:20], "game-controller", text=f"{fps:.0f} FPS")
        live(self.rt, "fps", game[:20], done=True)

    def stop(self) -> None:
        self.on = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


# ---------- 90: a project's window layout ----------
def restore_for_project(rt: Any, project: str) -> bool:
    """When a saved window layout carries the project's name, switching to the project restores it."""
    if not project or not getattr(rt.cfg.stark, "layout_memory", True):
        return False
    try:
        from . import workspace

        saved = workspace.list_all(rt)
    except Exception:  # noqa: BLE001
        return False
    match = next((w["name"] for w in saved if str(w.get("project", "")).lower() == project.lower()), None) or \
        next((w["name"] for w in saved if str(w.get("name", "")).lower() == project.lower()), None)
    if not match:
        return False
    from .tools import call

    rt.submit(call("workspace_restore", {"name": match}, rt))
    return True
