"""OMEGA wave 47: the notch follows the window JARVIS works in (752, 084), animated hand-offs between the PC and the phone
(083), Mochi moving to the phone and back (195) and the parts of the PC for the 3D explorer (193)."""
from __future__ import annotations

import re
import time

from .comms import fold

# ---------------------------------------------------------------- 752 / 084 anchoring to a window
WINDOW_ARGS = ("window", "title", "app", "name")


def target_window(tool: str, args: dict, wins: list[dict]) -> dict | None:
    """Which on-screen window a tool call is about (by title / app name in its arguments)."""
    if not wins:
        return None
    keys = [str(args.get(k) or "") for k in WINDOW_ARGS if args.get(k)]
    if not keys and not tool.startswith(("ui_", "window_", "type_", "click", "uia")):
        return None
    for k in keys:
        f = fold(k)
        hit = next((w for w in wins if f and (f in fold(w.get("title", "")) or f == fold(w.get("app", "")))), None)
        if hit:
            return hit
    return None


def anchor_offset(win: dict | None, mon_x: int, mon_w: int, notch_w: int, margin: int = 24) -> int:
    """Offset from the screen centre that puts the notch above the middle of the window, kept fully on the monitor."""
    if not win:
        return 0
    cx = win["x"] + win["w"] / 2 - mon_x
    left = cx - notch_w / 2
    left = max(margin, min(mon_w - notch_w - margin, left))
    return round(left - (mon_w - notch_w) / 2)


# ---------------------------------------------------------------- 083 hand-off
def handoff(rt, to: str, label: str, kind: str = "link") -> None:
    """Something just went from one device to the other – the notch and the phone animate it."""
    if to in ("phone", "pc"):
        rt.bus.publish("handoff", to=to, label=label[:80], kind=kind)


# ---------------------------------------------------------------- 195 Mochi on the phone
def mochi_move(rt, to: str) -> dict:
    if to not in ("pc", "phone"):
        raise ValueError("Mochi umí jen na PC nebo na telefon.")
    if to == "phone" and not rt.mobile_clients():
        raise ValueError("Telefon teď není připojený.")
    rt.mochi_at = to
    state = {"at": to, "since": time.time(), "mood": (getattr(getattr(rt, "mood", None), "_last", None) or {}).get("mood")}
    rt.bus.publish("mochi_where", **{k: v for k, v in state.items() if v is not None})
    handoff(rt, to, "Mochi", "mochi")
    return state


# ---------------------------------------------------------------- 193 PC parts
def hardware_overview() -> dict:
    """CPU, memory, graphics, disks and network adapters with their load – for the 3D explorer."""
    import platform

    import psutil

    parts = []
    freq = psutil.cpu_freq()
    parts.append({"kind": "cpu", "name": platform.processor() or "Procesor", "detail": f"{psutil.cpu_count(logical=False) or '?'} jader / {psutil.cpu_count()} vláken"
                  + (f", {freq.current / 1000:.1f} GHz" if freq else ""), "load": psutil.cpu_percent(interval=0.2), "size": psutil.cpu_count() or 4})
    vm = psutil.virtual_memory()
    parts.append({"kind": "ram", "name": "Paměť RAM", "detail": f"{vm.used / 2**30:.1f} z {vm.total / 2**30:.0f} GB", "load": vm.percent, "size": vm.total / 2**30})
    try:
        from .localai import hardware

        for g in hardware().get("gpus", []):
            parts.append({"kind": "gpu", "name": g.get("name", "Grafika"), "detail": f"{g.get('vram_gb') or '?'} GB VRAM", "load": None, "size": g.get("vram_gb") or 2})
    except Exception:  # noqa: BLE001
        pass
    seen = set()
    for p in psutil.disk_partitions(all=False):
        if p.device in seen or (p.fstype or "").lower() in ("squashfs", "tmpfs", "overlay"):
            continue
        seen.add(p.device)
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        parts.append({"kind": "disk", "name": p.mountpoint, "detail": f"volno {u.free / 2**30:.0f} z {u.total / 2**30:.0f} GB ({p.fstype})", "load": u.percent,
                      "size": u.total / 2**30})
    stats = psutil.net_if_stats()
    for name, s in stats.items():
        if s.isup and not re.search(r"(?i)loopback|^lo$|vethernet|docker|virtual", name):
            parts.append({"kind": "net", "name": name, "detail": f"{s.speed} Mb/s" if s.speed else "připojeno", "load": None, "size": 1})
    b = psutil.sensors_battery()
    if b:
        parts.append({"kind": "battery", "name": "Baterie", "detail": f"{b.percent:.0f} %" + (" · nabíjí se" if b.power_plugged else ""), "load": 100 - b.percent, "size": 1})
    return {"parts": parts[:16], "ts": time.time()}
