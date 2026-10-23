from __future__ import annotations

import asyncio
import platform as _pf
import socket
import sys
import time
from typing import Literal

import psutil

from .base import ToolResult, tool

SAFE_POWER = {"lock", "cancel_shutdown"}


@tool("system_power", "Zamknout, uspat, vypnout, restartovat PC, odhlásit, nebo zrušit naplánované vypnutí.",
      danger_if=lambda a: a.get("action") not in SAFE_POWER, category="systém")
async def system_power(ctx, action: Literal["lock", "sleep", "shutdown", "restart", "cancel_shutdown", "logoff"]) -> ToolResult:
    await asyncio.to_thread(ctx.platform.power, action)
    msg = {"lock": "Zamčeno", "sleep": "Uspávám", "shutdown": "Vypínám za 15 s (zrušit: 'zruš vypnutí')",
           "restart": "Restartuji za 15 s", "cancel_shutdown": "Vypnutí zrušeno", "logoff": "Odhlašuji"}[action]
    return ToolResult(True, msg)


_net_last: tuple[float, int, int] | None = None
_gpu_util: tuple[float, float | None] = (0.0, None)


def _disks() -> list[dict]:
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        if u.total < 2**30:  # tiny system / virtual mounts
            continue
        out.append({"mount": part.mountpoint, "used_pct": u.percent, "free_gb": round(u.free / 2**30, 1)})
    return out


def _net_rate(net) -> tuple[float, float]:
    global _net_last
    now = time.monotonic()
    up = down = 0.0
    if _net_last and now > _net_last[0]:
        dt_s = now - _net_last[0]
        up = max(0.0, (net.bytes_sent - _net_last[1]) / 1024 / dt_s)
        down = max(0.0, (net.bytes_recv - _net_last[2]) / 1024 / dt_s)
    _net_last = (now, net.bytes_sent, net.bytes_recv)
    return round(up, 1), round(down, 1)


def _gpu(util: bool) -> dict | None:
    """GPU name (cached CIM query) + 3D utilisation, measured only when asked and at most every 3 s."""
    global _gpu_util
    try:
        from ..llm.local import detect_hardware

        gpus = detect_hardware().get("gpus") or []
    except Exception:
        gpus = []
    if not gpus:
        return None
    value = None
    if util and _pf.system() == "Windows":
        if time.monotonic() - _gpu_util[0] > 3:
            import subprocess

            ps = ("(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue)"
                  ".CounterSamples | Measure-Object CookedValue -Sum | Select -Expand Sum")
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                                     timeout=10, creationflags=0x08000000).stdout.strip()
                _gpu_util = (time.monotonic(), round(min(100.0, float(out.replace(",", "."))), 1) if out else None)
            except Exception:
                _gpu_util = (time.monotonic(), None)
        value = _gpu_util[1]
    return {"name": gpus[0]["name"], "vram_gb": gpus[0].get("vram_gb"), "util": value}


def system_snapshot(gpu: bool = False) -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("C:\\" if _pf.system() == "Windows" else "/")
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = ""
    net = psutil.net_io_counters()
    up, down = _net_rate(net)
    return {
        "disks": _disks(),
        "net_up_kbps": float(up),
        "net_down_kbps": float(down),
        "gpu": _gpu(gpu),
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_cores": psutil.cpu_count(),
        "ram_percent": vm.percent,
        "ram_used_gb": round(vm.used / 2**30, 1),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "disk_percent": du.percent,
        "disk_free_gb": round(du.free / 2**30, 1),
        "battery_percent": round(bat.percent) if bat else None,
        "charging": bat.power_plugged if bat else None,
        "os": f"{_pf.system()} {_pf.release()}",
        "hostname": socket.gethostname(),
        "ip": ip,
        "net_sent_mb": round(net.bytes_sent / 2**20),
        "net_recv_mb": round(net.bytes_recv / 2**20),
        "uptime_h": round((__import__("time").time() - psutil.boot_time()) / 3600, 1),
    }


@tool("system_info", "Stav PC: CPU, RAM, disk, baterie, IP, uptime.", category="systém")
async def system_info(ctx) -> ToolResult:
    s = await asyncio.to_thread(system_snapshot)
    return ToolResult(True, f"CPU {s['cpu_percent']} %, RAM {s['ram_percent']} %", data=s)


@tool("top_processes", "Vypíše procesy, které nejvíc zatěžují CPU/RAM.", category="systém")
async def top_processes(ctx, by: Literal["cpu", "ram"] = "cpu", count: int = 8) -> ToolResult:
    def run():
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                procs.append({"name": p.info["name"], "cpu": p.info["cpu_percent"] or 0,
                              "ram_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 2**20)})
            except Exception:
                pass
        key = "cpu" if by == "cpu" else "ram_mb"
        return sorted(procs, key=lambda x: x[key], reverse=True)[:count]

    return ToolResult(True, "Top procesy", data=await asyncio.to_thread(run))


@tool("set_dark_mode", "Zapne nebo vypne tmavý režim Windows.", category="systém")
async def set_dark_mode(ctx, dark: bool) -> ToolResult:
    await asyncio.to_thread(ctx.platform.set_dark_mode, dark)
    return ToolResult(True, "Tmavý režim zapnut" if dark else "Světlý režim zapnut")


def _startup_items() -> int:
    n = 0
    if sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                    n += winreg.QueryInfoKey(k)[1]
            except OSError:
                pass
        import os
        from pathlib import Path

        for d in (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
                  Path(os.environ.get("ProgramData", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp"):
            if d.is_dir():
                n += sum(1 for f in d.iterdir() if f.suffix.lower() in (".lnk", ".exe", ".bat", ".cmd"))
    return n


def recommendations(d: dict) -> list[str]:
    tips = []
    if d.get("ram_percent", 0) >= 85 and d.get("top_ram"):
        t = d["top_ram"][0]
        tips.append(f"Paměť je skoro plná ({d['ram_percent']:.0f} %). Nejvíc si bere {t['name']} ({t['ram_mb']} MB) – "
                    "zavři ho, pokud ho nepotřebuješ.")
    busy = [p for p in d.get("top_cpu", []) if p.get("cpu", 0) >= 50]
    if busy:
        tips.append(f"Procesor teď hodně vytěžuje {busy[0]['name']} ({busy[0]['cpu']:.0f} %).")
    if d.get("startup_items", 0) > 10:
        tips.append(f"Po spuštění se zapíná {d['startup_items']} programů – zkontroluj je ve Správci úloh → "
                    "Aplikace po spuštění a vypni, co nepotřebuješ.")
    for disk in d.get("disks", []):
        if disk.get("used_pct", 0) >= 90:
            tips.append(f"Disk {disk['mount'].rstrip(chr(92))} je plný na {disk['used_pct']:.0f} % "
                        f"(volno {disk['free_gb']} GB) – uvolni místo (Nastavení → Systém → Úložiště).")
    if d.get("uptime_h", 0) > 72:
        tips.append(f"PC běží {d['uptime_h']:.0f} h bez restartu – restart často pomůže.")
    return tips or ["Nevidím nic, co by PC výrazně zpomalovalo."]


@tool("performance_report", "Zjistí, proč je PC pomalý: nejnáročnější procesy, paměť, disky, programy po spuštění. "
      "Jen čte a radí – nic nevypíná ani nemaže.", category="systém", perm="system")
async def performance_report(ctx) -> ToolResult:
    def run():
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                p.cpu_percent(None)
                procs.append(p)
            except Exception:
                pass
        time.sleep(0.5)
        rows = []
        for p in procs:
            try:
                rows.append({"name": p.info["name"], "cpu": p.cpu_percent(None),
                             "ram_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 2**20)})
            except Exception:
                pass
        snap = system_snapshot()
        return {"top_cpu": sorted(rows, key=lambda r: r["cpu"], reverse=True)[:5],
                "top_ram": sorted(rows, key=lambda r: r["ram_mb"], reverse=True)[:5],
                "ram_percent": snap["ram_percent"], "disks": snap["disks"], "uptime_h": snap["uptime_h"],
                "startup_items": _startup_items()}

    data = await asyncio.to_thread(run)
    return ToolResult(True, "\n".join(f"- {t}" for t in recommendations(data)), data=data)
