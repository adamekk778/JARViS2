"""OMEGA 316: find documents by what they mean, not the exact words – with a local embedding model (Ollama) when one is
installed, otherwise by letter-trigram similarity (copes with Czech word endings: „smlouvy“ ~ „smlouva“).
OMEGA 328: automatic versions – every saved change of a file in the chosen folders is kept (50 versions per file)."""
from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from pathlib import Path

log = logging.getLogger("jarvis.fsplus")

DOC_EXT = {".txt", ".md", ".pdf", ".docx", ".csv", ".html", ".htm", ".eml", ".json", ".rtf"}
VERSION_EXT = DOC_EXT | {".xlsx", ".pptx", ".odt", ".ods", ".py", ".js", ".ts", ".css", ".scad", ".blend", ".psd", ".svg"}
EMB_SQL = "CREATE TABLE IF NOT EXISTS file_emb (path TEXT, mtime REAL, model TEXT, vec BLOB, PRIMARY KEY (path, model))"


def trigrams(text: str) -> Counter:
    from .comms import fold

    words = re.findall(r"\w{2,}", fold(text))
    c: Counter = Counter()
    for w in words:
        w = f" {w} "
        for i in range(len(w) - 2):
            c[w[i:i + 3]] += 1
    return c


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())) or 1)


def lexical_rank(query: str, docs: list[tuple[str, str]], limit: int = 10) -> list[dict]:
    """docs: (path, text) → the closest by trigram profile, with idf so common syllables weigh less."""
    profiles = [(p, trigrams(t)) for p, t in docs if t]
    if not profiles:
        return []
    df: Counter = Counter()
    for _p, c in profiles:
        df.update(set(c))
    n = len(profiles)
    idf = {k: math.log((n + 1) / (v + 0.5)) for k, v in df.items()}
    q = Counter({k: v * idf.get(k, math.log(n + 1)) for k, v in trigrams(query).items()})
    scored = []
    for p, c in profiles:
        w = Counter({k: v * idf[k] for k, v in c.items()})
        scored.append((cosine(q, w), p))
    scored.sort(reverse=True)
    return [{"path": p, "score": round(s, 3)} for s, p in scored[:limit] if s > 0.05]


async def semantic_search(rt, folders: list[Path], query: str, limit: int = 8, max_files: int = 600) -> dict:
    import numpy as np

    from .fileuniverse import doc_text, walk

    files = [p for p in walk(folders, 30_000) if p.suffix.lower() in DOC_EXT][:max_files]
    texts = await asyncio.to_thread(lambda: [(str(p), doc_text(p, 3000)) for p in files])
    model = ""
    try:
        model = await rt.knowledge.embed_model()
    except Exception:  # noqa: BLE001
        model = ""
    if model:
        try:
            rt.db.conn.execute(EMB_SQL)
            have = {r["path"]: r for r in rt.db.all("SELECT path, mtime, vec FROM file_emb WHERE model=?", (model,))}
            todo = []
            for (path, text), p in zip(texts, files):
                mt = p.stat().st_mtime
                if text and (path not in have or have[path]["mtime"] != mt):
                    todo.append((path, mt, text))
            for i in range(0, len(todo), 32):
                batch = todo[i:i + 32]
                vecs = await rt.knowledge._embed(model, [f"{Path(x[0]).name}\n{x[2][:2000]}" for x in batch])
                for (path, mt, _t), v in zip(batch, vecs):
                    rt.db.exec("INSERT OR REPLACE INTO file_emb VALUES (?,?,?,?)", (path, mt, model, np.asarray(v, dtype=np.float32).tobytes()))
            rows = rt.db.all("SELECT path, vec FROM file_emb WHERE model=?", (model,))
            wanted = {t[0] for t in texts}
            rows = [r for r in rows if r["path"] in wanted]
            if rows:
                q = np.asarray((await rt.knowledge._embed(model, [query]))[0], dtype=np.float32)
                m = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
                sims = m @ q / (np.linalg.norm(m, axis=1) * (np.linalg.norm(q) or 1) + 1e-9)
                order = np.argsort(-sims)[:limit]
                return {"mode": f"význam ({model})", "hits": [{"path": rows[i]["path"], "score": round(float(sims[i]), 3)} for i in order if sims[i] > 0.3]}
        except Exception as e:  # noqa: BLE001 – the model failed → fall back to the letter profile
            log.debug("semantic search: %s", e)
    return {"mode": "podobnost slov", "hits": lexical_rank(query, texts, limit)}


# ---------------------------------------------------------------- 328 automatic versions
class VersionWatch:
    def __init__(self, rt):
        self.rt = rt
        self.seen: dict[str, float] = {}

    def scan(self, folders: list[Path], max_mb: float = 50) -> list[dict]:
        """Files changed since the last look → a version of each (the first look only learns the current state)."""
        from .fileuniverse import save_version

        out, first = [], not self.seen
        for root in folders:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in VERSION_EXT or p.name.startswith(("~$", ".")):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                key = str(p)
                old = self.seen.get(key)
                self.seen[key] = st.st_mtime
                if first or old == st.st_mtime or st.st_size > max_mb * 2**20:
                    if first and st.st_size <= max_mb * 2**20:
                        try:
                            save_version(p, "výchozí stav")
                        except OSError:
                            pass
                    continue
                try:
                    v = save_version(p, "automaticky po uložení")
                    if not v.get("unchanged"):
                        out.append({"path": key, **v})
                except OSError as e:
                    log.debug("version %s: %s", p, e)
        return out


async def version_loop(rt, every: float = 60.0) -> None:
    vw = VersionWatch(rt)
    rt.version_watch = vw
    while True:
        folders = [Path(f) for f in getattr(rt.cfg.powers, "version_folders", []) or []]
        if folders:
            try:
                saved = await asyncio.to_thread(vw.scan, folders)
                if saved:
                    rt.bus.publish("versions_saved", count=len(saved), files=[Path(x["path"]).name for x in saved[:5]])
            except Exception as e:  # noqa: BLE001
                log.debug("version watch: %s", e)
        await asyncio.sleep(every)
