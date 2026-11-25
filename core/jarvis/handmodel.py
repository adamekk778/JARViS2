"""3.17 Gesta prsty (návrh 11): the hand model (MediaPipe Hand Landmarker, Apache 2.0) that sees 21 points of your
hand in the camera picture – pinch to zoom, turn the open hand to rotate, a fist to take the model apart.

The model and its engine (WebAssembly) are ~22 MB; they are downloaded only after your click, each file checked by
its size and SHA-256, and served to the notch / HUD by JARVIS itself (nothing is loaded from the internet while you
use it). The camera picture never leaves the PC.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from . import paths

FILES = {  # name: (url, size, sha256)
    "hand_landmarker.task": ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                             7819105, "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"),
    "vision_wasm_internal.js": ("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.2.3/wasm/vision_wasm_internal.js",
                                336624, "2aa5fd3fdd3d8208cd7587df0bb19fb6925c4ea16a76dd025aedc1f64d6a6309"),
    "vision_wasm_internal.wasm": ("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.2.3/wasm/vision_wasm_internal.wasm",
                                  14665716, "225bc06c0f51a9cf31fea0e9e0b0243e9e01fb5ef332cc1a7fa6656dbdfdaabf"),
}
SIZE_MB = round(sum(f[1] for f in FILES.values()) / 1e6)
NAME_OK = re.compile(r"^[a-z_]+\.(task|js|wasm)$")


def folder() -> Path:
    d = paths.sub("models") / "hands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ready() -> bool:
    d = folder()
    return all((d / n).exists() and (d / n).stat().st_size == f[1] for n, f in FILES.items())


def status() -> dict:
    return {"ready": ready(), "size_mb": SIZE_MB}


def path_of(name: str) -> Path | None:
    if not NAME_OK.match(name or "") or name not in FILES:
        return None
    p = folder() / name
    return p if p.exists() and p.stat().st_size == FILES[name][1] else None


async def download(transport: Any = None, progress: Callable[[float], None] | None = None) -> dict:
    """Only on the user's click: each file to a .part, checked (size + SHA-256), then renamed."""
    import httpx

    from . import tlsctx

    d = folder()
    total = sum(f[1] for f in FILES.values())
    got = 0
    async with httpx.AsyncClient(verify=tlsctx.context(), transport=transport, timeout=None, follow_redirects=True) as c:
        for name, (url, size, sha) in FILES.items():
            dest = d / name
            if dest.exists() and dest.stat().st_size == size:
                got += size
                continue
            part = d / (name + ".part")
            h = hashlib.sha256()
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if progress:
                            progress(min(1.0, got / total))
            if part.stat().st_size != size or h.hexdigest() != sha:
                part.unlink(missing_ok=True)
                return {"ok": False, "error": f"{name}: stažený soubor nesedí (velikost nebo otisk) – zkus to znovu"}
            part.replace(dest)
    return {"ok": True, **status()}
