from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
import uuid
from typing import Annotated

from .. import paths
from .base import ToolResult, tool

RISKY = re.compile(r"\b(os\.remove|os\.unlink|unlink\(|rmtree|rmdir|os\.system|subprocess|Popen|shutil\.move|winreg|"
                   r"requests\.(post|put|delete)|httpx\.(post|put|delete)|smtplib|ctypes)\b|open\([^)]*['\"][A-Za-z]:\\\\")


def python_cmd(script: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-python", script]  # the JARVIS exe embeds Python + libraries
    return [sys.executable, script]


@tool("run_python", "Spustí Python kód na PC (výpočty, převody souborů, grafy přes matplotlib, úpravy obrázků přes PIL, "
      "Excel přes openpyxl…). Soubory, které kód vytvoří v aktuální složce, se pošlou do chatu. Výstup = print().",
      danger_if=lambda a: bool(RISKY.search(a.get("code", ""))), category="tvorba")
async def run_python(ctx, code: Annotated[str, "Python 3 kód"], timeout: int = 60) -> ToolResult:
    run_dir = paths.sub("sandbox") / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    run_dir.mkdir(parents=True)
    script = run_dir / "main.py"
    script.write_text(code, encoding="utf-8")
    flags = 0x08000000 if sys.platform == "win32" else 0

    def run():
        return subprocess.run(python_cmd(str(script)), cwd=run_dir, capture_output=True, text=True,
                              timeout=max(5, min(600, timeout)), encoding="utf-8", errors="replace", creationflags=flags,
                              env={**__import__("os").environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"})

    try:
        r = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Kód běžel déle než {timeout} s a byl ukončen")
    atts = []
    for f in sorted(run_dir.iterdir()):
        if f.name != "main.py" and f.is_file():
            import mimetypes

            att = await ctx.store.save_path(f, mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            atts.append(att.id)
    out = (r.stdout or "")[-6000:]
    err = (r.stderr or "")[-3000:]
    return ToolResult(r.returncode == 0, "OK" if r.returncode == 0 else f"Chyba (exit {r.returncode})",
                      data={"stdout": out, "stderr": err, "files": len(atts)}, attachments=atts)
