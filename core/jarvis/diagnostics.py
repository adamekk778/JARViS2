"""Diagnostics (spec §8): how much JARVIS itself costs, a redacted log tail, an export zip, and the --bench measurement."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

import psutil

from . import config as config_mod
from . import paths
from .redact import redact

log = logging.getLogger(__name__)

TARGETS = {"cpu_pct": 2.0, "ram_mb": 400}
GATE_FACTOR = 2.0  # CI fails only above 2× the target, so a noisy runner does not flake


def _proc() -> psutil.Process:
    return psutil.Process(os.getpid())


def _log_tail(n: int = 100) -> list[str]:
    log = paths.sub("logs") / "jarvis.log"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []
    return [redact(line) for line in lines]


def ensure_lag_probe(rt: Any) -> None:
    """Measures event-loop lag while somebody looks at the diagnostics page (stops 10 s after the last request)."""
    rt._diag_seen = time.monotonic()
    if getattr(rt, "_diag_task", None) and not rt._diag_task.done():
        return

    async def probe():
        while time.monotonic() - rt._diag_seen < 10:
            t0 = time.monotonic()
            await asyncio.sleep(0.5)
            rt.diag_lag_ms = max(0.0, (time.monotonic() - t0 - 0.5) * 1000)
        rt._diag_task = None

    try:
        rt._diag_task = asyncio.get_running_loop().create_task(probe())
    except RuntimeError:
        rt._diag_task = None


def start_stall_watch(rt: Any, loop: asyncio.AbstractEventLoop, limit_s: float = 8.0) -> threading.Thread:
    """When the event loop stops answering for limit_s, write where its thread is stuck to the log (once per stall).
    Everything – the window's messages, the phone, /api/show – waits on that loop, so this is the clue a hang needs."""
    loop_thread = threading.get_ident()
    state = {"pong": time.monotonic(), "reported": False}

    def pong() -> None:
        state["pong"] = time.monotonic()
        if state["reported"]:
            log.warning("event loop answers again")
            state["reported"] = False

    def watch() -> None:
        while not loop.is_closed():
            try:
                loop.call_soon_threadsafe(pong)
            except RuntimeError:
                return
            time.sleep(2)
            stuck = time.monotonic() - state["pong"]
            if stuck > limit_s and not state["reported"]:
                state["reported"] = True
                frame = sys._current_frames().get(loop_thread)
                where = "".join(traceback.format_stack(frame)[-12:]) if frame else "?"
                log.warning("event loop stuck for %.0f s, at:\n%s", stuck, where)

    t = threading.Thread(target=watch, daemon=True, name="stall-watch")
    t.start()
    return t


def snapshot(rt: Any) -> dict:
    p = _proc()
    with p.oneshot():
        cpu = float(p.cpu_percent(interval=None))
        ram = p.memory_info().rss / 2**20
        threads = p.num_threads()
    children = []
    for c in p.children(recursive=True):
        try:
            children.append({"name": c.name(), "pid": c.pid, "ram_mb": round(c.memory_info().rss / 2**20, 1)})
        except psutil.Error:
            pass
    voice = rt.voice.status() if getattr(rt, "voice", None) and hasattr(rt.voice, "status") else {"available": False}
    ttft = {k: [round(x) for x in v] for k, v in getattr(rt.router, "ttft", {}).items()}
    return {"cpu_pct": cpu, "ram_mb": round(ram, 1), "threads": threads, "children": children,
            "loop_lag_ms": round(float(getattr(rt, "diag_lag_ms", 0.0)), 1), "ttft": ttft, "voice": voice,
            "log_tail": _log_tail()}


def export_zip(rt: Any) -> Path:
    out = paths.sub("diagnostics") / f"jarvis-diagnostika-{dt.datetime.now():%Y%m%d-%H%M%S}.zip"
    cfg = config_mod.public_dump(rt.cfg)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("config.json", redact(json.dumps(cfg, ensure_ascii=False, indent=2)))
        snap = snapshot(rt)
        snap.pop("log_tail", None)
        z.writestr("snapshot.json", json.dumps(snap, ensure_ascii=False, indent=2))
        for f in sorted(paths.sub("logs").glob("jarvis.log*")):
            z.writestr(f"logs/{f.name}", redact(f.read_text(encoding="utf-8", errors="replace")))
    return out


def gate(result: dict) -> bool:
    return (result["cpu_pct"] <= TARGETS["cpu_pct"] * GATE_FACTOR
            and result["ram_mb"] <= TARGETS["ram_mb"] * GATE_FACTOR)


async def _bench(seconds: int) -> dict:
    import uvicorn

    from .runtime import Runtime
    from .server.app import create_app

    t0 = time.monotonic()
    rt = Runtime(persist_config=False)
    server = uvicorn.Server(uvicorn.Config(create_app(rt), host="127.0.0.1", port=0, log_config=None,
                                           access_log=False, lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.05)
    startup = time.monotonic() - t0
    p = _proc()
    await asyncio.sleep(min(3, seconds))  # warm-up
    p.cpu_percent(interval=None)
    cpu, ram = [], 0.0
    for _ in range(max(1, seconds)):
        await asyncio.sleep(1)
        cpu.append(p.cpu_percent(interval=None))
        ram = max(ram, p.memory_info().rss / 2**20)
    server.should_exit = True
    await asyncio.wait_for(task, 15)
    return {"startup_s": round(startup, 2), "cpu_pct": round(sum(cpu) / len(cpu), 2), "ram_mb": round(ram, 1),
            "seconds": seconds, "targets": TARGETS}


def bench(seconds: int = 30) -> dict:
    """Idle cost of the core (server + runtime, no windows, no voice, no local model)."""
    return asyncio.run(_bench(int(seconds)))
