"""Local AI manager (spec §5): hardware, model catalog with sizes, pull only on request, modes, unload, GPU test."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any

import httpx

from .. import paths

log = logging.getLogger(__name__)

# Sizes from the official Ollama library at the time of writing (GB).
MODELS: list[dict] = [
    {"name": "qwen2.5:3b", "label": "Qwen 2.5 3B", "size_gb": 1.9, "min_ram_gb": 8, "vision": False, "note": "výchozí, rychlý"},
    {"name": "llama3.2:3b", "label": "Llama 3.2 3B", "size_gb": 2.0, "min_ram_gb": 8, "vision": False, "note": ""},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "size_gb": 3.3, "min_ram_gb": 8, "vision": True, "note": "vidí obrázky"},
    {"name": "qwen2.5:7b", "label": "Qwen 2.5 7B", "size_gb": 4.7, "min_ram_gb": 16, "vision": False, "note": "chytřejší, pomalejší"},
    {"name": "llama3.1:8b", "label": "Llama 3.1 8B", "size_gb": 4.9, "min_ram_gb": 16, "vision": False, "note": ""},
    {"name": "qwen2.5vl:7b", "label": "Qwen 2.5 VL 7B", "size_gb": 6.0, "min_ram_gb": 16, "vision": True, "note": "vidí obrázky"},
    {"name": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B", "size_gb": 4.7, "min_ram_gb": 16, "vision": False, "note": "programování"},
]
MODES = {  # mode → (num_ctx, threads(cores), keep_alive)
    "eco": (2048, lambda c: max(2, c // 4), "1m"),
    "balanced": (4096, lambda c: max(2, c // 2), "5m"),
    "performance": (8192, lambda c: max(2, c - 1), "30m"),
}
_hw_cache: tuple[float, dict] | None = None


def mode_options(mode: str, cores: int) -> tuple[dict, str]:
    ctx, threads, keep = MODES.get(mode, MODES["balanced"])
    return {"num_ctx": ctx, "num_thread": threads(cores)}, keep


def _gpus() -> list[dict]:
    if sys.platform != "win32":
        return []
    ps = ("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=0x08000000).stdout
        rows = json.loads(out or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        return [{"name": r.get("Name", ""), "vram_gb": round(r["AdapterRAM"] / 1e9, 1) if r.get("AdapterRAM") else None}
                for r in rows if r.get("Name")]
    except Exception as e:
        log.debug("gpu detect: %s", e)
        return []


def detect_hardware(force: bool = False) -> dict:
    global _hw_cache
    if _hw_cache and not force and time.monotonic() - _hw_cache[0] < 3600:
        return _hw_cache[1]
    import psutil

    hw = {"ram_gb": round(psutil.virtual_memory().total / 1e9, 1), "cores": os.cpu_count() or 4, "gpus": _gpus(),
          "disk_free_gb": round(shutil.disk_usage(paths.data_dir()).free / 1e9, 1)}
    _hw_cache = (time.monotonic(), hw)
    return hw


def recommend(hw: dict) -> list[str]:
    limit = 3.5 if hw.get("ram_gb", 8) < 16 else 6.0
    names = [m["name"] for m in MODELS if m["size_gb"] <= limit]
    return ["qwen2.5:3b"] + [n for n in names if n != "qwen2.5:3b"]


class LocalManager:
    def __init__(self, rt: Any):
        self.rt = rt
        self.transport: httpx.AsyncBaseTransport | None = None
        self._cancel = False

    # ---------- helpers ----------
    def _provider(self):
        return next((p for p in self.rt.cfg.brain.providers if p.preset == "ollama"), None)

    @property
    def base(self) -> str:
        p = self._provider()
        return ((p.base_url if p else "") or "http://localhost:11434").rstrip("/").removesuffix("/v1")

    @property
    def model(self) -> str:
        p = self._provider()
        return (p.model if p else "") or "qwen2.5:3b"

    def _client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=timeout)

    # ---------- queries ----------
    async def status(self) -> dict:
        hw = detect_hardware()
        out = {"running": False, "version": "", "installed": [], "loaded": [], "hardware": hw, "catalog": MODELS,
               "recommended": recommend(hw), "mode": self.rt.cfg.brain.local_mode,
               "enabled": self.rt.cfg.brain.local_enabled, "gpu": self.rt.cfg.brain.local_gpu, "model": self.model}
        try:
            async with self._client(5) as c:
                out["version"] = (await c.get(self.base + "/api/version")).json().get("version", "")
                out["running"] = True
                tags = (await c.get(self.base + "/api/tags")).json().get("models", [])
                out["installed"] = [{"name": t["name"], "size_gb": round(t.get("size", 0) / 1e9, 1)} for t in tags]
                ps = (await c.get(self.base + "/api/ps")).json().get("models", [])
                out["loaded"] = [{"name": m["name"], "size_vram_gb": round(m.get("size_vram", 0) / 1e9, 1)} for m in ps]
        except (httpx.HTTPError, ValueError) as e:
            log.debug("ollama status: %s", e)
        return out

    # ---------- actions (only ever on an explicit click) ----------
    async def pull(self, name: str) -> bool:
        self._cancel = False
        pub = self.rt.bus.publish
        try:
            async with self._client(None) as c:
                async with c.stream("POST", self.base + "/api/pull", json={"model": name, "stream": True}) as r:
                    async for line in r.aiter_lines():
                        if self._cancel:
                            pub("local_pull_progress", name=name, cancelled=True)
                            return False
                        if not line.strip():
                            continue
                        d = json.loads(line)
                        if d.get("error"):
                            pub("local_pull_progress", name=name, error=d["error"])
                            return False
                        pub("local_pull_progress", name=name, status=d.get("status", ""),
                            total=d.get("total"), completed=d.get("completed"))
        except httpx.HTTPError as e:
            pub("local_pull_progress", name=name, error=f"Ollama neodpovídá: {e}")
            return False
        pub("local_pull_progress", name=name, done=True)
        return True

    def cancel_pull(self) -> None:
        self._cancel = True

    async def delete(self, name: str) -> bool:
        async with self._client() as c:
            r = await c.request("DELETE", self.base + "/api/delete", json={"model": name})
            return r.status_code < 400

    async def unload(self) -> None:
        try:
            async with self._client(5) as c:
                ps = (await c.get(self.base + "/api/ps")).json().get("models", [])
                for m in ps:
                    await c.post(self.base + "/api/generate", json={"model": m["name"], "keep_alive": 0})
        except (httpx.HTTPError, ValueError) as e:
            log.debug("ollama unload: %s", e)

    async def gpu_test(self) -> str:
        try:
            async with self._client(180) as c:
                await c.post(self.base + "/api/generate", json={"model": self.model, "prompt": "ok", "stream": False,
                                                                 "options": {"num_predict": 1}})
                ps = (await c.get(self.base + "/api/ps")).json().get("models", [])
        except (httpx.HTTPError, ValueError) as e:
            return f"Test se nepovedl – Ollama neodpovídá ({e})."
        vram = max((m.get("size_vram", 0) for m in ps), default=0)
        if vram > 0:
            self.rt.update_config({"brain": {"local_gpu": "gpu"}})
            gb = f"{vram / 1e9:.1f}".replace(".", ",")
            return f"Model běží na GPU ({gb} GB ve VRAM)."
        self.rt.update_config({"brain": {"local_gpu": "cpu"}})
        return ("Model běží jen na procesoru. Grafika (třeba AMD RX 6600) nemusí mít v Ollamě akceleraci – "
                "JARVIS tedy jede na CPU; zvol Úsporný režim, ať PC nezpomaluje.")
