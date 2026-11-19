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

# Sizes from the official Ollama library (GB, the default quantisation). 3.13: the newer families first – Qwen 3 answers
# well in Czech and calls tools reliably; gpt-oss:20b is the strongest that fits a 16 GB graphics card.
MODELS: list[dict] = [
    {"name": "qwen3:4b", "label": "Qwen 3 4B", "size_gb": 2.5, "min_ram_gb": 8, "vram_gb": 4, "vision": False, "note": "rychlý, slabší PC"},
    {"name": "qwen3:8b", "label": "Qwen 3 8B", "size_gb": 5.2, "min_ram_gb": 16, "vram_gb": 8, "vision": False, "note": "nejlepší poměr – grafika 8 GB"},
    {"name": "qwen3:14b", "label": "Qwen 3 14B", "size_gb": 9.3, "min_ram_gb": 16, "vram_gb": 12, "vision": False, "note": "chytřejší – grafika 12 GB"},
    {"name": "gpt-oss:20b", "label": "gpt-oss 20B (OpenAI)", "size_gb": 14.0, "min_ram_gb": 16, "vram_gb": 16, "vision": False, "note": "nejchytřejší pro grafiku 16 GB"},
    {"name": "qwen3:30b", "label": "Qwen 3 30B (MoE)", "size_gb": 19.0, "min_ram_gb": 32, "vram_gb": 24, "vision": False, "note": "rychlý i s 32 GB RAM (aktivní 3B)"},
    {"name": "gemma3:12b", "label": "Gemma 3 12B", "size_gb": 8.1, "min_ram_gb": 16, "vram_gb": 12, "vision": True, "note": "vidí obrázky"},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "size_gb": 3.3, "min_ram_gb": 8, "vram_gb": 4, "vision": True, "note": "vidí obrázky, malý"},
    {"name": "qwen2.5vl:7b", "label": "Qwen 2.5 VL 7B", "size_gb": 6.0, "min_ram_gb": 16, "vram_gb": 8, "vision": True, "note": "obrazovka a fotky"},
    {"name": "qwen2.5:3b", "label": "Qwen 2.5 3B", "size_gb": 1.9, "min_ram_gb": 8, "vram_gb": 3, "vision": False, "note": "starší, velmi malý"},
    {"name": "llama3.1:8b", "label": "Llama 3.1 8B", "size_gb": 4.9, "min_ram_gb": 16, "vram_gb": 8, "vision": False, "note": ""},
    {"name": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B", "size_gb": 4.7, "min_ram_gb": 16, "vram_gb": 8, "vision": False, "note": "programování"},
]
# 3.13 mode → (num_ctx, threads(cores), keep_alive). JARVIS' instructions + tools need ~6–8k tokens: a smaller context cut
# them off (the model then "forgot" its tools). The model stays loaded – a reload is the slowest part of an answer.
MODES = {
    "eco": (4096, lambda c: max(2, c // 4), "10m"),
    "balanced": (8192, lambda c: max(2, c // 2), "60m"),
    "performance": (16384, lambda c: max(2, c - 1), "-1"),
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
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace",
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


def vram(hw: dict) -> float:
    return max((g.get("vram_gb") or 0 for g in hw.get("gpus") or []), default=0.0)


def recommend(hw: dict) -> list[str]:
    """3.13 A short pick by the graphics card (what fits in VRAM is fast), then RAM: the main model and one that sees."""
    v, ram = vram(hw), hw.get("ram_gb", 8)
    if v >= 15:
        return ["gpt-oss:20b", "qwen3:14b", "gemma3:12b"]
    if v >= 11:
        return ["qwen3:14b", "qwen3:8b", "gemma3:12b"]
    if v >= 7:
        return ["qwen3:8b", "qwen2.5vl:7b"]
    if ram >= 32:
        return ["qwen3:30b", "qwen3:8b", "gemma3:4b"]     # MoE: only ~3B work per word – fast even without a big GPU
    if ram >= 16:
        return ["qwen3:8b", "qwen3:4b", "gemma3:4b"]
    return ["qwen3:4b", "gemma3:4b"]


def think_value(model: str) -> bool | str | None:
    """3.13 Ollama's "think": Qwen 3 / DeepSeek-R1 think aloud before every answer (slow) – off for JARVIS;
    gpt-oss cannot switch it off – the shortest. Other models: not sent (an old Ollama refuses the field)."""
    m = (model or "").lower()
    if m.startswith("gpt-oss"):
        return "low"
    if m.startswith(("qwen3", "deepseek-r1", "magistral", "qwen3-vl")) and "coder" not in m:
        return False
    return None


class LocalManager:
    def __init__(self, rt: Any):
        self.rt = rt
        self.transport: httpx.AsyncBaseTransport | None = None
        self._cancel = False
        self.missing: dict | None = None  # {"name", "size_gb"}: the configured offline model is not downloaded

    def set_missing(self, name: str, size_gb: float | None) -> None:
        """Remembered (not just a one-off event) so the notch and dashboard can show it whenever they connect."""
        self.missing = {"name": name, "size_gb": size_gb}
        self.rt.bus.publish_threadsafe("local_model_missing", **self.missing)

    # ---------- helpers ----------
    def _provider(self):
        return next((p for p in self.rt.cfg.brain.providers if p.preset == "ollama"), None)

    @property
    def base(self) -> str:
        p = self._provider()
        return (((p.base_url if p else "") or "http://127.0.0.1:11434").rstrip("/").removesuffix("/v1")
                .replace("://localhost", "://127.0.0.1"))            # 3.12 not ::1, not through a proxy

    @property
    def model(self) -> str:
        p = self._provider()
        return (p.model if p else "") or "qwen2.5:3b"

    def _client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=timeout, trust_env=False)

    # ---------- queries ----------
    async def status(self) -> dict:
        import asyncio

        hw = await asyncio.to_thread(detect_hardware)  # PowerShell CIM query can take seconds
        out = {"running": False, "version": "", "installed": [], "loaded": [], "hardware": hw, "catalog": MODELS,
               "backup": self.backup(),
               "recommended": recommend(hw), "mode": self.rt.cfg.brain.local_mode,
               "enabled": self.rt.cfg.brain.local_enabled, "gpu": self.rt.cfg.brain.local_gpu, "model": self.model,
               "missing": self.missing}
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
        if self.missing and self.missing.get("name") == name:
            self.missing = None
        return True

    # ---------- 3.12 offline backup: a model on this PC that answers only when the others cannot ----------
    def backup(self) -> dict:
        p = self._provider()
        chain = self.rt.cfg.brain.chain
        on = bool(p and p.enabled and self.rt.cfg.brain.local_enabled)
        return {"on": on, "model": (p.model if p else "") or "qwen2.5:3b", "last": bool(p and chain and chain[-1] == p.id)}

    def set_backup(self, on: bool, model: str = "") -> dict:
        """On: the Ollama provider exists, is enabled and goes LAST in the chain (the cloud answers first). Off: disabled."""
        from ..config import ProviderCfg

        brain = self.rt.cfg.brain
        provs = [p.model_dump() for p in brain.providers]
        p = next((x for x in provs if x.get("preset") == "ollama"), None)
        if on:
            if p is None:
                p = ProviderCfg(id="ollama", preset="ollama", model=model or "qwen2.5:3b").model_dump()
                provs.append(p)
            p["enabled"] = True
            if model:
                p["model"] = model
            chain = [c for c in brain.chain if c != p["id"]] + [p["id"]]
            self.rt.update_config({"brain": {"providers": provs, "chain": chain, "local_enabled": True, "offline_only": False}})
        elif p is not None:
            p["enabled"] = False
            self.rt.update_config({"brain": {"providers": provs}})
        return self.backup()

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

    async def warm(self, model: str | None = None) -> bool:
        """3.13 Load the model into memory now (no answer generated) – the first question is then as fast as the rest."""
        m = model or self.model
        if not m or not self.rt.cfg.brain.local_enabled:
            return False
        _, keep = mode_options(self.rt.cfg.brain.local_mode, os.cpu_count() or 4)
        try:
            async with self._client(120) as c:
                r = await c.post(self.base + "/api/generate", json={"model": m, "keep_alive": keep})
            return r.status_code < 400
        except httpx.HTTPError as e:
            log.debug("ollama warm: %s", e)
            return False

    def tune_windows(self) -> str:
        """3.13 Ollama's own speed switches for this Windows user (no admin): flash attention and a half-size memory
        for the conversation (KV cache q8_0) – faster and fits bigger models. They apply after Ollama restarts."""
        if sys.platform != "win32":
            return "Tohle nastavení je pro Ollamu ve Windows."
        done = []
        for k, v in (("OLLAMA_FLASH_ATTENTION", "1"), ("OLLAMA_KV_CACHE_TYPE", "q8_0")):
            r = subprocess.run(["setx", k, v], capture_output=True, text=True, timeout=15, creationflags=0x08000000)
            if r.returncode == 0:
                done.append(k)
        return ("Hotovo – zapnuto zrychlení Ollamy (flash attention a úspornější paměť konverzace). Ukonči Ollamu v liště "
                "(ikona lamy → Quit) a znovu ji spusť, pak to platí." if len(done) == 2 else "Nastavení se nepodařilo zapsat.")

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
