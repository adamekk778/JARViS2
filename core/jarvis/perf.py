"""OMEGA §26 Extreme Performance: what slows the PC down right now (CPU / GPU / RAM / disk / network), throttling,
latency + jitter + packet loss, a repeatable benchmark with before/after comparison, and the performance history.
Measured, never guessed: what a PC does not report is "neznámé"."""
from __future__ import annotations

import base64
import json
import os
import socket
import statistics
import sys
import tempfile
import time
from typing import Any

import psutil

from .pcreport import run_quiet

HIST_SQL = """
CREATE TABLE IF NOT EXISTS perf_history (ts REAL, cpu REAL, ram REAL, disk_mb_s REAL, gpu REAL, net_ms REAL);
CREATE TABLE IF NOT EXISTS perf_bench (ts REAL, label TEXT, cpu_score REAL, disk_write_mb_s REAL, disk_read_mb_s REAL,
  ram_gb_s REAL);
"""
GPU_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$o = @{}
try { $c = Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -ErrorAction Stop; $o.gpu = [math]::Round((($c.CounterSamples | Measure-Object CookedValue -Sum).Sum), 1) } catch { $o.gpu_error = $_.Exception.Message }
try { $m = Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop; $o.vram_mb = [math]::Round((($m.CounterSamples | Measure-Object CookedValue -Sum).Sum) / 1MB) } catch {}
try { $v = Get-CimInstance Win32_VideoController | Select-Object -First 1 Name, AdapterRAM; $o.gpu_name = $v.Name; $o.vram_total_mb = [math]::Round($v.AdapterRAM / 1MB) } catch {}
$o | ConvertTo-Json -Compress
"""


def gpu_sample() -> dict:
    if sys.platform != "win32":
        return {"error": "jen na Windows"}
    enc = base64.b64encode(GPU_PS.encode("utf-16-le")).decode()
    code, out, err = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 30)
    try:
        return json.loads(out[out.find("{"):]) if "{" in out else {"error": err[:200] or "bez výstupu"}
    except ValueError:
        return {"error": "nečitelný výstup"}


def tcp_latency(host: str = "1.1.1.1", port: int = 443, n: int = 10, timeout: float = 2.0) -> dict:
    """Round trips of a TCP handshake (works without administrator rights, unlike ping) → avg, jitter, loss."""
    times, lost = [], 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                times.append((time.perf_counter() - t0) * 1000)
        except OSError:
            lost += 1
        time.sleep(0.05)
    if not times:
        return {"host": host, "avg_ms": None, "jitter_ms": None, "loss_pct": 100.0}
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return {"host": host, "avg_ms": round(statistics.mean(times), 1), "min_ms": round(min(times), 1),
            "max_ms": round(max(times), 1), "jitter_ms": round(jitter, 1), "loss_pct": round(lost / n * 100, 1)}


def sample(seconds: float = 5.0, gpu: bool = True) -> dict:
    """Load over a few seconds: per-core CPU, frequency (throttling), RAM pressure, disk I/O, top processes, GPU."""
    procs = {p.pid: p for p in psutil.process_iter(["name"])}
    for p in procs.values():
        try:
            p.cpu_percent(None)
        except (psutil.Error, OSError):
            pass
    d0, t0 = psutil.disk_io_counters(perdisk=True), time.monotonic()
    per_core = psutil.cpu_percent(interval=seconds, percpu=True)
    dt = time.monotonic() - t0
    d1 = psutil.disk_io_counters(perdisk=True)
    disks = {}
    for k, v in d1.items():
        a = d0.get(k)
        if a:
            disks[k] = {"read_mb_s": round((v.read_bytes - a.read_bytes) / dt / 2**20, 2),
                        "write_mb_s": round((v.write_bytes - a.write_bytes) / dt / 2**20, 2),
                        "busy_pct": round(min(100.0, ((getattr(v, "busy_time", 0) - getattr(a, "busy_time", 0)) / (dt * 1000)) * 100), 1)
                        if hasattr(v, "busy_time") else None}
    top = []
    for p in procs.values():
        try:
            top.append((p.cpu_percent(None) / (psutil.cpu_count() or 1), p.info["name"] or "?", p.memory_info().rss))
        except (psutil.Error, OSError):
            pass
    top.sort(reverse=True)
    freq = psutil.cpu_freq()
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    out: dict[str, Any] = {
        "seconds": round(dt, 1), "cpu": round(sum(per_core) / len(per_core), 1), "per_core": per_core,
        "max_core": max(per_core), "freq_mhz": round(freq.current) if freq else None, "freq_max_mhz": round(freq.max) if freq and freq.max else None,
        "ram_pct": vm.percent, "ram_avail_gb": round(vm.available / 2**30, 1), "swap_pct": sw.percent, "disks": disks,
        "top_cpu": [{"name": n, "cpu": round(c, 1), "ram_mb": round(r / 2**20)} for c, n, r in top[:6]],
        "top_ram": sorted(({"name": n, "ram_mb": round(r / 2**20)} for _c, n, r in top), key=lambda x: -x["ram_mb"])[:6],
    }
    if gpu:
        out["gpu"] = gpu_sample()
    return out


def bottlenecks(s: dict) -> list[dict]:
    """Plain conclusions from one sample."""
    from .rescue import F

    out = []
    if s["cpu"] >= 85 or s["max_core"] >= 98 and s["cpu"] >= 40:
        who = ", ".join(f"{p['name']} {p['cpu']} %" for p in s["top_cpu"][:3])
        out.append(F("bad" if s["cpu"] >= 85 else "warn", f"Brzdí procesor: vytížení {s['cpu']} % (nejvíc {who}).",
                     "Zavři nebo pozastav náročné programy; u her sniž nastavení závislá na CPU (dohled, NPC).", "psutil.cpu_percent"))
    if s.get("freq_mhz") and s.get("freq_max_mhz") and s["cpu"] >= 60 and s["freq_mhz"] < 0.6 * s["freq_max_mhz"]:
        out.append(F("bad", f"Procesor je pod zátěží škrcený: běží na {s['freq_mhz']} MHz z {s['freq_max_mhz']} MHz.",
                     "Přehřátí nebo úsporný režim napájení: zkontroluj chlazení a přepni plán napájení na Vysoký výkon.", "psutil.cpu_freq"))
    if s["ram_pct"] >= 85:
        who = ", ".join(f"{p['name']} {p['ram_mb']} MB" for p in s["top_ram"][:3])
        out.append(F("bad" if s["ram_pct"] >= 93 else "warn", f"Dochází paměť RAM: {s['ram_pct']} % (nejvíc {who}).",
                     "Zavři nepoužívané programy a karty prohlížeče; při častém stavu zvaž víc RAM.", "psutil.virtual_memory"))
    for k, v in s["disks"].items():
        if v.get("busy_pct") and v["busy_pct"] >= 90:
            out.append(F("warn", f"Disk {k} je vytížený na {v['busy_pct']} % (čtení {v['read_mb_s']} MB/s, zápis {v['write_mb_s']} MB/s).",
                         "Něco intenzivně pracuje s diskem (aktualizace, antivir, indexování, synchronizace).", "psutil.disk_io_counters"))
    g = s.get("gpu") or {}
    if isinstance(g.get("gpu"), (int, float)):
        if g["gpu"] >= 95 and s["cpu"] < 70:
            out.append(F("info", f"Grafika jede naplno ({g['gpu']} %) – ve hrách brzdí grafika, ne procesor.", "Sniž rozlišení/detaily nebo zapni DLSS/FSR.", "Get-Counter GPU Engine"))
        if g.get("vram_mb") and g.get("vram_total_mb") and g["vram_mb"] > 0.92 * g["vram_total_mb"] > 0:
            out.append(F("warn", f"Grafická paměť je skoro plná ({g['vram_mb']} z {g['vram_total_mb']} MB).", "Sniž kvalitu textur.", "Get-Counter GPU Adapter Memory"))
    if not out:
        out.append(F("ok", f"Nic nebrzdí: CPU {s['cpu']} %, RAM {s['ram_pct']} %" + (f", grafika {g['gpu']} %" if isinstance(g.get("gpu"), (int, float)) else "") + ".",
                     source="psutil"))
    return out


# ---------------------------------------------------------------------------------------------- benchmark
def benchmark(label: str = "") -> dict:
    """OMEGA 314: a short, repeatable measurement (≈ 6 s): CPU loop, RAM copy, disk write/read of 256 MB in TEMP."""
    t0 = time.perf_counter()
    x, n = 0, 0
    while time.perf_counter() - t0 < 2.0:
        for i in range(10000):
            x = (x * 1103515245 + i) & 0xFFFFFFFF
        n += 1
    cpu_score = round(n / 2.0, 1)
    buf = bytearray(os.urandom(1 << 20)) * 64        # 64 MB
    t0 = time.perf_counter()
    for _ in range(4):
        _ = bytes(buf)
    ram = round(4 * 64 / 1024 / (time.perf_counter() - t0), 2)
    path = os.path.join(tempfile.gettempdir(), f"jarvis-bench-{os.getpid()}.bin")
    chunk = os.urandom(8 << 20)
    try:
        t0 = time.perf_counter()
        with open(path, "wb", buffering=0) as f:
            for _ in range(32):
                f.write(chunk)
            os.fsync(f.fileno())
        w = round(256 / (time.perf_counter() - t0), 1)
        t0 = time.perf_counter()
        with open(path, "rb", buffering=0) as f:
            while f.read(8 << 20):
                pass
        r = round(256 / (time.perf_counter() - t0), 1)       # often from the OS cache – marked as such in the UI
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ts": time.time(), "label": label, "cpu_score": cpu_score, "ram_gb_s": ram, "disk_write_mb_s": w, "disk_read_mb_s": r}


def compare(a: dict, b: dict) -> list[str]:
    out = []
    for k, name in (("cpu_score", "procesor"), ("ram_gb_s", "paměť"), ("disk_write_mb_s", "zápis na disk"), ("disk_read_mb_s", "čtení z disku")):
        if a.get(k) and b.get(k):
            ch = (b[k] - a[k]) / a[k] * 100
            out.append(f"{name}: {a[k]:g} → {b[k]:g} ({'+' if ch >= 0 else ''}{ch:.0f} %)")
    return out


class PerfHistory:
    """OMEGA 312: a light snapshot every 5 minutes (kept 30 days) for "how fast was it last week"."""

    def __init__(self, rt):
        self.rt = rt
        self._io_prev: tuple[float, int] | None = None
        rt.db.conn.executescript(HIST_SQL)

    def record(self, cpu: float | None, ram: float | None, gpu: float | None = None, net_ms: float | None = None) -> dict:
        """One row; the disk rate is the average since the previous row (cumulative psutil counters)."""
        now = time.time()
        disk = None
        try:
            io = psutil.disk_io_counters()
            total = io.read_bytes + io.write_bytes if io else None
        except (OSError, RuntimeError):
            total = None
        if total is not None and self._io_prev and now > self._io_prev[0]:
            disk = round((total - self._io_prev[1]) / (now - self._io_prev[0]) / 2**20, 2)
        self._io_prev = (now, total) if total is not None else None
        self.rt.db.exec("INSERT INTO perf_history VALUES (?,?,?,?,?,?)", (now, cpu, ram, disk, gpu, net_ms))
        self.rt.db.exec("DELETE FROM perf_history WHERE ts < ?", (now - 30 * 86400,))
        return {"ts": now, "cpu": cpu, "ram": ram, "disk_mb_s": disk, "gpu": gpu, "net_ms": net_ms}

    def summary(self, hours: float = 24) -> dict:
        """Average and peak per metric over the window (what "how was it yesterday" needs)."""
        rows = self.series(hours)
        out: dict[str, Any] = {"samples": len(rows), "hours": hours}
        for k in ("cpu", "ram", "disk_mb_s", "gpu", "net_ms"):
            vals = [r[k] for r in rows if r[k] is not None]
            if vals:
                out[k] = {"avg": round(statistics.mean(vals), 1), "max": round(max(vals), 1)}
        return out

    def series(self, hours: float = 24) -> list[dict]:
        return self.rt.db.all("SELECT * FROM perf_history WHERE ts>=? ORDER BY ts", (time.time() - hours * 3600,))

    def save_bench(self, b: dict) -> None:
        self.rt.db.exec("INSERT INTO perf_bench VALUES (?,?,?,?,?,?)",
                        (b["ts"], b["label"], b["cpu_score"], b["disk_write_mb_s"], b["disk_read_mb_s"], b["ram_gb_s"]))

    def benches(self, limit: int = 10) -> list[dict]:
        return self.rt.db.all("SELECT * FROM perf_bench ORDER BY ts DESC LIMIT ?", (limit,))
