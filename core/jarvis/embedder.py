"""3.14 Hledání podle významu bez Ollamy (návrh 8).

A small multilingual embedding model (multilingual-e5-small, 8-bit, ~135 MB with its tokenizer) runs inside JARVIS
through ONNX Runtime – "najdi tu smlouvu k bydlení" finds "Nájemní smlouva na byt" even with Ollama off. It is
downloaded only after you click (D8), checked by its SHA-256, and used by every search by meaning (Paměť → Hledat,
find_by_meaning, search_everything). An Ollama embedding model, if you have one, still goes first.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

NAME = "e5-small"
BASE = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/"
FILES = {
    "model.onnx": ("onnx/model_quantized.onnx", 118308185, "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"),
    "tokenizer.json": ("tokenizer.json", 17082730, "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
}
SIZE_MB = round(sum(f[1] for f in FILES.values()) / 1e6)
MAX_TOKENS = 512
_lock = threading.Lock()
_session: Any = None
_tok: Any = None


def folder() -> Path:
    from . import paths

    d = paths.sub("models") / "embed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def libs_ok() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return True


def ready() -> bool:
    d = folder()
    return libs_ok() and all((d / n).exists() and (d / n).stat().st_size == size for n, (_u, size, _h) in FILES.items())


def status() -> dict:
    return {"ready": ready(), "libs": libs_ok(), "size_mb": SIZE_MB, "name": NAME}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def download(transport: Any = None, progress: Callable[[float], None] | None = None) -> dict:
    """Only ever on the user's click. Each file goes to a .part file, is checked, then renamed."""
    import httpx

    from . import tlsctx

    if not libs_ok():
        return {"ok": False, "error": "chybí knihovny onnxruntime a tokenizers (jsou v instalaci JARVISe pro Windows)"}
    d = folder()
    total = sum(f[1] for f in FILES.values())
    got = 0
    async with httpx.AsyncClient(verify=tlsctx.context(), transport=transport, timeout=None, follow_redirects=True) as c:
        for name, (rel, size, sha) in FILES.items():
            dest = d / name
            if dest.exists() and dest.stat().st_size == size:
                got += size
                continue
            part = d / (name + ".part")
            h = hashlib.sha256()
            async with c.stream("GET", BASE + rel) as r:
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


def _load() -> tuple[Any, Any]:
    global _session, _tok
    with _lock:
        if _session is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            d = folder()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2                  # a background search must not take the whole processor
            _session = ort.InferenceSession(str(d / "model.onnx"), opts, providers=["CPUExecutionProvider"])
            _tok = Tokenizer.from_file(str(d / "tokenizer.json"))
            _tok.enable_truncation(MAX_TOKENS)
            _tok.enable_padding()
        return _session, _tok


def encode(texts: list[str], kind: str = "passage", batch: int = 16) -> list[list[float]]:
    """Unit vectors (384 numbers) – e5 wants "query: " for what you ask and "passage: " for what is searched."""
    import numpy as np

    sess, tok = _load()
    names = {i.name for i in sess.get_inputs()}
    out: list[list[float]] = []
    prefix = "query: " if kind == "query" else "passage: "
    for i in range(0, len(texts), batch):
        enc = tok.encode_batch([prefix + (t or "")[:4000] for t in texts[i:i + batch]])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = sess.run(None, feeds)[0]
        v = (hidden * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
        v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
        out += v.astype(np.float32).tolist()
    return out
