from __future__ import annotations

import asyncio
import platform as _pf
import socket
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


def system_snapshot() -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("C:\\" if _pf.system() == "Windows" else "/")
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = ""
    net = psutil.net_io_counters()
    return {
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
