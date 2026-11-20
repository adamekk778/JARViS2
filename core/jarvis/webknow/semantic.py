"""Spec 2026-11-20 §5.15: search by meaning in what JARVIS read ("ten článek o robotovi, co uměl vařit" finds "Robot
uvařil oběd"). It uses a LOCAL embedding model in Ollama that understands Czech – downloaded only when you click
"Stáhnout model" (the rule of knowledge.py: nothing is downloaded silently). Without it, the full-text search alone works.
Vectors are made after a study round in batches, never while a game is full screen."""
from __future__ import annotations

import asyncio
import logging
import re
import time

import numpy as np

log = logging.getLogger("jarvis.webknow")
EMBED_MODEL = "paraphrase-multilingual"       # multilingual (Czech included), ~560 MB in Ollama
OTHERS = re.compile(r"paraphrase-multilingual|granite-embedding|bge-m3|multilingual", re.I)
MIN_SCORE = 0.45
BATCH = 32
MAX_VECTORS = 20000
CACHE_S = 300
SQL = "CREATE TABLE IF NOT EXISTS web_emb (doc INTEGER, model TEXT, vec BLOB, PRIMARY KEY (doc, model))"


async def model(rt) -> str:
    """The installed embedding model to use ("" = none: full text only)."""
    try:
        async with rt.http() as c:
            r = await c.get(f"{rt.local.base}/api/tags", timeout=3)
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001 – Ollama not running
        return ""
    def has(n: str) -> str:
        return next((x for x in names if x == n or x == f"{n}:latest"), "")
    want = getattr(rt.cfg.memory, "embed_model", "") or ""
    return (want and has(want)) or has(EMBED_MODEL) or next((x for x in names if OTHERS.search(x)), "")


async def cached_model(rt) -> str:
    hit = getattr(rt, "_webknow_embed", None)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        name = await asyncio.wait_for(model(rt), 1.5)
    except asyncio.TimeoutError:
        name = ""
    rt._webknow_embed = (time.time(), name)
    return name


def _table(rt) -> None:
    rt.db.exec(SQL)


def _text(row: dict) -> str:
    return f"{row['title']}\n{(row['snippet'] or row['text'] or '')[:1000]}"


async def embed_pending(rt, limit: int = 200) -> int:
    from .study import ai_paused

    if ai_paused(rt):
        return 0
    m = await cached_model(rt)
    if not m:
        return 0
    _table(rt)
    rows = rt.db.all("SELECT d.id, d.title, d.snippet, d.text FROM web_docs d LEFT JOIN web_emb e ON e.doc=d.id AND e.model=? "
                     "WHERE e.doc IS NULL ORDER BY d.fetched DESC LIMIT ?", (m, limit))
    done = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        try:
            vecs = await rt.knowledge._embed(m, [_text(r) for r in batch])
        except Exception as e:  # noqa: BLE001 – Ollama busy / stopped: the rest next round
            log.debug("embed: %s", e)
            break
        for r, v in zip(batch, vecs):
            rt.db.exec("INSERT OR REPLACE INTO web_emb VALUES (?,?,?)", (r["id"], m, np.asarray(v, dtype=np.float32).tobytes()))
            done += 1
    return done


async def search(rt, query: str, limit: int = 5, budget_s: float | None = None) -> list[dict]:
    async def go() -> list[dict]:
        m = await cached_model(rt)
        if not m or not (query or "").strip():
            return []
        _table(rt)
        rows = rt.db.all("SELECT d.*, e.vec FROM web_emb e JOIN web_docs d ON d.id=e.doc WHERE e.model=? ORDER BY d.id DESC LIMIT ?",
                         (m, MAX_VECTORS))
        if not rows:
            return []
        q = np.asarray((await rt.knowledge._embed(m, [query]))[0], dtype=np.float32)
        mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) or 1) + 1e-9)
        out = []
        for i in np.argsort(-sims)[:limit]:
            if sims[i] > MIN_SCORE:
                r = dict(rows[i])
                r.pop("vec", None)
                r["score"] = round(float(sims[i]), 3)
                out.append(r)
        return out

    try:
        return await (asyncio.wait_for(go(), budget_s) if budget_s else go())
    except Exception as e:  # noqa: BLE001 – too slow / no model: the full text answered already
        log.debug("semantic: %s", e)
        return []
