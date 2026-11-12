"""3.12 Zdraví PC v telefonu: every 5 minutes a look at the disks, memory, processor, graphics temperature and crashed
apps. Something wrong → one quiet notice (on the phone when you are away from the PC), the same problem at most once
in 6 hours. The phone's "Zdraví PC" card shows the last 24 hours. Only reads – it never changes anything on the PC.
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
import time
from collections import deque
from typing import Any

log = logging.getLogger("jarvis.health")

EVERY_S = 5 * 60
REPEAT_S = 6 * 3600
DISK_FREE_GB = 5.0
DISK_USED_PCT = 95.0
RAM_PCT = 92.0
CPU_PCT = 90.0
HOT_GPU_C = 87
SUSTAINED = 3                     # samples in a row (15 minutes) for memory / processor
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def gpu_temp() -> int | None:
    """NVIDIA cards report their temperature through nvidia-smi (no admin rights needed); others: unknown."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8, creationflags=_NO_WINDOW).stdout
        vals = [int(v) for v in re.findall(r"\d+", out)]
        return max(vals) if vals else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def crashes(since_ms: int) -> list[str]:
    """Apps that crashed (Windows "Application Error", event 1000) in the last `since_ms` – their .exe names."""
    if sys.platform != "win32":
        return []
    q = f"*[System[(EventID=1000) and TimeCreated[timediff(@SystemTime) <= {int(since_ms)}]]]"
    try:
        out = subprocess.run(["wevtutil", "qe", "Application", f"/q:{q}", "/f:xml", "/c:10", "/rd:true"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for ev in re.findall(r"<EventData>(.*?)</EventData>", out, re.S):
        first = re.search(r"<Data[^>]*>([^<]+)</Data>", ev)        # the first value is the crashed program
        if first and first.group(1).lower().endswith(".exe") and first.group(1) not in names:
            names.append(first.group(1))
    return names


def top_procs(n: int = 3) -> list[dict]:
    """What uses the processor and memory most right now (CPU since the previous look – psutil remembers)."""
    try:
        import psutil
    except ImportError:
        return []
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            name = p.info["name"] or ""
            if not name or name.lower() in ("system idle process", "idle", "system"):
                continue
            procs.append({"name": name, "cpu": round(float(p.info["cpu_percent"] or 0) / max(1, psutil.cpu_count() or 1), 1),
                          "ram_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 2**20)})
        except (psutil.Error, AttributeError):
            continue
    procs.sort(key=lambda x: (x["cpu"], x["ram_mb"]), reverse=True)
    return procs[:n]


def evaluate(sample: dict, history: list[dict]) -> list[tuple[str, str, str]]:
    """(key, title, body) for what is wrong in this sample (history = the earlier samples, newest last)."""
    out = []
    for d in sample.get("disks") or []:
        if d.get("free_gb", 1e9) < DISK_FREE_GB or d.get("used_pct", 0) >= DISK_USED_PCT:
            out.append((f"disk:{d['mount']}", "Na disku dochází místo",
                        f"Disk {d['mount'].rstrip(chr(92))} má volných jen {d['free_gb']:.1f} GB. Řekni JARVISovi „uklid disk“."))
    recent = (history + [sample])[-SUSTAINED:]
    top = (sample.get("top") or [{}])[0].get("name", "")
    if len(recent) == SUSTAINED and all(s.get("ram", 0) >= RAM_PCT for s in recent):
        out.append(("ram", "Paměť PC je skoro plná", f"Už 15 minut je obsazeno {sample['ram']:.0f} % paměti"
                    + (f" – nejvíc bere {top}." if top else ".")))
    if len(recent) == SUSTAINED and all(s.get("cpu", 0) >= CPU_PCT for s in recent):
        out.append(("cpu", "Procesor jede naplno", f"Už 15 minut je procesor vytížený na {sample['cpu']:.0f} %"
                    + (f" – nejvíc {top}." if top else ".")))
    t = sample.get("gpu_temp")
    if t is not None and t >= HOT_GPU_C:
        out.append(("gpu_hot", "Grafika je moc horká", f"Grafická karta má {t} °C. Zkontroluj větrání PC."))
    for name in sample.get("crashed") or []:
        out.append((f"crash:{name.lower()}", "Aplikace na PC spadla", f"{name} se neočekávaně ukončila."))
    return out


class HealthWatch:
    def __init__(self, rt: Any):
        self.rt = rt
        self.history: deque = deque(maxlen=24 * 3600 // EVERY_S)     # the last 24 hours
        self.alerts: deque = deque(maxlen=20)
        self.sent: dict[str, float] = {}
        self._last_crash_check = time.time()

    def sample(self) -> dict:
        from .tools.system import system_snapshot

        s = system_snapshot()
        now = time.time()
        crashed = crashes(int((now - self._last_crash_check) * 1000) + 5000)
        self._last_crash_check = now
        return {"t": round(now), "cpu": float(s.get("cpu_percent") or 0), "ram": float(s.get("ram_percent") or 0),
                "disks": s.get("disks") or [], "gpu_temp": gpu_temp(), "battery": s.get("battery_percent"),
                "charging": s.get("charging"), "uptime_h": s.get("uptime_h"), "top": top_procs(), "crashed": crashed}

    def step(self, sample: dict) -> list[dict]:
        """Add one sample, send what is newly wrong; returns the alerts sent now."""
        now = sample.get("t") or time.time()
        found = evaluate(sample, list(self.history))
        self.history.append({k: sample.get(k) for k in ("t", "cpu", "ram", "gpu_temp")})
        new = []
        for key, title, body in found:
            if key in self.sent and now - self.sent[key] < REPEAT_S:
                continue
            self.sent[key] = now
            a = {"key": key, "title": title, "body": body, "t": now}
            self.alerts.appendleft(a)
            new.append(a)
            try:
                self.rt.notify(title, body, speak=False)       # away from the PC → it goes to the phone
            except Exception as e:  # noqa: BLE001
                log.debug("health notify: %s", e)
        self._last = sample
        return new

    def status(self) -> dict:
        last = getattr(self, "_last", None) or {}
        return {"now": last, "history": list(self.history), "alerts": list(self.alerts)[:10]}

    async def run(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                self.step(await asyncio.to_thread(self.sample))
            except Exception as e:  # noqa: BLE001 – a failed look must never stop the watch
                log.debug("health sample: %s", e)
            await asyncio.sleep(EVERY_S)
