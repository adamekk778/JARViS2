"""Start the free local brains if they are installed: OmniRoute (gateway) and Ollama (offline model)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time

import httpx

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code < 500
    except Exception:
        return False


def ensure_omniroute(base_url: str) -> str:
    root = base_url.rstrip("/").removesuffix("/v1")
    if _up(root + "/v1/models") or _up(root):
        return "běží"
    exe = shutil.which("omniroute") or shutil.which("omniroute.cmd")
    if not exe:
        return "nenainstalováno"
    subprocess.Popen([exe], creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(1)
        if _up(root):
            return "spuštěno"
    return "nepodařilo se spustit"


def ensure_ollama_model(base_url: str, model: str) -> str:
    root = base_url.rstrip("/").removesuffix("/v1")
    if not _up(root + "/api/tags"):
        exe = shutil.which("ollama")
        if not exe:
            return "nenainstalováno"
        subprocess.Popen([exe, "serve"], creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(1)
            if _up(root + "/api/tags"):
                break
        else:
            return "nepodařilo se spustit"
    tags = httpx.get(root + "/api/tags", timeout=5).json().get("models", [])
    if any(t.get("name", "").split(":latest")[0] == model.split(":latest")[0] for t in tags):
        return "připraveno"
    log.info("pulling ollama model %s (first run)", model)
    with httpx.stream("POST", root + "/api/pull", json={"model": model}, timeout=None) as r:
        for _ in r.iter_lines():
            pass
    return "staženo"


def start_background(rt) -> None:
    def run():
        for p in rt.cfg.brain.providers:
            if not p.enabled:
                continue
            try:
                if p.preset == "omniroute":
                    log.info("omniroute: %s", ensure_omniroute(p.base_url or "http://localhost:20128/v1"))
                elif p.preset == "ollama":
                    log.info("ollama: %s", ensure_ollama_model(p.base_url or "http://localhost:11434", p.model or "qwen2.5:3b"))
            except Exception as e:
                log.warning("bootstrap %s: %s", p.id, e)

    threading.Thread(target=run, daemon=True, name="bootstrap").start()
